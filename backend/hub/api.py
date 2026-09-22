"""
API de Prig Hub (/api/hub/*). app.py crea el router con sus dependencias:

    crear_router(runner=…, motor=…, consumir=…, ndjson=…, desafios=…, telemetria=…, publico=…, autor=…)

así este módulo no importa app (evita el ciclo) y las pruebas pueden montarlo con piezas falsas.
"""

from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

try:
    import github_lector as gl
except ImportError:
    from backend import github_lector as gl

from . import github as gh
from . import git
from .servicio import ErrorHub, Hub


class SincronizarLocal(BaseModel):
    destino: str = "prig"
    categorias_youtube: Optional[List[str]] = None
    incluir_todas_youtube: bool = False
    incluir_desafios: bool = True
    desafios_ids: Optional[List[str]] = None
    crear_ruta_estudio: bool = True


class Texto(BaseModel):
    texto: str


class Agregar(BaseModel):
    destino: str = "prig"
    url: str
    titulo: str = ""
    nota: str = ""
    etiquetas: Optional[List[str]] = None
    tipo: str = ""
    nivel: str = ""
    minutos: Optional[int] = None


class Clave(BaseModel):
    destino: str = "prig"
    clave: str


class Editar(Clave):
    cambios: Dict[str, Any]


class Copiar(BaseModel):
    origen: str
    clave: str
    destino: str = "prig"


class Manifiesto(BaseModel):
    destino: str
    cambios: Dict[str, Any]


class Pack(BaseModel):
    titulo: str
    descripcion: str = ""
    etiquetas: Optional[List[str]] = None
    nivel: str = ""


class Paso(BaseModel):
    titulo: str = ""
    destino: str
    nota: str = ""


class Ruta(BaseModel):
    destino: str
    id: str = ""
    titulo: str
    descripcion: str = ""
    nivel: str = ""
    etiquetas: Optional[List[str]] = None
    introduccion: str = ""
    pasos: List[Paso]


class RutaBorrar(BaseModel):
    destino: str
    id: str


class Url(BaseModel):
    url: str


class Suscripcion(BaseModel):
    clave: str


class Aplicar(BaseModel):
    clave: str
    commit: str


class Progreso(BaseModel):
    clave: str
    estado: str
    origen: str = ""
    version: str = ""


class Importar(BaseModel):
    origen: str
    id: str
    confirmado: bool = False


class Exportar(BaseModel):
    destino: str
    id_desafio: str


class Destino(BaseModel):
    destino: str


class Preguntar(BaseModel):
    origen: str
    mensajes: List[Dict[str, str]]
    modelo: Optional[str] = None


class Ajustes(BaseModel):
    publicar_resumen: Optional[bool] = None


