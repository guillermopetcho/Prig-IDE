"""
Compilación del conocimiento a una forma pensada para que la lea un modelo.

El material que Prig guardaba estaba escrito para una persona: frases completas,
citas textuales entre comillas, etiquetas en mayúsculas. Eso es correcto para leerlo
tú, y caro para el modelo. Cada token de entrada es atención que se gasta, y
atención gastada en reconstruir una frase es atención que no se gasta en razonar.

Lo que se elimina, y por qué cada cosa no hacía falta:

  · LA CITA LITERAL. Su trabajo es verificar que el modelo extractor no inventó, y
    ese trabajo ya se hizo en la extracción. Al razonar sobra: repite lo que la
    afirmación ya dice y duplica el tamaño del bloque. Se guarda en la base y se
    recupera solo cuando hay que citar de verdad.
  · EL SUJETO REPETIDO. "La regularización L2 penaliza la norma..." bajo una
    cabecera que ya dice «regularización L2». Se elide.
  · LO REPETIDO ENTRE LIBROS. Tres libros diciendo lo mismo son tres veces el coste
    y ninguna información nueva. Se funde en una línea con varias fuentes.
  · LAS ETIQUETAS LARGAS. `[DEFINITION]` son cuatro tokens por línea. Un signo con
    su leyenda al principio cuesta uno.

Lo que se AÑADE, porque el modelo lo necesitaba y no lo tenía:

  · las dependencias (qué requiere y qué habilita) en el propio bloque;
  · los errores típicos y los contrastes, que antes se perdían al recortar;
  · el orden inferencial: definición, luego restricción, luego ejemplo.

La compilación se guarda hecha. Rehacerla en cada pregunta gastaría en el momento
en que menos margen hay.
"""

import os
import re
import json
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from knowledge_base import KnowledgeBase, normalizar_nombre

CARACTERES_POR_TOKEN = 3.6
VERSION_FORMATO = "1.0"

# Un signo por tipo, con su leyenda al principio del bloque. El orden de esta lista
# es el orden en que se presentan: definición antes que intuición, intuición antes
# que fórmula. Es el orden en que se entiende algo, no el orden en que aparece en
# el libro.
SIGNOS = [
    ("DEFINITION", "=", "definición"),
    ("INTUITION", "~", "intuición"),
    ("FORMULA", "f", "fórmula"),
    ("RESULT", ">", "resultado"),
    ("PROCEDURE", "@", "procedimiento"),
    ("PROPERTY", "p", "propiedad"),
    ("THEOREM", "T", "teorema"),
    ("ALGORITHM", "A", "algoritmo"),
    ("CODE_PATTERN", "c", "código"),
    ("EXAMPLE", "e", "ejemplo"),
    ("COMPARISON", "/", "contraste"),
    ("CAVEAT", "!", "error típico"),
    ("PITFALL", "!", "error típico"),
    ("NOTATION", "n", "notación"),
]
SIGNO_DE = {t: s for t, s, _ in SIGNOS}
ORDEN_TIPO = {t: i for i, (t, _, _) in enumerate(SIGNOS)}

# Muletillas con las que un libro presenta un hecho. No aportan nada al modelo y
# aparecen en casi todas las afirmaciones.
RELLENO = [
    r"^(se\s+)?(dice|define|establece|afirma|observa|tiene|puede\s+decirse)\s+que\s+",
    r"^(es|son)\s+(decir|un\s+hecho\s+que)\s+",
    r"^(en\s+este\s+caso|por\s+tanto|as[ií]\s+pues|de\s+este\s+modo|de\s+hecho)[,\s]+",
    r"^(conviene|cabe|hay\s+que)\s+(observar|notar|se[nñ]alar|destacar)\s+que\s+",
    r"^(it\s+)?(is|can\s+be)\s+(said|defined|noted|observed)\s+that\s+",
]

