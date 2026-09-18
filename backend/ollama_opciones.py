"""
Todo lo configurable de los modelos de Ollama, y en qué capa lo decide el usuario.

SOLO LO QUE FUNCIONA. Cada opción de este catálogo se probó contra el Ollama de Prig
(0.34.1, motor llama-server) midiendo su EFECTO, no solo que la API la acepte:
salida distinta con la misma semilla, memoria en /api/ps, argumentos con los que
arranca el motor, velocidad o respuesta del servidor. Las que dan error o se
aceptan sin cambiar nada están en EXCLUIDAS con el motivo, y nunca se envían: una
opción que no hace nada es un interruptor falso en la pantalla.

CAPAS. Un valor puede fijarse en cuatro sitios, de menos a más prioridad:

    global            todos los modelos
    modelo            un modelo concreto (p. ej. qwen3:14b)
    uso               una tarea (tutor, flujos, extracción, revisión, autocompletado)
    modelo_uso        ese modelo en esa tarea

Lo que no se fija en ninguna capa NO se envía, y Ollama usa lo que trae el modelo en
su Modelfile. Antes Prig mandaba temperatura 0.3, top_k 40, top_p 0.9 y
repeat_penalty 1.1 a todos los modelos, y Qwen3 (que pide 0.6 / 20 / 0.95 / 1.0)
funcionaba peor de lo previsto.

Por encima de las capas solo están las opciones que una tarea exige por diseño
(la calibración, el canario de extracción, un paso JSON de un flujo): las pone quien
llama y mandan.
"""

import copy
import json
import os
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple

CAPAS = ("global", "modelo", "uso", "modelo_uso")

USOS = {
    "tutor": "Tutor y chat",
    "flujos": "Flujos de agentes",
    "extraccion": "Extracción de libros",
    "revision": "Revisión final",
    "autocompletado": "Autocompletado de código",
    "embeddings": "Embeddings (índice semántico)",
}

# ---------------------------------------------------------------------------
# Opciones del motor (van en "options")
# ---------------------------------------------------------------------------
# prueba: cómo se verificó en esta máquina (se enseña al usuario)

