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

# Con el banco del proyecto activo (banco_proyecto.py): el modelo consulta el proyecto entero sin
# que quepa en su contexto, y deja anotado lo que aprende para las próximas preguntas
DEFINICIONES_BANCO = {
    "consola": _funcion(
        "consola",
        "Ejecuta Python sobre la memoria de consulta del proyecto: el objeto P da acceso a TODO el proyecto "
        "(archivos, líneas, símbolos, grafo de hechos, cambios, memoria, SQL de solo lectura y P.llm para "
        "leer trozos con otro modelo). Las variables persisten entre llamadas. Devuelve lo impreso y el valor "
        "de la última expresión. Úsala para preguntas exactas o que abarcan muchos archivos.",
        {"codigo": {"type": "string", "description": "Código Python que usa P (ver la ayuda en las instrucciones)"}},
        ["codigo"]),
    "ver_simbolo": _funcion(
        "ver_simbolo",
        "Devuelve el código completo de una función, método o clase del proyecto, con su ubicación.",
        {"nombre": {"type": "string", "description": "Nombre (p. ej. calientes_para o Motor.asegurar)"}}, ["nombre"]),
    "anotar": _funcion(
        "anotar",
        "Guarda en la memoria del proyecto algo que valga para futuras preguntas: una definición del dominio, "
        "teoría que explica el código, una decisión de diseño o contexto. No anotes lo obvio ni lo temporal.",
        {"tipo": {"type": "string", "enum": ["definicion", "teoria", "decision", "contexto", "nota"]},
         "titulo": {"type": "string", "description": "Término o tema, corto"},
         "texto": {"type": "string", "description": "El contenido, en una a cinco frases"},
         "rutas": {"type": "array", "items": {"type": "string"}, "description": "Archivos a los que se refiere"}},
        ["tipo", "titulo", "texto"]),
}

ETIQUETAS = {
    "consola": "Consultando la memoria del proyecto",
    "ver_simbolo": "Leyendo una función",
    "anotar": "Anotando en la memoria del proyecto",
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
                 permitir_codigo: bool = False, timeout: int = 25, banco=None, consola=None):
        self.kb = knowledge_base
        self.fm = file_mgr
        self.ide = ide
        self.runner = runner
        self.permitir_codigo = permitir_codigo
        self.timeout = timeout
        self.banco = banco
        self.consola = consola          # memoria_consulta.Consola: una por respuesta
        self.rutas_consultadas: List[str] = []      # lo que el modelo miró: va a la resolución

    def definiciones(self) -> List[Dict[str, Any]]:
        nombres = [n for n in DEFINICIONES if n != "ejecutar_python" or self.permitir_codigo]
        if not self.kb:
            nombres.remove("buscar_biblioteca")
        definiciones = [DEFINICIONES[n] for n in nombres]
        if self.banco is not None:
            definiciones += [d for n, d in DEFINICIONES_BANCO.items() if n != "consola" or self.consola is not None]
        return definiciones

    def ejecutar(self, nombre: str, argumentos: Dict[str, Any]) -> str:
        if isinstance(argumentos, str):
            try:
                argumentos = json.loads(argumentos)
            except ValueError:
                argumentos = {}
        metodo: Optional[Callable] = getattr(self, f"_h_{nombre}", None)
        if metodo is None or (nombre == "ejecutar_python" and not self.permitir_codigo) \
                or (nombre in DEFINICIONES_BANCO and self.banco is None) \
                or (nombre == "consola" and self.consola is None):
            return f"Herramienta no disponible: {nombre}"
        ruta = (argumentos or {}).get("ruta") if isinstance(argumentos, dict) else None
        if ruta and ruta not in self.rutas_consultadas:
            self.rutas_consultadas.append(str(ruta))
        try:
            resultado = metodo(**(argumentos or {}))
            return resultado if nombre == "consola" else _recortar(resultado)   # la consola ya recorta
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

    # ------------------------------------------------------------------ banco del proyecto
    def _h_ver_simbolo(self, nombre: str = "") -> str:
        return self.banco.ver_simbolo(nombre)

    def _h_consola(self, codigo: str = "") -> str:
        import memoria_consulta
        return memoria_consulta.formatear(self.consola.ejecutar(codigo))

    def _h_anotar(self, tipo: str = "nota", titulo: str = "", texto: str = "", rutas=None) -> str:
        if isinstance(rutas, str):
            rutas = [rutas]
        r = self.banco.anotar(tipo, titulo, texto, rutas or [], origen="modelo")
        return f"{'Actualizado' if r['actualizado'] else 'Guardado'} en la memoria del proyecto: ({r['tipo']}) {r['titulo']}"
