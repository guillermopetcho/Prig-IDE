"""
Buscador de modelos en las plataformas desde las que Ollama descarga.

No hace falta ningún complemento: Ollama descarga por sí solo de tres registros, y
así se verificó en esta máquina (Ollama 0.34.1) bajando un modelo pequeño de cada
uno, generando texto con él y borrándolo:

    ollama.com       smollm2:135m                                      271 MB
    Hugging Face     hf.co/bartowski/SmolLM2-135M-Instruct-GGUF:Q4_K_M 105 MB
    ModelScope       modelscope.cn/Qwen/Qwen2.5-0.5B-Instruct-GGUF:q4_k_m  491 MB

Cómo se busca en cada una (verificado):

  · ollama.com no tiene API de búsqueda: la página /search tiene una estructura
    estable (nombre, descripción, capacidades, tamaños, descargas, fecha), acepta
    q, o=newest, c=<capacidad> y p=<página>, e incluye modelos de la comunidad
    (usuario/modelo). Las variantes salen de /<modelo>/tags.
  · Hugging Face tiene API oficial: /api/models con filter=gguf, orden por
    tendencia, descargas, me gusta, actualización o creación, y paginación por la
    cabecera Link. Los archivos y sus tamaños salen de /api/models/<repo>?blobs=true.
  · ModelScope tiene API oficial: /api/v1/dolphin/models (búsqueda) y
    /api/v1/models/<repo>/repo/files (archivos con tamaño).

Antes de descargar, cada variante se COMPRUEBA pidiendo su manifiesto al registro
correspondiente: si existe, se descarga seguro y se sabe su tamaño exacto; si no
(por ejemplo, un GGUF partido en varios archivos), se avisa en vez de fallar a mitad.

Lo que pide y lee está en Rust (backend-rust/crates/prig-modelos, buscador.rs): las peticiones (sin el GIL), leer
las páginas de ollama.com, normalizar Hugging Face y ModelScope, comprobar en el registro, agrupar los GGUF,
interpretar enlaces y la caché. Aquí queda lo fino que los junta (repartir una búsqueda entre plataformas, juntar
variantes con sus comprobaciones, localizar, seguir modelos), que llama a esas piezas por su nombre en este módulo.
"""

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import requests


def _rs():
    from nativo_rust import rust
    return rust().buscador


UA = {"User-Agent": _rs().UA}
MANIFIESTO = {"Accept": _rs().ACEPTA_MANIFIESTO, **UA}
# modelscope.cn da a Ollama un manifiesto con más campos que a otros clientes, y Ollama
# usa el sha256 de ese texto como digest del modelo: para poder compararlo hay que pedirlo
# igual. registry.ollama.ai, en cambio, responde 401 a ese User-Agent sin firma.
MANIFIESTO_COMO_OLLAMA = {**MANIFIESTO, "User-Agent": _rs().UA_OLLAMA}

FUENTES = {
    "ollama": {"nombre": "Ollama", "web": "https://ollama.com"},
    "huggingface": {"nombre": "Hugging Face", "web": "https://huggingface.co"},
    "modelscope": {"nombre": "ModelScope", "web": "https://modelscope.cn"},
}

ORDENES = {
    "ollama": {"relevancia": None, "recientes": "newest"},
    "huggingface": {"relevancia": "downloads", "descargas": "downloads", "tendencia": "trendingScore",
                    "me_gusta": "likes", "actualizados": "lastModified", "recientes": "createdAt"},
    "modelscope": {"relevancia": "Default", "descargas": "DownloadsCount", "actualizados": "GmtModified"},
}

CAPACIDADES_OLLAMA = tuple(_rs().CAPACIDADES_OLLAMA)

ErrorBuscador = _rs().ErrorBuscador


# ===========================================================================
# Utilidades
# ===========================================================================

Cache = _rs().Cache

_cache = Cache()


def _texto(fragmento: str) -> str:
    return _rs().texto(fragmento)


def _numero(texto: str) -> Optional[int]:
    return _rs().numero(texto)


