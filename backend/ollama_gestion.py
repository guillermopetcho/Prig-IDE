"""
Gestión de modelos de Ollama: ficha, variantes, copias, importar GGUF, actualizaciones,
modelos cargados y descargas a medias.

Verificado contra Ollama 0.34.1 (ver ollama_opciones.EXCLUIDAS para lo que no entra):
  · /api/show verbose trae licencia, plantilla, Modelfile, parámetros, capacidades,
    model_info y tensores.
  · /api/create con from + system + parameters + messages + license crea la variante,
    y responde con esas instrucciones ("Arr!" con un system de pirata).
    `template` al crear se ACEPTA pero no se guarda: no se ofrece. `quantize` da error
    con modelos GGUF ("only supported for safetensors imports"): tampoco.
  · /api/copy y /api/delete.
  · Importar: HEAD/POST /api/blobs/<digest> + /api/create con `files`.
  · Actualizaciones: el digest de /api/tags es el sha256 del manifiesto del registro.
"""

import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Generator, List, Optional

import requests

REGISTRO = "https://registry.ollama.ai"
NOMBRE_VALIDO = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\-/]{0,120}(:[a-zA-Z0-9._\-]{1,80})?$")


class ErrorGestion(Exception):
    pass


def _nombre(nombre: str) -> str:
    nombre = (nombre or "").strip()
    if not NOMBRE_VALIDO.match(nombre):
        raise ErrorGestion("Nombre de modelo no válido: letras, números, guiones, puntos y opcionalmente :etiqueta")
    return nombre


def _parametros(texto: str) -> Dict[str, Any]:
    """ "temperature 0.6\\nstop \\"<|im_end|>\\"" → {"temperature": "0.6", "stop": [...]} """
    salida: Dict[str, Any] = {}
    for linea in (texto or "").splitlines():
        partes = linea.strip().split(None, 1)
        if len(partes) != 2:
            continue
        clave, valor = partes
        valor = valor.strip()
        if valor.startswith('"') and valor.endswith('"'):
            valor = valor[1:-1]
        if clave in salida:
            salida[clave] = (salida[clave] if isinstance(salida[clave], list) else [salida[clave]]) + [valor]
        else:
            salida[clave] = valor
    return salida