OPCIONES: List[Dict[str, Any]] = [
    # ---- Muestreo
    dict(clave="temperature", grupo="Muestreo", nombre="Temperatura", tipo="float", min=0, max=2, paso=0.05,
         ayuda="Creatividad frente a precisión. 0 es determinista; 0.2-0.4 para código; 0.7-1 para ideas.",
         prueba="Con 0 la salida pasa a ser la más probable palabra a palabra."),
    dict(clave="top_k", grupo="Muestreo", nombre="Top K", tipo="int", min=1, max=200, paso=1,
         ayuda="Solo elige entre las K palabras más probables. Menos = más conservador.",
         prueba="top_k 1 da la salida voraz, distinta de la normal."),
    dict(clave="top_p", grupo="Muestreo", nombre="Top P", tipo="float", min=0.05, max=1, paso=0.05,
         ayuda="Elige entre las palabras que suman esta probabilidad. 0.9-0.95 es lo habitual.",
         prueba="top_p 0.2 cambia la salida con la misma semilla."),
    dict(clave="min_p", grupo="Muestreo", nombre="Min P", tipo="float", min=0, max=1, paso=0.01,
         ayuda="Descarta palabras con menos de esta fracción de la probabilidad de la mejor. "
               "Más estable que top_p con temperaturas altas; 0.05-0.1 es un buen valor.",
         prueba="min_p 0.5 cambia la salida y es reproducible."),
    dict(clave="seed", grupo="Muestreo", nombre="Semilla", tipo="int", min=0, max=2**31 - 1, paso=1,
         ayuda="Con la misma semilla y los mismos ajustes, la misma respuesta. Útil para comparar configuraciones.",
         prueba="Misma semilla → misma salida; semilla 8 frente a 7 → salida distinta."),
    # ---- Repeticiones
    dict(clave="repeat_penalty", grupo="Repeticiones", nombre="Penalización por repetir", tipo="float", min=0.5, max=2.5, paso=0.05,
         ayuda="Castiga repetir palabras recientes. 1 es no castigar; 1.05-1.15 suele bastar.",
         prueba="1.8 cambia la salida."),
    dict(clave="repeat_last_n", grupo="Repeticiones", nombre="Ventana de repetición", tipo="int", min=-1, max=4096, paso=16,
         ayuda="Cuántos tokens hacia atrás mira la penalización. 0 la desactiva; -1 usa todo el contexto.",
         prueba="Con 0 desaparece el efecto de repeat_penalty."),
    dict(clave="presence_penalty", grupo="Repeticiones", nombre="Penalización por presencia", tipo="float", min=-2, max=2, paso=0.1,
         ayuda="Castiga cualquier palabra que ya salió, aunque sea una vez: empuja a hablar de cosas nuevas.",
         prueba="1.8 cambia la salida."),
    dict(clave="frequency_penalty", grupo="Repeticiones", nombre="Penalización por frecuencia", tipo="float", min=-2, max=2, paso=0.1,
         ayuda="Castiga más cuantas más veces salió una palabra.",
         prueba="1.8 cambia la salida."),
    # ---- Longitud
    dict(clave="num_predict", grupo="Longitud", nombre="Máximo de tokens de respuesta", tipo="int", min=-1, max=32768, paso=64,
         ayuda="Tope de la respuesta. -1 es sin límite. Si se alcanza, la respuesta queda cortada y se puede continuar.",
         prueba="10 corta la respuesta a 10 tokens."),
    dict(clave="stop", grupo="Longitud", nombre="Textos de parada", tipo="lista",
         ayuda="La respuesta se corta al generar cualquiera de estos textos.",
         prueba="stop [\",\"] corta en la primera coma."),
    # ---- Contexto
    dict(clave="num_ctx", grupo="Contexto y memoria", nombre="Contexto (tokens)", tipo="int", min=512, max=262144, paso=512,
         ayuda="Cuánto texto cabe entre pregunta y respuesta. Cada token ocupa memoria: mira Recomendado antes de subirlo.",
         prueba="El motor arranca con -c igual al valor (1024 → 8192 en /api/ps)."),
    dict(clave="num_keep", grupo="Contexto y memoria", nombre="Tokens iniciales que se conservan", tipo="int", min=-1, max=8192, paso=16,
         ayuda="Si el contexto se llena, estos primeros tokens (instrucciones) no se descartan.",
         prueba="Con contexto de 256 y el dato al principio: con 60 lo recuerda, con 0 lo olvida."),
    dict(clave="num_batch", grupo="Contexto y memoria", nombre="Lote de lectura", tipo="int", min=16, max=4096, paso=16,
         ayuda="Tokens del prompt que se procesan de golpe. Más = lectura más rápida y más memoria.",
         prueba="Leyendo 1500 tokens: 5441 tok/s con 512 frente a 1767 tok/s con 16."),
    dict(clave="num_gpu", grupo="Contexto y memoria", nombre="Capas en GPU", tipo="int", min=-1, max=256, paso=1,
         ayuda="-1 automático (recomendado). Medido: forzar más capas no acelera y puede quedarse sin memoria. 0 = todo en CPU.",
         prueba="Con 0 la VRAM usada pasa de 1,1 GB a 0; el motor recibe -ngl."),
    dict(clave="num_thread", grupo="Contexto y memoria", nombre="Hilos de CPU", tipo="int", min=0, max=256, paso=1,
         ayuda="Hilos para la parte que va en CPU. 0 automático. Suele convenir el número de núcleos físicos.",
         prueba="En CPU: 12,8 tok/s con 1 hilo, 21,2 tok/s con 8."),
    dict(clave="use_mmap", grupo="Contexto y memoria", nombre="Leer pesos con mmap", tipo="bool",
         ayuda="Activado: los pesos se leen del disco según se necesitan (arranca rápido). "
               "Desactivado: se cargan enteros en RAM (útil con discos lentos o de red).",
         prueba="Desactivado, el motor arranca con --load-mode none."),
    dict(clave="main_gpu", grupo="Contexto y memoria", nombre="GPU principal", tipo="int", min=0, max=16, paso=1,
         requiere_gpus=2,
         ayuda="Con varias GPUs, cuál hace de principal.",
         prueba="El motor recibe --main-gpu; en este equipo hay una sola GPU, así que solo se ofrece con dos o más."),
]

