"""
Sondeo rápido de un libro, antes de gastar horas extrayéndolo.

Extraer un libro de 600 páginas son varias horas de GPU. Antes conviene saber con
qué se está tratando, porque hay cosas que cambian por completo cómo hay que
procesarlo y que no se ven en el título:

  · un PDF escaneado no tiene texto que extraer, y ningún modelo lo va a arreglar;
  · un libro de matemáticas puro necesita que se pida LaTeX en la extracción;
  · uno de programación necesita que se pida el lenguaje de cada fragmento;
  · uno de 1200 páginas conviene partirlo, y uno de 80 no merece siete pasos de
    análisis;
  · uno con una figura cada dos páginas apoya su explicación en imágenes que la
    extracción de texto no va a ver.

El orden importa y es lo que hace que esto sea rápido:

  1. MEDIR — determinista, sin modelo. Páginas, densidad de texto, de matemáticas,
     de código, imágenes, idioma, si hay índice. Segundos, no minutos.
  2. CLASIFICAR — UNA llamada corta al modelo sobre una muestra de páginas, no
     sobre el libro. Para lo que una cuenta no puede decidir: de qué va, a qué
     nivel, para quién.
  3. RECOMENDAR — qué configuración de extracción y qué flujo le convienen.

Nunca se leen las 600 páginas: se muestrean unas 24 repartidas por todo el libro.
Leer solo las primeras daría una idea falsa, porque el principio de casi cualquier
libro es introductorio y parece más fácil que el resto.
"""

import os
import re
import json
import math
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional

PAGINAS_MUESTRA = 24
CHARS_PAGINA_ESCANEADO = 120      # por debajo de esto, la página no tiene texto real

# Señales de matemáticas en texto ya extraído de un PDF. Los símbolos sueltos pesan
# poco por separado, pero su densidad distingue muy bien un libro de análisis de uno
# de historia.
SIMBOLOS_MAT = set("∑∏∫∮∂∇√∞≈≠≤≥±∓×÷⊂⊆∈∉∪∩∀∃⇒⇔→←↔αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ")
PATRONES_MAT = [
    r"\\[a-zA-Z]{2,}\{",              # \frac{, \sum_{
    r"\$[^$]{2,60}\$",                # $x^2$
    r"\b[a-z]\s*=\s*[^=]",            # x = ...
    r"\^\s*[0-9{]",                   # x^2
    r"_\s*[0-9{i-n]",                 # a_i
    r"\b(teorema|lema|corolario|demostraci[oó]n|proposici[oó]n|axioma|"
    r"theorem|lemma|corollary|proof|proposition)\b",
    # Notación que usa el texto matemático y no usa el código
    r"\b[a-zA-Z]'\s*\(",               # f'(x), la derivada
    r"\[\s*[a-z]\s*,\s*[a-z]\s*\]",       # el intervalo [a,b]
    r"\)\s*/\s*\(",                   # (a-b)/(c-d)
    r"\b(sea|sean|supongamos|entonces existe|para todo|si y s[oó]lo si|"
    r"let|suppose|there exists|for all|if and only if)\b",
]

PALABRAS_CODIGO = {
    "def", "class", "import", "return", "function", "const", "let", "var",
    "public", "private", "static", "void", "int", "float", "double", "struct",
    "include", "namespace", "template", "printf", "println", "console",
    "if", "else", "for", "while", "try", "catch", "except", "lambda",
    "self", "this", "null", "none", "true", "false", "async", "await",
}
# Cuidado con lo que se cuenta aquí: en un libro de matemáticas "f(b)" parece
# una llamada a función y una fórmula centrada parece una línea indentada. Un
# teorema entero llegaba a puntuar como código, y ese libro se habría
# configurado para extraer lenguajes de programación en vez de fórmulas.
PATRONES_CODIGO = [
    r"[;{}]\s*$",                      # termina en ; o en llave
    # Identificador de tres letras o más: descarta f(x), g(a), P(A)
    r"\b[a-zA-Z_]\w{2,}\s*\([^)]*\)",
    r"^\s*(#\s|//|/\*)",              # comentario de código
    r"\b\w{2,}\.\w{2,}\(",            # objeto.metodo(
    r"->|=>|::|\+=|-=|\*=|==|!=",      # operadores que la matemática no usa
    r"\b(import|from|def|class|return|function|const|var|let|public|void|"
    r"include|namespace|print|printf)\b",
    r"^\s{4,}\w{2,}\s*[=(.]",         # indentada Y además asigna o llama
]