# Cópulas que unen el sujeto elidido con el predicado
COPULAS = r"(es|son|se\s+define\s+como|se\s+conoce\s+como|consiste\s+en|significa|" \
          r"es\s+una?|es\s+el|es\s+la|se\s+llama|se\s+denomina)"


def tokens(texto: str) -> int:
    return int(len(texto or "") / CARACTERES_POR_TOKEN) + 1


def _sin_acentos(t: str) -> str:
    t = unicodedata.normalize("NFD", (t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


class CompiladorContexto:
    def __init__(self, kb: Optional[KnowledgeBase] = None):
        self.kb = kb or KnowledgeBase()
        self._codigos: Dict[str, str] = {}      # source_id -> código corto

    # ==================================================================
    # Referencias a los libros
    # ==================================================================

    def codigos_de_libros(self) -> Dict[str, Dict[str, str]]:
        """ Un código corto por libro, declarado una vez.

        "Pattern Recognition (Bishop), p.10" son nueve tokens, y se repite en cada
        línea que salga de ese libro. "Bis10" es uno. El nombre completo se declara
        una sola vez en la cabecera.
        """
        with self.kb.conectar() as c:
            libros = [dict(r) for r in c.execute(
                "SELECT source_id, title, domain FROM books ORDER BY source_id;")]

        usados, mapa = set(), {}
        for b in libros:
            base = re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", " ", b["title"] or b["source_id"])
            # Se prefiere el apellido entre paréntesis: "Pattern Recognition (Bishop)"
            m = re.search(r"\(([^)]+)\)", b["title"] or "")
            palabra = (m.group(1) if m else base).strip().split()
            palabra = palabra[0] if palabra else b["source_id"]
            codigo = _sin_acentos(palabra)[:3].capitalize() or "Lib"
            n = 2
            while codigo in usados:
                codigo = f"{codigo[:3]}{n}"
                n += 1
            usados.add(codigo)
            mapa[b["source_id"]] = {"codigo": codigo, "titulo": b["title"],
                                    "dominio": b["domain"]}
        self._codigos = {k: v["codigo"] for k, v in mapa.items()}
        return mapa

    # ==================================================================
    # Limpieza de una afirmación
    # ==================================================================

    def _elidir(self, texto: str, nombres: List[str], tipo: str = "") -> str:
        """ Quita el sujeto cuando repite el concepto que encabeza el bloque.

        "La regularización L2 penaliza la norma" bajo la cabecera «regularización
        L2» se queda en "penaliza la norma". El modelo no pierde nada: el sujeto
        está dos líneas más arriba.

        La comparación va sobre el texto SIN TILDES. El nombre canónico del
        concepto sale de la normalización y suele venir sin acentos, mientras que
        el libro sí los escribe: comparando tal cual, "regularizacion L2" nunca
        coincidía con "regularización L2" y no se elidía nada.
        """
        t = (texto or "").strip()
        for patron in RELLENO:
            t = re.sub(patron, "", t, flags=re.I)

        if tipo == "FORMULA":
            t = self._solo_formula(t)

        # Un calificador delante ("En regresión lineal, …") NO es relleno: acota
        # cuándo vale lo que viene después. Se conserva como prefijo corto en lugar
        # de tirarlo con el sujeto, que era lo que pasaba y cambiaba el sentido.
        prefijo = ""
        m = re.match(r"^(en|para|con|bajo|dentro\s+de)\s+([^,]{3,45}),\s*", t, flags=re.I)
        if m:
            candidato = t[m.end():]
            if re.match(rf"^(el|la|los|las|un|una)?\s*"
                        rf"({'|'.join(re.escape(_sin_acentos(n)) for n in nombres if n)})\s",
                        _sin_acentos(candidato), flags=re.I):
                prefijo = f"[{m.group(2).strip()}] "
                t = candidato.strip()

        plano = _sin_acentos(t)
        for nombre in sorted({n for n in nombres if n}, key=len, reverse=True):
            escapado = re.escape(_sin_acentos(nombre))
            for patron in (
                    rf"^(el|la|los|las|un|una|lo)?\s*{escapado}\s+{COPULAS}\s+",
                    rf"^(el|la|los|las|un|una|lo)?\s*{escapado}\s+"):
                m = re.match(patron, plano, flags=re.I)
                if m and len(t) - m.end() > 12:
                    # Se corta el ORIGINAL por el mismo desplazamiento: quitar los
                    # acentos no cambia la longitud, así que los índices coinciden.
                    t = t[m.end():].strip()
                    plano = _sin_acentos(t)
                    break
            else:
                continue
            break

        if tipo in ("CAVEAT", "PITFALL"):
            # El signo ! ya dice que es un error típico
            t = re.sub(r"^(un\s+)?error\s+(frecuente|com[uú]n|habitual|t[ií]pico)\s+"
                       r"(es|consiste\s+en)\s+", "", t, flags=re.I)

        t = (prefijo + t).strip().rstrip(".").strip()

        # En una fórmula, J y j son símbolos distintos: minusculizar la inicial
        # cambia lo que dice. Lo mismo en código y en notación.
        if tipo in ("FORMULA", "NOTATION", "CODE_PATTERN"):
            return t
        return (t[0].lower() + t[1:]) if t and t[0].isupper() and not t[:3].isupper() else t

    @staticmethod
    def _solo_formula(t: str) -> str:
        """ De "La solución ridge es w = (XᵀX+λI)⁻¹Xᵀy" a la fórmula sola.

        La frase que la presenta no aporta: el signo de la línea ya dice que es una
        fórmula, y el concepto ya está en la cabecera.
        """
        m = re.search(r"([A-Za-zΑ-Ωα-ω∇∂][^\s]*\s*[=≈≤≥<>]\s*.+)$", t)
        return m.group(1).strip() if m and len(m.group(1)) > 6 else t

    @staticmethod
    def _huella(texto: str) -> frozenset:
        """ Qué palabras con contenido tiene una afirmación, para comparar dos.

        Dos libros que dicen lo mismo con otras palabras comparten casi todas las
        palabras largas; las cortas son las que cambian con el estilo.
        """
        palabras = re.findall(r"[a-z0-9áéíóúñ]{4,}", _sin_acentos(texto))
        return frozenset(palabras)

    @classmethod
    def _misma_idea(cls, a: str, b: str, umbral: float = 0.62) -> bool:
        ha, hb = cls._huella(a), cls._huella(b)
        if not ha or not hb:
            return False
        comun = len(ha & hb)
        return comun / min(len(ha), len(hb)) >= umbral

    # ==================================================================
    # Compilar un concepto
    # ==================================================================

    def compilar_concepto(self, concept_id: str,
                          codigos: Optional[Dict[str, Dict[str, str]]] = None
                          ) -> Optional[Dict[str, Any]]:
        codigos = codigos or self.codigos_de_libros()
        with self.kb.conectar() as c:
            con = c.execute("SELECT * FROM concepts WHERE concept_id = ?;",
                            (concept_id,)).fetchone()
            if not con:
                return None
            con = dict(con)
            afirmaciones = [dict(r) for r in c.execute(
                """SELECT claim_id, type, text, page, source_id, latex, code_language,
                          confidence
                   FROM claims WHERE concept_id = ? ORDER BY confidence DESC;""",
                (concept_id,))]
            alias = [r["surface"] for r in c.execute(
                """SELECT DISTINCT surface FROM aliases
                   WHERE concept_id = ? AND surface IS NOT NULL;""", (concept_id,))]
            requiere = [dict(r) for r in c.execute(
                """SELECT DISTINCT co.canonical_name AS n, r.type
                   FROM relations r JOIN concepts co ON co.concept_id = r.target_concept
                   WHERE r.source_concept = ? LIMIT 10;""", (concept_id,))]
            habilita = [dict(r) for r in c.execute(
                """SELECT DISTINCT co.canonical_name AS n, r.type
                   FROM relations r JOIN concepts co ON co.concept_id = r.source_concept
                   WHERE r.target_concept = ? LIMIT 10;""", (concept_id,))]

        nombre = con["canonical_name"]
        nombres = [nombre] + [a for a in alias if a]
        norm_canon = normalizar_nombre(nombre)
        otros_alias = []
        vistos = {norm_canon}
        for a in alias:
            na = normalizar_nombre(a)
            if na and na not in vistos:
                vistos.add(na)
                otros_alias.append(a)

        # Fundir lo que dicen varios libros en una sola línea con varias fuentes
        lineas: List[Dict[str, Any]] = []
        for a in afirmaciones:
            crudo = (a["latex"] or a["text"]) if a["type"] == "FORMULA" else a["text"]
            texto = self._elidir(crudo, nombres, a["type"])
            if not texto:
                continue
            fuente = {"codigo": (codigos.get(a["source_id"]) or {}).get("codigo", "?"),
                      "pagina": a["page"], "claim_id": a["claim_id"]}
            for previa in lineas:
                if previa["tipo"] == a["type"] and self._misma_idea(previa["texto"], texto):
                    previa["fuentes"].append(fuente)
                    # Se conserva la redacción más corta: dice lo mismo con menos
                    if len(texto) < len(previa["texto"]):
                        previa["texto"] = texto
                    break
            else:
                lineas.append({"tipo": a["type"], "texto": texto, "fuentes": [fuente],
                               "lenguaje": a["code_language"]})

        lineas.sort(key=lambda l: (ORDEN_TIPO.get(l["tipo"], 99), -len(l["fuentes"])))

        dominios = json.loads(con["domains"] or "[]")
        return {
            "concept_id": concept_id,
            "nombre": nombre,
            "alias": otros_alias,
            "dominios": dominios,
            "es_puente": bool(con["is_bridge"]),
            "lineas": lineas,
            "requiere": [r["n"] for r in requiere if r["type"] in ("REQUIRES", "PART_OF")],
            "generaliza": [r["n"] for r in requiere if r["type"] == "GENERALIZES"],
            "habilita": [r["n"] for r in habilita if r["type"] in ("REQUIRES", "PART_OF")],
            "contrasta": [r["n"] for r in requiere if r["type"] == "CONTRASTS_WITH"],
            "resuelve": [r["n"] for r in requiere if r["type"] in ("SOLVES", "CAUSES")],
        }

    # ==================================================================
    # Render
    # ==================================================================

    @staticmethod
    def leyenda_de(signos_usados: set) -> str:
        """ Solo los signos que aparecen de verdad en este contexto.

        Declarar los trece cuando el bloque usa cuatro cuesta más de lo que ahorra
        comprimir. Medido: la leyenda completa son 78 tokens y se comía entera la
        reducción del material en una consulta de un solo concepto.
        """
        vistos, partes = set(), []
        for tipo, signo, nombre in SIGNOS:
            if signo in signos_usados and signo not in vistos:
                vistos.add(signo)
                partes.append(f"{signo}{nombre}")
        for signo, nombre in (("<", "requiere"), (">", "habilita"),
                              ("≠", "contrasta"), ("→", "resuelve")):
            if signo in signos_usados:
                partes.append(f"{signo}{nombre}")
        return ("· " + "  ".join(partes)) if partes else ""

    # Al principiante la fórmula le estorba antes de la intuición; al avanzado la
    # intuición le sobra. El material es el mismo, cambia el orden en que se sirve.
    ORDEN_NIVEL = {
        "principiante": ["INTUITION", "EXAMPLE", "DEFINITION", "CAVEAT"],
        "avanzado": ["THEOREM", "FORMULA", "PROPERTY", "RESULT"],
    }

    @classmethod
    def ordenar_lineas(cls, lineas: List[Dict[str, Any]], nivel: str = "intermedio",
                       dominio_preferido: Optional[str] = None,
                       dominio_de_libro: Optional[Dict[str, str]] = None
                       ) -> List[Dict[str, Any]]:
        """ Reordena según a quién se le explica y desde qué campo.

        Se hace aquí y no al compilar porque el bloque guardado es uno solo y el
        alumno cambia de nivel; recompilar por nivel multiplicaría por tres lo
        almacenado para no ganar nada.
        """
        primero = cls.ORDEN_NIVEL.get(nivel, [])
        dominio_de_libro = dominio_de_libro or {}

        def clave(l):
            prioridad_nivel = (primero.index(l["tipo"]) if l["tipo"] in primero
                               else len(primero) + ORDEN_TIPO.get(l["tipo"], 99))
            del_campo = 1
            if dominio_preferido:
                campos = {dominio_de_libro.get(f.get("codigo"))
                          for f in l.get("fuentes", [])}
                del_campo = 0 if dominio_preferido in campos else 1
            return (del_campo, prioridad_nivel, -len(l.get("fuentes", [])))

        return sorted(lineas, key=clave)

    def render_concepto(self, bloque: Dict[str, Any], tope_tokens: int = 0,
                        nivel: str = "intermedio",
                        dominio_preferido: Optional[str] = None,
                        dominio_de_libro: Optional[Dict[str, str]] = None) -> str:
        if not bloque:
            return ""
        cab = "@" + bloque["nombre"]
        if bloque["alias"]:
            cab += " ≡" + "≡".join(bloque["alias"][:4])
        if bloque["dominios"]:
            cab += "  [" + "|".join(d[:2].upper() if d else "" for d in bloque["dominios"]) + "]"
        if bloque["es_puente"]:
            cab += "*"

        lineas = [cab]
        ordenadas = (self.ordenar_lineas(bloque["lineas"], nivel, dominio_preferido,
                                         dominio_de_libro)
                     if (nivel != "intermedio" or dominio_preferido)
                     else bloque["lineas"])
        for l in ordenadas:
            signo = SIGNO_DE.get(l["tipo"], "-")
            fuentes = ",".join(f"{f['codigo']}{f['pagina'] or ''}" for f in l["fuentes"][:3])
            linea = f"{signo} {l['texto']} {{{fuentes}}}"
            if tope_tokens and tokens("\n".join(lineas) + linea) > tope_tokens:
                break
            lineas.append(linea)

        for etiqueta, clave in (("<", "requiere"), (">", "habilita"),
                                ("≠", "contrasta"), ("→", "resuelve")):
            valores = bloque.get(clave) or []
            if valores:
                lineas.append(f"{etiqueta} {', '.join(valores[:5])}")
        return "\n".join(lineas)

    # ==================================================================
    # Precompilar y guardar
    # ==================================================================

    def precompilar(self, minimo_lineas: int = 1) -> Dict[str, Any]:
        """ Deja compilado y guardado el bloque de cada concepto.

        Compilar en el momento de responder gastaría justo cuando menos margen hay.
        Esto se hace una vez, al importar.
        """
        codigos = self.codigos_de_libros()
        hechos = 0
        ahorro_total = original_total = 0

        with self.kb.conectar() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS contexto_modelo (
                concept_id TEXT PRIMARY KEY, bloque TEXT, texto TEXT,
                tokens INTEGER, tokens_origen INTEGER, compilado_en TEXT,
                version TEXT);""")
            c.execute("""CREATE TABLE IF NOT EXISTS contexto_libros (
                source_id TEXT PRIMARY KEY, codigo TEXT, titulo TEXT, dominio TEXT);""")
            c.execute("DELETE FROM contexto_libros;")
            for sid, info in codigos.items():
                c.execute("INSERT OR REPLACE INTO contexto_libros VALUES (?,?,?,?);",
                          (sid, info["codigo"], info["titulo"], info["dominio"]))

            ids = [r[0] for r in c.execute(
                "SELECT concept_id FROM concepts WHERE mentions > 0;")]

        for cid in ids:
            bloque = self.compilar_concepto(cid, codigos)
            if not bloque or len(bloque["lineas"]) < minimo_lineas:
                continue
            texto = self.render_concepto(bloque)
            origen = self._tokens_sin_compilar(cid)
            original_total += origen
            ahorro_total += origen - tokens(texto)
            with self.kb.conectar() as c:
                c.execute("INSERT OR REPLACE INTO contexto_modelo VALUES (?,?,?,?,?,?,?);",
                          (cid, json.dumps(bloque, ensure_ascii=False), texto,
                           tokens(texto), origen, datetime.now().isoformat(),
                           VERSION_FORMATO))
                c.commit()
            hechos += 1

        return {
            "conceptos": hechos,
            "tokens_antes": original_total,
            "tokens_despues": original_total - ahorro_total,
            "reduccion": (round(ahorro_total / original_total * 100, 1)
                          if original_total else 0),
        }

    def _tokens_sin_compilar(self, concept_id: str) -> int:
        """ Lo que ocuparía el mismo conocimiento en el formato de antes """
        with self.kb.conectar() as c:
            filas = c.execute(
                """SELECT cl.type, cl.text, cl.quote, cl.page, b.title
                   FROM claims cl LEFT JOIN books b ON b.source_id = cl.source_id
                   WHERE cl.concept_id = ?;""", (concept_id,)).fetchall()
        partes = []
        for f in filas:
            partes.append(f"- [{f['type']}] {f['text']}\n  «{f['quote']}» — "
                          f"{f['title']}, p.{f['page']}")
        return tokens("\n".join(partes))

    # ==================================================================
    # Servir
    # ==================================================================

    def _bloque_json(self, concept_id: str) -> Optional[Dict[str, Any]]:
        """ El bloque guardado en su forma estructurada, para poder reordenarlo """
        with self.kb.conectar() as c:
            try:
                f = c.execute("SELECT bloque FROM contexto_modelo WHERE concept_id = ?;",
                              (concept_id,)).fetchone()
            except Exception:
                return None
        return json.loads(f["bloque"]) if f else None

    def bloque(self, concept_id: str) -> Optional[str]:
        with self.kb.conectar() as c:
            try:
                f = c.execute("SELECT texto FROM contexto_modelo WHERE concept_id = ?;",
                              (concept_id,)).fetchone()
            except Exception:
                return None
        return f["texto"] if f else None

    def cabecera(self, codigos_usados: Optional[set] = None,
                 signos_usados: Optional[set] = None) -> str:
        """ Leyenda y libros. Solo lo que aparece en el contexto que acompaña.

        Declarar los diez libros de la biblioteca cuando el contexto cita dos es
        gastar ocho líneas en algo que el modelo no va a usar.
        """
        with self.kb.conectar() as c:
            try:
                filas = [dict(r) for r in c.execute(
                    "SELECT source_id, codigo, titulo, dominio FROM contexto_libros;")]
            except Exception:
                filas = []
        if codigos_usados is not None:
            filas = [f for f in filas if f["codigo"] in codigos_usados]
        # El campo de cada libro va en la cabecera: es lo que permite al modelo
        # anclar un concepto puente en el campo que el alumno ya conoce, sin
        # repetir el dominio en cada línea.
        libros = "  ".join(
            f"{f['codigo']}={f['titulo']}"
            + (f"[{(f.get('dominio') or '')[:2].upper()}]" if f.get("dominio") else "")
            for f in filas)
        leyenda = self.leyenda_de(signos_usados if signos_usados is not None
                                  else {s for _, s, _ in SIGNOS} | {"<", ">", "≠", "→"})
        partes = [p for p in (leyenda, f"· {libros}" if libros else "") if p]
        return "\n".join(partes)

    def compilar_para(self, concept_ids: List[str], presupuesto: int = 1200,
                      nivel: str = "intermedio",
                      dominio_preferido: Optional[str] = None) -> Dict[str, Any]:
        """ Varios conceptos dentro de un presupuesto, con una cabecera a medida.

        La cabecera se calcula DESPUÉS de elegir los bloques, para declarar solo
        los signos y los libros que aparecen. Reservarla por adelantado obligaba a
        declararlo todo y se comía el ahorro.
        """
        bloques, usados = [], []
        # Se reserva un margen prudente para la cabecera y se ajusta al final
        gastado = 40

        # Con nivel o campo preferido hay que reordenar, así que se parte del bloque
        # guardado en JSON en vez del texto ya renderizado.
        a_medida = nivel != "intermedio" or bool(dominio_preferido)
        dominio_de_libro = {}
        if a_medida:
            # Si todavía no se ha precompilado no hay tabla de códigos, y sin ella
            # el campo preferido no tendría con qué ordenar y se ignoraría en
            # silencio. Se calculan los códigos al vuelo.
            with self.kb.conectar() as c:
                try:
                    dominio_de_libro = {r["codigo"]: r["dominio"] for r in c.execute(
                        "SELECT codigo, dominio FROM contexto_libros;")}
                except Exception:
                    dominio_de_libro = {}
            if not dominio_de_libro:
                dominio_de_libro = {v["codigo"]: v["dominio"]
                                    for v in self.codigos_de_libros().values()}

        orden_claims: List[str] = []
        for cid in concept_ids:
            compilado = None
            texto = None if a_medida else self.bloque(cid)
            if not texto:
                compilado = self._bloque_json(cid) or self.compilar_concepto(cid)
                texto = (self.render_concepto(compilado, nivel=nivel,
                                              dominio_preferido=dominio_preferido,
                                              dominio_de_libro=dominio_de_libro)
                         if compilado else "")
            if not texto:
                continue
            # El orden en que salen las afirmaciones: quien enseñe las citas debe
            # enseñarlas en el mismo orden en que el modelo las leyó, o la primera
            # cita de la lista no será la que sostiene lo primero que dice.
            compilado = compilado or self._bloque_json(cid)
            if compilado:
                for l in self.ordenar_lineas(compilado["lineas"], nivel,
                                             dominio_preferido, dominio_de_libro):
                    orden_claims += [f["claim_id"] for f in l.get("fuentes", [])]
            coste = tokens(texto)
            if gastado + coste > presupuesto:
                continue
            bloques.append(texto)
            usados.append(cid)
            gastado += coste

        if not bloques:
            return {"texto": "", "tokens": 0, "conceptos": [], "vacio": True}

        cuerpo = "\n\n".join(bloques)
        signos = {l[0] for l in cuerpo.splitlines() if l and not l.startswith("@")}
        codigos = set()
        for grupo in re.findall(r"\{([^}]+)\}", cuerpo):
            for ref in grupo.split(","):
                m = re.match(r"([A-Za-z]+)", ref.strip())
                if m:
                    codigos.add(m.group(1))

        cabecera = self.cabecera(codigos_usados=codigos, signos_usados=signos)
        texto = f"{cabecera}\n\n{cuerpo}" if cabecera else cuerpo
        return {"texto": texto, "tokens": tokens(texto), "conceptos": usados,
                "orden_claims": orden_claims, "vacio": False}

    # ==================================================================
    # Volver a la cita textual cuando hace falta
    # ==================================================================

    def citas_de(self, concept_id: str) -> List[Dict[str, Any]]:
        """ Las citas literales, que salieron del contexto del modelo.

        No desaparecen: se quedan en la base. Cuando el tutor afirma algo y hay que
        respaldarlo, se recupera de aquí. El modelo razona sin cargar con ellas y
        la interfaz las enseña al alumno cuando pincha.
        """
        with self.kb.conectar() as c:
            return [dict(r) for r in c.execute(
                """SELECT cl.claim_id, cl.type, cl.text, cl.quote, cl.page,
                          b.title AS libro
                   FROM claims cl LEFT JOIN books b ON b.source_id = cl.source_id
                   WHERE cl.concept_id = ? ORDER BY cl.confidence DESC;""",
                (concept_id,))]
