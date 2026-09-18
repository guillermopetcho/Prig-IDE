"""
Calibración: medir de verdad en la máquina del usuario.

La calculadora parte de valores previos (ancho de banda de GPUs conocidas, reserva
típica de Ollama). Son buenos para ordenar, no para prometer. Una prueba corta con
un modelo real da tres números que sustituyen a los previos:

  · presupuesto de GPU: cuánto llena Ollama la tarjeta cuando un modelo no cabe.
  · ancho de GPU: se despeja de la velocidad de un modelo que cabe entero.
  · ancho de CPU: se despeja de un modelo repartido, conocido ya el de GPU.

Cada prueba es además un CANARIO de extracción: se pide un JSON con citas literales
de un texto y se comprueba que las citas existen. Es lo que se estropeó al cuantizar
la caché, y no se ve mirando solo la velocidad.

Falta de memoria: si Ollama revienta al cargar, se reintenta bajando primero el
contexto y después las capas en GPU. Se guarda la primera configuración que funciona.

Calor: antes de cada prueba se espera a que la GPU baje de temperatura, cada prueba
genera poco y el modelo se descarga al terminar. Solo una calibración a la vez.
"""

import json
import re
import shutil
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

from .calculadora import (GB, LATENCIA_CAPA_S, Maquina, estimar, penalizacion_contexto,
                          recomendar)
from .ficha import kv_bytes
from . import termico

OLLAMA = "http://localhost:11434"

# Temperaturas: las del gobernador térmico (límite de la GPU, 60 °C por defecto).
# Antes de cada prueba se espera a la de reanudar; si durante la prueba se llega al
# límite, se corta, se enfría y se repite una vez.
ESPERA_MAX_S = 240
MAX_INTENTOS = 5

# Mensajes con los que Ollama y llama.cpp informan de falta de memoria
_OOM = re.compile(
    r"out of memory|cudaMalloc failed|CUDA error|failed to allocate|"
    r"llama runner process has terminated|llama-server process has terminated|"
    r"requires more system memory|insufficient memory|unable to allocate|"
    r"ErrorOutOfDeviceMemory|vk::.*OutOfMemory", re.I)

EN_CURSO = threading.Lock()

Evento = Callable[[Dict[str, Any]], None]


class Cancelado(Exception):
    pass


# ===========================================================================
# Canario
# ===========================================================================

TEXTO_CANARIO = (
    "La regularización L2 añade a la función de pérdida la suma de los cuadrados de "
    "los pesos multiplicada por un coeficiente lambda. Cuanto mayor es lambda, más se "
    "penalizan los pesos grandes y más simple resulta el modelo. A diferencia de la "
    "regularización L1, la L2 no lleva los pesos exactamente a cero, sino que los "
    "reduce de forma proporcional. El descenso de gradiente con L2 equivale a "
    "multiplicar cada peso por un factor ligeramente menor que uno antes de cada "
    "actualización, lo que se conoce como decaimiento de pesos. En redes profundas, "
    "el decaimiento de pesos suele combinarse con la normalización por lotes, aunque "
    "la interacción entre ambas técnicas no es trivial: la normalización hace que la "
    "escala de los pesos sea irrelevante para la salida, y el decaimiento pasa a "
    "controlar sobre todo la tasa de aprendizaje efectiva. El abandono aleatorio, o "
    "dropout, apaga en cada paso una fracción de las neuronas con probabilidad p. "
    "Durante la inferencia no se apaga ninguna neurona y las activaciones se escalan "
    "para conservar el valor esperado. La parada temprana detiene el entrenamiento "
    "cuando el error de validación deja de mejorar durante un número fijo de épocas."
)

PROMPT_CANARIO = (
    "Extrae exactamente 3 afirmaciones del texto. Para cada una da la afirmación "
    "resumida y una cita LITERAL, copiada carácter a carácter del texto, de entre 6 y "
    "15 palabras.\n"
    'Responde solo con JSON: {"afirmaciones": [{"texto": "...", "cita": "..."}]}\n\n'
    "TEXTO:\n" + TEXTO_CANARIO
)