# Palabras muy frecuentes, para adivinar el idioma sin instalar nada
PISTAS_IDIOMA = {
    "es": {"de", "la", "que", "el", "en", "los", "se", "del", "las", "por", "con", "para"},
    "en": {"the", "of", "and", "to", "in", "is", "that", "for", "with", "as", "this", "are"},
    "pt": {"de", "que", "não", "uma", "para", "com", "por", "dos", "das", "são"},
    "fr": {"de", "la", "le", "les", "des", "est", "une", "pour", "dans", "que"},
}


def estimar_fragmentos(caracteres: int, max_chunk_tokens: int) -> int:
    """ Cuántos fragmentos saldrán de un texto de ese tamaño.

    El factor 0,75 no es arbitrario: el troceador cierra el fragmento cuando el
    siguiente párrafo no cabe, así que casi ninguno llega al tope. Medido sobre un
    libro real de 237.000 caracteres con tope 500, salen 183 fragmentos; esta
    fórmula da 176. La versión anterior daba 132 y dejaba el coste corto en un 40 %.
    """
    if caracteres <= 0:
        return 0
    por_fragmento = max_chunk_tokens * CARACTERES_POR_TOKEN * 0.75
    return max(1, round(caracteres / por_fragmento))


CARACTERES_POR_TOKEN = 3.6