# ---------------------------------------------------------------------------
# Campos de la petición (fuera de "options")
# ---------------------------------------------------------------------------

CAMPOS: List[Dict[str, Any]] = [
    dict(clave="keep_alive", grupo="Carga", nombre="Mantener cargado", tipo="duracion",
         ayuda="Cuánto sigue el modelo en memoria tras responder: 0 lo descarga al momento, -1 lo deja siempre. Ej.: 5m, 30m, 1h.",
         prueba="El vencimiento en /api/ps sigue al valor pedido."),
    dict(clave="think", grupo="Razonamiento", nombre="Pensar antes de responder", tipo="bool", requiere="thinking",
         ayuda="Solo en modelos que razonan (Qwen3…). Mejora problemas y críticas; en pasos JSON estorba.",
         prueba="Qwen3 30B: con true piensa ~830 caracteres; con false responde directo."),
    dict(clave="system_extra", grupo="Instrucciones", nombre="Instrucciones adicionales", tipo="texto",
         ayuda="Se añaden a las instrucciones de sistema de cada tarea (no las sustituyen).",
         prueba="Un system de pirata hace que responda 'Arr!'."),
    dict(clave="truncate", grupo="Contexto lleno", nombre="Recortar si no cabe el prompt", tipo="bool",
         ayuda="Desactivado: si el prompt no cabe en el contexto, error claro en vez de recortarlo en silencio.",
         prueba="Con false y 631 tokens en un contexto de 256: error 'exceeds the available context size'."),
    dict(clave="shift", grupo="Contexto lleno", nombre="Desplazar el contexto al llenarse", tipo="bool",
         ayuda="Activado: al llenarse el contexto se descarta lo más antiguo y sigue generando. Desactivado: la respuesta se corta.",
         prueba="Contexto 256: sin desplazar se corta a 211 tokens; desplazando llega a 292."),
]

# Solo en "Probar" y en las llamadas que lo necesitan, no como ajuste guardado:
# cambiar el formato de todas las respuestas del tutor rompería el chat.
CAMPOS_PRUEBA = {
    "format": "JSON o esquema JSON: la respuesta cumple la estructura (verificado: {\"animal\": \"Perro\", \"patas\": 4}).",
    "system": "Instrucciones de sistema completas.",
    "template": "Plantilla propia para esta petición (verificado: cambia la respuesta).",
    "raw": "Sin plantilla: el texto va tal cual al modelo (verificado: continúa código).",
    "suffix": "Texto después del cursor; el modelo rellena el medio (verificado en qwen2.5-coder).",
    "logprobs": "Probabilidad de cada token y alternativas (verificado: 3 alternativas por token).",
}

# ---------------------------------------------------------------------------
# Lo que NO se añade, y por qué (medido en esta máquina)
# ---------------------------------------------------------------------------

