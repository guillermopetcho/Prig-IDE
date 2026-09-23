"""
Lo que hace el modelo en los desafíos.

Reglas que atraviesan todo el módulo:

  · El modelo nunca decide si el código está bien: eso lo decide ejecutar las pruebas.
  · La caja de razonamiento, el plan, las pistas y el chat NO dan la solución; enseñan
    a pensar el problema. Lo que parezca código se retira de la caja de razonamiento.
  · Un desafío creado por el modelo solo se entrega si su referencia pasa las pruebas y
    el código de partida no; si falla, se reintenta contándole al modelo por qué falló.
  · Los modelos que piensan en voz alta (think) lo hacen en silencio aquí: se pide
    think=False cuando el modelo lo admite y los bloques <think> se retiran siempre.
"""

import re
import time
from typing import Any, Callable, Dict, Generator, List, Optional

from . import ejecucion
from .ejecucion import ErrorDesafio

_PENSAMIENTO = re.compile(r"<think(?:ing)?>.*?(?:</think(?:ing)?>|$)\s*", re.S | re.I)
NIVELES = ("principiante", "intermedio", "avanzado", "senior")


# ===========================================================================
# Llamadas al modelo
# ===========================================================================

def _error_de_modelo(texto: str) -> Optional[str]:
    t = (texto or "").strip()
    if t.startswith("[Error Gemini:"):
        return t[len("[Error Gemini:"):].rstrip("]").strip()
    if t.startswith("[Error Ollama") or t.startswith("[Error de conexión"):
        try:
            from ai_engine.ai_engine_class import explicar_error_motor
            return explicar_error_motor(t) or t.strip("[]")
        except ImportError:
            return t.strip("[]")
    return None


def generar(ai, modelo: str, prompt: str, sistema: str, temperatura: float = 0.3,
            on_token: Optional[Callable[[str], None]] = None,
            formato: Optional[str] = None) -> str:
    partes = []
    opciones = {"temperature": temperatura}
    if formato:
        opciones["format"] = formato
    for trozo in ai.generate_response(prompt, model=modelo, system_prompt=sistema, think=False,
                                      options=opciones, uso="tutor",
                                      on_token=on_token):
        partes.append(trozo)
    texto = "".join(partes)
    error = _error_de_modelo(texto)
    if error:
        raise ErrorDesafio(error)
    return _PENSAMIENTO.sub("", texto).strip()


def extraer_contenido_cuaderno(texto_ipynb: str) -> str:
    """ Extrae de un cuaderno Jupyter (.ipynb) las celdas de teoría en markdown y los bloques de código,
    para que el modelo reciba un texto pedagógico limpio en lugar de un JSON crudo con metadatos. """
    try:
        import json
        data = json.loads(texto_ipynb)
        celdas = data.get("cells") or []
        partes = []
        for c in celdas:
            ctype = c.get("cell_type")
            src = "".join(c.get("source") or [])
            if not src.strip():
                continue
            if ctype == "markdown":
                partes.append(f"# [Instrucciones / Explicación]\n{src.strip()}\n")
            elif ctype == "code":
                partes.append(f"```\n{src.strip()}\n```\n")
        return "\n\n".join(partes) if partes else texto_ipynb
    except Exception:
        return texto_ipynb


def flujo(ai, modelo: str, prompt: str, sistema: str, temperatura: float = 0.4,
          pensar: bool = False) -> Generator[Dict[str, Any], None, str]:
    """ Eventos {"tipo": "texto", "delta"} con lo que escribe el modelo (sin su pensamiento)
    y {"tipo": "pensando"} mientras piensa. Devuelve el texto completo. """
    tokens: List[str] = []
    pensando = []
    texto = []
    visible, emitido = "", 0
    for trozo in ai.generate_response(prompt, model=modelo, system_prompt=sistema, think=pensar,
                                      options={"temperature": temperatura}, uso="tutor",
                                      on_token=tokens.append, on_thinking=pensando.append):
        texto.append(trozo)
        if len(texto) == 1:
            error = _error_de_modelo(trozo)
            if error:
                raise ErrorDesafio(error)
        if pensando:
            pensando.clear()
            yield {"tipo": "pensando"}
        if tokens:
            visible += "".join(tokens)
            tokens.clear()
            # Las etiquetas <think> pueden llegar partidas entre trozos: se limpia lo
            # acumulado y se retiene un posible comienzo de etiqueta al final
            limpio = _PENSAMIENTO.sub("", visible)
            corte = limpio.rfind("<")
            if corte >= 0 and "<think".startswith(limpio[corte:corte + 6]) and ">" not in limpio[corte:]:
                limpio = limpio[:corte]
            if len(limpio) > emitido:
                yield {"tipo": "texto", "delta": limpio[emitido:]}
                emitido = len(limpio)
    return _PENSAMIENTO.sub("", "".join(texto)).strip()


def _paginas_texto(paginas: List[Dict[str, Any]], limite: int = 6000) -> str:
    partes = []
    for p in paginas or []:
        partes.append(f"--- página {p['nombre']}{' (' + p['descripcion'] + ')' if p.get('descripcion') else ''} ---\n{p.get('contenido') or ''}")
    texto = "\n".join(partes)
    return texto if len(texto) <= limite else texto[:limite] + "\n…(recortado)"


def _enunciado(d: Dict[str, Any]) -> str:
    return (d.get("enunciado_es") or d.get("enunciado") or "")[:6000]


# ===========================================================================
# Crear un desafío verificado
# ===========================================================================

SISTEMA_CREAR = """Eres un CREADOR DE DESAFÍOS DE PROGRAMACIÓN en Python para aprender razonando.

Devuelve ÚNICAMENTE un objeto JSON válido (sin bloques markdown ni ``` alrededor ni dentro de los campos) con esta forma:
{
  "titulo": "Título breve",
  "enunciado": "Contexto del problema, qué hay que construir, reglas y 2 o 3 ejemplos de entrada → salida (en markdown)",
  "nivel": "principiante | intermedio | avanzado | senior",
  "conceptos": ["concepto 1", "concepto 2"],
  "paginas": [
    {"nombre": "archivo.py", "descripcion": "para qué sirve esta página", "contenido": "código de partida"}
  ],
  "referencia": [
    {"nombre": "archivo.py", "contenido": "solución completa de esa página"}
  ],
  "pruebas": [
    "from archivo import funcion\\nassert funcion(2) == 4",
    "from archivo import funcion\\nassert funcion(0) == 0"
  ]
}

REGLAS:
1. PÁGINAS: usa UNA página si el problema es una función o una clase. Usa 2 o 3 páginas solo
   cuando el diseño lo pide de verdad (por ejemplo: modelo de datos, lógica, programa
   principal). Las páginas se usan entre sí con import: `from inventario import Producto`
   (el nombre del módulo es el de la página sin .py). Nombres de página: minúsculas, _ y .py.
2. El código de partida tiene firmas, docstrings y `pass` o `raise NotImplementedError`,
   con comentarios TODO que orienten. NUNCA la solución: CADA página con funciones o clases
   debe tener algo por implementar. SIEMPRE incluye `pass` en cuerpos incompletos para que
   el código compile limpiamente.
3. "referencia" tiene exactamente las mismas páginas que "paginas", completas y correctas.
4. "pruebas": entre 4 y 8 fragmentos INDEPENDIENTES; cada uno importa lo que usa y termina en
   assert. Incluye casos normales y casos límite (vacío, cero, negativos, repetidos…).
   Deben PASAR con la referencia y FALLAR con el código de partida.
5. Si el nivel es 'senior', incluye en el enunciado las cotas asintóticas requeridas (tiempo y espacio O(...))
   y prueba casos exigentes y límites de escala.
6. Solo biblioteca estándar. Nada de input(), red, archivos ni aleatoriedad sin semilla.
7. Usa \\n para los saltos de línea dentro de las cadenas JSON. NUNCA envuelvas el valor de "contenido" en cercas ```."""


