"""
Ficha del libro: lo que hay que saber de él para planificar y proponer ejercicios.

Un libro de 600 páginas no cabe en un modelo de 7B, y no hace falta que quepa. La
extracción ya lo condensó: índice con páginas, conceptos con sus frecuencias,
afirmaciones tipadas con su cita, símbolos, figuras. Todo eso junto ocupa unos
miles de tokens y describe el libro entero. El flujo de agentes lee ESO.

La diferencia con lo que ya guardaba Prig es de nivel. Las afirmaciones responden
"¿qué dice el libro sobre la regularización?". La ficha responde lo que un plan de
estudio necesita y nadie estaba contestando:

    ¿qué enseña de verdad, más allá del título?
    ¿qué da por sabido?
    ¿en qué orden hay que leerlo, y qué se puede saltar?
    ¿dónde están los ejemplos resueltos?
    ¿sobre qué conceptos hay material suficiente para montar un ejercicio?
    ¿y qué NO cubre?

Lo último es lo más fácil de olvidar y lo más caro: un plan que promete algo que el
libro no trae manda al alumno a buscar algo que no está.
"""

import os
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from knowledge_base import KnowledgeBase

# Cuánto ocupa cada parte del resumen. Se reparte a propósito: el índice es lo que
# más rinde por token (dice de qué va cada capítulo y en qué página), y la muestra
# de afirmaciones es lo que más ocupa, así que se recorta antes que nada.
PRESUPUESTO = {
    "indice": 1200,
    "conceptos": 500,
    "muestra": 1400,
    "simbolos": 250,
    "figuras": 250,
    "preguntas": 300,
}

TIPOS_UTILES = ["DEFINITION", "INTUITION", "FORMULA", "PROCEDURE",
                "EXAMPLE", "CAVEAT", "COMPARISON", "RESULT", "NOTATION"]


