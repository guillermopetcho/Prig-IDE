"""
Calculadora: cuánta memoria ocupará un modelo, dónde irá y a qué velocidad.

Las fórmulas están calibradas contra mediciones reales, no contra hojas de datos.
Sobre una RTX 4050 portátil de 6 GB, con qwen2.5-coder:7b, qwen3:14b y
qwen3:30b-a3b a contextos de 2048, 4096 y 8192:

    memoria total        error medio 0,3 %   (máximo 0,5 %)
    reparto GPU/CPU      exacto a un punto
    velocidad            error medio 11 %    (máximo 24 %)

MEMORIA. Total = pesos + caché KV + búfer de cómputo. El búfer resultó casi
constante: −0,15 GB cuando el modelo cabe entero (parte del vocabulario se queda en
RAM) y +0,25 GB cuando se reparte entre GPU y CPU.

HASTA DÓNDE LLENA OLLAMA LA GPU. Nunca pasó de 4,85 GB en una tarjeta de 6,1. Forzar
más capas a mano no aceleró nada (14B con 22 capas: 5,9 tok/s, igual que con las
automáticas) y con 24 reventó por falta de memoria. Por eso esta calculadora predice
el reparto automático de Ollama en lugar de pelearse con él.

VELOCIDAD. Generar un token obliga a leer los parámetros activos una vez. Lo que va
en GPU se lee a la velocidad de la VRAM y lo que va en RAM a la de la RAM:

    t_token = fracción_gpu × activos / ancho_gpu  +  (1 − fracción_gpu) × activos / ancho_cpu

En un MoE los activos son una fracción pequeña del total (3,4 B de 30,5 B en
qwen3:30b-a3b), y por eso va a 22-28 tok/s con solo el 25 % en GPU mientras un 14B
denso con el 48 % va a 6.
"""

import math
from typing import Any, Dict, List, Optional

from .ficha import kv_bytes
from .perfiles import perfil as obtener_perfil

GB = 1e9

# Valores medidos en la máquina de referencia. Solo se usan hasta que la calibración
# de la máquina del usuario los sustituye por los suyos.
OVERHEAD_ENTERO = -0.15 * GB
OVERHEAD_PARCIAL = 0.25 * GB
MARGEN_RAM = 3 * GB            # lo que se deja al sistema antes de hablar de swap
FACTOR_BANCO_RAM = 3.75        # medida en Python puro → ancho efectivo en inferencia

# Ancho de banda de memoria de GPUs conocidas, en GB/s. El efectivo en inferencia
# resultó ser un 93 % del nominal (RTX 4050 portátil: 192 nominal, 178 medido).
ANCHO_GPU = {
    "rtx 4050": 192, "rtx 4060 laptop": 192, "rtx 4060 ti": 288, "rtx 4060": 272,
    "rtx 4070 laptop": 256, "rtx 4070 ti": 504, "rtx 4070": 504, "rtx 4080": 717,
    "rtx 4090": 1008, "rtx 3050": 224, "rtx 3060 laptop": 336, "rtx 3060": 360,
    "rtx 3070": 448, "rtx 3080": 760, "rtx 3090": 936, "rtx 2060": 336,
    "rtx 2070": 448, "rtx 2080": 448, "gtx 1660": 192, "gtx 1650": 128,
    "rtx 5060": 448, "rtx 5070": 672, "rtx 5080": 960, "rtx 5090": 1792,
    "rx 7900": 800, "rx 7800": 576, "rx 7600": 288, "rx 6700": 360,
    "m1 max": 400, "m1 pro": 200, "m1": 68, "m2 max": 400, "m2 pro": 200, "m2": 100,
    "m3 max": 400, "m3 pro": 150, "m3": 100, "m4 max": 546, "m4 pro": 273, "m4": 120,
}
EFICIENCIA_GPU = 0.93