SISTEMA_CREAR_CPP = """Eres un CREADOR DE DESAFÍOS DE PROGRAMACIÓN en C++ (estándar C++20) para aprender razonando.

Devuelve ÚNICAMENTE un objeto JSON válido (sin bloques markdown ni ``` alrededor ni dentro de los campos) con esta forma:
{
  "titulo": "Título breve",
  "enunciado": "Contexto del problema, qué hay que construir, firmas de funciones o clases, reglas y 2 o 3 ejemplos de entrada → salida (en markdown)",
  "nivel": "principiante | intermedio | avanzado | senior",
  "conceptos": ["concepto 1", "concepto 2"],
  "paginas": [
    {"nombre": "solucion.h", "descripcion": "declaraciones de la clase o funciones", "contenido": "código de cabecera con comentarios"},
    {"nombre": "solucion.cpp", "descripcion": "implementación a completar", "contenido": "esqueleto con TODOs y valores por defecto"}
  ],
  "referencia": [
    {"nombre": "solucion.h", "contenido": "cabecera completa"},
    {"nombre": "solucion.cpp", "contenido": "implementación correcta y completa"}
  ],
  "pruebas": [
    "REQUIRE(funcion(2) == 4);",
    "REQUIRE(funcion(0) == 0);"
  ]
}

REGLAS:
1. PÁGINAS: define una cabecera (.h) con las declaraciones e interfaces, y una implementación (.cpp) con el esqueleto. Nombres en minúsculas y guiones bajos (solucion.h, solucion.cpp).
2. El código de partida DEBE compilar limpiamente pero FALLAR las pruebas (devuelve 0, false, "", etc., con comentarios // TODO). NUNCA dejes la solución completa en las páginas de partida.
3. "referencia" tiene exactamente las mismas páginas que "paginas", con la solución completa, eficiente y correcta.
4. "pruebas": entre 4 y 8 aserciones con REQUIRE(...) de Catch2 (no incluyas TEST_CASE, solo la línea con REQUIRE o bloque).
5. Si el nivel es 'senior', especifica complejidades O(...) en el enunciado, aprovecha características de C++20 (ranges, concepts, move semantics si aplica) y garantiza eficiencia sin copias innecesarias.
6. Solo biblioteca estándar C++ (STL). Nada de librerías externas ni entrada interactiva std::cin.
7. Usa \\n para los saltos de línea dentro de las cadenas JSON. NUNCA envuelvas el valor de "contenido" en cercas ```."""


SISTEMA_REPLICAR = """Eres un EXPERTO EN EDUCACIÓN DE PROGRAMACIÓN. Tu tarea es tomar código, un ejercicio, algoritmo o problema de un repositorio de GitHub y convertirlo en un DESAFÍO DIDÁCTICO interactivo para Prig IDE en Python.

Devuelve ÚNICAMENTE un objeto JSON válido (sin bloques markdown ni ``` alrededor ni dentro de los campos) con esta forma:
{
  "titulo": "Título breve y descriptivo en español",
  "enunciado": "Explicación clara del problema en español, requisitos, reglas y 2 o 3 ejemplos de entrada → salida (en markdown)",
  "nivel": "principiante | intermedio | avanzado | senior",
  "conceptos": ["concepto 1", "concepto 2"],
  "paginas": [
    {"nombre": "modulo.py", "descripcion": "Descripción del módulo", "contenido": "código de partida con firmas y pass/TODOs"}
  ],
  "referencia": [
    {"nombre": "modulo.py", "contenido": "solución completa, óptima y limpia"}
  ],
  "pruebas": [
    "from modulo import funcion\\nassert funcion(2) == 4",
    "from modulo import funcion\\nassert funcion(0) == 0"
  ]
}

REGLAS:
1. El código de partida ("paginas") NO debe contener la solución: incluye las firmas de funciones/clases, docstrings explicativos y comentarios # TODO con pass o retorno neutro. CADA función, método o clase sin implementar DEBE tener `pass` para que el código compile sin errores de sintaxis pero falle las pruebas.
2. "referencia" debe implementar la solución correcta, eficiente y completa.
3. "pruebas": de 3 a 6 aserciones independientes con assert, importando el módulo de las páginas.
4. Si es de nivel 'senior' o algoritmo complejo, incluye en el enunciado las cotas de complejidad esperadas.
5. Solo biblioteca estándar de Python.
6. Usa \\n para saltos de línea dentro de cadenas JSON. NUNCA envuelvas el valor de "contenido" en cercas ```."""


SISTEMA_REPLICAR_CPP = """Eres un EXPERTO EN EDUCACIÓN DE PROGRAMACIÓN. Tu tarea es tomar código, un ejercicio, algoritmo o problema de un repositorio de GitHub y convertirlo en un DESAFÍO DIDÁCTICO interactivo para Prig IDE en C++ (estándar C++20).

Devuelve ÚNICAMENTE un objeto JSON válido (sin bloques markdown ni ``` alrededor ni dentro de los campos) con esta forma:
{
  "titulo": "Título breve y descriptivo en español",
  "enunciado": "Explicación clara del problema en español, firmas de funciones o clases, requisitos y 2 o 3 ejemplos de entrada → salida (en markdown)",
  "nivel": "principiante | intermedio | avanzado | senior",
  "conceptos": ["concepto 1", "concepto 2"],
  "paginas": [
    {"nombre": "solucion.h", "descripcion": "declaraciones de clases o funciones", "contenido": "#ifndef SOLUCION_H\\n#define SOLUCION_H\\n...\\n#endif"},
    {"nombre": "solucion.cpp", "descripcion": "esqueleto de implementación", "contenido": "#include \\"solucion.h\\"\\n... con valores dummy y // TODO"}
  ],
  "referencia": [
    {"nombre": "solucion.h", "contenido": "cabecera completa"},
    {"nombre": "solucion.cpp", "contenido": "implementación correcta y completa"}
  ],
  "pruebas": [
    "REQUIRE(funcion(2) == 4);",
    "REQUIRE(funcion(0) == 0);"
  ]
}

REGLAS:
1. "paginas": define cabecera (.h) e implementación (.cpp) con esqueleto que compila pero falla las pruebas (devuelve 0, false, \\"\\", etc., con // TODO).
2. "referencia" contiene la solución completa, eficiente y óptima en C++20.
3. "pruebas": de 3 a 6 aserciones con REQUIRE(...) de Catch2 (no incluyas TEST_CASE).
4. Si es de nivel 'senior', detalla requerimientos de complejidad y asegura el uso óptimo de memoria y STL.
5. Solo biblioteca estándar C++ (STL).
6. Usa \\n para saltos de línea dentro de cadenas JSON. NUNCA envuelvas el valor de "contenido" en cercas ```."""