def crear_router(runner, motor: Callable, consumir: Callable, ndjson: Callable, desafios, telemetria: Callable,
                 publico: Callable, validar_desafio: Callable, autor: Callable[[], str] = lambda: "",
                 hub: Optional[Hub] = None) -> APIRouter:
    r = APIRouter(prefix="/api/hub")
    # Un Hub por petición: su carpeta sale de PRIG_HUB_DIR en ese momento (las pruebas la cambian)
    servicio = (lambda: hub) if hub else Hub

    def h(fn, *a, **k):
        try:
            return fn(*a, **k)
        except (ErrorHub, git.ErrorGit, gh.ErrorGitHubHub) as e:
            raise HTTPException(status_code=400, detail=str(e))

    def propio(destino: str) -> str:
        nombre = destino.split(":", 1)[1] if destino.startswith("propio:") else destino
        if nombre == "prig":
            h(servicio().asegurar_perfil, autor())
        return nombre

    @r.get("/estado")
    def estado():
        t = gl.token()
        s = servicio()
        e = s._estado()
        return {"git": git.disponible(), "token": bool(t), "origen_token": (t or {}).get("origen"),
                "github": e.get("github"), "ajustes": e["ajustes"], "carpeta": s.base}

    @r.get("/todo")
    def todo():
        s = servicio()
        h(s.asegurar_perfil, autor())
        return h(s.todo)

    @r.get("/repos")
    def repos():
        return h(servicio().repos)

    @r.get("/repo")
    def repo(origen: str):
        return h(servicio().leer, origen)

    @r.post("/analizar")
    def analizar(req: Texto):
        return h(servicio().analizar, req.texto, gh.es_hub)

    @r.post("/agregar")
    def agregar(req: Agregar):
        return h(servicio().agregar, propio(req.destino), req.url, req.titulo, req.nota, req.etiquetas,
                 req.tipo, req.nivel, req.minutos)

    @r.post("/quitar")
    def quitar(req: Clave):
        return {"ok": h(servicio().quitar, propio(req.destino), req.clave)}

    @r.post("/editar")
    def editar(req: Editar):
        return {"ok": h(servicio().editar, propio(req.destino), req.clave, req.cambios)}

    @r.post("/copiar")
    def copiar(req: Copiar):
        return h(servicio().copiar, req.origen, req.clave, propio(req.destino))

    @r.post("/manifiesto")
    def manifiesto(req: Manifiesto):
        return h(servicio().editar_manifiesto, propio(req.destino), req.cambios)

    @r.post("/packs")
    def crear_pack(req: Pack):
        return {"nombre": h(servicio().crear_pack, req.titulo, req.descripcion, req.etiquetas, req.nivel, autor())}

    @r.post("/rutas")
    def guardar_ruta(req: Ruta):
        pasos = [p.model_dump() for p in req.pasos]
        return {"id": h(servicio().guardar_ruta, propio(req.destino), req.titulo, pasos, req.id, req.descripcion,
                        req.nivel, req.etiquetas, req.introduccion)}

    @r.post("/rutas/borrar")
    def borrar_ruta(req: RutaBorrar):
        h(servicio().borrar_ruta, propio(req.destino), req.id)
        return {"ok": True}

    @r.get("/recursos_locales")
    def recursos_locales():
        s = servicio()
        return h(s.obtener_recursos_locales_catalogo, desafios)

    @r.post("/sincronizar_local")
    def sincronizar_local(req: SincronizarLocal):
        s = servicio()
        return h(s.sincronizar_desde_prig, propio(req.destino), req.model_dump(), autor(), desafios)

    @r.post("/seguir")
    def seguir(req: Url):
        texto = req.url.strip()
        s = servicio()
        if "/" not in texto and "." not in texto:                  # un usuario suelto: su perfil o nombre pack
            if texto.lower().startswith("prig-"):
                t = gl.token()
                login = (t or {}).get("usuario") or (t or {}).get("login")
                if login:
                    texto = f"https://github.com/{login}/{texto}"
                else:
                    texto = f"https://github.com/{texto}"
            else:
                texto = f"https://github.com/{texto.lstrip('@')}/prig"
        elif "/" in texto and not texto.startswith(("http://", "https://", "git@")):
            texto = f"https://github.com/{texto.lstrip('@')}"
        return h(s.seguir, texto, autor())

    @r.post("/dejar")
    def dejar(req: Suscripcion):
        h(servicio().dejar, req.clave)
        return {"ok": True}

    @r.post("/novedades")
    def novedades(req: Suscripcion):
        return h(servicio().novedades, req.clave)

    @r.post("/aplicar")
    def aplicar(req: Aplicar):
        return h(servicio().aplicar, req.clave, req.commit)

    @r.post("/descartar")
    def descartar(req: Suscripcion):
        h(servicio().descartar, req.clave)
        return {"ok": True}

    @r.post("/progreso")
    def progreso(req: Progreso):
        return h(servicio().marcar, req.clave, req.estado, req.origen, req.version)

    @r.get("/desafio")
    def desafio(origen: str, id: str):
        """ Todo el código a la vista ANTES de importarlo: nada se ejecuta aquí """
        return h(servicio().desafio, origen, id)

    @r.post("/desafio/importar")
    def importar(req: Importar):
        if not req.confirmado:
            raise HTTPException(status_code=400, detail="Revisa el código del desafío y confirma antes de importarlo.")
        s = servicio()
        d = h(s.a_desafio_prig, req.origen, req.id)
        priv = d["privado"]
        v = validar_desafio(runner, d["paginas"], priv["referencia"], priv)
        if not v["valido"]:
            raise HTTPException(status_code=400, detail=f"No pasa la verificación, así que no se importa: {v['motivo']}")
        d["comprobacion"]["pruebas"] = v["pruebas"]
        d["origen"]["verificado"] = True
        d = desafios.guardar(d)
        telemetria(d, "generated")
        s.marcar(s.clave_desafio(req.origen, req.id), "en_curso", req.origen, d["origen"].get("version") or "")
        return publico(d)

    @r.post("/desafio/exportar")
    def exportar(req: Exportar):
        try:
            d = desafios.obtener(req.id_desafio)
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e))
        return {"id": h(servicio().exportar_desafio, propio(req.destino), d)}

    @r.get("/desafios_locales")
    def desafios_locales():
        """ Los desafíos de la sección Desafíos que se pueden compartir en un pack """
        filas = []
        for d in desafios.lista():
            filas.append({"id": d.get("id"), "titulo": d.get("titulo"), "nivel": d.get("nivel"),
                          "origen": (d.get("origen") or {}).get("nombre") or (d.get("origen") or {}).get("tipo")})
        return {"desafios": filas}

    @r.post("/publicar")
    def publicar(req: Destino):
        t = gl.token()
        token = (t or {}).get("token")
        return h(servicio().publicar, propio(req.destino), gh.Cuenta(token) if token else None, token)

    @r.get("/descubrir")
    def descubrir(q: str = "", tipo: str = "pack", pagina: int = 1):
        return h(gh.descubrir, q, tipo, pagina)

    @r.post("/ajustes")
    def ajustes(req: Ajustes):
        return h(servicio().ajustes, req.model_dump(exclude_none=True))

    @r.post("/preguntar")
    def preguntar(req: Preguntar):
        """ El tutor sobre un repositorio: su contenido va como DATOS y sin herramientas """
        if not req.mensajes:
            raise HTTPException(status_code=400, detail="Escribe una pregunta.")
        s = servicio()
        datos = h(s.contexto_ia, req.origen)
        motor_ia, nombre = motor(req.modelo, "explicar")
        from desafios.tutor import flujo
        historial = "\n".join(f"{'Alumno' if m.get('rol') == 'usuario' else 'Tutor'}: {str(m.get('texto'))[:1500]}"
                              for m in req.mensajes[-10:])

        def trabajo(avisar):
            return {"texto": consumir(flujo(motor_ia, nombre, f"{datos}\n\nCONVERSACIÓN:\n{historial}\nTutor:",
                                            s.SISTEMA_IA, temperatura=0.4), avisar)}
        return ndjson(trabajo)

    return r