EXCLUIDAS: Dict[str, Dict[str, str]] = {
    "typical_p": {"tipo": "error", "motivo": "Ollama responde 400: «typical_p is no longer supported»."},
    "mirostat": {"tipo": "sin_efecto", "motivo": "Aceptado, pero la salida es idéntica con mirostat 1 o 2 (misma semilla, caché caliente)."},
    "mirostat_tau": {"tipo": "sin_efecto", "motivo": "Sin efecto: con mirostat activo, cambiarlo no altera la salida."},
    "mirostat_eta": {"tipo": "sin_efecto", "motivo": "Sin efecto: con mirostat activo, cambiarlo no altera la salida."},
    "tfs_z": {"tipo": "sin_efecto", "motivo": "Aceptado, salida idéntica con 0.1 y sin él."},
    "penalize_newline": {"tipo": "sin_efecto", "motivo": "Aceptado, salida idéntica activado y desactivado."},
    "use_mlock": {"tipo": "sin_efecto", "motivo": "Aceptado, pero no llega al motor (no cambia sus argumentos)."},
    "numa": {"tipo": "sin_efecto", "motivo": "Aceptado, no llega al motor; además este equipo tiene un solo nodo NUMA."},
    "low_vram": {"tipo": "sin_efecto", "motivo": "Aceptado, no llega al motor ni cambia la memoria (1,105 GB igual)."},
    "f16_kv": {"tipo": "sin_efecto", "motivo": "Aceptado, no llega al motor. La precisión de la caché se controla con OLLAMA_KV_CACHE_TYPE."},
    "vocab_only": {"tipo": "sin_efecto", "motivo": "Aceptado, no llega al motor; el modelo responde igual."},
    "logits_all": {"tipo": "sin_efecto", "motivo": "Aceptado, no llega al motor."},
    "embedding_only": {"tipo": "sin_efecto", "motivo": "Aceptado, no llega al motor."},
    "think_niveles": {"tipo": "sin_efecto", "motivo": "think high/medium/low: aceptado por Qwen3, pero piensa lo mismo (823/811/811 caracteres). "
                                                     "Ningún modelo instalado usa niveles."},
    "images": {"tipo": "no_verificable", "motivo": "No hay ningún modelo con visión instalado; con uno sin visión Ollama da 400."},
}

# Variables del servidor probadas en un Ollama aparte que NO entran
EXCLUIDAS_SERVIDOR: Dict[str, Dict[str, str]] = {
    "OLLAMA_GPU_OVERHEAD": {"tipo": "sin_efecto", "motivo": "Con 2,5 GB y con 1,5 GB reservados, el 7B y el 14B ocuparon exactamente la misma VRAM (4,75 y 4,84 GB)."},
    "LLAMA_ARG_FIT=off": {"tipo": "error", "motivo": "Desactiva el reparto automático y el 14B no llega a cargar: «cudaMalloc failed: out of memory»."},
    "OLLAMA_MAX_QUEUE": {"tipo": "sin_efecto", "motivo": "Con cola 1 y 8 peticiones largas simultáneas, las 8 respondieron 200 (ninguna rechazada)."},
    "OLLAMA_NOPRUNE": {"tipo": "sin_efecto", "motivo": "Un archivo huérfano en la carpeta de modelos no se borró ni con ni sin la variable."},
    "OLLAMA_SCHED_SPREAD": {"tipo": "no_verificable", "motivo": "Reparte entre varias GPUs y este equipo tiene una."},
    "OLLAMA_MAX_TRANSFER_STREAMS": {"tipo": "no_verificable", "motivo": "Solo afecta a descargas de modelos safetensors; no había ninguna que probar."},
}

# Gestión de modelos y cuenta que NO entran
EXCLUIDAS_GESTION: Dict[str, Dict[str, str]] = {
    "cuantizar al crear": {"tipo": "error", "motivo": "«create-time quantization is only supported for safetensors imports»: con modelos GGUF no funciona."},
    "plantilla al crear variante": {"tipo": "sin_efecto", "motivo": "Se acepta, pero la variante conserva la plantilla del modelo base."},
    "adaptador LoRA (ADAPTER)": {"tipo": "no_verificable", "motivo": "No hay ningún adaptador LoRA en el equipo con el que probarlo."},
    "visión (imágenes)": {"tipo": "no_verificable", "motivo": "No hay modelos con visión instalados; con uno sin visión Ollama responde 400."},
    "publicar modelos (push)": {"tipo": "no_verificable", "motivo": "Requiere una cuenta de ollama.com con la sesión iniciada."},
    "iniciar / cerrar sesión (signin)": {"tipo": "no_verificable", "motivo": "Abre ollama.com en el navegador y necesita tu cuenta."},
    "modelos en la nube (:cloud)": {"tipo": "no_verificable", "motivo": "Sin sesión el servidor responde 401 Unauthorized. Sí se incluye bloquearlos (OLLAMA_NO_CLOUD)."},
    "búsqueda web de Ollama": {"tipo": "no_verificable", "motivo": "Requiere cuenta o clave de API de ollama.com."},
    "ollama launch (integraciones)": {"tipo": "no_verificable", "motivo": "Lanza integraciones externas; no tiene uso dentro de Prig."},
}