class Maquina:
    """ Lo que la calculadora necesita saber de la máquina, ya destilado.

    Mezcla la radiografía del detector con lo calibrado. Cada valor recuerda de
    dónde sale ("medido" o "previo") para poder decir al usuario cuánto fiarse.
    """

    def __init__(self, radiografia: Dict[str, Any],
                 calibracion: Optional[Dict[str, Any]] = None):
        cal = calibracion or {}
        self.radiografia = radiografia
        gpus = radiografia.get("gpus") or []
        g = gpus[0] if gpus else None
        mem = radiografia.get("memoria") or {}

        self.hay_gpu = g is not None
        self.gpu_nombre = g.get("nombre", "") if g else ""
        self.unificada = bool(g and g.get("memoria_unificada"))
        self.vram_total = (g.get("vram_total_mb") or 0) * 1024 ** 2 if g else 0
        ajena = sum(p.get("mb", 0) for p in (g or {}).get("otros_procesos", [])) * 1024 ** 2
        self.vram_libre = max(0, self.vram_total - ajena)
        self.ram_disponible = mem.get("ram_disponible", 0)
        self.ram_total = mem.get("ram_total", 0)
        self.nucleos = (radiografia.get("cpu") or {}).get("nucleos_fisicos", 1)
        self.flash_attention = bool(g and g.get("flash_attention"))

        # Hasta dónde llena Ollama la GPU. Previo: reserva del 25 % con límites.
        if "presupuesto_gpu" in cal:
            self.presupuesto_gpu = cal["presupuesto_gpu"]
            self.origen_presupuesto = "medido"
        else:
            reserva = min(1.6 * GB, max(0.6 * GB, 0.245 * self.vram_total))
            self.presupuesto_gpu = max(0, self.vram_libre - reserva)
            self.origen_presupuesto = "previo"
        self.vram_parcial = cal.get("vram_parcial", self.presupuesto_gpu - 0.1 * GB)

        if "ancho_gpu" in cal:
            self.ancho_gpu, self.origen_ancho_gpu = cal["ancho_gpu"], "medido"
        else:
            self.ancho_gpu = self._ancho_gpu_previo()
            self.origen_ancho_gpu = "previo"

        if "ancho_cpu" in cal:
            self.ancho_cpu, self.origen_ancho_cpu = cal["ancho_cpu"], "medido"
        else:
            banco = radiografia.get("ancho_banda_ram_gbps") or 10
            self.ancho_cpu = max(10.0, min(120.0, banco * FACTOR_BANCO_RAM))
            self.origen_ancho_cpu = "previo"

        self.overhead_entero = cal.get("overhead_entero", OVERHEAD_ENTERO)
        self.overhead_parcial = cal.get("overhead_parcial", OVERHEAD_PARCIAL)

        # Ajustes que son del SERVIDOR y no de cada petición. Un único Ollama no puede
        # tener la caché en q8_0 para el tutor y en f16 para la extracción a la vez,
        # ni dos ranuras para un modelo y una para otro.
        entorno = (radiografia.get("ollama") or {}).get("entorno") or {}
        self.servidor = servidor_efectivo(entorno)

    def _ancho_gpu_previo(self) -> float:
        nombre = self.gpu_nombre.lower()
        # Las claves más largas primero: "rtx 4060 ti" antes que "rtx 4060"
        for clave in sorted(ANCHO_GPU, key=len, reverse=True):
            if clave in nombre:
                return ANCHO_GPU[clave] * EFICIENCIA_GPU
        return 200.0 * EFICIENCIA_GPU

    @property
    def calibrada(self) -> bool:
        return "medido" in (self.origen_presupuesto, self.origen_ancho_gpu,
                            self.origen_ancho_cpu)

    def resumen(self) -> Dict[str, Any]:
        return {
            "gpu": self.gpu_nombre or "sin GPU",
            "vram_total_gb": round(self.vram_total / GB, 2),
            "vram_libre_gb": round(self.vram_libre / GB, 2),
            "presupuesto_gpu_gb": round(self.presupuesto_gpu / GB, 2),
            "ram_disponible_gb": round(self.ram_disponible / GB, 1),
            "ancho_gpu_gbps": round(self.ancho_gpu),
            "ancho_cpu_gbps": round(self.ancho_cpu),
            "memoria_unificada": self.unificada,
            "origen": {"presupuesto": self.origen_presupuesto,
                       "ancho_gpu": self.origen_ancho_gpu,
                       "ancho_cpu": self.origen_ancho_cpu},
        }


