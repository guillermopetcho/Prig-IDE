"""
Ensamblador de contexto: de una pregunta al material que el tutor necesita.

El problema que resuelve es de presupuesto. Un dosier completo de un concepto muy
tratado puede superar los 4000 tokens, y hay que meter varios conceptos, la pregunta
y la respuesta en una ventana que en local es de 8k. Meter texto hasta que quepa deja
fuera justo lo que faltaba; aquí se elige qué entra y en qué orden.

El criterio es pedagógico, no estadístico:

  1. La DEFINICIÓN del concepto principal. Sin ella no hay explicación.
  2. La INTUICIÓN. Es lo que convierte una definición en comprensión.
  3. Los PRERREQUISITOS, porque explicar sobre algo que el alumno no tiene no sirve.
  4. La FÓRMULA y el CÓDIGO, que son las dos formas de concretar.
  5. Los PUENTES a otros campos: el mismo concepto contado desde las matemáticas
     cuando el alumno viene de programar, o al revés.
  6. Los ERRORES TÍPICOS, que es lo último que se recorta.

Todo lo que sale de aquí lleva libro y página. El tutor no puede citar lo que no
tiene cita, y eso es lo que separa explicar de inventar.
"""

import json
import re
from typing import Any, Dict, List, Optional, Set

from knowledge_base import (KnowledgeBase, normalizar_nombre, palabras_contenido,
                            PALABRAS_VACIAS)

# Aproximación de tokens por carácter en español y con código intercalado.
# Es una estimación deliberadamente conservadora: pasarse de ventana trunca la
# respuesta del modelo a media frase, quedarse corto solo desaprovecha espacio.
CARS_POR_TOKEN = 3.6

ORDEN_PEDAGOGICO = [
    ("DEFINITION", 2),   # (tipo, cuántas como máximo)
    ("INTUITION", 2),
    ("FORMULA", 2),
    ("THEOREM", 1),
    ("ALGORITHM", 1),
    ("CODE_PATTERN", 2),
    ("EXAMPLE", 1),
    ("PROPERTY", 1),
    ("PITFALL", 2),
]

def tokens(texto: str) -> int:
    return int(len(texto or "") / CARS_POR_TOKEN) + 1