_POR_CLAVE = {o["clave"]: o for o in OPCIONES}
_CAMPO_POR_CLAVE = {c["clave"]: c for c in CAMPOS}
DURACION = __import__("re").compile(r"^-?\d+(\.\d+)?(ms|s|m|h)?$")


class ErrorConfig(ValueError):
    pass


def validar(valores: Dict[str, Any]) -> Dict[str, Any]:
    """ Tipos y rangos. Una clave excluida o desconocida es un error, no se ignora. """
    limpio: Dict[str, Any] = {}
    for clave, valor in (valores or {}).items():
        if clave in EXCLUIDAS:
            raise ErrorConfig(f"{clave} no se admite: {EXCLUIDAS[clave]['motivo']}")
        definicion = _POR_CLAVE.get(clave) or _CAMPO_POR_CLAVE.get(clave)
        if not definicion:
            raise ErrorConfig(f"Opción desconocida: {clave}")
        tipo = definicion["tipo"]
        try:
            if tipo == "int":
                v = int(valor)
                if float(valor) != v:
                    raise ValueError
            elif tipo == "float":
                v = float(valor)
            elif tipo == "bool":
                if not isinstance(valor, bool):
                    raise ValueError
                v = valor
            elif tipo == "lista":
                if isinstance(valor, str):
                    valor = [valor]
                v = [str(x) for x in valor if str(x) != ""]
                if len(v) > 8:
                    raise ErrorConfig("Como mucho 8 textos de parada")
            elif tipo == "duracion":
                v = str(valor).strip()
                if not DURACION.match(v):
                    raise ValueError
            elif tipo == "texto":
                v = str(valor)
                if len(v) > 4000:
                    raise ErrorConfig("Las instrucciones adicionales no pueden pasar de 4000 caracteres")
            else:
                raise ValueError
        except ErrorConfig:
            raise
        except (TypeError, ValueError):
            raise ErrorConfig(f"{definicion['nombre']}: valor no válido ({valor!r})")
        if tipo in ("int", "float"):
            if v < definicion["min"] or v > definicion["max"]:
                raise ErrorConfig(f"{definicion['nombre']}: debe estar entre {definicion['min']} y {definicion['max']}")
        limpio[clave] = v
    return limpio