def limpiar_codigo(codigo: str, lenguaje: str = "python") -> str:
    """ Limpia delimitadores markdown (```python ... ```), espacios superfluos
    y adapta comentarios de estilo C en Python para que el código sea sintácticamente válido. """
    if not isinstance(codigo, str):
        return ""
    texto = codigo.strip()

    # Quitar delimitadores markdown al inicio y al final si el modelo envolvió el contenido en ellos
    if texto.startswith("```"):
        lineas = texto.splitlines()
        if lineas and lineas[0].strip().startswith("```"):
            lineas = lineas[1:]
        if lineas and lineas[-1].strip() == "```":
            lineas = lineas[:-1]
        texto = "\n".join(lineas).strip()

    # Si aún quedase un bloque cerrado por ``` al final
    if texto.endswith("```"):
        texto = texto[:-3].rstrip()

    if lenguaje == "python":
        lineas_p = []
        for linea in texto.split("\n"):
            stripped = linea.lstrip()
            # Convertir comentarios de estilo C '//' al inicio de línea en '#'
            if stripped.startswith("//"):
                indent = len(linea) - len(stripped)
                lineas_p.append(" " * indent + "#" + stripped[2:])
            else:
                lineas_p.append(linea)
        texto = "\n".join(lineas_p)

    return texto


def _normalizar_creado(datos: Dict[str, Any], lenguaje: str = "python") -> Dict[str, Any]:
    def paginas(lista, con_desc=True):
        salida = []
        for p in lista or []:
            if not isinstance(p, dict):
                continue
            nombre = str(p.get("nombre") or p.get("name") or "").strip()
            if nombre and not (nombre.endswith(".py") or nombre.endswith((".cpp", ".h", ".hpp", ".cc", ".cxx"))):
                nombre += ".cpp" if lenguaje == "cpp" else ".py"
            contenido = limpiar_codigo(str(p.get("contenido") or p.get("content") or ""), lenguaje)
            item = {"nombre": nombre, "contenido": contenido}
            if con_desc:
                item["descripcion"] = str(p.get("descripcion") or "")
            salida.append(item)
        return salida

    pruebas_raw = datos.get("pruebas") or datos.get("tests") or []
    if isinstance(pruebas_raw, str):
        pruebas_raw = [b for b in re.split(r"\n\s*\n", pruebas_raw) if b.strip()]
    pruebas = []
    for t in pruebas_raw:
        limpio = limpiar_codigo(str(t), lenguaje).strip()
        if limpio:
            pruebas.append(limpio)
    nivel = str(datos.get("nivel") or "intermedio").lower()
    return {
        "titulo": str(datos.get("titulo") or "Desafío").strip()[:120],
        "enunciado": str(datos.get("enunciado") or "").strip(),
        "nivel": nivel if nivel in NIVELES else "intermedio",
        "conceptos": [str(c) for c in (datos.get("conceptos") or [])][:6],
        "paginas": paginas(datos.get("paginas")),
        "referencia": paginas(datos.get("referencia"), con_desc=False),
        "pruebas": pruebas,
        "lenguaje": lenguaje,
    }


def reparar_cuerpos_vacios(codigo: str, maximo: int = 30) -> str:
    """ Añade `pass` a def/class/if… cuyo cuerpo es solo comentarios TODO o está vacío.

    Los modelos pequeños dejan con frecuencia métodos así, que no compilan: el alumno
    empezaría con un error de sintaxis y las pruebas fallarían por eso, no por lo que
    falta programar. """
    codigo = limpiar_codigo(codigo, "python")
    lineas = codigo.split("\n")
    for _ in range(maximo):
        try:
            compile("\n".join(lineas), "<pagina>", "exec")
            break
        except SyntaxError as e:
            m = re.search(r"expected an indented block.*on line (\d+)", str(e.msg))
            cabecera = None
            if m:
                cabecera = int(m.group(1)) - 1
            elif "expected an indented block" in str(e.msg):
                idx = (e.lineno or 1) - 1
                while idx >= 0:
                    linea_strip = lineas[idx].strip()
                    if linea_strip.endswith(":") and any(linea_strip.startswith(kw) for kw in (
                        "def ", "class ", "if ", "elif ", "else:", "for ", "while ",
                        "try:", "except", "finally:", "with ", "async def ", "async for ", "async with "
                    )):
                        cabecera = idx
                        break
                    idx -= 1

            if cabecera is None or cabecera < 0 or cabecera >= len(lineas):
                break

            sangria = len(lineas[cabecera]) - len(lineas[cabecera].lstrip()) + 4
            i = cabecera + 1
            while i < len(lineas) and (not lineas[i].strip() or (lineas[i].strip().startswith("#")
                                                                    and len(lineas[i]) - len(lineas[i].lstrip()) >= sangria)):
                i += 1
            while i > cabecera + 1 and not lineas[i - 1].strip():
                i -= 1
            lineas.insert(i, " " * sangria + "pass")
    return "\n".join(lineas)


def _sin_compilar(paginas: List[Dict[str, Any]], lenguaje: str = "python") -> Optional[str]:
    if lenguaje == "cpp":
        return None
    for p in paginas:
        try:
            compile(p["contenido"], p["nombre"], "exec")
        except SyntaxError as e:
            return f"{p['nombre']} (línea {e.lineno}: {e.msg})"
    return None


def _pruebas_sin_compilar(pruebas: List[str], lenguaje: str = "python") -> Optional[str]:
    if lenguaje == "cpp":
        return None
    for i, fragmento in enumerate(pruebas, 1):
        try:
            compile(fragmento, f"<prueba {i}>", "exec")
        except SyntaxError as e:
            return f"prueba {i} (línea {e.lineno}: {e.msg})"
    return None