class PerfilLibro:
    def __init__(self, kb: Optional[KnowledgeBase] = None):
        self.kb = kb or KnowledgeBase()

    # ==================================================================
    # El resumen que lee el flujo
    # ==================================================================

    def datos(self, source_id: str) -> Dict[str, Any]:
        """ Todo lo que hay guardado del libro, en crudo y sin recortar """
        with self.kb.conectar() as c:
            libro = c.execute("SELECT * FROM books WHERE source_id = ?;",
                              (source_id,)).fetchone()
            if not libro:
                return {}
            libro = dict(libro)

            libro["secciones"] = [dict(r) for r in c.execute(
                """SELECT * FROM sections WHERE source_id = ?
                   ORDER BY es_capitulo DESC, pagina_inicio;""", (source_id,))]

            libro["conceptos"] = [dict(r) for r in c.execute(
                """SELECT co.canonical_name AS nombre, co.concept_id, co.is_bridge,
                          co.domains, COUNT(*) AS veces,
                          MIN(cl.page) AS primera_pagina
                   FROM claims cl JOIN concepts co ON co.concept_id = cl.concept_id
                   WHERE cl.source_id = ?
                   GROUP BY co.concept_id ORDER BY veces DESC;""", (source_id,))]

            libro["por_tipo"] = {r["type"]: r["n"] for r in c.execute(
                """SELECT type, COUNT(*) n FROM claims WHERE source_id = ?
                   GROUP BY type;""", (source_id,))}

            libro["simbolos"] = [dict(r) for r in c.execute(
                """SELECT DISTINCT symbol, meaning, page FROM symbols
                   WHERE source_id = ? ORDER BY page;""", (source_id,))]

            libro["figuras"] = [dict(r) for r in c.execute(
                "SELECT label, caption, tipo, page FROM figures WHERE source_id = ? ORDER BY page;",
                (source_id,))]

            libro["preguntas"] = [r["texto"] for r in c.execute(
                "SELECT texto FROM questions WHERE source_id = ?;", (source_id,))]

            libro["relaciones"] = [dict(r) for r in c.execute(
                """SELECT a.canonical_name AS origen, b.canonical_name AS destino, r.type
                   FROM relations r
                   JOIN concepts a ON a.concept_id = r.source_concept
                   JOIN concepts b ON b.concept_id = r.target_concept
                   WHERE r.source_id = ? LIMIT 120;""", (source_id,))]
        return libro

    # -- las variables que ve cada paso del flujo --------------------------

    def variables(self, source_id: str) -> Dict[str, str]:
        """ El libro convertido en trozos de texto que caben en un prompt.

        Cada trozo va por separado para que un paso pida solo lo que necesita: el
        que deduce la notación no gana nada leyendo el índice, y metérselo le quita
        ventana de contexto y lo distrae.
        """
        d = self.datos(source_id)
        if not d:
            return {}
        return {
            "libro:titulo": d.get("title") or source_id,
            "libro:indice": self._indice(d),
            "libro:conceptos": self._conceptos(d),
            "libro:muestra": self._muestra(source_id, d),
            "libro:simbolos": self._simbolos(d),
            "libro:figuras": self._figuras(d),
            "libro:preguntas": self._preguntas(d),
            "libro:datos": self._datos_sueltos(d),
            "libro:relaciones": self._relaciones(d),
        }

    def _indice(self, d) -> str:
        secciones = d.get("secciones") or []
        if not secciones:
            return ("(este libro no trae índice detectado; dedúcelo de los conceptos "
                    "y sus páginas)")
        lineas = []
        for s in secciones:
            sangria = "" if s["es_capitulo"] else "   "
            paginas = (f" [p.{s['pagina_inicio']}-{s['pagina_fin']}]"
                       if s.get("pagina_inicio") else "")
            temas = json.loads(s.get("temas") or "[]")
            lineas.append(f"{sangria}{s.get('numero','')} {s.get('titulo','')}{paginas}"
                          + (f"  · temas: {', '.join(temas[:6])}" if temas else ""))
            if s.get("resumen"):
                lineas.append(f"{sangria}   {s['resumen'][:160]}")
        return _cabe("\n".join(lineas), PRESUPUESTO["indice"])

    def _conceptos(self, d) -> str:
        cs = d.get("conceptos") or []
        if not cs:
            return "(sin conceptos extraídos todavía)"
        lineas = []
        for c in cs:
            dominios = json.loads(c.get("domains") or "[]")
            puente = " ⟷" + "/".join(dominios) if c.get("is_bridge") else ""
            lineas.append(f"{c['nombre']} ({c['veces']}×, desde p.{c.get('primera_pagina') or '?'})"
                          + puente)
        return _cabe(" · ".join(lineas), PRESUPUESTO["conceptos"])

    def _muestra(self, source_id: str, d) -> str:
        """ Unas pocas afirmaciones de cada tipo, repartidas por todo el libro.

        Coger las primeras daría una idea falsa: los primeros capítulos de casi
        cualquier libro son introductorios y parecen más fáciles de lo que es el
        resto. Se muestrea a lo largo de las páginas.
        """
        por_tipo = {}
        with self.kb.conectar() as c:
            for tipo in TIPOS_UTILES:
                filas = c.execute(
                    """SELECT text, quote, page FROM claims
                       WHERE source_id = ? AND type = ? ORDER BY page;""",
                    (source_id, tipo)).fetchall()
                if not filas:
                    continue
                paso = max(1, len(filas) // 4)
                por_tipo[tipo] = [dict(f) for f in filas[::paso][:4]]

        lineas = []
        for tipo, items in por_tipo.items():
            lineas.append(f"[{tipo}]")
            for i in items:
                lineas.append(f"  p.{i.get('page') or '?'} · {(i.get('text') or '')[:190]}")
        return _cabe("\n".join(lineas), PRESUPUESTO["muestra"]) or "(sin afirmaciones)"

    def _simbolos(self, d) -> str:
        ss = d.get("simbolos") or []
        if not ss:
            return "(no se detectó notación)"
        return _cabe(" · ".join(f"{s['symbol']} = {s['meaning']} (p.{s.get('page') or '?'})"
                                for s in ss), PRESUPUESTO["simbolos"])

    def _figuras(self, d) -> str:
        fs = d.get("figuras") or []
        if not fs:
            return "(no se detectaron figuras)"
        return _cabe("\n".join(f"p.{f.get('page') or '?'} {f.get('label','')}: "
                               f"{(f.get('caption') or '')[:110]}" for f in fs),
                     PRESUPUESTO["figuras"])

    def _preguntas(self, d) -> str:
        ps = d.get("preguntas") or []
        if not ps:
            return "(el extractor no guardó preguntas de este libro)"
        return _cabe("\n".join(f"- {p}" for p in ps), PRESUPUESTO["preguntas"])

    def _relaciones(self, d) -> str:
        rs = d.get("relaciones") or []
        if not rs:
            return "(sin relaciones entre conceptos)"
        return _cabe(" · ".join(f"{r['origen']} —{r['type']}→ {r['destino']}" for r in rs), 500)

    def _datos_sueltos(self, d) -> str:
        tipos = ", ".join(f"{k}: {v}" for k, v in
                          sorted((d.get("por_tipo") or {}).items(), key=lambda kv: -kv[1]))
        return (f"Título: {d.get('title')}\n"
                f"Campo: {d.get('domain')}\n"
                f"Páginas: {d.get('pages') or '?'}\n"
                f"Afirmaciones extraídas: {d.get('claims_verified', 0)} ({tipos})\n"
                f"Conceptos: {len(d.get('conceptos') or [])}\n"
                f"Capítulos detectados: {sum(1 for s in (d.get('secciones') or []) if s['es_capitulo'])}\n"
                f"Figuras: {len(d.get('figuras') or [])} · "
                f"Símbolos: {len(d.get('simbolos') or [])}")

    # ==================================================================
    # La ficha
    # ==================================================================

    def montar_ficha(self, source_id: str, salidas: Dict[str, Any],
                     modelos: List[str]) -> Dict[str, Any]:
        """ Junta en código lo que produjo cada paso.

        El montaje NO lo hace un modelo a propósito. Pedirle a un séptimo agente que
        reúna las salidas de los otros seis significaría meterlas todas en una
        ventana de 4096 tokens, que no caben, y arriesgar que reescriba datos que ya
        estaban bien. Aquí es un `dict.update` y no se puede equivocar.
        """
        d = self.datos(source_id)
        ficha: Dict[str, Any] = {
            "source_id": source_id,
            "titulo": d.get("title") or source_id,
            "campo": d.get("domain"),
            "paginas": d.get("pages"),
            "construida": datetime.now().isoformat(),
            "modelos": modelos,
        }
        # Cada paso aporta su parte bajo su propia clave; si uno falló, el resto
        # de la ficha sigue sirviendo.
        for clave, paso in (("temario", "temario"), ("notacion", "notacion"),
                            ("asume", "prerrequisitos"), ("identidad", "identidad"),
                            ("ejercicios", "ejercicios"), ("lagunas", "lagunas")):
            valor = salidas.get(paso)
            if isinstance(valor, str):
                valor = _json_suelto(valor) or valor
            # Un paso que devuelve {"asume": [...]} y se guarda bajo "asume" dejaría
            # la ficha anidada dos veces por el mismo nombre. Se desenvuelve.
            if isinstance(valor, dict) and len(valor) == 1 and clave in valor:
                valor = valor[clave]
            if valor:
                ficha[clave] = valor

        ficha["medido"] = {
            "conceptos": len(d.get("conceptos") or []),
            "afirmaciones": d.get("claims_verified", 0),
            "por_tipo": d.get("por_tipo") or {},
            "capitulos": sum(1 for s in (d.get("secciones") or []) if s["es_capitulo"]),
            "figuras": len(d.get("figuras") or []),
            "simbolos": len(d.get("simbolos") or []),
            "preguntas": len(d.get("preguntas") or []),
            # Conceptos con material suficiente para montar algo encima. El umbral
            # es bajo a propósito: con tres afirmaciones de tipos distintos ya se
            # puede escribir un ejercicio que se apoye en el libro.
            "conceptos_con_material": [
                c["nombre"] for c in (d.get("conceptos") or []) if c["veces"] >= 3][:40],
        }
        return ficha

    def guardar(self, source_id: str, ficha: Dict[str, Any]) -> Dict[str, Any]:
        with self.kb.conectar() as c:
            c.execute("INSERT OR REPLACE INTO book_profiles VALUES (?,?,?,?);",
                      (source_id, json.dumps(ficha, ensure_ascii=False),
                       datetime.now().isoformat(),
                       json.dumps(ficha.get("modelos") or [], ensure_ascii=False)))
            c.commit()
        return ficha

    def obtener(self, source_id: str) -> Optional[Dict[str, Any]]:
        with self.kb.conectar() as c:
            f = c.execute("SELECT json FROM book_profiles WHERE source_id = ?;",
                          (source_id,)).fetchone()
        return json.loads(f["json"]) if f else None

    def listar(self) -> List[Dict[str, Any]]:
        """ Los libros, diciendo cuáles ya tienen ficha y cuánto material hay """
        with self.kb.conectar() as c:
            filas = [dict(r) for r in c.execute("""
                SELECT b.source_id, b.title, b.domain, b.pages, b.claims_verified,
                       (SELECT COUNT(*) FROM sections s WHERE s.source_id = b.source_id
                        AND s.es_capitulo = 1) AS capitulos,
                       (SELECT COUNT(DISTINCT concept_id) FROM claims cl
                        WHERE cl.source_id = b.source_id) AS conceptos,
                       (SELECT COUNT(*) FROM figures f WHERE f.source_id = b.source_id) AS figuras,
                       (SELECT built_at FROM book_profiles p
                        WHERE p.source_id = b.source_id) AS ficha_hecha
                FROM books b ORDER BY b.title;""")]
        return filas

    # ==================================================================
    # Para el planificador y los ejercicios
    # ==================================================================

    def contexto_para_plan(self, objetivo: str, limite_libros: int = 4) -> str:
        """ Las fichas resumidas, para que quien arma un plan sepa con qué cuenta.

        Sin esto el planificador inventa un temario razonable y luego manda a leer
        capítulos que no existen. Con esto propone lo que hay, y dice lo que falta.
        """
        trozos = []
        for libro in self.listar()[:limite_libros]:
            ficha = self.obtener(libro["source_id"])
            if not ficha:
                trozos.append(f"### {libro['title']} [{libro['domain']}] — sin analizar. "
                              f"{libro['conceptos']} conceptos, {libro['capitulos']} capítulos.")
                continue
            ident = ficha.get("identidad") or {}
            partes = [f"### {ficha['titulo']} [{ficha.get('campo')}]"]
            if isinstance(ident, dict):
                if ident.get("nivel"):
                    partes.append(f"Nivel: {ident['nivel']}")
                if ident.get("que_cubre"):
                    partes.append(f"Cubre: {ident['que_cubre']}")
            asume = ficha.get("asume")
            if asume:
                partes.append("Da por sabido: " + _lista_corta(asume))
            temario = ficha.get("temario")
            if isinstance(temario, dict):
                temario = temario.get("capitulos") or temario.get("temario")
            if isinstance(temario, list):
                for cap in temario[:12]:
                    if not isinstance(cap, dict):
                        continue
                    pag = cap.get("paginas") or cap.get("pagina")
                    partes.append(f"  cap {cap.get('capitulo', '?')}: {cap.get('titulo', '')}"
                                  + (f" (p.{pag})" if pag else "")
                                  + (f" · dificultad {cap['dificultad']}/5"
                                     if cap.get("dificultad") else ""))
            lagunas = ficha.get("lagunas")
            if lagunas:
                partes.append("NO cubre: " + _lista_corta(lagunas))
            trozos.append("\n".join(partes))
        return "\n\n".join(trozos)

    def material_para_ejercicio(self, concepto: str) -> Dict[str, Any]:
        """ Con qué se puede montar un ejercicio sobre este concepto.

        Devuelve de qué libro sale, en qué páginas, qué ejemplos resueltos hay cerca
        y qué preguntas trae el propio texto. Un ejercicio construido sobre esto
        remite a algo que el alumno puede ir a leer; uno inventado, no.
        """
        con = self.kb.resolver(concepto)
        if not con:
            return {"encontrado": False, "concepto": concepto}
        cid = con["concept_id"]
        with self.kb.conectar() as c:
            afirmaciones = [dict(r) for r in c.execute(
                """SELECT cl.type, cl.text, cl.quote, cl.page, cl.source_id, cl.latex,
                          cl.code_language, b.title
                   FROM claims cl LEFT JOIN books b ON b.source_id = cl.source_id
                   WHERE cl.concept_id = ? ORDER BY cl.confidence DESC LIMIT 30;""", (cid,))]
            libros = sorted({a["source_id"] for a in afirmaciones})
            secciones = []
            for sid in libros:
                paginas = [a["page"] for a in afirmaciones
                           if a["source_id"] == sid and a.get("page")]
                if not paginas:
                    continue
                secciones += [dict(r) for r in c.execute(
                    """SELECT numero, titulo, pagina_inicio, pagina_fin, source_id
                       FROM sections WHERE source_id = ?
                         AND pagina_inicio <= ? AND COALESCE(pagina_fin, 99999) >= ?
                       LIMIT 3;""", (sid, max(paginas), min(paginas)))]
            preguntas = [r["texto"] for r in c.execute(
                """SELECT texto FROM questions WHERE source_id IN (%s) LIMIT 12;"""
                % ",".join("?" * len(libros)), libros)] if libros else []

        por_tipo: Dict[str, List[dict]] = {}
        for a in afirmaciones:
            por_tipo.setdefault(a["type"], []).append(a)

        return {
            "encontrado": True,
            "concepto": con["canonical_name"],
            "dominios": con.get("domains"),
            "es_puente": bool(con.get("is_bridge")),
            "por_tipo": por_tipo,
            "ejemplos_resueltos": por_tipo.get("EXAMPLE", []),
            "errores_tipicos": por_tipo.get("CAVEAT", []),
            "formulas": por_tipo.get("FORMULA", []),
            "procedimientos": por_tipo.get("PROCEDURE", []),
            "secciones": secciones,
            "preguntas_del_libro": preguntas,
            "prerrequisitos": self.kb.prerrequisitos(cid, profundidad=2),
            # Un ejercicio necesita más que una definición: hace falta algo que
            # hacer. Sin procedimiento, ejemplo o fórmula, solo da para preguntar.
            "suficiente_para_ejercicio": bool(
                por_tipo.get("PROCEDURE") or por_tipo.get("EXAMPLE")
                or por_tipo.get("FORMULA")),
        }


# ===========================================================================

def _cabe(texto: str, tope_tokens: int) -> str:
    tope = int(tope_tokens * 3.6)
    if len(texto) <= tope:
        return texto
    return texto[:tope] + f"\n[… {len(texto) - tope} caracteres más, recortados …]"


# Las claves con las que un modelo suele nombrar la cosa, en orden de preferencia.
# El paso devuelve JSON libre dentro de la forma que se le pidió, y no siempre usa
# el mismo nombre; leerlo mal deja el contexto del plan lleno de diccionarios en
# crudo, que es exactamente lo que el planificador no sabe interpretar.
CLAVES_NOMBRE = ("tema", "nombre", "concepto", "titulo", "texto", "que")


def _nombrar(x) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        for k in CLAVES_NOMBRE:
            if isinstance(x.get(k), str) and x[k].strip():
                # La gravedad o la necesidad matizan y caben en un paréntesis
                matiz = x.get("gravedad") or x.get("como_de_necesario")
                return f"{x[k]} ({matiz})" if isinstance(matiz, str) else x[k]
        return ", ".join(str(v)[:40] for v in x.values() if isinstance(v, (str, int)))
    return str(x)


def _aplanar(v) -> list:
    """ De la forma que sea a una lista de cosas nombrables """
    if isinstance(v, list):
        salida = []
        for x in v:
            salida += _aplanar(x) if isinstance(x, (list, dict)) and not _nombrar(x) else [x]
        return salida
    if isinstance(v, dict):
        # {"asume": [...], "nivel_de_entrada": "..."} → la lista es lo que importa
        listas = [x for x in v.values() if isinstance(x, list)]
        if listas:
            return [y for lista in listas for y in lista]
        if any(k in v for k in CLAVES_NOMBRE):
            return [v]
        return [x for x in v.values() if isinstance(x, str)]
    return [v] if v else []


def _lista_corta(v, n: int = 8) -> str:
    items = _aplanar(v)
    return ", ".join(_nombrar(x) for x in items[:n] if _nombrar(x))


def _json_suelto(texto: str):
    for abre, cierra in (("{", "}"), ("[", "]")):
        i = texto.find(abre)
        if i < 0:
            continue
        prof, cad, esc = 0, False, False
        for k in range(i, len(texto)):
            ch = texto[k]
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                cad = not cad
                continue
            if cad:
                continue
            if ch == abre:
                prof += 1
            elif ch == cierra:
                prof -= 1
                if prof == 0:
                    try:
                        return json.loads(texto[i:k + 1])
                    except Exception:
                        break
    return None