def _bytes(texto: str) -> Optional[int]:
    return _rs().bytes_(texto)


def cuantizacion_de(nombre_archivo: str) -> Optional[str]:
    return _rs().cuantizacion_de(nombre_archivo)


def validar_ref(ref: str) -> str:
    return _rs().validar_ref(ref)


# ===========================================================================
# Comprobar en el registro (sin descargar)
# ===========================================================================

def registro_de(ref: str) -> Tuple[str, str, str]:
    from recursos.ficha import registro_de as _r
    return _r(ref)


def _motivo_registro(codigo: int, cuerpo: str, tag: str) -> str:
    """ El registro explica el 400 en el cuerpo; se traduce lo conocido """
    return _rs().motivo_registro(codigo, cuerpo, tag)


def comprobar(ref: str, timeout: float = 30) -> Dict[str, Any]:
    """ ¿Se puede descargar? Pide el manifiesto al registro que corresponde.
    Devuelve el tamaño exacto, las capas (modelo, plantilla, proyector de visión…)
    y el digest con el que luego se detectan actualizaciones. """
    return _rs().comprobar(ref or "", registro_de((ref or "").strip()), _cache, timeout)


# ===========================================================================
# Ollama
# ===========================================================================

class Ollama:
    BASE = "https://ollama.com"

    def buscar(self, consulta: str = "", orden: str = "relevancia", capacidad: Optional[str] = None,
               pagina: int = 1) -> Dict[str, Any]:
        return _rs().ollama_buscar(self.BASE, consulta or "", orden, capacidad, pagina, _cache)

    @staticmethod
    def analizar_busqueda(pagina: str) -> List[Dict[str, Any]]:
        return _rs().analizar_busqueda(pagina)

    def variantes(self, nombre: str) -> Dict[str, Any]:
        return _rs().ollama_variantes(self.BASE, nombre or "", _cache)

    @staticmethod
    def analizar_etiquetas(pagina: str, ruta: str) -> List[Dict[str, Any]]:
        return _rs().analizar_etiquetas(pagina, ruta)


# ===========================================================================
# Hugging Face
# ===========================================================================

class HuggingFace:
    BASE = "https://huggingface.co"
    EXPANDIR = list(_rs().EXPANDIR)

    def buscar(self, consulta: str = "", orden: str = "relevancia", pagina: Optional[str] = None,
               limite: int = 30) -> Dict[str, Any]:
        return _rs().hf_buscar(self.BASE, consulta or "", orden, pagina, limite, _cache)

    @staticmethod
    def normalizar(m: Dict[str, Any]) -> Dict[str, Any]:
        return _rs().hf_normalizar(m)

    def variantes(self, repo: str) -> Dict[str, Any]:
        return _rs().hf_variantes(self.BASE, repo or "", _cache)


# ===========================================================================
# ModelScope
# ===========================================================================

class ModelScope:
    BASE = "https://modelscope.cn"

    def buscar(self, consulta: str = "", orden: str = "relevancia", pagina: int = 1, limite: int = 30) -> Dict[str, Any]:
        return _rs().ms_buscar(self.BASE, consulta or "", orden, int(pagina), limite, _cache)

    @staticmethod
    def normalizar(m: Dict[str, Any]) -> Dict[str, Any]:
        return _rs().ms_normalizar(m)

    def variantes(self, repo: str) -> Dict[str, Any]:
        return _rs().ms_variantes(self.BASE, repo or "", _cache)


def agrupar_gguf(archivos: List[Tuple[str, int]], prefijo: str) -> List[Dict[str, Any]]:
    """ Archivos .gguf de un repositorio → variantes descargables por Ollama.

    Una variante partida en varios archivos (-00001-of-00003) se agrupa en una sola
    entrada; el proyector de visión (mmproj) no es una variante. La etiqueta de Ollama
    es la cuantización tal como aparece en el nombre (Q4_K_M, UD-Q4_K_XL, q4_k_m…).
    """
    return _rs().agrupar_gguf(list(archivos), prefijo)


# ===========================================================================
# Fachada
# ===========================================================================