def _pagina_ya_resuelta(datos: Dict[str, Any]) -> Optional[str]:
    """ Comprueba si alguna página de partida ya es idéntica a la referencia """
    if datos.get("lenguaje") == "cpp":
        # En C++ es normal que .h sea igual entre partida y referencia
        for pi in datos.get("paginas") or []:
            if pi["nombre"].endswith(('.cpp', '.cc', '.cxx')):
                pr = next((r for r in datos.get("referencia") or [] if r["nombre"] == pi["nombre"]), None)
                if pr and pi.get("contenido", "").strip() == pr.get("contenido", "").strip() and len(pi.get("contenido", "").strip()) > 30:
                    return pi["nombre"]
        return None
    for pi in datos.get("paginas") or []:
        pr = next((r for r in datos.get("referencia") or [] if r["nombre"] == pi["nombre"]), None)
        if pr and pi.get("contenido", "").strip() == pr.get("contenido", "").strip() and len(pi.get("contenido", "").strip()) > 40:
            return pi["nombre"]
    return None


def crear(ai, runner, modelo: str, tema: str, nivel: str = "intermedio", contexto: str = "", intentos: int = 4,
          avisar: Callable[[Dict[str, Any]], None] = lambda ev: None, lenguaje: str = "python") -> Dict[str, Any]:
    """ Pide el desafío al modelo y lo comprueba ejecutándolo; reintenta contando qué falló """
    if not (tema or contexto).strip():
        raise ErrorDesafio("Di qué quieres practicar.")
    nivel = nivel if nivel in NIVELES else "intermedio"
    fallo_anterior = ""
    historial = []
    sistema = SISTEMA_CREAR_CPP if lenguaje == "cpp" else SISTEMA_CREAR
    for n in range(1, intentos + 1):
        avisar({"tipo": "progreso", "mensaje": f"Intento {n} de {intentos}: el modelo escribe el desafío en {lenguaje.upper()}…", "intento": n})
        prompt = (f"Tema a practicar: {tema or '(ver conversación)'}\nLenguaje: {lenguaje}\nNivel del alumno: {nivel}\n"
                  + (f"\nContexto:\n{contexto[:4000]}\n" if contexto else "")
                  + (f"\nEl intento anterior no sirvió porque: {fallo_anterior}\nCorrígelo.\n" if fallo_anterior else "")
                  + "\nCrea el desafío.")
        try:
            texto = generar(ai, modelo, prompt, sistema, temperatura=0.4, formato="json")
            try:
                datos_crudos = ai._extract_and_parse_json(texto)
            except Exception:
                from ai_engine.ai_engine_class import reparar_y_parsear_json
                datos_crudos = reparar_y_parsear_json(texto)
            datos = _normalizar_creado(datos_crudos, lenguaje=lenguaje)
        except ErrorDesafio:
            raise
        except Exception as e:
            fallo_anterior = (
                "La respuesta no tuvo un formato JSON válido o se cortó antes de cerrar las llaves. "
                "Devuelve ÚNICAMENTE el objeto JSON completo con las llaves, cerrando todas las comillas."
            )
            historial.append({"intento": n, "motivo": str(e)[:120]})
            continue
        datos["enunciado"] = re.sub(r"^\s*(markdown( en español)?|enunciado)\s*:\s*", "", datos["enunciado"], flags=re.I)
        if lenguaje == "python":
            for p in datos["paginas"]:
                p["contenido"] = reparar_cuerpos_vacios(p["contenido"])
            for p in datos["referencia"]:
                p["contenido"] = reparar_cuerpos_vacios(p["contenido"])
        elif lenguaje == "cpp":
            for p in datos["paginas"]:
                p["contenido"] = limpiar_codigo(p["contenido"], "cpp")
            for p in datos["referencia"]:
                p["contenido"] = limpiar_codigo(p["contenido"], "cpp")
        rota = _sin_compilar(datos["paginas"], lenguaje=lenguaje) or _sin_compilar(datos["referencia"], lenguaje=lenguaje)
        if rota:
            fallo_anterior = f"el código no compila: {rota}. Pon pass en los cuerpos sin implementar"
            historial.append({"intento": n, "motivo": fallo_anterior})
            avisar({"tipo": "progreso", "mensaje": f"Intento {n} descartado: {fallo_anterior}", "intento": n, "descartado": True})
            continue
        pruebas_rotas = _pruebas_sin_compilar(datos["pruebas"], lenguaje=lenguaje)
        if pruebas_rotas:
            fallo_anterior = f"las pruebas no compilan: {pruebas_rotas}. Corrige la sintaxis de los asserts"
            historial.append({"intento": n, "motivo": fallo_anterior})
            avisar({"tipo": "progreso", "mensaje": f"Intento {n} descartado: {fallo_anterior}", "intento": n, "descartado": True})
            continue
        resuelta = _pagina_ya_resuelta(datos)
        if resuelta:
            fallo_anterior = f"la página {resuelta} del código de partida ya trae la solución: deja su lógica sin implementar"
            historial.append({"intento": n, "motivo": fallo_anterior})
            avisar({"tipo": "progreso", "mensaje": f"Intento {n} descartado: {fallo_anterior}", "intento": n, "descartado": True})
            continue
        if len(datos["pruebas"]) < 3:
            fallo_anterior = "hacen falta al menos 4 pruebas"
            historial.append({"intento": n, "motivo": fallo_anterior})
            continue
        avisar({"tipo": "progreso", "mensaje": f"Intento {n}: comprobando que la solución pasa las pruebas y el código de partida no…", "intento": n})
        tipo_comprobacion = "cpp_asserts" if lenguaje == "cpp" else "asserts"
        privado = {"comprobacion": {"tipo": tipo_comprobacion, "asserts": datos["pruebas"]}, "referencia": datos["referencia"]}
        v = ejecucion.validar_desafio(runner, datos["paginas"], datos["referencia"], privado, minimo_pruebas=3)
        historial.append({"intento": n, "valido": v["valido"], "motivo": v["motivo"]})
        if v["valido"]:
            return {
                "titulo": datos["titulo"], "enunciado": datos["enunciado"], "idioma": "es", "teoria": "",
                "nivel": datos["nivel"], "conceptos": datos["conceptos"] or [tema], "lenguaje": lenguaje,
                "paginas": [{**p, "descripcion": p.get("descripcion", "")} for p in datos["paginas"]],
                "comprobacion": {"tipo": tipo_comprobacion, "pruebas": v["pruebas"], "pruebas_visibles": False},
                "privado": privado, "intentos_creacion": historial,
            }
        fallo_anterior = v["motivo"]
        avisar({"tipo": "progreso", "mensaje": f"Intento {n} descartado: {v['motivo'][:160]}", "intento": n, "descartado": True})
    raise ErrorDesafio("El modelo no consiguió un desafío que se pueda comprobar en "
                       f"{intentos} intentos (último motivo: {fallo_anterior[:200]}). "
                       "Prueba con un modelo más capaz o con un tema más concreto.")