# ===========================================================================
# Estimar una configuración concreta
# ===========================================================================

def servidor_efectivo(entorno: Dict[str, str]) -> Dict[str, Any]:
    """ Lo que el servidor aplica de verdad, rellenando los valores por defecto """
    def entero(v, defecto):
        try:
            return max(1, int(v))
        except (TypeError, ValueError):
            return defecto
    return {
        "kv": (entorno.get("OLLAMA_KV_CACHE_TYPE") or "f16").lower(),
        "paralelo": entero(entorno.get("OLLAMA_NUM_PARALLEL"), 1),
        "flash_attention": str(entorno.get("OLLAMA_FLASH_ATTENTION", "")).lower()
                           in ("1", "true", "yes"),
        "max_modelos": entero(entorno.get("OLLAMA_MAX_LOADED_MODELS"), 0) or None,
    }


def penalizacion_contexto(ctx: int) -> float:
    """ La atención cuesta más cuanto más contexto: ~3,5 % cada vez que se dobla """
    return 1 + 0.035 * math.log2(max(ctx, 2048) / 2048)


def estimar(ficha: Dict[str, Any], maq: Maquina, ctx: int,
            paralelo: int = 1, kv: str = "f16") -> Dict[str, Any]:
    peso = ficha["bytes_peso"]
    cache = kv_bytes(ficha, ctx, paralelo, kv)
    activos = peso * ficha.get("fraccion_activa", 1.0) / GB

    if not maq.hay_gpu:
        total, frac, donde = peso + cache + maq.overhead_parcial, 0.0, "cpu"
    else:
        entero = peso + cache + maq.overhead_entero
        if entero <= maq.presupuesto_gpu:
            total, frac, donde = entero, 1.0, "gpu"
        else:
            total = peso + cache + maq.overhead_parcial
            frac = min(1.0, max(0.0, maq.vram_parcial / total)) if maq.vram_parcial > 0 else 0.0
            donde = "repartido" if frac > 0.02 else "cpu"

    en_gpu = total * frac
    en_ram = total - en_gpu
    # En memoria unificada, lo de la "GPU" también sale de la RAM
    ram_necesaria = total if maq.unificada else en_ram

    t = 0.0
    if frac > 0:
        t += frac * activos / maq.ancho_gpu
    if frac < 1:
        t += (1 - frac) * activos / maq.ancho_cpu
    if t > 0:
        t += (ficha.get("capas") or 32) * LATENCIA_CAPA_S
    tok_s = (1 / t / penalizacion_contexto(ctx)) if t > 0 else 0.0

    cabe_en_ram = ram_necesaria <= max(0, maq.ram_disponible - MARGEN_RAM)
    return {
        "ctx": ctx, "paralelo": paralelo, "kv": kv,
        "total_gb": round(total / GB, 2),
        "cache_gb": round(cache / GB, 2),
        "en_gpu_gb": round(en_gpu / GB, 2),
        "en_ram_gb": round(en_ram / GB, 2),
        "fraccion_gpu": round(frac, 3),
        "donde": donde,
        "tok_s": round(tok_s, 1),
        # Error medido de la fórmula: ±25 % en el peor caso
        "tok_s_rango": [round(tok_s * 0.75, 1), round(tok_s * 1.25, 1)],
        "cabe_en_ram": cabe_en_ram,
        "riesgo_swap": not cabe_en_ram,
    }


# ===========================================================================
# Veredicto y recomendación
# ===========================================================================

VEREDICTOS = {
    "entero": "Entero en GPU",
    "ajustando": "Entero ajustando",
    "parcial": "Repartido GPU + RAM",
    "lento": "Cabe, pero lento para esto",
    "solo_cpu": "Solo CPU",
    "no_viable": "No viable",
    "embeddings": "Embeddings en CPU",
}