class SondeoLibro:
    def __init__(self, ai_engine=None):
        self.ai = ai_engine

    # ==================================================================
    # 1 · Medir (sin modelo)
    # ==================================================================

    def medir(self, ruta: str) -> Dict[str, Any]:
        ruta = os.path.abspath(os.path.expanduser(ruta))
        if not os.path.isfile(ruta):
            raise FileNotFoundError(f"No existe: {ruta}")

        ext = os.path.splitext(ruta)[1].lower()
        base = {
            "ruta": ruta,
            "nombre": os.path.basename(ruta),
            "extension": ext,
            "mb": round(os.path.getsize(ruta) / (1024 * 1024), 2),
            "medido_en": datetime.now().isoformat(),
        }
        if ext == ".pdf":
            base.update(self._medir_pdf(ruta))
        else:
            base.update(self._medir_texto(ruta))

        base.update(self._analizar_paginas(base.pop("_paginas_texto", []),
                                           base.get("_muestra_texto", "")))
        base.update(self._derivar(base))
        return base

    def _medir_pdf(self, ruta: str) -> Dict[str, Any]:
        try:
            import pypdf
        except ImportError:
            return {"error": "pypdf no está instalado; no se puede sondear un PDF",
                    "paginas": 0, "_muestra_texto": ""}
        try:
            lector = pypdf.PdfReader(ruta)
        except Exception as err:
            return {"error": f"el PDF no se puede abrir ({err})",
                    "paginas": 0, "_muestra_texto": ""}

        if getattr(lector, "is_encrypted", False):
            try:
                lector.decrypt("")
            except Exception:
                return {"error": "el PDF está protegido con contraseña",
                        "paginas": 0, "_muestra_texto": "", "cifrado": True}

        total = len(lector.pages)
        if not total:
            return {"error": "el PDF no tiene páginas", "paginas": 0, "_muestra_texto": ""}

        # Se muestrea a lo largo del libro, saltándose la portada y los créditos:
        # las primeras páginas casi nunca representan el contenido.
        arranque = min(int(total * 0.05) + 1, 12)
        indices = sorted(set(
            round(arranque + i * (total - arranque - 1) / max(1, PAGINAS_MUESTRA - 1))
            for i in range(PAGINAS_MUESTRA)))
        indices = [i for i in indices if 0 <= i < total]

        textos, imagenes, paginas_vacias = [], 0, 0
        for i in indices:
            try:
                pagina = lector.pages[i]
                texto = pagina.extract_text() or ""
            except Exception:
                texto = ""
            textos.append(texto)
            if len(texto.strip()) < CHARS_PAGINA_ESCANEADO:
                paginas_vacias += 1
            imagenes += self._contar_imagenes(pagina)

        indice = self._indice_pdf(lector)
        muestreadas = max(1, len(indices))
        return {
            "paginas": total,
            "paginas_muestreadas": muestreadas,
            "chars_por_pagina": round(sum(len(t) for t in textos) / muestreadas),
            "fraccion_sin_texto": round(paginas_vacias / muestreadas, 2),
            "imagenes_por_pagina": round(imagenes / muestreadas, 2),
            "tiene_indice": bool(indice),
            "entradas_indice": len(indice),
            "indice_muestra": indice[:25],
            "metadatos": self._metadatos(lector),
            "_paginas_texto": textos,
            "_muestra_texto": "\n\n".join(t for t in textos if t.strip())[:24000],
        }

    @staticmethod
    def _contar_imagenes(pagina) -> int:
        """ Imágenes incrustadas en la página, sin decodificarlas.

        Se cuentan los XObject de tipo imagen en los recursos. Decodificarlas para
        contarlas costaría segundos por página y no aporta nada: lo que interesa es
        cuántas hay, no qué muestran.
        """
        try:
            recursos = pagina.get("/Resources")
            if recursos is None:
                return 0
            xobjetos = recursos.get_object().get("/XObject")
            if xobjetos is None:
                return 0
            xobjetos = xobjetos.get_object()
            return sum(1 for k in xobjetos
                       if xobjetos[k].get_object().get("/Subtype") == "/Image")
        except Exception:
            return 0

    @staticmethod
    def _indice_pdf(lector) -> List[Dict[str, Any]]:
        """ Marcadores del PDF, que suelen ser el índice de verdad """
        salida = []

        def recorrer(nodos, nivel=0):
            for n in nodos:
                if isinstance(n, list):
                    recorrer(n, nivel + 1)
                    continue
                try:
                    salida.append({"titulo": str(n.title).strip(), "nivel": nivel})
                except Exception:
                    continue
        try:
            recorrer(lector.outline)
        except Exception:
            return []
        return salida

    @staticmethod
    def _metadatos(lector) -> Dict[str, str]:
        try:
            meta = lector.metadata or {}
            return {k.lstrip("/"): str(v)[:200] for k, v in meta.items()
                    if k in ("/Title", "/Author", "/Subject", "/Producer")}
        except Exception:
            return {}

    def _medir_texto(self, ruta: str) -> Dict[str, Any]:
        try:
            with open(ruta, encoding="utf-8", errors="ignore") as f:
                texto = f.read()
        except Exception as err:
            return {"error": str(err), "paginas": 0, "_muestra_texto": ""}

        if ruta.lower().endswith(".ipynb"):
            texto = self._texto_de_cuaderno(texto)

        # Un archivo de texto no tiene páginas; se estima a 2500 caracteres, que es
        # más o menos lo que cabe en una página de libro.
        paginas = max(1, round(len(texto) / 2500))
        encabezados = re.findall(r"^#{1,3}\s+(.+)$", texto, re.M)
        return {
            "paginas": paginas,
            "paginas_muestreadas": paginas,
            "chars_por_pagina": round(len(texto) / paginas),
            "fraccion_sin_texto": 0.0,
            "imagenes_por_pagina": round(
                len(re.findall(r"!\[[^\]]*\]\(", texto)) / paginas, 2),
            "tiene_indice": bool(encabezados),
            "entradas_indice": len(encabezados),
            "indice_muestra": [{"titulo": h.strip(), "nivel": 0} for h in encabezados[:25]],
            "metadatos": {},
            # Un archivo de texto se parte en trozos del tamaño de una página para
            # poder medir igual que en un PDF: por página, no en promedio.
            "_paginas_texto": [texto[i:i + 2500] for i in range(0, len(texto), 2500)][:40],
            "_muestra_texto": texto[:24000],
        }

    @staticmethod
    def _texto_de_cuaderno(bruto: str) -> str:
        try:
            nb = json.loads(bruto)
        except Exception:
            return bruto
        partes = []
        for celda in nb.get("cells", []):
            fuente = celda.get("source", [])
            partes.append("".join(fuente) if isinstance(fuente, list) else str(fuente))
        return "\n\n".join(partes)

    # ==================================================================
    # Densidades
    # ==================================================================

    @staticmethod
    def _densidades(texto: str) -> tuple:
        """ Señales de matemáticas y de código por cada mil caracteres """
        n = max(1, len(texto))
        simbolos = sum(1 for ch in texto if ch in SIMBOLOS_MAT)
        for patron in PATRONES_MAT:
            simbolos += len(re.findall(patron, texto, re.M | re.I))

        palabras = re.findall(r"[a-zA-Z_]{2,}", texto.lower())
        codigo = sum(1 for p in palabras if p in PALABRAS_CODIGO)
        for patron in PATRONES_CODIGO:
            codigo += len(re.findall(patron, texto, re.M))

        return simbolos * 1000 / n, codigo * 1000 / n, palabras

    def _analizar_paginas(self, paginas: List[str], todo: str) -> Dict[str, Any]:
        """ Se mide PÁGINA A PÁGINA, no sobre el libro entero.

        Un libro de programación con un tercio de páginas de código y dos tercios de
        prosa da un promedio bajo y parecería un libro de texto corriente. Lo que
        importa no es la media sino cuántas páginas son de código: son las que
        obligan a pedir el lenguaje en la extracción.
        """
        paginas = [p for p in (paginas or []) if p and p.strip()]
        if not paginas:
            return {"densidad_matematicas": 0.0, "densidad_codigo": 0.0,
                    "fraccion_paginas_matematicas": 0.0, "fraccion_paginas_codigo": 0.0,
                    "idioma": "?", "palabras_muestra": 0}

        mats, cods, palabras_todas = [], [], []
        for texto in paginas:
            mat, cod, palabras = self._densidades(texto)
            mats.append(mat)
            cods.append(cod)
            palabras_todas += palabras[:200]

        # Umbrales por página, calibrados sobre libros reales: la prosa corriente
        # ronda 0,5 de código y 0-2 de matemáticas; una página con un listado de
        # Python pasa de 15, y una con una derivación pasa de 10.
        con_mat = sum(1 for m in mats if m >= 10)
        con_cod = sum(1 for c in cods if c >= 15)
        n = len(paginas)

        return {
            "densidad_matematicas": round(sum(mats) / n, 1),
            "densidad_codigo": round(sum(cods) / n, 1),
            "fraccion_paginas_matematicas": round(con_mat / n, 2),
            "fraccion_paginas_codigo": round(con_cod / n, 2),
            "pico_matematicas": round(max(mats), 1),
            "pico_codigo": round(max(cods), 1),
            "idioma": self._idioma(palabras_todas),
            "palabras_muestra": len(palabras_todas),
        }

    @staticmethod
    def _idioma(palabras: List[str]) -> str:
        if not palabras:
            return "?"
        conjunto = palabras[:4000]
        puntos = {idioma: sum(1 for p in conjunto if p in pistas)
                  for idioma, pistas in PISTAS_IDIOMA.items()}
        mejor = max(puntos, key=puntos.get)
        return mejor if puntos[mejor] > len(conjunto) * 0.01 else "?"

    # ==================================================================
    # Lo que se deduce de las cifras
    # ==================================================================

    def _derivar(self, m: Dict[str, Any]) -> Dict[str, Any]:
        paginas = m.get("paginas") or 0
        sin_texto = m.get("fraccion_sin_texto", 0)
        mat = m.get("fraccion_paginas_matematicas", 0)
        cod = m.get("fraccion_paginas_codigo", 0)
        imgs = m.get("imagenes_por_pagina", 0)

        # Un PDF escaneado es el único caso en que no hay nada que hacer sin OCR.
        # Detectarlo aquí evita una corrida entera que habría dado casi nada.
        escaneado = sin_texto >= 0.5 or (paginas > 5 and m.get("chars_por_pagina", 0) < 200)

        naturaleza = []
        if mat >= 0.35:
            naturaleza.append("matemático")
        elif mat >= 0.12:
            naturaleza.append("con bastantes matemáticas")
        if cod >= 0.30:
            naturaleza.append("de programación")
        elif cod >= 0.10:
            naturaleza.append("con código")
        if imgs >= 0.5:
            naturaleza.append("muy ilustrado")
        elif imgs >= 0.2:
            naturaleza.append("con figuras")
        if not naturaleza:
            naturaleza.append("de texto corrido")

        if paginas >= 800:
            tamano = "enorme"
        elif paginas >= 400:
            tamano = "largo"
        elif paginas >= 120:
            tamano = "normal"
        else:
            tamano = "corto"

        chars = m.get("chars_por_pagina", 0) * paginas
        fragmentos = 0 if escaneado else estimar_fragmentos(chars, 500)

        return {
            "escaneado": escaneado,
            "naturaleza": naturaleza,
            "tamano": tamano,
            "fragmentos_estimados": fragmentos,
            "horas_estimadas_local": round(fragmentos * 35 / 3600, 1),
        }

    # ==================================================================
    # 2 · Clasificar (una llamada, sobre una muestra)
    # ==================================================================

    SISTEMA = (
        "Clasificas un libro a partir de unas páginas sueltas suyas y de unas cifras "
        "medidas sobre el archivo. No has leído el libro entero y no debes fingir que "
        "sí: si la muestra no alcanza para decidir algo, responde \"indeterminado\" en "
        "ese campo. Devuelves únicamente JSON válido."
    )

    def clasificar(self, medicion: Dict[str, Any], modelo: str,
                   max_tokens: int = 700) -> Dict[str, Any]:
        """ Lo que una cuenta no puede decidir: de qué va, a qué nivel, para quién """
        if not self.ai:
            return {"error": "no hay motor de IA disponible"}

        indice = "\n".join(f"{'  ' * e['nivel']}{e['titulo']}"
                           for e in (medicion.get("indice_muestra") or [])[:25])
        muestra = (medicion.get("muestra_texto") or "")[:5000]

        prompt = (
            f"Archivo: {medicion.get('nombre')}\n"
            f"Medido sobre el propio archivo:\n"
            f"  {medicion.get('paginas')} páginas · {medicion.get('mb')} MB\n"
            f"  {medicion.get('chars_por_pagina')} caracteres por página\n"
            f"  páginas con matemáticas: "
            f"{round(medicion.get('fraccion_paginas_matematicas', 0) * 100)} %\n"
            f"  páginas con código: "
            f"{round(medicion.get('fraccion_paginas_codigo', 0) * 100)} %\n"
            f"  imágenes por página: {medicion.get('imagenes_por_pagina')}\n"
            f"  idioma detectado: {medicion.get('idioma')}\n\n"
            + (f"Índice del archivo:\n{indice}\n\n" if indice else "")
            + f"Páginas sueltas, tomadas a lo largo del libro:\n{muestra}\n\n"
            "Clasifícalo. El campo tiene que ser uno de: math, physics, cpp, python, "
            "machine_learning, deep_learning. Si es de programación pero de otro "
            "lenguaje, elige el más cercano y dilo en 'observaciones'.\n\n"
            '{"titulo_real": "el título de verdad, no el del archivo", '
            '"campo": "...", "campo_alternativo": "" , '
            '"nivel": "introductorio|intermedio|avanzado|referencia", '
            '"de_que_trata": "una frase", "para_quien": "...", '
            '"tipo": "manual|libro de texto|referencia|apuntes|paper|tutorial", '
            '"temas_principales": ["..."], '
            '"merece_extraccion": true, "observaciones": ""}'
        )
        partes = []
        for trozo in self.ai.generate_response(
                prompt, model=modelo, system_prompt=self.SISTEMA,
                options={"temperature": 0.1, "num_predict": max_tokens}):
            partes.append(trozo)
        datos = _json_de("".join(partes))
        return datos if isinstance(datos, dict) else {
            "error": "el modelo no devolvió JSON válido", "bruto": "".join(partes)[:500]}

    # ==================================================================
    # 3 · Recomendar
    # ==================================================================

    def recomendar(self, m: Dict[str, Any],
                   clasificacion: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """ Qué configuración le conviene a ESTE libro.

        No hay una buena para todos: un libro de matemáticas necesita que se pida
        LaTeX, uno de programación que se pida el lenguaje, y uno escaneado no
        necesita nada porque no se puede extraer.
        """
        avisos, ajustes, bloqueos = [], {}, []
        clasificacion = clasificacion or {}

        if m.get("error"):
            bloqueos.append(m["error"])
        if m.get("escaneado"):
            bloqueos.append(
                "Parece escaneado: las páginas casi no tienen texto extraíble. "
                "Hace falta pasarle OCR antes (ocrmypdf) o no habrá nada que extraer.")

        paginas = m.get("paginas") or 0
        mat = m.get("fraccion_paginas_matematicas", 0)
        cod = m.get("fraccion_paginas_codigo", 0)
        imgs = m.get("imagenes_por_pagina", 0)

        if mat >= 0.12:
            ajustes["pedir_latex"] = True
            avisos.append(f"El {round(mat * 100)} % de las páginas llevan matemáticas: "
                          f"la extracción tiene que pedir la fórmula en LaTeX, no solo "
                          f"el texto, o las derivaciones se pierden.")
        if cod >= 0.10:
            ajustes["pedir_lenguaje_codigo"] = True
            avisos.append(f"El {round(cod * 100)} % de las páginas llevan código: hay que "
                          f"pedir el lenguaje de cada fragmento para poder ejecutarlo "
                          f"después.")
        if imgs >= 0.5:
            avisos.append(f"Una imagen cada {round(1 / max(imgs, 0.01), 1)} páginas: parte "
                          f"de la explicación está en figuras que la extracción de texto "
                          f"no ve. Los pies de figura pasan a ser importantes.")
        if not m.get("tiene_indice"):
            avisos.append("Sin índice en el archivo: el temario habrá que deducirlo de "
                          "las páginas donde aparece cada concepto.")
        if m.get("idioma") not in ("es", "en", "?"):
            avisos.append(f"Idioma detectado '{m.get('idioma')}': comprueba que el modelo "
                          f"lo maneja bien antes de lanzar la extracción entera.")

        # Fragmento más corto cuando hay mucha fórmula: cortar una derivación por la
        # mitad produce afirmaciones que no se sostienen solas.
        ajustes["max_chunk_tokens"] = 350 if mat >= 0.35 else (500 if paginas < 600 else 600)

        if paginas >= 800:
            avisos.append(f"{paginas} páginas: pártelo en dos o tres trabajos. Depender "
                          f"de una sola corrida larga es la forma más fácil de perder "
                          f"horas.")

        # Qué flujo de análisis le conviene después de extraerlo
        if paginas < 80:
            flujo = "plantilla_libro"
            razon = ("Es corto: la ficha completa de siete pasos no tiene de dónde sacar "
                     "un temario. Mejor analizar sus temas directamente.")
        elif m.get("escaneado"):
            flujo = None
            razon = "Sin OCR no hay nada que analizar."
        else:
            flujo = "plantilla_ficha_libro"
            razon = "Tiene tamaño y estructura suficientes para la ficha completa."

        perfil = "core" if paginas >= 600 else "full"
        if perfil == "core":
            avisos.append("Por su tamaño, conviene el perfil 'core' en la extracción: "
                          "omite preguntas y figuras y ahorra un 20 % de tokens de salida.")

        # Recalcular con el tope que se acaba de recomendar: un libro muy
        # matemático usa fragmentos más cortos, así que salen bastantes más.
        # Se recalcula con el tope recomendado (un libro muy matemático usa
        # fragmentos más cortos, así que salen bastantes más). Si la medición no
        # trae los caracteres, vale la estimación que ya venía hecha: devolver
        # cero haría creer que extraerlo es gratis.
        chars = (m.get("chars_por_pagina") or 0) * paginas
        if m.get("escaneado") or bloqueos:
            fragmentos = 0
        elif chars:
            fragmentos = estimar_fragmentos(chars, ajustes["max_chunk_tokens"])
        else:
            fragmentos = m.get("fragmentos_estimados", 0)
        return {
            "se_puede_extraer": not bloqueos,
            "bloqueos": bloqueos,
            "avisos": avisos,
            "ajustes_extraccion": {**ajustes, "profile": perfil},
            "flujo_recomendado": flujo,
            "razon_del_flujo": razon,
            "campo_sugerido": clasificacion.get("campo"),
            "coste": {
                "fragmentos": fragmentos,
                # 35 s por fragmento es lo medido en esta máquina con un 7B en Q4
                "horas_en_local": round(fragmentos * 35 / 3600, 1),
                "minutos_en_dos_T4": round(fragmentos * 2.5 / 60, 1) if fragmentos else 0,
            },
        }

    # ==================================================================
    # Todo junto
    # ==================================================================

    def sondear(self, ruta: str, modelo: Optional[str] = None,
                con_modelo: bool = True) -> Dict[str, Any]:
        medicion = self.medir(ruta)
        muestra = medicion.pop("_muestra_texto", "")
        medicion["muestra_texto"] = muestra[:6000]

        clasificacion = {}
        if con_modelo and modelo and self.ai and not medicion.get("escaneado") \
                and not medicion.get("error"):
            try:
                clasificacion = self.clasificar(medicion, modelo)
            except Exception as err:
                clasificacion = {"error": str(err)}

        medicion.pop("muestra_texto", None)
        return {
            "medicion": medicion,
            "clasificacion": clasificacion,
            "recomendacion": self.recomendar(medicion, clasificacion),
        }


def _json_de(texto: str):
    inicio = (texto or "").find("{")
    if inicio < 0:
        return None
    prof, cad, esc = 0, False, False
    for i in range(inicio, len(texto)):
        c = texto[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            cad = not cad
            continue
        if cad:
            continue
        if c == "{":
            prof += 1
        elif c == "}":
            prof -= 1
            if prof == 0:
                try:
                    return json.loads(texto[inicio:i + 1])
                except Exception:
                    return None
    return None