def replicar_desde_github(ai, runner, modelo: str, ref: str, ruta: str, contenido: str,
                          lenguaje: str = "python", tema: str = "", nivel: str = "intermedio",
                          intentos: int = 3, avisar: Callable[[Dict[str, Any]], None] = lambda ev: None) -> Dict[str, Any]:
    """ Toma el código/enunciado de un archivo en GitHub y lo replica como un desafío interactivo evaluable en Prig. """
    if not (contenido or ruta).strip():
        raise ErrorDesafio("El archivo de GitHub está vacío o no es válido.")

    sistema = SISTEMA_REPLICAR_CPP if lenguaje == "cpp" else SISTEMA_REPLICAR
    fallo_anterior = ""
    historial = []

    for n in range(1, intentos + 1):
        avisar({"tipo": "progreso", "mensaje": f"Intento {n} de {intentos}: el modelo analiza y adapta el desafío desde {ref}/{ruta}…", "intento": n})
        prompt = (f"Repositorio de origen: {ref}\n"
                  f"Archivo de origen: {ruta}\n"
                  f"Lenguaje objetivo: {lenguaje}\n"
                  f"Nivel sugerido: {nivel}\n"
                  f"Tema/Contexto: {tema or ruta}\n\n"
                  f"Contenido original del archivo en GitHub (recortado):\n```\n{contenido[:3500]}\n```\n"
                  + (f"\nEl intento anterior falló porque: {fallo_anterior}\nCorrige este problema.\n" if fallo_anterior else "")
                  + "\nGenera el desafío didáctico interactivo. Responde ÚNICAMENTE con el objeto JSON válido.")

        tokens_recibidos = 0
        ultimo_aviso = time.time()

        def al_token(_tok: str) -> None:
            nonlocal tokens_recibidos, ultimo_aviso
            tokens_recibidos += 1
            ahora = time.time()
            if ahora - ultimo_aviso >= 2.0:
                ultimo_aviso = ahora
                avisar({"tipo": "progreso", "mensaje": f"Intento {n} de {intentos}: redactando desafío… ({tokens_recibidos} tokens)", "intento": n, "tokens": tokens_recibidos})

        try:
            texto = generar(ai, modelo, prompt, sistema, temperatura=0.3, on_token=al_token, formato="json")
            try:
                datos_crudos = ai._extract_and_parse_json(texto)
            except Exception:
                from ai_engine.ai_engine_class import reparar_y_parsear_json
                datos_crudos = reparar_y_parsear_json(texto)
            datos = _normalizar_creado(datos_crudos, lenguaje=lenguaje)
        except ErrorDesafio:
            raise
        except Exception as e:
            fallo_anterior = (
                "La respuesta no tuvo un formato JSON válido o se cortó antes de cerrar las llaves. "
                "Devuelve ÚNICAMENTE el objeto JSON completo con las llaves, cerrando todas las comillas."
            )
            historial.append({"intento": n, "motivo": str(e)[:120]})
            avisar({"tipo": "progreso", "mensaje": f"Intento {n} descartado: formato no válido ({str(e)[:80]}). Reintentando con estructura corregida…", "intento": n, "descartado": True})
            continue

        datos["enunciado"] = re.sub(r"^\s*(markdown( en español)?|enunciado)\s*:\s*", "", datos["enunciado"], flags=re.I)
        if lenguaje == "python":
            for p in datos["paginas"]:
                p["contenido"] = reparar_cuerpos_vacios(p["contenido"])
            for p in datos["referencia"]:
                p["contenido"] = reparar_cuerpos_vacios(p["contenido"])
        elif lenguaje == "cpp":
            for p in datos["paginas"]:
                p["contenido"] = limpiar_codigo(p["contenido"], "cpp")
            for p in datos["referencia"]:
                p["contenido"] = limpiar_codigo(p["contenido"], "cpp")

        rota = _sin_compilar(datos["paginas"], lenguaje=lenguaje) or _sin_compilar(datos["referencia"], lenguaje=lenguaje)
        if rota:
            fallo_anterior = f"el código no compila: {rota}. Pon pass en los cuerpos sin implementar"
            historial.append({"intento": n, "motivo": fallo_anterior})
            avisar({"tipo": "progreso", "mensaje": f"Intento {n} descartado: {fallo_anterior[:120]}… Reintentando con correcciones…", "intento": n, "descartado": True})
            continue

        pruebas_rotas = _pruebas_sin_compilar(datos["pruebas"], lenguaje=lenguaje)
        if pruebas_rotas:
            fallo_anterior = f"las pruebas no compilan: {pruebas_rotas}. Corrige la sintaxis de los asserts"
            historial.append({"intento": n, "motivo": fallo_anterior})
            avisar({"tipo": "progreso", "mensaje": f"Intento {n} descartado: {fallo_anterior[:120]}… Reintentando con correcciones…", "intento": n, "descartado": True})
            continue

        resuelta = _pagina_ya_resuelta(datos)
        if resuelta:
            fallo_anterior = f"la página {resuelta} del código de partida ya trae la solución: deja su lógica sin implementar"
            historial.append({"intento": n, "motivo": fallo_anterior})
            avisar({"tipo": "progreso", "mensaje": f"Intento {n} descartado: {fallo_anterior[:120]}… Reintentando con correcciones…", "intento": n, "descartado": True})
            continue

        if len(datos["pruebas"]) < 2:
            fallo_anterior = "hacen falta al menos 3 pruebas"
            historial.append({"intento": n, "motivo": fallo_anterior})
            avisar({"tipo": "progreso", "mensaje": f"Intento {n} descartado: {fallo_anterior[:120]}… Reintentando con correcciones…", "intento": n, "descartado": True})
            continue

        avisar({"tipo": "progreso", "mensaje": f"Intento {n}: comprobando que la solución pasa las pruebas y el código de partida no…", "intento": n})
        tipo_comprobacion = "cpp_asserts" if lenguaje == "cpp" else "asserts"
        privado = {"comprobacion": {"tipo": tipo_comprobacion, "asserts": datos["pruebas"]}, "referencia": datos["referencia"]}
        v = ejecucion.validar_desafio(runner, datos["paginas"], datos["referencia"], privado, minimo_pruebas=2)
        historial.append({"intento": n, "valido": v["valido"], "motivo": v["motivo"]})
        if v["valido"]:
            return {
                "titulo": datos["titulo"],
                "enunciado": datos["enunciado"],
                "idioma": "es",
                "teoria": f"Replicado y adaptado automáticamente a partir de `{ref}/{ruta}` en GitHub.",
                "nivel": datos["nivel"],
                "conceptos": datos["conceptos"] or [tema or "algoritmos"],
                "lenguaje": lenguaje,
                "paginas": [{**p, "descripcion": p.get("descripcion", "")} for p in datos["paginas"]],
                "comprobacion": {"tipo": tipo_comprobacion, "pruebas": v["pruebas"], "pruebas_visibles": False},
                "privado": privado,
                "intentos_creacion": historial,
                "origen": {
                    "tipo": "github",
                    "nombre": f"GitHub · {ref}",
                    "ref": f"{ref}/{ruta}",
                    "url": f"https://github.com/{ref}/blob/master/{ruta}",
                    "licencia": "Open Source",
                    "lenguaje": lenguaje
                }
            }
        fallo_anterior = v["motivo"]
        avisar({"tipo": "progreso", "mensaje": f"Intento {n} descartado: {v['motivo'][:160]}", "intento": n, "descartado": True})

    raise ErrorDesafio(f"No se pudo replicar automáticamente el archivo como desafío evaluable tras {intentos} intentos: {fallo_anterior[:200]}")