class GestorModelos:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base = base_url.rstrip("/")

    # ------------------------------------------------------------ utilidades
    def _get(self, ruta: str, timeout: float = 15):
        r = requests.get(self.base + ruta, timeout=timeout)
        if r.status_code != 200:
            raise ErrorGestion(self._error(r))
        return r.json()

    def _post(self, ruta: str, cuerpo: Dict[str, Any], timeout: float = 120):
        r = requests.post(self.base + ruta, json=cuerpo, timeout=timeout)
        if r.status_code != 200:
            raise ErrorGestion(self._error(r))
        return r.json() if r.content else {}

    @staticmethod
    def _error(r) -> str:
        try:
            d = r.json()
            e = d.get("error")
            return (e.get("message") if isinstance(e, dict) else e) or f"HTTP {r.status_code}"
        except Exception:
            return r.text[:300] or f"HTTP {r.status_code}"

    def _stream(self, ruta: str, cuerpo: Dict[str, Any], timeout: float = 3600) -> Generator[Dict[str, Any], None, None]:
        with requests.post(self.base + ruta, json={**cuerpo, "stream": True}, stream=True, timeout=timeout) as r:
            if r.status_code != 200:
                raise ErrorGestion(self._error(r))
            for linea in r.iter_lines():
                if not linea:
                    continue
                d = json.loads(linea)
                if d.get("error"):
                    raise ErrorGestion(d["error"])
                yield d

    # ------------------------------------------------------------ listado y ficha
    def instalados(self) -> List[Dict[str, Any]]:
        modelos = self._get("/api/tags").get("models", [])
        cargados = {m["name"]: m for m in self._get("/api/ps").get("models", [])}

        def ficha_corta(m):
            try:
                d = self._post("/api/show", {"model": m["name"]}, timeout=20)
            except Exception:
                d = {}
            det = m.get("details") or {}
            info = d.get("model_info") or {}
            arq = info.get("general.architecture", det.get("family", ""))
            c = cargados.get(m["name"])
            return {
                "nombre": m["name"], "bytes": m.get("size", 0), "digest": m.get("digest"),
                "modificado": m.get("modified_at"), "familia": det.get("family"),
                "parametros": det.get("parameter_size"), "cuantizacion": det.get("quantization_level"),
                "formato": det.get("format"), "capacidades": d.get("capabilities") or [],
                "contexto_max": info.get(f"{arq}.context_length"),
                "cargado": {"bytes": c.get("size"), "vram": c.get("size_vram"), "contexto": c.get("context_length"),
                            "expira": c.get("expires_at")} if c else None,
            }
        with ThreadPoolExecutor(6) as ex:
            return list(ex.map(ficha_corta, modelos))

    def ficha(self, modelo: str) -> Dict[str, Any]:
        d = self._post("/api/show", {"model": modelo, "verbose": True}, timeout=60)
        tensores = d.get("tensors") or []
        info = d.get("model_info") or {}
        # Los vocabularios verbosos pesan megas: fuera de la respuesta
        info = {k: v for k, v in info.items() if not (isinstance(v, list) and len(v) > 64)}
        return {
            "modelo": modelo,
            "capacidades": d.get("capabilities") or [],
            "detalles": d.get("details") or {},
            "info": info,
            "parametros": _parametros(d.get("parameters", "")),
            "plantilla": d.get("template", ""),
            "system": d.get("system", ""),
            "licencia": d.get("license", ""),
            "modelfile": d.get("modelfile", ""),
            "mensajes": d.get("messages") or [],
            "modificado": d.get("modified_at"),
            "tensores": {"total": len(tensores), "lista": tensores[:400],
                         "tipos": _contar(t.get("type") for t in tensores)},
        }

    # ------------------------------------------------------------ crear, copiar, borrar
    def crear_variante(self, nombre: str, desde: str, system: str = "", parametros: Optional[Dict[str, Any]] = None,
                       mensajes: Optional[List[Dict[str, str]]] = None, licencia: str = "") -> Generator[Dict[str, Any], None, None]:
        nombre = _nombre(nombre)
        if nombre == desde or nombre in (desde + ":latest",):
            raise ErrorGestion("La variante necesita un nombre distinto del modelo base")
        cuerpo: Dict[str, Any] = {"model": nombre, "from": desde}
        if system.strip():
            cuerpo["system"] = system
        if parametros:
            from ollama_opciones import validar, EXCLUIDAS
            cuerpo["parameters"] = validar({k: v for k, v in parametros.items() if k not in ("keep_alive", "think", "system_extra", "truncate", "shift")})
        if mensajes:
            limpios = [{"role": m["role"], "content": m["content"]} for m in mensajes
                       if m.get("role") in ("user", "assistant", "system") and (m.get("content") or "").strip()]
            if limpios:
                cuerpo["messages"] = limpios
        if licencia.strip():
            cuerpo["license"] = licencia
        yield from self._stream("/api/create", cuerpo)

    def copiar(self, origen: str, destino: str) -> Dict[str, Any]:
        destino = _nombre(destino)
        r = requests.post(self.base + "/api/copy", json={"source": origen, "destination": destino}, timeout=120)
        if r.status_code != 200:
            raise ErrorGestion(self._error(r))
        return {"ok": True, "modelo": destino}

    def borrar(self, modelo: str) -> Dict[str, Any]:
        r = requests.delete(self.base + "/api/delete", json={"model": modelo}, timeout=120)
        if r.status_code != 200:
            raise ErrorGestion(self._error(r))
        return {"ok": True}

    # ------------------------------------------------------------ importar GGUF
    def importar_gguf(self, ruta: str, nombre: str, cancelar: Optional[Callable[[], bool]] = None) -> Generator[Dict[str, Any], None, None]:
        nombre = _nombre(nombre)
        if not os.path.isfile(ruta):
            raise ErrorGestion(f"No existe el archivo: {ruta}")
        with open(ruta, "rb") as f:
            if f.read(4) != b"GGUF":
                raise ErrorGestion("El archivo no es un modelo GGUF (no empieza por la firma GGUF)")
        total = os.path.getsize(ruta)

        # 1. Huella del archivo
        h = hashlib.sha256()
        leidos = 0
        with open(ruta, "rb") as f:
            while True:
                bloque = f.read(8 * 1024 * 1024)
                if not bloque:
                    break
                h.update(bloque)
                leidos += len(bloque)
                if cancelar and cancelar():
                    raise ErrorGestion("Cancelado")
                yield {"fase": "huella", "hecho": leidos, "total": total}
        digest = "sha256:" + h.hexdigest()

        # 2. Subirlo a Ollama si no lo tiene ya
        if requests.head(f"{self.base}/api/blobs/{digest}", timeout=30).status_code != 200:
            enviado = {"n": 0}

            def trozos():
                with open(ruta, "rb") as f:
                    while True:
                        bloque = f.read(8 * 1024 * 1024)
                        if not bloque:
                            break
                        enviado["n"] += len(bloque)
                        yield bloque
            # La subida corre en otro hilo para poder informar del avance
            with ThreadPoolExecutor(1) as ex:
                futuro = ex.submit(lambda: requests.post(f"{self.base}/api/blobs/{digest}", data=trozos(), timeout=24 * 3600))
                while not futuro.done():
                    yield {"fase": "subida", "hecho": enviado["n"], "total": total}
                    time.sleep(0.5)
                r = futuro.result()
            if r.status_code not in (200, 201):
                raise ErrorGestion(f"Ollama rechazó el archivo: {self._error(r)}")
        yield {"fase": "subida", "hecho": total, "total": total}

        # 3. Crear el modelo a partir del archivo
        for d in self._stream("/api/create", {"model": nombre, "files": {os.path.basename(ruta): digest}}):
            yield {"fase": "creando", "estado": d.get("status")}
        yield {"fase": "listo", "modelo": nombre}

    # ------------------------------------------------------------ actualizaciones
    @staticmethod
    def _repo_tag(nombre: str):
        base, _, tag = nombre.partition(":")
        return (base if "/" in base else f"library/{base}"), (tag or "latest")

    def actualizaciones(self) -> List[Dict[str, Any]]:
        modelos = self._get("/api/tags").get("models", [])

        def revisar(m):
            repo, tag = self._repo_tag(m["name"])
            try:
                r = requests.get(f"{REGISTRO}/v2/{repo}/manifests/{tag}", timeout=20,
                                 headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"})
            except Exception as e:
                return {"modelo": m["name"], "estado": "error", "detalle": str(e)}
            if r.status_code == 404:
                return {"modelo": m["name"], "estado": "local", "detalle": "No está en el registro (creado o importado aquí)"}
            if r.status_code != 200:
                return {"modelo": m["name"], "estado": "error", "detalle": f"HTTP {r.status_code}"}
            remoto = hashlib.sha256(r.content).hexdigest()
            return {"modelo": m["name"], "estado": "al_dia" if remoto == m.get("digest") else "actualizable",
                    "local": (m.get("digest") or "")[:12], "remoto": remoto[:12]}
        with ThreadPoolExecutor(6) as ex:
            return list(ex.map(revisar, modelos))

    # ------------------------------------------------------------ cargados
    def cargados(self) -> List[Dict[str, Any]]:
        return [{"nombre": m["name"], "bytes": m.get("size", 0), "vram": m.get("size_vram", 0),
                 "contexto": m.get("context_length"), "expira": m.get("expires_at")}
                for m in self._get("/api/ps").get("models", [])]

    def precargar(self, modelo: str, opciones: Dict[str, Any], keep_alive: Optional[str]) -> Dict[str, Any]:
        cuerpo: Dict[str, Any] = {"model": modelo, "prompt": "", "stream": False, "options": opciones}
        if keep_alive is not None:
            cuerpo["keep_alive"] = keep_alive
        self._post("/api/generate", cuerpo, timeout=600)
        return {"ok": True, "cargados": self.cargados()}

    def descargar(self, modelo: str) -> Dict[str, Any]:
        self._post("/api/generate", {"model": modelo, "keep_alive": 0}, timeout=60)
        return {"ok": True, "cargados": self.cargados()}

    # ------------------------------------------------------------ descargas a medias
    @staticmethod
    def carpeta_modelos() -> str:
        return os.environ.get("OLLAMA_MODELS") or os.path.expanduser("~/.ollama/models")

    def parciales(self, carpeta: Optional[str] = None) -> Dict[str, Any]:
        blobs = os.path.join(carpeta or self.carpeta_modelos(), "blobs")
        archivos = []
        if os.path.isdir(blobs):
            for n in os.listdir(blobs):
                if "partial" in n:
                    ruta = os.path.join(blobs, n)
                    try:
                        archivos.append({"nombre": n, "bytes": os.path.getsize(ruta), "ruta": ruta})
                    except OSError:
                        pass
        return {"carpeta": blobs, "archivos": archivos, "bytes": sum(a["bytes"] for a in archivos)}

    def borrar_parciales(self, carpeta: Optional[str] = None) -> Dict[str, Any]:
        """ Solo archivos con "partial" en el nombre dentro de blobs/: nunca un modelo completo """
        info = self.parciales(carpeta)
        borrados = 0
        for a in info["archivos"]:
            if os.path.dirname(a["ruta"]) != info["carpeta"] or "partial" not in a["nombre"]:
                continue
            try:
                os.remove(a["ruta"])
                borrados += 1
            except OSError:
                pass
        return {"borrados": borrados, "bytes": info["bytes"]}

    # ------------------------------------------------------------ probar
    def probar(self, cuerpo: Dict[str, Any], timeout: float = 900) -> Dict[str, Any]:
        r = requests.post(self.base + "/api/generate", json={**cuerpo, "stream": False}, timeout=timeout)
        if r.status_code != 200:
            raise ErrorGestion(self._error(r))
        return r.json()

    def uso_disco(self) -> Dict[str, Any]:
        modelos = self._get("/api/tags").get("models", [])
        return {"modelos": len(modelos), "bytes": sum(m.get("size", 0) for m in modelos),
                "carpeta": self.carpeta_modelos()}


def _contar(valores) -> Dict[str, int]:
    cuenta: Dict[str, int] = {}
    for v in valores:
        cuenta[v or "?"] = cuenta.get(v or "?", 0) + 1
    return cuenta