def _candidatos(ficha, prf, tirador, paralelo_servidor: int = 1) -> List[Dict[str, Any]]:
    """ Combinaciones que tiene sentido probar para este perfil """
    tope = min(prf["ctx_max"], ficha.get("contexto_max") or prf["ctx_max"])
    contextos = sorted({c for c in (prf["ctx_min"], prf["ctx_preferido"], 4096, 8192,
                                    16384, prf["ctx_max"])
                        if prf["ctx_min"] <= c <= tope}) or [prf["ctx_min"]]
    kvs = ["f16"] + (["q8_0"] if prf["kv_cuantizable"] and tirador != "calidad" else [])
    paralelos = sorted({1, prf["paralelo_deseado"], paralelo_servidor})
    return [{"ctx": c, "kv": k, "paralelo": p}
            for c in contextos for k in kvs for p in paralelos]


def recomendar(ficha: Dict[str, Any], maq: Maquina, nombre_perfil: str,
               tirador: str = "equilibrado") -> Dict[str, Any]:
    prf = obtener_perfil(nombre_perfil)

    if ficha.get("embedding"):
        est = estimar(ficha, Maquina({**maq.radiografia, "gpus": []}), 512)
        return {
            "modelo": ficha["nombre"], "perfil": nombre_perfil, "tirador": tirador,
            "veredicto": "embeddings" if est["cabe_en_ram"] else "no_viable",
            "etiqueta": VEREDICTOS["embeddings"],
            "opciones": {"num_gpu": 0, "keep_alive": "30m"},
            "estimacion": est,
            "motivo": ("Un embebedor no genera texto: se deja en CPU para que el "
                       "generador tenga la GPU entera. Medido: 72 ms por pregunta y "
                       "ninguna recarga del generador."),
            "alternativas": [],
        }

    srv = maq.servidor
    todas = []
    for cand in _candidatos(ficha, prf, tirador, srv["paralelo"]):
        est = estimar(ficha, maq, cand["ctx"], cand["paralelo"], cand["kv"])
        if est["riesgo_swap"]:
            continue
        todas.append(est)

    # Lo que se puede aplicar YA, sin tocar el servidor. Las ranuras tienen que ser
    # exactamente las del servidor: Ollama reserva caché para todas aunque la
    # petición sea una sola, así que suponer menos subestimaría la memoria.
    estimaciones = [e for e in todas
                    if e["kv"] == srv["kv"] and e["paralelo"] == srv["paralelo"]]
    if not estimaciones and todas:
        # El servidor tiene una caché que este uso no admite (q8_0 para extraer):
        # se evalúa igualmente con su configuración real, y se avisa.
        for ctx in sorted({e["ctx"] for e in todas}):
            est = estimar(ficha, maq, ctx, srv["paralelo"], srv["kv"])
            if not est["riesgo_swap"]:
                estimaciones.append(est)

    if not estimaciones:
        minimo = estimar(ficha, maq, prf["ctx_min"])
        return _sin_opcion(ficha, prf, tirador, minimo,
                           f"Necesita {minimo['en_ram_gb'] if not maq.unificada else minimo['total_gb']} GB "
                           f"de RAM y hay {round(maq.ram_disponible / GB, 1)} GB disponibles. "
                           f"Paginaría a disco y dejaría de responder.")

    elegida = max(estimaciones, key=lambda e: _puntuar(e, prf, tirador))
    veredicto = _veredicto(elegida, estimaciones, prf, maq)
    alternativas = sorted(
        (e for e in estimaciones if e is not elegida),
        key=lambda e: _puntuar(e, prf, tirador), reverse=True)[:3]

    return {
        "modelo": ficha["nombre"], "perfil": nombre_perfil, "tirador": tirador,
        "veredicto": veredicto, "etiqueta": VEREDICTOS[veredicto],
        "opciones": _opciones(elegida, prf, ficha),
        "estimacion": elegida,
        "motivo": _motivo(ficha, elegida, veredicto, prf, maq),
        "alternativas": alternativas,
        "mejora_con_servidor": _mejora_servidor(ficha, elegida, todas, prf, tirador, maq),
        "aviso_servidor": _aviso_servidor(prf, srv),
        "fiabilidad": "calibrada" if maq.calibrada else "estimada",
        "ficha_estimada": bool(ficha.get("estimada")),
    }