# ===========================================================================
# Caja de razonamiento
# ===========================================================================

PASOS = ["Qué me piden", "Ejemplos a mano y casos límite", "Descomponer el problema",
         "Qué estrategia usar y por qué", "El algoritmo paso a paso", "Cómo comprobarlo y cuánto cuesta"]

SISTEMA_RAZONAR = """Eres un profesor de RESOLUCIÓN DE PROBLEMAS. Enseñas CÓMO PENSAR un desafío de
programación antes de escribir código. NO lo resuelves.

PROHIBIDO escribir código en cualquier lenguaje (ni Python, ni pseudocódigo con sintaxis de
programación). Usa frases en español, listas y, si ayuda, tablas pequeñas.

Escribe EXACTAMENTE estas seis secciones, con estos encabezados:
## 1. Qué me piden
Reformula el problema con otras palabras: datos de entrada, resultado esperado y restricciones.
## 2. Ejemplos a mano y casos límite
Resuelve a mano un ejemplo pequeño mostrando cada paso, y lista los casos límite que hay que cuidar.
## 3. Descomponer el problema
Divide el problema en subproblemas pequeños. Si hay varias páginas, qué responsabilidad tiene cada una.
## 4. Qué estrategia usar y por qué
Qué patrón o técnica encaja (recorrido, acumulador, dos punteros, recursión, diccionario de
conteo, ordenar primero, divide y vencerás…), por qué, y qué alternativa descartas y por qué.
## 5. El algoritmo paso a paso
Pasos numerados en lenguaje natural, sin sintaxis de programación.
## 6. Cómo comprobarlo y cuánto cuesta
Cómo verificar que funciona (qué probar) y su coste en tiempo y memoria explicado con palabras.

Empieza cada sección con una o dos PREGUNTAS que el alumno debería hacerse, en cursiva."""

_CODIGO = re.compile(r"```[\w+-]*\n(.*?)```", re.S)
_PARECE_CODIGO = re.compile(r"(^|\n)\s*(def |class |import |from \w+ import|return\b|for \w+ in |while .+:|print\(|\w+\s*=\s*\[|#include|std::|template\s*<|cout\s*<<|int\s+main\s*\()", re.M)


def _sin_codigo(texto: str) -> str:
    def cambiar(m):
        return "*(Aquí iba código: la caja de razonamiento no da la solución.)*" if _PARECE_CODIGO.search(m.group(1)) else m.group(0)
    return _CODIGO.sub(cambiar, texto)


def separar_pasos(texto: str) -> List[Dict[str, str]]:
    texto = _sin_codigo(_PENSAMIENTO.sub("", texto or ""))
    trozos = re.split(r"(?m)^##\s+", texto)
    pasos = []
    for t in trozos[1:]:
        titulo, _, cuerpo = t.partition("\n")
        titulo = re.sub(r"^\d+[.)]\s*", "", titulo.strip()).strip("# ")
        if cuerpo.strip():
            pasos.append({"titulo": titulo or f"Paso {len(pasos) + 1}", "contenido": cuerpo.strip()})
    if len(pasos) < 3:
        return [{"titulo": "Cómo pensar este desafío", "contenido": texto.strip()}] if texto.strip() else []
    return pasos


def razonamiento(ai, modelo: str, d: Dict[str, Any]) -> Generator[Dict[str, Any], None, List[Dict[str, str]]]:
    paginas = "\n".join(f"- {p['nombre']}: {p.get('descripcion') or ''}" for p in d.get("paginas") or [])
    prompt = (f"DESAFÍO: {d.get('titulo')}\nNivel: {d.get('nivel')}\n\nENUNCIADO:\n{_enunciado(d)}\n\n"
              f"PÁGINAS DE CÓDIGO:\n{paginas}\n\nCÓDIGO DE PARTIDA (solo firmas):\n{_paginas_texto(d.get('paginas'), 3000)}\n\n"
              "Explica cómo razonar este desafío en las seis secciones.")
    texto = yield from flujo(ai, modelo, prompt, SISTEMA_RAZONAR, temperatura=0.3)
    return separar_pasos(texto)


# ===========================================================================
# Plan del alumno, pistas, reflexión
# ===========================================================================

def revisar_plan(ai, modelo: str, d: Dict[str, Any], plan: str):
    if not (plan or "").strip():
        raise ErrorDesafio("Escribe primero tu plan.")
    sistema = ("Eres un tutor socrático. El alumno escribió CÓMO piensa resolver un desafío antes de programar. "
               "Valóralo en español, en menos de 160 palabras y con esta estructura:\n"
               "**Bien pensado:** lo que está bien.\n**Falta considerar:** el caso o paso que se le escapa, en forma de pregunta.\n"
               "**Siguiente paso:** una acción concreta.\n"
               "Sin código. No reveles la solución aunque la conozcas; si el plan es incorrecto, guíale con preguntas.")
    ref = _paginas_texto((d.get("privado") or {}).get("referencia") or [], 3000)
    prompt = (f"DESAFÍO: {d.get('titulo')}\n{_enunciado(d)}\n\nPLAN DEL ALUMNO:\n{plan[:3000]}\n\n"
              + (f"(Solución de referencia, SOLO para que juzgues; NO la muestres:\n{ref})" if ref else ""))
    return (yield from flujo(ai, modelo, prompt, sistema, temperatura=0.3))


def analizar_propuesta(ai, modelo: str, propuesta: str, lenguaje: str = "python", nivel: str = "intermedio"):
    """ Analiza la propuesta, idea de desafío o planteamiento algorítmico del usuario y devuelve
    una evaluación técnica completa (viabilidad, complejidad asintótica, casos límite y recomendaciones). """
    if not (propuesta or "").strip():
        raise ErrorDesafio("Escribe primero tu propuesta o planteo.")
    es_cpp = (lenguaje or "").lower() == "cpp"
    lang_label = "C++ (C++20)" if es_cpp else "Python 3"
    sistema = (
        f"Eres un ingeniero senior y especialista en algoritmia y estructuras de datos para {lang_label}.\n"
        f"El usuario te presenta una propuesta técnica o tema a nivel {nivel}.\n"
        "Tu objetivo es analizar su propuesta y devolver exactamente lo que el usuario pide o necesita en Markdown conciso y estructurado:\n\n"
        "1. **Evaluación de la Propuesta**: Viabilidad técnica, pertinencia algorítmica y enfoque general.\n"
        "2. **Complejidad y Rendimiento**: Cota asintótica Big-O esperada de tiempo y espacio (O(N), O(log N), etc.) y cómo optimizarla.\n"
        "3. **Casos Críticos y de Borde**: Casos extremos que deben considerarse.\n"
        "4. **Recomendaciones de Implementación**: Estructuras de datos óptimas y mejores prácticas idiomáticas para "
        + ("C++20 (STL, semántica de movimiento, gestión de memoria RAII)" if es_cpp else "Python 3 (estructuras estándar, generadores, legibilidad)")
        + ".\n\n"
        "Responde en español de forma directa, sin introducciones innecesarias."
    )
    prompt = f"LENGUAJE: {lang_label}\nNIVEL: {nivel}\n\nPROPUESTA O SOLICITUD:\n{propuesta.strip()[:4000]}"
    return (yield from flujo(ai, modelo, prompt, sistema, temperatura=0.3))