def _normalizar(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip().strip('"«»').lower())


_CITA = re.compile(r'"cita"\s*:\s*"((?:[^"\\]|\\.)*)"')

# Por debajo de esto, la calidad medida no se usa para ordenar modelos
CITAS_MINIMAS = 2


def puntuar_canario(respuesta: str) -> Dict[str, Any]:
    """ 0..1: fracción de citas que están de verdad en el texto.

    Las citas se sacan también de un JSON cortado: la prueba limita los tokens para
    no calentar la GPU, y en la primera versión el tope cortaba el JSON antes de
    cerrar ninguna cita, así que TODOS los modelos puntuaban 0.
    """
    json_valido = True
    try:
        datos = json.loads(respuesta)
        items = datos.get("afirmaciones") if isinstance(datos, dict) else None
        if not isinstance(items, list):
            raise ValueError
        citas = [str(i.get("cita", "")) for i in items if isinstance(i, dict)]
    except Exception:
        json_valido = False
        citas = []
        for bruta in _CITA.findall(respuesta or ""):
            try:
                citas.append(json.loads(f'"{bruta}"'))
            except Exception:
                citas.append(bruta)
    fuente = _normalizar(TEXTO_CANARIO)
    buenas = sum(1 for c in citas if len(_normalizar(c)) >= 15 and _normalizar(c) in fuente)
    calidad = buenas / len(citas) if citas else 0.0
    return {"json_valido": json_valido, "citas": len(citas), "citas_literales": buenas,
            "calidad": round(calidad, 2), "fiable": len(citas) >= CITAS_MINIMAS}


# ===========================================================================
# Sensores
# ===========================================================================

def estado_gpu() -> Optional[Dict[str, float]]:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        salida = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5).stdout
        usado, temp, consumo = [x.strip() for x in salida.splitlines()[0].split(",")]
        return {"vram_mb": float(usado), "temp_c": float(temp),
                "consumo_w": float(consumo) if consumo.replace(".", "").isdigit() else None}
    except Exception:
        return None


class Muestreador(threading.Thread):
    """ Pico de VRAM y temperatura mientras dura la prueba """

    def __init__(self, limite: Optional[float] = None):
        super().__init__(daemon=True)
        self.parar = threading.Event()
        self.limite = limite
        self.vram_pico_mb = 0.0
        self.temp_max = 0.0
        self.caliente = False

    def run(self):
        while not self.parar.is_set():
            e = estado_gpu()
            if e:
                self.vram_pico_mb = max(self.vram_pico_mb, e["vram_mb"])
                self.temp_max = max(self.temp_max, e["temp_c"])
                if self.limite is not None and e["temp_c"] >= self.limite:
                    self.caliente = True
            self.parar.wait(0.5)


class _PorCalor(Exception):
    pass


def esperar_temperatura(avisar: Evento, cancelar: threading.Event,
                        tope: Optional[float] = None, espera_max: float = ESPERA_MAX_S) -> bool:
    tope = termico.gobernador().reanudar if tope is None else tope
    inicio = time.time()
    avisado = False
    while True:
        e = estado_gpu()
        if not e or e["temp_c"] <= tope:
            return True
        if not avisado:
            avisar({"tipo": "enfriando", "temp_c": e["temp_c"],
                    "mensaje": f"La GPU está a {e['temp_c']:.0f} °C; espero a que baje "
                               f"de {tope} °C antes de probar."})
            avisado = True
        if time.time() - inicio > espera_max:
            return False
        if cancelar.wait(5):
            raise Cancelado()


# ===========================================================================
# Ollama
# ===========================================================================