def _aviso_servidor(prf, srv) -> Optional[str]:
    if srv["kv"] != "f16" and not prf["kv_cuantizable"]:
        return (f"El servidor tiene la caché en {srv['kv']}. Para "
                f"{prf['nombre'].lower()} eso resta exactitud (medido en extracción: citas "
                f"verificadas del 100 % al 79 %). Conviene volver a f16 antes de este trabajo.")
    return None


def _mejora_servidor(ficha, actual, todas, prf, tirador, maq) -> Optional[Dict[str, Any]]:
    """ Qué se ganaría cambiando el servidor, y qué se perdería.

    Solo se propone si la mejora es clara (otro tramo de velocidad, o pasar de
    repartido a entero). Cambiar la caché a q8_0 SIEMPRE lleva el aviso de lo que
    cuesta en extracción, porque es un ajuste común a todos los usos.
    """
    if not todas:
        return None
    mejor = max(todas, key=lambda e: _puntuar(e, prf, tirador))
    if mejor["kv"] == actual["kv"] and mejor["paralelo"] == actual["paralelo"]:
        return None
    gana = (_puntuar(mejor, prf, tirador) > _puntuar(actual, prf, tirador)
            and (round(rendimiento(mejor) / 5) > round(rendimiento(actual) / 5)
                 or (mejor["donde"] == "gpu" and actual["donde"] != "gpu")))
    # Volver a una caché exacta en un uso que la necesita se propone siempre
    if actual["kv"] != "f16" and mejor["kv"] == "f16" and not prf["kv_cuantizable"]:
        gana = True
    if not gana:
        return None

    cambios, contras = {}, []
    if mejor["kv"] != maq.servidor["kv"]:
        cambios["OLLAMA_KV_CACHE_TYPE"] = mejor["kv"]
        if mejor["kv"] != "f16":
            contras.append("Afecta a TODOS los usos: medido, la caché q8_0 bajó las citas "
                           "verificadas de la extracción del 100 % al 79 %.")
    if mejor["paralelo"] != maq.servidor["paralelo"]:
        cambios["OLLAMA_NUM_PARALLEL"] = str(mejor["paralelo"])
        contras.append(f"Cada ranura reserva su propia caché: con {mejor['paralelo']} "
                       f"ranuras los demás modelos tienen menos sitio en GPU.")
    if cambios.get("OLLAMA_KV_CACHE_TYPE") == "f16":
        contras.append("El tutor pierde la caché compacta: le cabe menos contexto en GPU.")
    return {
        "cambios": cambios,
        "estimacion": mejor,
        "ganancia": (f"{actual['tok_s']} → {mejor['tok_s']} tok/s"
                     + (f", y pasa a caber entero en la GPU"
                        if mejor["donde"] == "gpu" and actual["donde"] != "gpu" else "")),
        "contras": contras,
        "requiere_reiniciar": True,
    }


# Medido: dos peticiones simultáneas rinden 1,32 veces lo que una, no el doble. Cada
# ranura extra reserva su propia caché y comparte la misma GPU.
# Coste fijo por capa y token (lanzar núcleos, enrutar expertos, sincronizar). En la
# máquina de referencia sube el error medio de velocidad del 9,5 % al 11,5 % sin
# mover el máximo (24 %); sin él, en una GPU grande donde leer pesos ya no es el
# cuello de botella, un MoE salía a 440 tok/s cuando rinde en torno a 200.
LATENCIA_CAPA_S = 0.04e-3

GANANCIA_RANURA = 0.32


def rendimiento(e: Dict[str, Any]) -> float:
    """ Tokens por segundo sumando todas las ranuras """
    return e["tok_s"] * (1 + GANANCIA_RANURA * (e["paralelo"] - 1))