NIVELES_PISTA = {
    1: ("Pista conceptual", "Da UNA pista CONCEPTUAL: qué idea o estructura resuelve esto. Sin código. Máximo 2 frases."),
    2: ("Pista de estructura", "Describe los PASOS en una lista breve, en lenguaje natural, sin escribir Python. Máximo 5 líneas."),
    3: ("Pista concreta", "Señala en el código del alumno la línea o parte que falla o falta, y muestra SOLO la expresión clave "
                          "que le falta con una frase de explicación. No entregues la solución completa."),
}


def pista(ai, modelo: str, d: Dict[str, Any], nivel: int, paginas: List[Dict[str, Any]], resultado: Optional[Dict[str, Any]] = None):
    nivel = max(1, min(int(nivel), 3))
    titulo, instruccion = NIVELES_PISTA[nivel]
    sistema = (f"Eres un tutor que guía sin resolver. {instruccion}\n"
               "Responde en español, directo, sin saludos. Nunca entregues la solución completa.")
    fallos = ""
    if resultado and resultado.get("fallos"):
        fallos = "\n".join(f"- {f.get('nombre')}: {f.get('mensaje')}" for f in resultado["fallos"][:4])
    prompt = (f"DESAFÍO: {d.get('titulo')}\n{_enunciado(d)}\n\nCÓDIGO ACTUAL DEL ALUMNO:\n{_paginas_texto(paginas)}\n\n"
              + (f"PRUEBAS QUE FALLAN:\n{fallos}\n\n" if fallos else "")
              + f"(Referencia interna, NO revelar:\n{_paginas_texto((d.get('privado') or {}).get('referencia') or [], 3000)})")
    yield {"tipo": "titulo", "texto": f"{titulo} {nivel}/3"}
    return (yield from flujo(ai, modelo, prompt, sistema, temperatura=0.3))


def reflexion(ai, modelo: str, d: Dict[str, Any], paginas: List[Dict[str, Any]]):
    sistema = ("Eres un mentor de programación. El alumno YA resolvió el desafío. Haz una revisión breve en español "
               "(menos de 250 palabras) con estas secciones:\n"
               "**Lo que hiciste bien**\n**Coste**: tiempo y memoria de SU solución, explicado.\n"
               "**Una mejora**: legibilidad o eficiencia, con un fragmento corto si ayuda.\n"
               "**Otra forma de pensarlo**: una estrategia distinta (compárala con la de referencia si es otra), sin el código completo.")
    ref = _paginas_texto((d.get("privado") or {}).get("referencia") or [], 3000)
    prompt = (f"DESAFÍO: {d.get('titulo')}\n{_enunciado(d)[:3000]}\n\nSOLUCIÓN DEL ALUMNO (aprobada):\n{_paginas_texto(paginas)}\n\n"
              + (f"SOLUCIÓN DE REFERENCIA:\n{ref}" if ref else ""))
    return (yield from flujo(ai, modelo, prompt, sistema, temperatura=0.4))


# ===========================================================================
# Traducir y chat
# ===========================================================================

SISTEMA_ANALISIS = """Eres el tutor que revisa el AVANCE de un alumno de programación en Python.

Te dan datos MEDIDOS (desafíos resueltos ejecutando pruebas, intentos, pistas, dominio por
concepto, bloques del plan). Analízalos sin inventar nada: si algo no está en los datos, no lo
digas. Habla en español, en segunda persona, directo y sin halagos vacíos.

Escribe estas secciones con encabezados «## »:
## Dónde estás
Dos o tres frases con lo que los datos muestran (volumen, constancia, qué ya resuelve solo).
## Lo que se te resiste
Los conceptos con menor dominio y POR QUÉ lo parecen (muchas pistas, rendirse, varios intentos).
## Cómo estás aprendiendo
Hábitos que se ven en los datos: si usa la caja de razonamiento, si escribe el plan antes de
programar, si reintenta o se rinde. Di qué hábito le conviene cambiar y por qué.
## Plan para las próximas tres sesiones
Tres puntos, uno por sesión: `- **tema concreto** — qué hacer y por qué ese tema ahora`.
## Cómo sabrás que avanzaste
Una señal observable y comprobable (por ejemplo: resolver X sin pistas).

Termina con un bloque ```json {"temas": ["tema 1", "tema 2", "tema 3"]} ``` con los temas del
plan, tal como los pondrías en el buscador de desafíos. Nada de código en el resto del texto."""


def analisis_progreso(ai, modelo: str, contexto: str):
    """ Lectura del avance del alumno. Se pide con razonamiento en voz alta si el modelo lo
    trae: aquí sí ayuda a cruzar datos, y el pensamiento no se le muestra al alumno. """
    return (yield from flujo(ai, modelo, f"DATOS DEL ALUMNO:\n{contexto[:12000]}\n\nAnaliza su avance.",
                             SISTEMA_ANALISIS, temperatura=0.3, pensar=True))


def traducir(ai, modelo: str, texto: str):
    sistema = ("Traduce al español el texto en markdown que te da el usuario. Conserva EXACTAMENTE: bloques de código, "
               "nombres de funciones, variables y archivos, fórmulas entre $ y enlaces. Devuelve solo la traducción.")
    return (yield from flujo(ai, modelo, texto[:8000], sistema, temperatura=0.1))


def palabras_clave(ai, modelo: str, tema: str) -> List[str]:
    """ Términos en inglés para buscar en fuentes que usan ese idioma """
    sistema = ('Devuelve ÚNICAMENTE un JSON {"terminos": ["...", "..."]} con 3 a 6 términos cortos en INGLÉS '
               "(nombres de algoritmos, estructuras de datos o conceptos de Python) que describan el tema.")
    try:
        datos = ai._extract_and_parse_json(generar(ai, modelo, f"Tema: {tema[:500]}", sistema, temperatura=0.1))
        return [str(t)[:40] for t in (datos.get("terminos") or [])][:6]
    except Exception:
        return []