class ContextAssembler:
    def __init__(self, kb: Optional[KnowledgeBase] = None, compilador=None):
        self.kb = kb or KnowledgeBase()
        # El compilador sirve el conocimiento ya masticado. Si no hay nada
        # compilado todavía se sigue por el camino de siempre: media biblioteca
        # compilada y media sin compilar tiene que funcionar igual.
        if compilador is None:
            try:
                from contexto_modelo import CompiladorContexto
                compilador = CompiladorContexto(self.kb)
            except Exception:
                compilador = None
        self.compilador = compilador
        # El índice semántico es OPCIONAL: sin él todo funciona como antes. Sirve
        # para descartar los conceptos que la búsqueda por palabras trae de más.
        try:
            from indice_semantico import IndiceSemantico
            self.indice = IndiceSemantico(self.kb)
        except Exception:
            self.indice = None

    # ------------------------------------------------------------------

    def conceptos_de_pregunta(self, pregunta: str, maximo: int = 4) -> List[Dict[str, Any]]:
        """ Qué conceptos conocidos menciona la pregunta.

        Primero se prueban las secuencias largas de palabras: "regla de la cadena"
        tiene que ganar a "regla" y a "cadena" por separado, porque es un concepto
        y las partes no lo son.
        """
        limpia = re.sub(r"[^\wáéíóúüñ\s]", " ", (pregunta or "").lower())
        palabras = [p for p in limpia.split() if p and p not in PALABRAS_VACIAS]
        encontrados: Dict[str, Dict[str, Any]] = {}
        cubiertas: Set[int] = set()

        for n in range(min(5, len(palabras)), 0, -1):
            for i in range(len(palabras) - n + 1):
                if any(j in cubiertas for j in range(i, i + n)):
                    continue
                concepto = self.kb.resolver(" ".join(palabras[i:i + n]))
                if concepto and concepto["concept_id"] not in encontrados:
                    encontrados[concepto["concept_id"]] = dict(concepto)
                    cubiertas.update(range(i, i + n))

        orden = sorted(encontrados.values(), key=lambda c: -(c.get("mentions") or 0))
        if orden:
            return self._afinar(pregunta, orden[:maximo])

        # Nada reconocido: se cae a la búsqueda de texto, que siempre da algo
        por_texto = self._por_texto(pregunta, maximo)
        if por_texto:
            return self._afinar(pregunta, por_texto)

        # Y si tampoco, queda lo semántico: una pregunta parafraseada que no
        # comparte vocabulario con el libro no tiene otra forma de llegar.
        if self.indice and self.indice.hay_indice():
            return self.indice.buscar(pregunta, limite=maximo)
        return []

    def _afinar(self, pregunta: str,
                conceptos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """ Descarta los que la búsqueda por palabras trajo de más.

        El solapamiento de palabras no es relevancia: a «¿hacia dónde mover los
        pesos?» la búsqueda por texto devuelve también regularización y dropout,
        porque la palabra «pesos» sale en sus afirmaciones. Ese material ocupa
        presupuesto y compite por la atención con lo que sí responde.

        Si no hay índice, o el embebedor no responde, se devuelve la lista tal
        cual: esto mejora el resultado, no puede impedirlo.
        """
        if not self.indice or len(conceptos) <= 1:
            return conceptos
        try:
            if not self.indice.hay_indice():
                return conceptos
            elegidos = self.indice.filtrar(pregunta, [c["concept_id"] for c in conceptos])
        except Exception:
            return conceptos
        if not elegidos:
            return conceptos
        por_id = {c["concept_id"]: c for c in conceptos}
        return [por_id[cid] for cid in elegidos if cid in por_id] or conceptos

    def _por_texto(self, pregunta: str, maximo: int) -> List[Dict[str, Any]]:
        """ Repliegue cuando la pregunta no nombra ningún concepto conocido.

        Exige solapamiento léxico real: FTS5 puntúa con BM25 y siempre devuelve algo
        si hay una sola coincidencia floja, y devolver material irrelevante es peor
        que no devolver nada — el tutor lo presentaría como respaldado por el libro.
        """
        raices = {normalizar_nombre(p) for p in palabras_contenido(pregunta)}
        raices.discard("")
        if not raices:
            return []
        vistos, salida = set(), []
        for fila in self.kb.buscar(pregunta, limite=12):
            cid = fila.get("concept_id")
            if not cid or cid in vistos:
                continue
            texto_norm = normalizar_nombre(f"{fila.get('text','')} {fila.get('quote','')}")
            if not (raices & set(texto_norm.split())):
                continue
            vistos.add(cid)
            con = self._concepto(cid)
            if con:
                salida.append(con)
            if len(salida) >= maximo:
                break
        return salida

    def _concepto(self, concept_id: str) -> Optional[Dict[str, Any]]:
        with self.kb.conectar() as c:
            fila = c.execute("SELECT * FROM concepts WHERE concept_id = ?;",
                             (concept_id,)).fetchone()
        return dict(fila) if fila else None

    def dosier(self, concept_id: str) -> Optional[Dict[str, Any]]:
        with self.kb.conectar() as c:
            fila = c.execute("SELECT json FROM dossiers WHERE concept_id = ?;",
                             (concept_id,)).fetchone()
        return json.loads(fila["json"]) if fila else None

    # ------------------------------------------------------------------

    def ensamblar(self, pregunta: str, presupuesto_tokens: int = 2600,
                  dominio_preferido: Optional[str] = None,
                  nivel: str = "intermedio",
                  compilado: bool = True) -> Dict[str, Any]:
        """ Devuelve el contexto listo para pegar en el prompt del tutor.

        Con `compilado` se sirve la forma densa: mismo conocimiento en algo menos
        de la mitad de tokens, porque va sin las citas literales (que están en la
        base para cuando haya que respaldar algo), sin repetir el sujeto en cada
        línea y con lo que dicen varios libros fundido.
        """
        conceptos = self.conceptos_de_pregunta(pregunta)
        if compilado and self.compilador and conceptos:
            denso = self._ensamblar_compilado(conceptos, presupuesto_tokens,
                                              nivel, dominio_preferido)
            if denso:
                return denso
        if not conceptos:
            return {"texto": "", "tokens": 0, "conceptos": [], "fuentes": [],
                    "vacio": True,
                    "motivo": "Ningún concepto de la biblioteca coincide con la pregunta"}

        principal = conceptos[0]
        gastado = 0
        bloques: List[str] = []
        fuentes: List[Dict[str, Any]] = []
        usados: List[str] = []

        # Los prerrequisitos del concepto principal entran como conceptos de apoyo:
        # explicar la retropropagación sin la regla de la cadena no explica nada.
        apoyos = self.kb.prerrequisitos(principal["concept_id"], profundidad=1)[:2]
        cola = conceptos + [a for a in apoyos
                            if a["concept_id"] not in {c["concept_id"] for c in conceptos}]

        for pos, con in enumerate(cola):
            dos = self.dosier(con["concept_id"])
            if not dos:
                continue
            # Al principal se le da la mitad del presupuesto; el resto se reparte
            reserva = (presupuesto_tokens // 2 if pos == 0
                       else max(200, (presupuesto_tokens - gastado) // max(1, len(cola) - pos)))
            bloque, coste, cits = self._bloque(dos, min(reserva, presupuesto_tokens - gastado),
                                               dominio_preferido, nivel,
                                               es_principal=(pos == 0))
            if not bloque or coste > presupuesto_tokens - gastado:
                continue
            bloques.append(bloque)
            fuentes.extend(cits)
            usados.append(dos["nombre"])
            gastado += coste
            if gastado >= presupuesto_tokens * 0.95:
                break

        texto = "\n\n".join(bloques)
        return {
            "texto": texto,
            "tokens": tokens(texto),
            "presupuesto": presupuesto_tokens,
            "conceptos": usados,
            "concepto_principal": principal.get("canonical_name"),
            "fuentes": fuentes,
            "vacio": not texto,
        }

    def _ensamblar_compilado(self, conceptos: List[Dict[str, Any]], presupuesto: int,
                             nivel: str = "intermedio",
                             dominio_preferido: Optional[str] = None
                             ) -> Optional[Dict[str, Any]]:
        """ El contexto en forma compilada, si hay bloques para estos conceptos.

        Se arrastran también los prerrequisitos del principal: explicar algo sobre
        lo que el alumno no tiene base no sirve, y en formato denso caben.
        """
        ids = [c["concept_id"] for c in conceptos]
        apoyos = self.kb.prerrequisitos(ids[0], profundidad=1)[:2]
        ids += [a["concept_id"] for a in apoyos if a["concept_id"] not in ids]

        r = self.compilador.compilar_para(ids, presupuesto=presupuesto, nivel=nivel,
                                          dominio_preferido=dominio_preferido)
        if r.get("vacio"):
            return None

        # Las fuentes siguen siendo citables: el bloque lleva los códigos y la
        # base guarda la cita literal de cada afirmación.
        # Las citas se etiquetan con el NOMBRE del concepto, no con su
        # identificador interno: quien las consume filtra por lo que ve el usuario.
        fuentes, nombres = [], []
        for cid in r["conceptos"]:
            con = self._concepto(cid)
            nombre = con["canonical_name"] if con else cid
            if con:
                nombres.append(nombre)
            for cita in self.compilador.citas_de(cid)[:6]:
                fuentes.append({"libro": cita["libro"], "pagina": cita["page"],
                                "cita": cita["quote"], "tipo": cita["type"],
                                "concepto": nombre, "concept_id": cid,
                                "claim_id": cita["claim_id"]})

        # Las citas se ordenan como el modelo leyó las líneas: si se le sirvió
        # primero lo del libro de matemáticas, la primera cita tiene que ser esa.
        posicion = {cid: i for i, cid in enumerate(r.get("orden_claims") or [])}
        fuentes.sort(key=lambda f: posicion.get(f["claim_id"], 10 ** 6))
        return {
            "texto": r["texto"], "tokens": r["tokens"],
            "presupuesto": presupuesto, "conceptos": nombres,
            "concepto_principal": nombres[0] if nombres else None,
            "fuentes": fuentes, "vacio": False, "formato": "compilado",
        }

    def _bloque(self, dos: Dict[str, Any], tope: int, dominio_preferido: Optional[str],
                nivel: str, es_principal: bool):
        """ Un concepto convertido en texto citable, dentro de su tope """
        cabecera = f"### {dos['nombre']}"
        if dos.get("alias"):
            otros = [a for a in dos["alias"] if a.lower() != dos["nombre"].lower()][:4]
            if otros:
                cabecera += f"  (también: {', '.join(otros)})"
        if dos.get("es_puente"):
            cabecera += f"\n[concepto puente entre {', '.join(dos['dominios'])}]"

        lineas = [cabecera]
        gastado = tokens(cabecera)
        citas: List[Dict[str, Any]] = []

        # Al principiante la fórmula le estorba antes de la intuición; al avanzado
        # la intuición le sobra. El orden cambia, el material es el mismo.
        orden = list(ORDEN_PEDAGOGICO)
        if nivel == "principiante":
            orden.sort(key=lambda t: 0 if t[0] in ("INTUITION", "EXAMPLE", "DEFINITION") else 1)
        elif nivel == "avanzado":
            orden.sort(key=lambda t: 0 if t[0] in ("THEOREM", "FORMULA", "PROPERTY") else 1)

        for tipo, maximo in orden:
            items = dos.get("por_tipo", {}).get(tipo) or []
            if dominio_preferido:
                items = sorted(items, key=lambda a: a.get("domain") != dominio_preferido)
            for it in items[:maximo if es_principal else 1]:
                linea = f"- [{tipo}] {it['text']}"
                if it.get("latex"):
                    linea += f"\n  {it['latex']}"
                if it.get("quote"):
                    linea += f'\n  «{it["quote"][:220]}» — {it["book"]}, p.{it.get("page") or "?"}'
                coste = tokens(linea)
                if gastado + coste > tope:
                    break
                lineas.append(linea)
                gastado += coste
                citas.append({"libro": it["book"], "pagina": it.get("page"),
                              "cita": it.get("quote"), "tipo": tipo,
                              "concepto": dos["nombre"], "source_id": it.get("source_id")})

        if es_principal and dos.get("prerrequisitos"):
            previos = ", ".join(p["nombre"] for p in dos["prerrequisitos"][:5])
            linea = f"- [REQUIERE] Antes conviene dominar: {previos}"
            if gastado + tokens(linea) <= tope:
                lineas.append(linea)
                gastado += tokens(linea)

        # La analogía entre campos va al final: es lo primero que se recorta si no
        # cabe, pero cuando cabe es lo que hace que la explicación enganche.
        for a in (dos.get("analogias") or [])[:2]:
            if dominio_preferido and a["dominio"] == dominio_preferido:
                continue
            linea = f"- [DESDE {a['dominio'].upper()}] {a['texto']} ({a['libro']})"
            if gastado + tokens(linea) > tope:
                break
            lineas.append(linea)
            gastado += tokens(linea)

        return ("\n".join(lineas) if len(lineas) > 1 else ""), gastado, citas

    # ------------------------------------------------------------------

    def prompt_tutor(self, pregunta: str, **kw) -> Dict[str, Any]:
        """ El mensaje de sistema completo, con su contexto y sus reglas de cita """
        ctx = self.ensamblar(pregunta, **kw)
        if ctx["vacio"]:
            return {**ctx, "sistema": (
                "Responde con lo que sepas y avisa al alumno de que esta respuesta "
                "NO está respaldada por su biblioteca de libros.")}
        denso = ctx.get("formato") == "compilado"

        intro = ("Eres un tutor que explica apoyándose EXCLUSIVAMENTE en los libros "
                 "del alumno. El material de abajo está extraído de ellos.\n\n")

        if denso:
            # El formato denso hay que explicarlo, pero en dos frases: si la
            # explicación crece más que lo que ahorra comprimir, no sirve de nada.
            formato = ("El material va comprimido: la primera línea dice qué "
                       "significa cada signo y qué libro es cada código. Está así "
                       "para que gastes el esfuerzo en razonar y no en leer. "
                       "Responde en prosa normal, nunca con estos signos.\n\n")
            citar = ("1. Cada dato lleva su fuente entre llaves: {Goo228} es la "
                     "página 228 del libro con código Goo, declarado arriba. Al "
                     "afirmar algo del material, di el libro y la página en "
                     "palabras: «(Goodfellow, p.228)».\n")
            extra = ("3. Las líneas < y > son dependencias: lo que hace falta saber "
                     "antes y lo que esto permite después. Úsalas para ordenar la "
                     "explicación.\n"
                     "4. Un concepto con * aparece en varios campos: ánclalo en el "
                     "que el alumno ya conozca.\n")
        else:
            formato = "Cada punto lleva su cita textual con libro y página.\n\n"
            citar = ("1. Cita el libro y la página cada vez que afirmes algo del "
                     "material.\n")
            extra = ("3. Si hay un bloque [DESDE OTRO CAMPO], úsalo para conectar el "
                     "tema con algo que el alumno ya conoce.\n")

        sistema = (
            intro + formato + "Reglas:\n" + citar
            + "2. Si algo no está en el material, dilo explícitamente en lugar de "
              "rellenarlo de memoria.\n"
            + extra
            + "5. Empieza por la idea y deja la formalización para después.\n\n"
            + f"--- MATERIAL DE LA BIBLIOTECA ---\n{ctx['texto']}\n--- FIN ---"
        )
        return {**ctx, "sistema": sistema, "tokens_sistema": tokens(sistema)}