def _puntuar(e: Dict[str, Any], prf: Dict[str, Any], tirador: str) -> tuple:
    """ Orden de preferencia entre combinaciones, de lo que más pesa a lo que menos.

    Es una tupla y no una suma de puntos a propósito: con pesos, un ajuste pequeño
    en una constante cambia la recomendación de forma imposible de prever. Con una
    tupla se lee directamente qué se sacrifica antes.
    """
    util = e["tok_s_rango"][0] >= prf["tok_s_min"]      # con la cota baja, como _veredicto
    ctx_llega = min(e["ctx"], prf["ctx_preferido"]) / prf["ctx_preferido"]
    sin_exceso = e["ctx"] <= prf["ctx_preferido"]
    kv_exacta = e["kv"] == "f16"
    rend = rendimiento(e)
    # Tramos de 5 tok/s: diferencias menores son ruido (error medio medido: 11 %)
    tramo = round(rend / 5)

    if tirador == "calidad":
        return (util, kv_exacta, ctx_llega, sin_exceso, rend)
    if tirador == "velocidad":
        return (util, tramo, ctx_llega, kv_exacta, rend)
    # Equilibrado: el contexto que pide la tarea, la precisión si la tarea la exige,
    # y dentro de eso lo más rápido. Si la tarea tolera cuantizar la caché, eso no
    # cuenta como pérdida: es justo lo que permite meter el modelo entero en GPU.
    precision = kv_exacta if not prf["kv_cuantizable"] else True
    return (util, ctx_llega, precision, tramo, sin_exceso, kv_exacta, rend)


def _veredicto(e, todas, prf, maq) -> str:
    if not maq.hay_gpu:
        return "solo_cpu" if e["tok_s_rango"][0] >= prf["tok_s_min"] else "lento"
    if e["tok_s"] < 1.0:
        return "no_viable"
    # Frontera de "lento" con la cota baja del error (±25 %): un 14B estimado en
    # 8,5 tok/s para un mínimo de 8 midió 4,7. Prometer lo justo y quedarse corto
    # es peor que avisar de más.
    lento = e["tok_s_rango"][0] < prf["tok_s_min"]
    if e["donde"] == "gpu":
        preferida_entera = any(x["donde"] == "gpu" and x["ctx"] >= prf["ctx_preferido"]
                               and x["kv"] == "f16" for x in todas)
        return "entero" if preferida_entera else "ajustando"
    if lento:
        return "lento"
    return "parcial" if e["donde"] == "repartido" else "solo_cpu"


def _opciones(e, prf, ficha) -> Dict[str, Any]:
    """ Lo que se manda en cada petición.

    `num_gpu` NO se fija: medido que forzar capas por encima del reparto automático
    no acelera y provoca falta de memoria. Solo se baja al recuperarse de un OOM.
    """
    opc = {"num_ctx": e["ctx"], "keep_alive": prf["keep_alive"]}
    if ficha.get("piensa") and prf["pensar"] in (True, False):
        opc["think"] = prf["pensar"]
    return opc


def _motivo(ficha, e, veredicto, prf, maq) -> str:
    nombre = ficha["nombre"]
    if veredicto in ("entero", "ajustando"):
        libre = max(0.0, maq.vram_total / GB - e["total_gb"])
        texto = (f"Cabe entero en la GPU: ocupa {e['total_gb']} GB de tus "
                 f"{round(maq.vram_total / GB, 1)} (quedan {libre:.1f} GB). "
                 f"Contexto de {e['ctx']} tokens a unos {e['tok_s']} tok/s.")
        if veredicto == "ajustando":
            texto += (f" Para caber hubo que bajar a {e['ctx']} tokens"
                      + (" y cuantizar la caché" if e["kv"] != "f16" else "") + ".")
        return texto
    if veredicto == "parcial":
        base = (f"No cabe entero: {e['en_gpu_gb']} GB van a la GPU y {e['en_ram_gb']} GB "
                f"a la RAM ({round(e['fraccion_gpu'] * 100)} % en GPU). ")
        if ficha.get("es_moe"):
            base += (f"Aun así va rápido, unos {e['tok_s']} tok/s: es una mezcla de "
                     f"expertos y por cada token solo lee "
                     f"{round(ficha['parametros_activos'] / 1e9, 1)} B de sus "
                     f"{round(ficha['parametros'] / 1e9, 1)} B de parámetros.")
        else:
            base += f"Unos {e['tok_s']} tok/s, suficiente para {prf['nombre'].lower()}."
        return base
    if veredicto == "lento":
        return (f"Funciona, pero a unos {e['tok_s']} tok/s y {prf['nombre'].lower()} "
                f"necesita al menos {prf['tok_s_min']}. Sirve para tareas cortas y "
                f"puntuales.")
    if veredicto == "solo_cpu":
        return f"Sin GPU útil: todo en RAM a unos {e['tok_s']} tok/s."
    return f"{nombre} no es viable en esta máquina para este uso."