def chat(ai, modelo: str, mensajes: List[Dict[str, str]], d: Optional[Dict[str, Any]] = None,
         paginas: Optional[List[Dict[str, Any]]] = None, resultado: Optional[Dict[str, Any]] = None):
    if d:
        sistema = ("Eres el tutor de un desafío de programación en Python. Responde dudas en español, breve (menos de 150 "
                   "palabras): explica conceptos, interpreta errores y guía con preguntas. NUNCA des la solución completa "
                   "ni reescribas la función entera; como mucho una línea o expresión si el alumno ya lo intentó.")
        contexto = (f"DESAFÍO: {d.get('titulo')}\n{_enunciado(d)[:3000]}\n\nCÓDIGO ACTUAL:\n{_paginas_texto(paginas or [], 4000)}\n"
                    + (f"\nÚLTIMA COMPROBACIÓN: {resultado.get('pasados')}/{resultado.get('total')} pruebas; "
                       + "; ".join(f"{f.get('nombre')}: {f.get('mensaje')}" for f in (resultado.get('fallos') or [])[:3])
                       if resultado else ""))
    else:
        sistema = ("Eres el entrenador de desafíos de Prig. Ayudas al alumno a decidir QUÉ practicar. Conversa en español, breve "
                   "(menos de 120 palabras). Si no sabes su nivel o el tema, pregúntalo. Propón 2 o 3 ideas de desafío concretas "
                   "(qué habría que construir, no cómo). Cuando esté decidido, dile que pulse «Crear desafío» o «Buscar en "
                   "internet». No escribas soluciones.")
        contexto = ""
    historial = "\n".join(f"{'Alumno' if m.get('rol') == 'usuario' else 'Tutor'}: {str(m.get('texto'))[:1500]}"
                          for m in (mensajes or [])[-12:])
    prompt = (contexto + "\n\n" if contexto else "") + f"CONVERSACIÓN:\n{historial}\nTutor:"
    return (yield from flujo(ai, modelo, prompt, sistema, temperatura=0.5))


def conversacion_como_contexto(mensajes: List[Dict[str, str]]) -> str:
    return "\n".join(f"{'Alumno' if m.get('rol') == 'usuario' else 'Tutor'}: {str(m.get('texto'))[:800]}"
                     for m in (mensajes or [])[-10:])


# ===========================================================================
# Evaluación de la solución y salida por el modelo
# ===========================================================================

SISTEMA_EVALUAR_SALIDA = """Eres un TUTOR Y EVALUADOR EXPERTO DE PROGRAMACIÓN.
Tu misión es evaluar la solución del alumno para un desafío de programación.
Debes analizar detalladamente:
1. El CÓDIGO que programó el alumno.
2. La SALIDA que produjo al ejecutarse (código de salida, stdout, stderr).
3. El resultado de las pruebas automatizadas (si las hay).

Devuelve ÚNICAMENTE un objeto JSON válido (sin markdown ni bloques ```json alrededor) con este formato exacto:
{
  "aprobado": true o false,
  "calificacion": número entero del 1 al 10,
  "estado": "aprobado" | "parcial" | "error",
  "resumen": "Resumen conciso en 1 o 2 oraciones del veredicto.",
  "analisis_salida": "Qué imprimió el programa y por qué cumple o no con lo que pide el enunciado.",
  "analisis_codigo": "Calidad, lógica, buenas prácticas, legibilidad y posibles casos límite.",
  "consejos": ["Consejo 1...", "Consejo 2..."]
}

REGLAS DE EVALUACIÓN:
1. 'aprobado' es true SOLO si el código corre limpiamente (exit_code 0 y sin excepciones no controladas) Y la salida/lógica cumple satisfactoriamente con el objetivo del desafío.
2. Si el proceso falló con errores de sintaxis, excepciones (Traceback) o la salida no cumple lo pedido, 'aprobado' debe ser false y 'estado' debe ser 'error'.
3. Si el alumno casi lo logra pero le faltó un caso o tuvo un fallo menor, califica con 6-7, 'aprobado' es false y 'estado' es 'parcial'.
4. Si la solución es excelente, califica con 9-10 y 'aprobado' es true.
5. Sé pedagógico, motivador y claro en español."""


def evaluar_con_salida(ai, modelo: str, d: Dict[str, Any], paginas: List[Dict[str, Any]],
                       salida: str, stderr: str = "", exit_code: int = 0,
                       resultado_pruebas: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    lenguaje = d.get("lenguaje") or "python"
    titulo = d.get("titulo") or "Desafío de programación"
    enunciado = _enunciado(d)
    codigo_str = _paginas_texto(paginas, 6000)

    pruebas_info = ""
    if resultado_pruebas:
        pruebas_info = (f"\nPRUEBAS AUTOMATIZADAS:\n"
                        f"- Total: {resultado_pruebas.get('total', 0)}\n"
                        f"- Pasadas: {resultado_pruebas.get('pasados', 0)}\n"
                        f"- Aprobado: {resultado_pruebas.get('aprobado', False)}\n")
        if resultado_pruebas.get("fallos"):
            pruebas_info += "- Fallos detectados:\n" + "\n".join(
                f"  * {f.get('nombre', '')}: {f.get('mensaje', '')}" for f in resultado_pruebas["fallos"][:4]
            )

    prompt = (
        f"LENGUAJE: {lenguaje}\n"
        f"DESAFÍO: {titulo}\n"
        f"NIVEL: {d.get('nivel', 'intermedio')}\n\n"
        f"ENUNCIADO Y REQUISITOS:\n{enunciado[:4000]}\n\n"
        f"CÓDIGO DEL ALUMNO:\n{codigo_str}\n\n"
        f"RESULTADO DE LA EJECUCIÓN DEL ALUMNO:\n"
        f"- Código de salida (Exit Code): {exit_code}\n"
        f"- STDOUT:\n{salida[:4000] if salida else '(vacío)'}\n"
        f"- STDERR:\n{stderr[:2000] if stderr else '(vacío)'}\n"
        f"{pruebas_info}\n"
        f"Evalúa la solución y responde ÚNICAMENTE con el JSON solicitado."
    )

    respuesta_texto = generar(ai, modelo, prompt, SISTEMA_EVALUAR_SALIDA, temperatura=0.2)
    try:
        if hasattr(ai, "_extract_and_parse_json"):
            datos = ai._extract_and_parse_json(respuesta_texto)
        else:
            import json as _json
            m = re.search(r"\{[\s\S]*\}", respuesta_texto)
            datos = _json.loads(m.group(0)) if m else {}
    except Exception:
        datos = {}

    if not isinstance(datos, dict) or not datos.get("resumen"):
        aprobado = (exit_code == 0 and not stderr and ("aprobado" in respuesta_texto.lower() or "correcto" in respuesta_texto.lower()))
        datos = {
            "aprobado": aprobado,
            "calificacion": 8 if aprobado else 4,
            "estado": "aprobado" if aprobado else "error",
            "resumen": respuesta_texto[:250].strip() or ("Solución evaluada." if aprobado else "La ejecución tuvo observaciones."),
            "analisis_salida": f"Salida observada (exit code {exit_code}).",
            "analisis_codigo": "Revisa la lógica y los casos de prueba.",
            "consejos": ["Comprueba los casos borde y optimiza la eficiencia."]
        }

    return datos