def _post(ruta: str, cuerpo: dict, timeout: float = 600) -> dict:
    req = urllib.request.Request(OLLAMA + ruta, data=json.dumps(cuerpo).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detalle = json.load(e).get("error", "")
        except Exception:
            detalle = str(e)
        raise RuntimeError(detalle or str(e)) from None


def _generar_stream(cuerpo: dict, parar: Callable[[], bool], timeout: float = 600) -> dict:
    """ Genera en streaming para poder cortar si la GPU llega al límite.
    Devuelve el último mensaje (el que trae las estadísticas) con la respuesta entera. """
    req = urllib.request.Request(OLLAMA + "/api/generate",
                                 data=json.dumps({**cuerpo, "stream": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    texto = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for linea in r:
                if not linea.strip():
                    continue
                d = json.loads(linea)
                if d.get("error"):
                    raise RuntimeError(d["error"])
                texto.append(d.get("response", ""))
                if d.get("done"):
                    d["response"] = "".join(texto)
                    return d
                if parar():
                    raise _PorCalor()
    except urllib.error.HTTPError as e:
        try:
            detalle = json.load(e).get("error", "")
        except Exception:
            detalle = str(e)
        raise RuntimeError(detalle or str(e)) from None
    raise RuntimeError("Ollama cerró la respuesta sin terminar")


def _ps(modelo: str) -> Optional[Dict[str, Any]]:
    try:
        with urllib.request.urlopen(OLLAMA + "/api/ps", timeout=5) as r:
            for m in json.load(r).get("models", []):
                if m.get("name") == modelo or m.get("model") == modelo:
                    return m
    except Exception:
        pass
    return None


def descargar(modelo: str):
    try:
        _post("/api/generate", {"model": modelo, "keep_alive": 0}, timeout=30)
    except Exception:
        pass


def es_oom(mensaje: str) -> bool:
    return bool(_OOM.search(mensaje or ""))


# ===========================================================================
# Una prueba
# ===========================================================================

def probar(ficha: Dict[str, Any], opciones: Dict[str, Any], avisar: Evento = lambda e: None,
           cancelar: Optional[threading.Event] = None, num_predict: int = 200,
           dejar_cargado: bool = False, generar: Optional[Callable[..., dict]] = None,
           ps: Optional[Callable[[str], Optional[dict]]] = None) -> Dict[str, Any]:
    """ Carga el modelo con estas opciones, genera el canario y mide.

    `generar` y `ps` se pueden sustituir (pruebas automáticas sin GPU).
    Si revienta por memoria, reintenta: primero menos contexto, luego menos capas.
    """
    cancelar = cancelar or threading.Event()
    muestras: Optional[Muestreador] = None
    generar = generar or (lambda cuerpo: _generar_stream(
        cuerpo, lambda: bool(muestras and muestras.caliente)))
    reintentos_calor = 0
    ps = ps or _ps
    modelo = ficha["nombre"]
    opc = {k: v for k, v in opciones.items() if k in ("num_ctx", "num_gpu")}
    opc.setdefault("num_ctx", 4096)
    think = opciones.get("think")
    intentos: List[Dict[str, Any]] = []

    for n in range(1, MAX_INTENTOS + 1):
        if cancelar.is_set():
            raise Cancelado()
        if not esperar_temperatura(avisar, cancelar):
            return {"ok": False, "modelo": modelo, "opciones": opc, "intentos": intentos,
                    "error": "La GPU no se enfrió a tiempo; prueba cancelada por calor."}
        avisar({"tipo": "intento", "n": n, "modelo": modelo, "opciones": dict(opc),
                "mensaje": f"Probando {modelo} con {opc['num_ctx']} tokens de contexto"
                           + (f" y {opc['num_gpu']} capas en GPU" if "num_gpu" in opc else "")
                           + "…"})
        cuerpo = {"model": modelo, "prompt": PROMPT_CANARIO, "stream": False,
                  "format": "json", "keep_alive": "2m",
                  "options": {**opc, "num_predict": num_predict, "temperature": 0}}
        if ficha.get("piensa"):
            cuerpo["think"] = bool(think) if think is not None else False

        muestras = Muestreador(termico.gobernador().limite)
        muestras.start()
        t0 = time.time()
        por_calor = False
        try:
            d = generar(cuerpo)
            error = None
        except _PorCalor:
            d, error, por_calor = None, None, True
        except Exception as e:
            d, error = None, str(e)
        finally:
            muestras.parar.set()
            muestras.join(timeout=2)
        pared = time.time() - t0

        if por_calor:
            # Cortar la conexión ya detuvo la generación: enfriar y repetir una vez
            if reintentos_calor >= 1:
                descargar(modelo)
                return {"ok": False, "modelo": modelo, "opciones": opc, "intentos": intentos,
                        "temp_max_c": muestras.temp_max,
                        "error": f"La GPU volvió a llegar a {muestras.temp_max:.0f} °C; "
                                 f"prueba cortada. Prueba con un modelo más pequeño."}
            reintentos_calor += 1
            avisar({"tipo": "enfriando", "temp_c": muestras.temp_max,
                    "mensaje": f"La GPU llegó a {muestras.temp_max:.0f} °C: prueba cortada; "
                               f"se repite al enfriar."})
            continue

        if error:
            try:
                from ai_engine.ai_engine_class import explicar_error_motor
                error = explicar_error_motor(error) or error
            except ImportError:
                pass
            oom = es_oom(error)
            intentos.append({"opciones": dict(opc), "error": error[:300], "oom": oom})
            avisar({"tipo": "fallo", "n": n, "oom": oom, "mensaje": error[:300]})
            if not oom:
                return {"ok": False, "modelo": modelo, "opciones": opc,
                        "intentos": intentos, "error": error[:500]}
            siguiente = reducir(ficha, opc)
            if siguiente is None:
                return {"ok": False, "modelo": modelo, "opciones": opc, "intentos": intentos,
                        "error": "No cabe ni con el mínimo de contexto y capas en GPU."}
            descargar(modelo)
            time.sleep(2)
            opc = siguiente
            continue

        cargado = ps(modelo) or {}
        if not dejar_cargado:
            descargar(modelo)
        tam = cargado.get("size") or 0
        en_vram = cargado.get("size_vram") or 0
        gen_s = max(d.get("eval_duration", 0) / 1e9, 1e-6)
        pre_s = max(d.get("prompt_eval_duration", 0) / 1e9, 1e-6)
        resultado = {
            "ok": True, "modelo": modelo, "opciones": dict(opc),
            "tok_s": round(d.get("eval_count", 0) / gen_s, 1),
            "prefill_tok_s": round(d.get("prompt_eval_count", 0) / pre_s, 1),
            "carga_s": round(d.get("load_duration", 0) / 1e9, 1),
            "tokens_generados": d.get("eval_count", 0),
            "tokens_prompt": d.get("prompt_eval_count", 0),
            "total_gb": round(tam / GB, 2) if tam else None,
            "vram_gb": round(en_vram / GB, 2) if tam else None,
            "fraccion_gpu": round(en_vram / tam, 3) if tam else None,
            "vram_pico_mb": muestras.vram_pico_mb or None,
            "temp_max_c": muestras.temp_max or None,
            "segundos": round(pared, 1),
            "canario": puntuar_canario(d.get("response", "")),
            "intentos": intentos,
            "recuperado_de_oom": bool(intentos),
        }
        # Sin citas suficientes la calidad no se sabe: None, no 0 (un 0 hundiría al
        # modelo en el ranking por un fallo de la prueba, no del modelo)
        resultado["calidad"] = (resultado["canario"]["calidad"]
                                if resultado["canario"]["fiable"] else None)
        avisar({"tipo": "medido", **{k: resultado[k] for k in
                ("modelo", "tok_s", "prefill_tok_s", "total_gb", "fraccion_gpu", "calidad")}})
        return resultado

    return {"ok": False, "modelo": modelo, "opciones": opc, "intentos": intentos,
            "error": "Demasiados intentos fallidos."}


def reducir(ficha: Dict[str, Any], opc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """ El siguiente escalón tras una falta de memoria.

    Primero el contexto (hasta 2048): es barato y no cambia la velocidad por token.
    Después las capas en GPU, en saltos de un cuarto: más RAM y menos velocidad,
    pero funciona. Con 0 capas ya no queda nada que quitar a la GPU.
    """
    nueva = dict(opc)
    if nueva.get("num_ctx", 4096) > 2048:
        nueva["num_ctx"] = max(2048, nueva["num_ctx"] // 2)
        return nueva
    capas = (ficha.get("capas") or 32) + 1
    actual = nueva.get("num_gpu", capas)
    if actual <= 0:
        return None
    nueva["num_gpu"] = max(0, actual - max(1, capas // 4))
    return nueva


# ===========================================================================
# Deducir los parámetros de la máquina
# ===========================================================================

def deducir(ficha: Dict[str, Any], r: Dict[str, Any], maq: Maquina) -> Dict[str, Any]:
    """ Despeja lo que la prueba permite saber. Devuelve solo lo medido. """
    if not r.get("ok") or not r.get("tok_s") or not r.get("total_gb"):
        return {}
    if "num_gpu" in r["opciones"]:
        # Capas forzadas por una recuperación: no es el reparto automático
        return {}
    ctx = r["opciones"]["num_ctx"]
    activos = ficha["bytes_peso"] * ficha.get("fraccion_activa", 1.0) / GB
    # Segundos por token que se van en leer pesos (sin el coste fijo por capa)
    t = 1 / (r["tok_s"] * penalizacion_contexto(ctx))
    t = max(t * 0.2, t - (ficha.get("capas") or 32) * LATENCIA_CAPA_S)
    frac = r["fraccion_gpu"] or 0.0
    total = r["total_gb"] * GB
    cache = kv_bytes(ficha, ctx, 1, "f16")
    base = ficha["bytes_peso"] + cache
    datos: Dict[str, Any] = {}

    if not maq.hay_gpu or frac <= 0.02:
        datos["ancho_cpu"] = round(activos / t, 1)
        return datos
    if frac >= 0.99:
        datos["ancho_gpu"] = round(activos / t, 1)
        datos["overhead_entero"] = total - base
        # Cabe entero: el presupuesto es al menos esto
        datos["presupuesto_minimo"] = total
        return datos

    datos["vram_parcial"] = frac * total
    datos["presupuesto_gpu"] = frac * total + 0.1 * GB
    datos["overhead_parcial"] = total - base
    resto = t - frac * activos / maq.ancho_gpu
    if resto > 0:
        ancho_cpu = (1 - frac) * activos / resto
        if 3 <= ancho_cpu <= 400:          # fuera de esto la medida es ruido
            datos["ancho_cpu"] = round(ancho_cpu, 1)
    return datos


def combinar(previa: Optional[Dict[str, Any]], nuevas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """ Mediana de todas las muestras de cada parámetro, las viejas incluidas """
    muestras: Dict[str, List[float]] = {k: list(v) for k, v in
                                        ((previa or {}).get("muestras") or {}).items()}
    for n in nuevas:
        for k, v in n.items():
            if isinstance(v, (int, float)):
                muestras.setdefault(k, []).append(float(v))
    valores: Dict[str, Any] = {}
    for k, vs in muestras.items():
        muestras[k] = vs[-9:]
        valores[k] = statistics.median(muestras[k])
    # El presupuesto nunca por debajo de lo que se vio caber entero
    if "presupuesto_minimo" in valores:
        minimo = max(muestras["presupuesto_minimo"])
        if valores.get("presupuesto_gpu", 0) < minimo:
            valores["presupuesto_gpu"] = minimo
            valores.setdefault("vram_parcial", minimo - 0.1 * GB)
        del valores["presupuesto_minimo"]
    valores["muestras"] = muestras
    return valores


# ===========================================================================
# Calibración completa
# ===========================================================================

def elegir_modelos_prueba(fichas: List[Dict[str, Any]], maq: Maquina) -> List[Dict[str, Any]]:
    """ Dos modelos instalados que den información distinta.

    Uno que quepa entero (mide la GPU) y uno que se reparta (mide el presupuesto y
    la RAM). De cada clase el más pequeño que sirva: carga antes y calienta menos.
    Sin GPU, uno pequeño basta.
    """
    candidatos = [f for f in fichas if not f.get("embedding") and not f.get("estimada")
                  and f.get("bytes_peso")]
    candidatos.sort(key=lambda f: f["bytes_peso"])
    if not maq.hay_gpu:
        return candidatos[:1]
    enteros, repartidos = [], []
    for f in candidatos:
        e = estimar(f, maq, 4096)
        if e["riesgo_swap"]:
            continue
        if e["donde"] == "gpu":
            enteros.append(f)
        elif e["donde"] == "repartido" and 0.25 <= e["fraccion_gpu"] <= 0.9:
            repartidos.append(f)
    # Para medir la GPU conviene el más grande que cabe: menos ruido fijo por token
    elegidos = enteros[-1:] + repartidos[:1]
    return elegidos or candidatos[:1]


def calibrar(fichas: List[Dict[str, Any]], maq: Maquina, avisar: Evento = lambda e: None,
             cancelar: Optional[threading.Event] = None,
             previa: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not EN_CURSO.acquire(blocking=False):
        raise RuntimeError("Ya hay una calibración en marcha.")
    cancelar = cancelar or threading.Event()
    try:
        elegidos = elegir_modelos_prueba(fichas, maq)
        if not elegidos:
            return {"ok": False, "error": "No hay ningún modelo instalado con el que medir."}
        avisar({"tipo": "plan", "modelos": [f["nombre"] for f in elegidos],
                "mensaje": "Voy a medir con " + " y ".join(f["nombre"] for f in elegidos)
                           + ". Cada prueba dura unos segundos y el modelo se descarga al "
                             "terminar."})
        pruebas, deducidos = [], []
        for f in elegidos:
            r = probar(f, {"num_ctx": 4096}, avisar, cancelar)
            prevista = estimar(f, maq, r["opciones"].get("num_ctx", 4096))
            r["prevision"] = {k: prevista[k] for k in ("tok_s", "total_gb", "fraccion_gpu")}
            pruebas.append(r)
            d = deducir(f, r, maq)
            if d:
                deducidos.append(d)
                # Lo recién medido de la GPU sirve para despejar la CPU en la siguiente
                maq = Maquina(maq.radiografia, combinar(previa, deducidos))
            time.sleep(3)
        if not deducidos:
            return {"ok": False, "pruebas": pruebas,
                    "error": next((p.get("error") for p in pruebas if p.get("error")),
                                  "Las pruebas no dieron medidas utilizables.")}
        valores = combinar(previa, deducidos)
        avisar({"tipo": "calibrado", "valores": {k: v for k, v in valores.items()
                                                 if k != "muestras"}})
        return {"ok": True, "valores": valores, "pruebas": pruebas}
    finally:
        EN_CURSO.release()


def probar_recomendacion(ficha: Dict[str, Any], maq: Maquina, perfil: str, tirador: str,
                         avisar: Evento = lambda e: None,
                         cancelar: Optional[threading.Event] = None) -> Dict[str, Any]:
    """ El botón "Probar": la recomendación con la máquina, y la comparación """
    if not EN_CURSO.acquire(blocking=False):
        raise RuntimeError("Ya hay una prueba o calibración en marcha.")
    try:
        rec = recomendar(ficha, maq, perfil, tirador)
        if rec["veredicto"] == "no_viable":
            return {"ok": False, "error": rec["motivo"], "recomendacion": rec}
        r = probar(ficha, rec["opciones"], avisar, cancelar)
        r["recomendacion"] = rec
        if r.get("ok"):
            prev = rec["estimacion"]
            r["desvio"] = {
                "tok_s_pct": round(100 * (r["tok_s"] - prev["tok_s"]) / max(prev["tok_s"], 0.1)),
                "total_gb_pct": (round(100 * (r["total_gb"] - prev["total_gb"])
                                       / max(prev["total_gb"], 0.01))
                                 if r.get("total_gb") else None),
            }
            r["deducido"] = deducir(ficha, r, maq)
            if r["opciones"] != {k: v for k, v in rec["opciones"].items()
                                 if k in ("num_ctx", "num_gpu")}:
                r["aviso"] = ("La recomendación no cupo tal cual: funcionó con "
                              f"{r['opciones']}. Se usará esto.")
        return r
    finally:
        EN_CURSO.release()