def _sin_opcion(ficha, prf, tirador, est, motivo) -> Dict[str, Any]:
    return {"modelo": ficha["nombre"], "perfil": prf["id"], "tirador": tirador,
            "veredicto": "no_viable", "etiqueta": VEREDICTOS["no_viable"],
            "opciones": {}, "estimacion": est, "motivo": motivo, "alternativas": [],
            "fiabilidad": "estimada", "ficha_estimada": bool(ficha.get("estimada"))}


# ===========================================================================
# Qué modelo usar
# ===========================================================================

def calidad_esperada(ficha: Dict[str, Any]) -> float:
    """ Una aproximación a "cuánto sabe" un modelo, para ordenar candidatos.

    En un MoE no vale el total ni los activos. La media geométrica, la regla
    habitual, lo infravalora en los MoE de expertos finos: daba 10 B para
    Qwen3-30B-A3B, y en el informe técnico de Qwen3 ese modelo empata con Qwen3-14B
    (MMLU 81,4 frente a 81,1; GSM8K 91,8 frente a 92,5). Ponderar 0,7 el total y
    0,3 los activos da 15,7 B, en línea con eso. Las familias recientes rinden más
    por parámetro. Es una heurística para ORDENAR; lo medido en la calibración manda.
    """
    total = ficha.get("parametros", 0) / 1e9
    activos = ficha.get("parametros_activos", 0) / 1e9
    efectivo = (total ** 0.7 * activos ** 0.3) if ficha.get("es_moe") else total
    arch = (ficha.get("arquitectura") or "").lower()
    generacion = 1.25 if arch.startswith(("qwen3", "gemma3", "llama4")) else 1.0
    return efectivo * generacion


def elegir_modelo(fichas: List[Dict[str, Any]], maq: Maquina, nombre_perfil: str,
                  tirador: str = "equilibrado",
                  medidas: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """ Modelos instalados ordenados de mejor a peor para este uso """
    prf = obtener_perfil(nombre_perfil)
    medidas = medidas or {}
    filas = []
    for f in fichas:
        if f.get("embedding"):
            continue
        r = recomendar(f, maq, nombre_perfil, tirador)
        util = r["veredicto"] in ("entero", "ajustando", "parcial", "solo_cpu")
        calidad = calidad_esperada(f)
        medida = medidas.get(f["nombre"], {})
        if medida.get("calidad") is not None:
            calidad *= 0.5 + medida["calidad"]          # 0..1 medido en el canario
        vel = r["estimacion"].get("tok_s", 0)
        if tirador == "velocidad":
            puntos = vel * (2 if util else 0.1) + calidad
        elif tirador == "calidad":
            puntos = calidad * (10 if util else 1) + vel * 0.1
        else:
            puntos = (calidad * 4 + min(vel, prf["tok_s_min"] * 3)) * (1 if util else 0.1)
        # Pensar en voz alta ayuda a revisar y estorba a extraer
        if f.get("piensa") and nombre_perfil in ("revision", "flujos"):
            puntos *= 1.15
        filas.append({**r, "puntos": round(puntos, 2), "util": util,
                      "calidad_esperada": round(calidad, 1)})
    return sorted(filas, key=lambda x: -x["puntos"])
