"""
Herramientas que un modelo puede usar desde el chat (tool calling de Ollama).

Verificado con qwen3:30b-a3b: pidió `sumar(a=1234, b=4321)`, recibió 5555 y respondió
con ese resultado. Solo se ofrecen a modelos con la capacidad `tools`.

Todas leen: la biblioteca, los archivos de la carpeta de trabajo, la hora. La única
que actúa, ejecutar Python, solo se ofrece si el usuario lo permite explícitamente
en ese mensaje, y corre en la misma sesión aislada que los cuadernos, con el mismo
tiempo máximo.
"""

import json
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

MAX_RESULTADO = 6000


def _funcion(nombre: str, descripcion: str, propiedades: Dict[str, Any], requeridas: List[str]) -> Dict[str, Any]:
    return {"type": "function", "function": {
        "name": nombre, "description": descripcion,
        "parameters": {"type": "object", "properties": propiedades, "required": requeridas}}}


DEFINICIONES = {
    "buscar_biblioteca": _funcion(
        "buscar_biblioteca",
        "Busca en los libros importados del usuario afirmaciones sobre un tema, con su cita literal y página.",
        {"consulta": {"type": "string", "description": "Tema o pregunta a buscar"}}, ["consulta"]),
    "listar_archivos": _funcion(
        "listar_archivos",
        "Lista los archivos y carpetas de la carpeta de trabajo del usuario (o de una subcarpeta).",
        {"carpeta": {"type": "string", "description": "Subcarpeta relativa; vacío para la raíz"}}, []),
    "leer_archivo": _funcion(
        "leer_archivo",
        "Lee un archivo de la carpeta de trabajo. Devuelve las líneas numeradas.",
        {"ruta": {"type": "string", "description": "Ruta relativa a la carpeta de trabajo"},
         "desde_linea": {"type": "integer", "description": "Primera línea (1 por defecto)"},
         "hasta_linea": {"type": "integer", "description": "Última línea (200 más por defecto)"}}, ["ruta"]),
    "buscar_en_archivos": _funcion(
        "buscar_en_archivos",
        "Busca un texto en todos los archivos de la carpeta de trabajo y devuelve archivo, línea y contenido.",
        {"texto": {"type": "string", "description": "Texto a buscar"}}, ["texto"]),
    "fecha_hora": _funcion("fecha_hora", "Devuelve la fecha y hora actuales del equipo.", {}, []),
    "ejecutar_python": _funcion(
        "ejecutar_python",
        "Ejecuta código Python en una sesión aislada y devuelve lo que imprime. Úsalo para calcular o comprobar.",
        {"codigo": {"type": "string", "description": "Código Python a ejecutar"}}, ["codigo"]),
}

ETIQUETAS = {
    "buscar_biblioteca": "Buscando en la biblioteca",
    "listar_archivos": "Listando archivos",
    "leer_archivo": "Leyendo archivo",
    "buscar_en_archivos": "Buscando en los archivos",
    "fecha_hora": "Consultando la hora",
    "ejecutar_python": "Ejecutando Python",
}


def _recortar(texto: str) -> str:
    return texto if len(texto) <= MAX_RESULTADO else texto[:MAX_RESULTADO] + "\n[… recortado]"


class Herramientas:
    def __init__(self, knowledge_base=None, file_mgr=None, ide=None, runner=None,
                 permitir_codigo: bool = False, timeout: int = 25):
        self.kb = knowledge_base
        self.fm = file_mgr
        self.ide = ide
        self.runner = runner
        self.permitir_codigo = permitir_codigo
        self.timeout = timeout

    def definiciones(self) -> List[Dict[str, Any]]:
        nombres = [n for n in DEFINICIONES if n != "ejecutar_python" or self.permitir_codigo]
        if not self.kb:
            nombres.remove("buscar_biblioteca")
        return [DEFINICIONES[n] for n in nombres]

    def ejecutar(self, nombre: str, argumentos: Dict[str, Any]) -> str:
        if isinstance(argumentos, str):
            try:
                argumentos = json.loads(argumentos)
            except ValueError:
                argumentos = {}
        metodo: Optional[Callable] = getattr(self, f"_h_{nombre}", None)
        if metodo is None or (nombre == "ejecutar_python" and not self.permitir_codigo):
            return f"Herramienta no disponible: {nombre}"
        try:
            return _recortar(metodo(**(argumentos or {})))
        except TypeError as e:
            return f"Argumentos no válidos para {nombre}: {e}"
        except PermissionError as e:
            return f"Acceso denegado: {e}"
        except Exception as e:
            return f"Error en {nombre}: {e}"

    # ------------------------------------------------------------------
    def _h_buscar_biblioteca(self, consulta: str = "") -> str:
        filas = self.kb.buscar(consulta, limite=8)
        if not filas:
            return "No hay afirmaciones sobre eso en la biblioteca."
        titulos = {}
        try:
            with self.kb.conectar() as c:
                titulos = {f["source_id"]: f["title"] for f in c.execute("SELECT source_id, title FROM books;")}
        except Exception:
            pass
        lineas = []
        for f in filas:
            libro = titulos.get(f.get("source_id"), f.get("source_id"))
            cita = f" — «{f['quote']}»" if f.get("quote") else ""
            lineas.append(f"- {f.get('text')}{cita} ({libro}, p. {f.get('page')})")
        return "\n".join(lineas)

    def _h_listar_archivos(self, carpeta: str = "") -> str:
        base = self.fm.resolve(carpeta or self.fm.base_dir)
        if not os.path.isdir(base):
            return f"No es una carpeta: {carpeta}"
        entradas = []
        for nombre in sorted(os.listdir(base))[:300]:
            if nombre.startswith(".") or nombre in ("__pycache__", "node_modules", ".venv", "venv"):
                continue
            ruta = os.path.join(base, nombre)
            entradas.append(f"{nombre}/" if os.path.isdir(ruta) else nombre)
        return "\n".join(entradas) or "(carpeta vacía)"

    def _h_leer_archivo(self, ruta: str, desde_linea: int = 1, hasta_linea: Optional[int] = None) -> str:
        datos = self.fm.read_file(ruta)
        if "error" in datos:
            return datos["error"]
        lineas = (datos.get("content") or "").splitlines()
        desde = max(1, int(desde_linea or 1))
        hasta = min(len(lineas), int(hasta_linea or desde + 199))
        cuerpo = "\n".join(f"{n:>5}  {lineas[n - 1]}" for n in range(desde, hasta + 1))
        return f"{ruta} (líneas {desde}-{hasta} de {len(lineas)})\n{cuerpo}"

    def _h_buscar_en_archivos(self, texto: str = "") -> str:
        r = self.ide.buscar(texto, limite=60)
        if not r["resultados"]:
            return "Sin coincidencias."
        return "\n".join(f"{a['rel']}:{c['linea']}: {c['texto'].strip()}"
                         for a in r["resultados"] for c in a["coincidencias"])

    def _h_fecha_hora(self) -> str:
        return datetime.now().strftime("%A %d/%m/%Y %H:%M:%S")

    def _h_ejecutar_python(self, codigo: str = "") -> str:
        r = self.runner.run_cell_code(codigo, cwd=self.fm.base_dir, session_id="chat-herramientas",
                                      timeout=self.timeout)
        partes = []
        if r.get("stdout"):
            partes.append(r["stdout"])
        if r.get("stderr"):
            partes.append("ERROR:\n" + r["stderr"])
        return "\n".join(partes) or ("(sin salida)" if r.get("success") else "(falló sin mensaje)")