def separar(valores: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """ (options del motor, campos de la petición) """
    opciones = {k: v for k, v in valores.items() if k in _POR_CLAVE}
    campos = {k: v for k, v in valores.items() if k in _CAMPO_POR_CLAVE}
    return opciones, campos


def limpiar_para_ollama(opciones: Dict[str, Any]) -> Dict[str, Any]:
    """ Quita lo que Ollama rechaza o ignora, venga de donde venga (configuraciones
    viejas, llamadas antiguas). typical_p rompería la petición con un 400. """
    return {k: v for k, v in (opciones or {}).items() if k not in EXCLUIDAS}


PLANTILLAS = {
    "recomendado": {"nombre": "Recomendado por el modelo", "valores": {},
                    "ayuda": "No fija nada: se usan los valores que trae el modelo."},
    "codigo": {"nombre": "Código / preciso", "valores": {"temperature": 0.2, "top_p": 0.9, "min_p": 0.05, "repeat_penalty": 1.05}},
    "equilibrado": {"nombre": "Equilibrado", "valores": {"temperature": 0.6, "top_p": 0.95, "min_p": 0.05}},
    "creativo": {"nombre": "Creativo", "valores": {"temperature": 1.0, "top_p": 0.98, "min_p": 0.05, "presence_penalty": 0.3}},
    "determinista": {"nombre": "Determinista", "valores": {"temperature": 0.0, "seed": 42}},
}


# ===========================================================================
# Almacén de capas
# ===========================================================================

def ruta_por_defecto() -> str:
    return os.environ.get("PRIG_MODELOS_ARCHIVO") or os.path.expanduser("~/.prig_modelos.json")


class ConfigModelos:
    def __init__(self, ruta: Optional[str] = None):
        self.ruta = ruta or ruta_por_defecto()
        self._cerrojo = threading.RLock()
        self._datos = self._leer()

    def _leer(self) -> Dict[str, Any]:
        vacio = {"version": 1, "global": {}, "modelo": {}, "uso": {}, "modelo_uso": {},
                 "embeddings": {"modelo": None, "dimensiones": None, "truncar": True}}
        try:
            with open(self.ruta, encoding="utf-8") as f:
                datos = json.load(f)
            for k, v in vacio.items():
                datos.setdefault(k, copy.deepcopy(v))
            # Una configuración vieja con opciones que ahora fallan no puede
            # romper cada petición: se limpian al leer
            for capa in ("global",):
                datos[capa] = {k: v for k, v in datos[capa].items() if k not in EXCLUIDAS}
            for capa in ("modelo", "uso", "modelo_uso"):
                datos[capa] = {n: {k: v for k, v in d.items() if k not in EXCLUIDAS} for n, d in datos[capa].items()}
            return datos
        except FileNotFoundError:
            return vacio
        except Exception:
            try:
                os.replace(self.ruta, self.ruta + ".roto")
            except OSError:
                pass
            return vacio

    def _guardar(self):
        carpeta = os.path.dirname(os.path.abspath(self.ruta))
        os.makedirs(carpeta, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".prig_modelos.", dir=carpeta)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self._datos, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.ruta)

    @staticmethod
    def _clave(capa: str, modelo: Optional[str], uso: Optional[str]) -> Optional[str]:
        if capa == "global":
            return None
        if capa == "modelo":
            if not modelo:
                raise ErrorConfig("Falta el modelo")
            return modelo
        if capa == "uso":
            if uso not in USOS:
                raise ErrorConfig(f"Uso desconocido: {uso}")
            return uso
        if capa == "modelo_uso":
            if not modelo or uso not in USOS:
                raise ErrorConfig("Hacen falta modelo y uso")
            return f"{modelo}|{uso}"
        raise ErrorConfig(f"Capa desconocida: {capa}")

    def capa(self, capa: str, modelo: Optional[str] = None, uso: Optional[str] = None) -> Dict[str, Any]:
        with self._cerrojo:
            clave = self._clave(capa, modelo, uso)
            datos = self._datos["global"] if clave is None else self._datos[capa].get(clave, {})
            return copy.deepcopy(datos)

    def fijar(self, capa: str, valores: Dict[str, Any], modelo: Optional[str] = None,
              uso: Optional[str] = None, reemplazar: bool = False) -> Dict[str, Any]:
        """ Guarda valores en una capa. `None` en un valor lo quita de la capa. """
        quitar = [k for k, v in valores.items() if v is None]
        limpio = validar({k: v for k, v in valores.items() if v is not None})
        with self._cerrojo:
            clave = self._clave(capa, modelo, uso)
            if clave is None:
                destino = {} if reemplazar else self._datos["global"]
                destino.update(limpio)
                for k in quitar:
                    destino.pop(k, None)
                self._datos["global"] = destino
            else:
                destino = {} if reemplazar else self._datos[capa].get(clave, {})
                destino.update(limpio)
                for k in quitar:
                    destino.pop(k, None)
                if destino:
                    self._datos[capa][clave] = destino
                else:
                    self._datos[capa].pop(clave, None)
            self._guardar()
            return copy.deepcopy(destino)

    # ---- embeddings (verificado: dimensions 128 → vectores de 128; truncate false →
    # error «input length exceeds the context length»; varios textos por petición)
    def embeddings(self) -> Dict[str, Any]:
        with self._cerrojo:
            return dict(self._datos["embeddings"])

    def fijar_embeddings(self, modelo: Optional[str] = None, dimensiones: Optional[int] = None,
                         truncar: Optional[bool] = None, quitar_dimensiones: bool = False) -> Dict[str, Any]:
        with self._cerrojo:
            e = self._datos["embeddings"]
            if modelo is not None:
                e["modelo"] = str(modelo).strip() or None
            if quitar_dimensiones:
                e["dimensiones"] = None
            elif dimensiones is not None:
                d = int(dimensiones)
                if not 16 <= d <= 8192:
                    raise ErrorConfig("Las dimensiones deben estar entre 16 y 8192")
                e["dimensiones"] = d
            if truncar is not None:
                e["truncar"] = bool(truncar)
            self._guardar()
            return dict(e)

    def renombrar_modelo(self, anterior: str, nuevo: str):
        """ Al copiar un modelo, su configuración viaja con él """
        with self._cerrojo:
            if anterior in self._datos["modelo"]:
                self._datos["modelo"][nuevo] = copy.deepcopy(self._datos["modelo"][anterior])
            for k in list(self._datos["modelo_uso"]):
                m, _, u = k.rpartition("|")
                if m == anterior:
                    self._datos["modelo_uso"][f"{nuevo}|{u}"] = copy.deepcopy(self._datos["modelo_uso"][k])
            self._guardar()

    def resolver(self, modelo: Optional[str], uso: Optional[str] = None) -> Dict[str, Any]:
        """ Valores efectivos y de qué capa sale cada uno """
        with self._cerrojo:
            capas = [("global", self._datos["global"])]
            if modelo:
                capas.append(("modelo", self._datos["modelo"].get(modelo, {})))
                # "qwen3:14b" y "qwen3:14b:latest"-style: el nombre sin :latest también cuenta
                if modelo.endswith(":latest"):
                    capas.insert(1, ("modelo", self._datos["modelo"].get(modelo[:-7], {})))
            if uso in USOS:
                capas.append(("uso", self._datos["uso"].get(uso, {})))
                if modelo:
                    capas.append(("modelo_uso", self._datos["modelo_uso"].get(f"{modelo}|{uso}", {})))
            valores: Dict[str, Any] = {}
            origen: Dict[str, str] = {}
            for nombre, datos in capas:
                for k, v in datos.items():
                    valores[k] = copy.deepcopy(v)
                    origen[k] = nombre
        opciones, campos = separar(valores)
        return {"opciones": opciones, "campos": campos, "origen": origen}

    def todo(self) -> Dict[str, Any]:
        with self._cerrojo:
            return copy.deepcopy(self._datos)


_config: Optional[ConfigModelos] = None
_config_cerrojo = threading.Lock()


def config() -> ConfigModelos:
    global _config
    with _config_cerrojo:
        if _config is None or _config.ruta != ruta_por_defecto():
            _config = ConfigModelos()
        return _config


def catalogo(num_gpus: int = 1) -> Dict[str, Any]:
    return {
        "opciones": [o for o in OPCIONES if num_gpus >= o.get("requiere_gpus", 1)],
        "campos": CAMPOS,
        "campos_prueba": CAMPOS_PRUEBA,
        "excluidas": EXCLUIDAS,
        "excluidas_servidor": EXCLUIDAS_SERVIDOR,
        "excluidas_gestion": EXCLUIDAS_GESTION,
        "usos": USOS,
        "capas": CAPAS,
        "plantillas": PLANTILLAS,
    }