PROVEEDORES = {"ollama": Ollama(), "huggingface": HuggingFace(), "modelscope": ModelScope()}


def buscar(consulta: str, fuentes: List[str], orden: str = "relevancia", capacidad: Optional[str] = None,
           paginas: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """ Busca en varias plataformas a la vez. Si una falla, las demás siguen. """
    paginas = paginas or {}
    fuentes = [f for f in fuentes if f in PROVEEDORES] or list(PROVEEDORES)

    def una(fuente):
        try:
            p = PROVEEDORES[fuente]
            if fuente == "ollama":
                return fuente, p.buscar(consulta, orden, capacidad, int(paginas.get(fuente) or 1)), None
            if fuente == "huggingface":
                return fuente, p.buscar(consulta, orden, paginas.get(fuente)), None
            return fuente, p.buscar(consulta, orden, int(paginas.get(fuente) or 1)), None
        except (ErrorBuscador, requests.RequestException, ValueError) as e:
            return fuente, {"modelos": [], "siguiente": None}, str(e)

    with ThreadPoolExecutor(len(fuentes)) as ex:
        resultados = list(ex.map(una, fuentes))
    return {"fuentes": {f: {**r, "error": e} for f, r, e in resultados}}


def variantes(fuente: str, id_modelo: str, comprobar_todas: bool = True) -> Dict[str, Any]:
    if fuente not in PROVEEDORES:
        raise ErrorBuscador("Fuente desconocida")
    datos = dict(PROVEEDORES[fuente].variantes(id_modelo))
    lista = [dict(v) for v in datos["variantes"]]
    if comprobar_todas:
        pendientes = [v for v in lista if v.get("descargable") is None][:60]
        with ThreadPoolExecutor(8) as ex:
            for v, c in zip(pendientes, ex.map(lambda v: comprobar(v["ref"]), pendientes)):
                v["descargable"] = c["descargable"]
                if c["descargable"]:
                    v["bytes"] = c["bytes"]
                    v["vision"] = c.get("vision")
                else:
                    v["nota"] = c.get("motivo")
    datos["variantes"] = lista
    return datos


def novedades() -> Dict[str, Any]:
    """ Lo último de cada plataforma: modelos nuevos en Ollama, tendencias GGUF en
    Hugging Face y lo más recién actualizado en ModelScope. """
    trabajos = {
        "ollama_nuevos": lambda: PROVEEDORES["ollama"].buscar("", "recientes")["modelos"],
        "huggingface_tendencia": lambda: PROVEEDORES["huggingface"].buscar("", "tendencia", limite=20)["modelos"],
        "modelscope_actualizados": lambda: PROVEEDORES["modelscope"].buscar("", "actualizados", limite=20)["modelos"],
    }

    def correr(item):
        nombre, fn = item
        try:
            return nombre, fn(), None
        except Exception as e:
            return nombre, [], str(e)
    with ThreadPoolExecutor(3) as ex:
        return {n: {"modelos": m, "error": e} for n, m, e in ex.map(correr, trabajos.items())}


def fuente_de_ref(ref: str) -> str:
    return _rs().fuente_de_ref(ref)


def actualizaciones_instalados(instalados: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ Compara cada modelo instalado con su registro de origen. El digest local de
    /api/tags es el sha256 del manifiesto (verificado descargando de Ollama, Hugging Face
    y ModelScope). """
    def revisar(m):
        ref = m["name"]
        c = comprobar(ref)
        base = {"modelo": ref, "fuente": fuente_de_ref(ref)}
        if not c["descargable"]:
            estado = "local" if c.get("codigo") in (404, 400) else "error"
            return {**base, "estado": estado, "detalle": "No está en ningún registro (creado o importado aquí)" if estado == "local" else c.get("motivo")}
        return {**base, "estado": "al_dia" if c["digest"] == m.get("digest") else "actualizable",
                "bytes": c["bytes"], "local": (m.get("digest") or "")[:12], "remoto": c["digest"][:12]}
    with ThreadPoolExecutor(6) as ex:
        return list(ex.map(revisar, instalados))


def analizar_variante(ref: str) -> Dict[str, Any]:
    """ ¿Cómo iría en esta máquina? Lee solo la cabecera GGUF del registro y pasa la
    ficha por la calculadora de Recomendado. """
    from recursos import ficha as fichas
    from recursos.calculadora import recomendar
    from recursos.gestor import gestor
    ref = validar_ref(ref)
    f = fichas.desde_registro(ref)
    maq = gestor().maquina()
    resultado = {"ref": ref, "ficha": {k: f.get(k) for k in ("arquitectura", "parametros", "parametros_activos", "es_moe", "capas",
                                                           "contexto_max", "piensa", "embedding", "bytes_peso")}}
    if f.get("embedding"):
        resultado["veredicto"] = {"veredicto": "embeddings", "etiqueta": "Modelo de embeddings", "motivo": "Se usa en CPU para el índice semántico."}
        return resultado
    rec = recomendar(f, maq, "tutor")
    resultado["veredicto"] = {k: rec.get(k) for k in ("veredicto", "etiqueta", "motivo")}
    resultado["veredicto"]["tok_s"] = rec.get("estimacion", {}).get("tok_s")
    resultado["veredicto"]["memoria_gb"] = rec.get("estimacion", {}).get("total_gb")
    return resultado


# ===========================================================================
# Encontrar un modelo concreto: por nombre o pegando un enlace
# ===========================================================================

def interpretar(texto: str) -> Dict[str, Any]:
    """ Qué ha escrito o pegado el usuario.

    · enlace de ollama.com, huggingface.co / hf.co o modelscope.cn (a la ficha, a las
      etiquetas, a un archivo .gguf…)            → {"tipo": "enlace", fuente, id, etiqueta}
    · lo que se le pasa a Ollama: «ollama run hf.co/…:Q4_K_M», «qwen3:8b»
    · «propietario/repositorio», que puede estar en cualquier plataforma → {"tipo": "repo"}
    · cualquier otra cosa es un nombre a buscar  → {"tipo": "nombre", consulta, etiqueta}
    """
    return _rs().interpretar(texto)


def interpretar_nombre(texto: str) -> Dict[str, Any]:
    return _rs().interpretar_nombre(texto)


def _clave(nombre: str) -> str:
    """ «unsloth/Qwen3-8B-GGUF», «qwen3-8b» y «Qwen3 8B» son el mismo nombre """
    return _rs().clave(nombre)


def _parecido(consulta: str, id_modelo: str) -> bool:
    return _rs().parecido(consulta, id_modelo)


def ficha_repo(fuente: str, id_modelo: str) -> Optional[Dict[str, Any]]:
    """ Datos de un modelo concreto, o None si no existe (o es privado) en esa plataforma """
    return _rs().ficha_repo(fuente, id_modelo, (Ollama.BASE, HuggingFace.BASE, ModelScope.BASE), _cache)


def localizar(texto: str) -> Dict[str, Any]:
    """ Encuentra un modelo concreto en las plataformas.

    Con un enlace se va directo a ese modelo; con «propietario/repositorio» se mira en
    las tres; con un nombre se busca en las tres y se separan las coincidencias exactas
    de las parecidas. Si lo encontrado no tiene GGUF (Ollama no podría usarlo), se
    buscan versiones GGUF con el mismo nombre. """
    q = interpretar(texto)
    exactos: List[Dict[str, Any]] = []
    parecidos: List[Dict[str, Any]] = []
    errores: Dict[str, str] = {}

    def ficha_segura(fuente, id_modelo):
        try:
            return fuente, ficha_repo(fuente, id_modelo), None
        except (ErrorBuscador, requests.RequestException, ValueError) as e:
            return fuente, None, str(e)

    if q["tipo"] in ("enlace", "repo"):
        fuentes = [q["fuente"]] if q["fuente"] else list(PROVEEDORES)
        with ThreadPoolExecutor(len(fuentes)) as ex:
            for fuente, ficha, error in ex.map(lambda f: ficha_segura(f, q["id"]), fuentes):
                if ficha:
                    exactos.append(ficha)
                elif error:
                    errores[fuente] = error
        buscar_nombre = not exactos or all(m.get("sin_gguf") for m in exactos)
    else:
        buscar_nombre = True

    if buscar_nombre:
        consulta = q["consulta"]
        with ThreadPoolExecutor(2) as ex:
            directo = ex.submit(ficha_segura, "ollama", _clave_ollama(consulta)) if q["tipo"] == "nombre" and _clave_ollama(consulta) else None
            r = buscar(consulta, list(PROVEEDORES))
            if directo:
                _, ficha, _ = directo.result()
                if ficha:
                    exactos.append(ficha)
        vistos = {(m["fuente"], m["id"].lower()) for m in exactos}
        objetivo = _clave(consulta)
        mismos_nombres: List[Dict[str, Any]] = []
        for fuente, datos in r["fuentes"].items():
            if datos.get("error"):
                errores.setdefault(fuente, datos["error"])
            n = 0
            for m in datos["modelos"]:
                if (fuente, m["id"].lower()) in vistos:
                    continue
                if _clave(m["id"]) == objetivo:
                    # Con un nombre, es lo que se buscaba; si el enlace era un repo sin GGUF,
                    # son sus versiones GGUF y van delante de lo parecido
                    (exactos if q["tipo"] == "nombre" else mismos_nombres).append(m)
                    vistos.add((fuente, m["id"].lower()))
                elif _parecido(consulta, m["id"]) and n < 6:
                    parecidos.append(m)
                    vistos.add((fuente, m["id"].lower()))
                    n += 1
        parecidos = mismos_nombres + parecidos
        # Lo comprobado directamente va primero; lo que salió de buscar, por descargas
        directos = [m for m in exactos if m.get("sin_gguf") is not None]      # solo ficha_repo pone «sin_gguf»
        de_busqueda = sorted((m for m in exactos if m.get("sin_gguf") is None), key=lambda m: -(m.get("descargas") or 0))
        exactos = directos + de_busqueda

    for m in exactos:
        m["destacar"] = q["etiqueta"]
    return {"interpretado": q, "exactos": exactos, "parecidos": parecidos, "errores": errores}


def _clave_ollama(consulta: str) -> Optional[str]:
    """ «Qwen3» → «qwen3»: los modelos oficiales de Ollama van en minúsculas y sin espacios """
    return _rs().clave_ollama(consulta)


# ===========================================================================
# Seguidos y comprobación periódica
# ===========================================================================

def ruta_estado() -> str:
    return os.environ.get("PRIG_BUSCADOR_ARCHIVO") or os.path.expanduser("~/.prig_buscador.json")


class Seguimiento:
    """ Modelos que el usuario sigue. Guarda cómo estaban la última vez que los vio y
    avisa de variantes nuevas, retiradas o cambiadas (otro tamaño o digest). """

    def __init__(self, ruta: Optional[str] = None, proveedores=None):
        self.ruta = ruta or ruta_estado()
        self.proveedores = proveedores or PROVEEDORES
        self._cerrojo = threading.RLock()

    def _leer(self) -> Dict[str, Any]:
        try:
            with open(self.ruta, encoding="utf-8") as f:
                datos = json.load(f)
        except (FileNotFoundError, ValueError):
            datos = {}
        datos.setdefault("seguidos", {})
        datos.setdefault("actualizaciones", None)
        return datos

    def _guardar(self, datos: Dict[str, Any]):
        tmp = self.ruta + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.ruta)

    @staticmethod
    def _instantanea(variantes: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {v["etiqueta"]: {"bytes": v.get("bytes"), "digest": v.get("digest")} for v in variantes}

    def _variantes(self, fuente: str, id_modelo: str) -> List[Dict[str, Any]]:
        return self.proveedores[fuente].variantes(id_modelo)["variantes"]

    def seguir(self, fuente: str, id_modelo: str, titulo: Optional[str] = None) -> Dict[str, Any]:
        if fuente not in self.proveedores:
            raise ErrorBuscador("Fuente desconocida")
        variantes = self._variantes(fuente, id_modelo)
        with self._cerrojo:
            datos = self._leer()
            datos["seguidos"][f"{fuente}:{id_modelo}"] = {
                "fuente": fuente, "id": id_modelo, "titulo": titulo or id_modelo, "desde": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "instantanea": self._instantanea(variantes), "cambios": None, "revisado": time.strftime("%Y-%m-%dT%H:%M:%S")}
            self._guardar(datos)
            return datos["seguidos"][f"{fuente}:{id_modelo}"]

    def dejar(self, fuente: str, id_modelo: str):
        with self._cerrojo:
            datos = self._leer()
            datos["seguidos"].pop(f"{fuente}:{id_modelo}", None)
            self._guardar(datos)

    def lista(self) -> List[Dict[str, Any]]:
        with self._cerrojo:
            return [{k: v for k, v in s.items() if k != "instantanea"} for s in self._leer()["seguidos"].values()]

    def revisar(self) -> List[Dict[str, Any]]:
        with self._cerrojo:
            datos = self._leer()
        seguidos = list(datos["seguidos"].values())

        def uno(s):
            try:
                ahora = self._instantanea(self._variantes(s["fuente"], s["id"]))
            except Exception as e:
                return s, None, str(e)
            antes = s["instantanea"]
            cambios = {
                "nuevas": sorted(set(ahora) - set(antes)),
                "retiradas": sorted(set(antes) - set(ahora)),
                "cambiadas": sorted(k for k in set(ahora) & set(antes)
                                    if (ahora[k].get("digest") and antes[k].get("digest") and ahora[k]["digest"] != antes[k]["digest"])
                                    or (ahora[k].get("bytes") and antes[k].get("bytes") and ahora[k]["bytes"] != antes[k]["bytes"])),
            }
            return s, cambios, None
        with ThreadPoolExecutor(4) as ex:
            resultados = list(ex.map(uno, seguidos))
        with self._cerrojo:
            datos = self._leer()
            for s, cambios, error in resultados:
                clave = f"{s['fuente']}:{s['id']}"
                if clave not in datos["seguidos"]:
                    continue
                datos["seguidos"][clave]["revisado"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                datos["seguidos"][clave]["error"] = error
                if cambios is not None:
                    datos["seguidos"][clave]["cambios"] = cambios if any(cambios.values()) else None
            self._guardar(datos)
        return self.lista()

    def marcar_visto(self, fuente: str, id_modelo: str) -> Dict[str, Any]:
        """ Acepta el estado actual como el nuevo punto de comparación """
        return self.seguir(fuente, id_modelo, (self._leer()["seguidos"].get(f"{fuente}:{id_modelo}") or {}).get("titulo"))

    def marcar_actualizado(self, ref: str):
        """ Tras descargar `ref`, lo guardado deja de decir que tiene versión nueva """
        with self._cerrojo:
            datos = self._leer()
            guardado = datos.get("actualizaciones")
            if not guardado:
                return
            for m in guardado["modelos"]:
                if m["modelo"] in (ref, f"{ref}:latest") and m["estado"] == "actualizable":
                    m["estado"] = "al_dia"
            guardado["actualizables"] = sum(1 for m in guardado["modelos"] if m["estado"] == "actualizable")
            self._guardar(datos)

    def actualizaciones(self, instalados_fn, max_edad: float = 86400, forzar: bool = False) -> Dict[str, Any]:
        """ Resultado guardado si tiene menos de `max_edad` segundos; si no, se recalcula """
        with self._cerrojo:
            guardado = self._leer().get("actualizaciones")
        if guardado and not forzar and time.time() - guardado.get("marca", 0) < max_edad:
            return {**guardado, "de_cache": True}
        resultados = actualizaciones_instalados(instalados_fn())
        nuevo = {"marca": time.time(), "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"), "modelos": resultados,
                 "actualizables": sum(1 for r in resultados if r["estado"] == "actualizable")}
        with self._cerrojo:
            datos = self._leer()
            datos["actualizaciones"] = nuevo
            self._guardar(datos)
        return {**nuevo, "de_cache": False}
