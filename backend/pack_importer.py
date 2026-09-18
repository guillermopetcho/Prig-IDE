"""
Importación de paquetes de conocimiento y unificación entre libros.

Tres responsabilidades, en este orden:

  1. IMPORTAR   verificar el .prigpack y volcarlo a la base, por libro
  2. UNIFICAR   fusionar los conceptos de TODOS los libros en canónicos
  3. DOSIERES   reunir por concepto todo lo que se sabe de él

El paso 2 es el que convierte cien libros en una biblioteca: sin él, cada libro
guarda sus propios nombres y "weight decay", "regularización L2" y "ridge" quedan
como tres cosas distintas.

Todo es idempotente: reimportar un libro lo reemplaza limpiamente, y la unificación
se puede volver a lanzar tras cada importación.
"""

import os
import json
import zipfile
import hashlib
import sys
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kaggle_worker"))
from domains import DOMAINS, KNOWN_BRIDGES, distancia_dominios  # noqa: E402

from knowledge_base import KnowledgeBase, UnionFind, normalizar_nombre  # noqa: E402

ESQUEMAS_COMPATIBLES = {"3.0", "3.1"}


class PackImportError(Exception):
    pass


def norm_de_id(concept_id: str) -> str:
    """ Del identificador de un concepto a su nombre normalizado.

    Durante la importación los conceptos llevan prefijo `tmp:` y tras unificar
    llevan `c:`. Al reunificar (porque se reimporta un libro) conviven los dos, y
    tratar un `c:gradient` como si fuese un nombre crearía el concepto duplicado
    `c:c:gradient`. Este es el único sitio donde se quita el prefijo.
    """
    cid = concept_id or ""
    for prefijo in ("tmp:", "c:"):
        if cid.startswith(prefijo):
            return cid[len(prefijo):]
    return cid


class PackImporter:
    def __init__(self, kb: Optional[KnowledgeBase] = None):
        self.kb = kb or KnowledgeBase()

    # ==================================================================
    # 1 · Importar
    # ==================================================================

    def verificar(self, ruta_pack: str) -> Dict[str, Any]:
        """ Comprueba el paquete SIN escribir nada.

        Un paquete corrupto a medio importar deja la base en un estado peor que no
        haberlo importado, así que primero se valida entero.
        """
        if not zipfile.is_zipfile(ruta_pack):
            raise PackImportError(f"No es un paquete válido: {os.path.basename(ruta_pack)}")

        problemas: List[str] = []
        with zipfile.ZipFile(ruta_pack) as z:
            nombres = set(z.namelist())
            for obligatorio in ("manifest.json", "claims.jsonl", "concepts.jsonl", "checksums.json"):
                if obligatorio not in nombres:
                    raise PackImportError(f"Falta {obligatorio} en el paquete")

            manifest = json.loads(z.read("manifest.json"))
            version = str(manifest.get("schema_version", "?"))
            if version not in ESQUEMAS_COMPATIBLES:
                problemas.append(f"esquema v{version} no reconocido (se esperaba "
                                 f"{' o '.join(sorted(ESQUEMAS_COMPATIBLES))})")

            # Integridad: el checksum de cada archivo debe cuadrar
            checksums = json.loads(z.read("checksums.json"))
            for nombre, esperado in checksums.items():
                if nombre == "checksums.json" or nombre not in nombres:
                    continue
                real = hashlib.sha256(z.read(nombre)).hexdigest()
                if real != esperado:
                    problemas.append(f"{nombre}: checksum no coincide")

            claims = self._leer_jsonl(z, "claims.jsonl")
            concepts = self._leer_jsonl(z, "concepts.jsonl")

            declarado = manifest.get("claims_verified")
            if declarado is not None and declarado != len(claims):
                problemas.append(f"el manifiesto declara {declarado} afirmaciones "
                                 f"pero el archivo trae {len(claims)}")

            dominio = manifest.get("domain")
            if dominio and dominio not in DOMAINS:
                problemas.append(f"dominio desconocido: {dominio}")

            # Un paquete de medio libro es coherente consigo mismo: declara
            # exactamente las afirmaciones que trae. Lo único que lo delata es
            # cuántos fragmentos DEBERÍA haber procesado, y eso lo escribe el
            # extractor. Suele pasar al empaquetar antes de que termine el otro
            # reparto de la segunda GPU.
            procesados = manifest.get("chunks_processed")
            esperados = manifest.get("chunks_expected")
            if manifest.get("complete") is False or (
                    isinstance(procesados, int) and isinstance(esperados, int)
                    and procesados < esperados):
                problemas.append(
                    f"libro incompleto: {procesados} de {esperados} fragmentos "
                    f"(termina los repartos y vuelve a empaquetar con --pack-only)")

            fallidos = manifest.get("chunks_failed") or 0
            if esperados and fallidos > esperados * 0.2:
                problemas.append(f"{fallidos} fragmentos fallaron de {esperados}: "
                                 f"revisa el modelo antes de darlo por bueno")

        return {
            "ok": not problemas,
            "problemas": problemas,
            "manifest": manifest,
            "claims": len(claims),
            "concepts": len(concepts),
        }

    @staticmethod
    def _normalizar_indice(indice: dict, source_id: str) -> dict:
        """ El índice del paquete viene suelto, pero el del trabajo va por libro.

        Son dos archivos con el mismo nombre y forma distinta, y confundirlos hace
        que el libro entre sin capítulos: no da error, simplemente el plan de
        estudio se queda luego sin poder decir qué leer.
        """
        if not isinstance(indice, dict):
            return {}
        if "chapters" in indice or "sections" in indice:
            return indice
        interno = indice.get(source_id)
        if isinstance(interno, dict):
            return interno
        # Un único libro dentro: casi seguro es el que toca
        valores = [v for v in indice.values() if isinstance(v, dict) and "chapters" in v]
        return valores[0] if len(valores) == 1 else {}

    @staticmethod
    def _leer_json(z: zipfile.ZipFile, nombre: str):
        if nombre not in z.namelist():
            return None
        try:
            return json.loads(z.read(nombre))
        except Exception:
            return None

    @staticmethod
    def _leer_jsonl(z: zipfile.ZipFile, nombre: str) -> List[dict]:
        if nombre not in z.namelist():
            return []
        salida = []
        for linea in z.read(nombre).decode("utf-8").splitlines():
            linea = linea.strip()
            if linea:
                try:
                    salida.append(json.loads(linea))
                except json.JSONDecodeError:
                    continue
        return salida

    def importar(self, ruta_pack: str, forzar: bool = False) -> Dict[str, Any]:
        """ Vuelca un paquete en la base. Reimportar reemplaza, no duplica. """
        verif = self.verificar(ruta_pack)
        if not verif["ok"] and not forzar:
            raise PackImportError("Paquete con problemas: " + "; ".join(verif["problemas"]))

        manifest = verif["manifest"]
        source_id = manifest["source_id"]
        dominio = manifest.get("domain") or "machine_learning"

        with zipfile.ZipFile(ruta_pack) as z:
            claims = self._leer_jsonl(z, "claims.jsonl")
            concepts = self._leer_jsonl(z, "concepts.jsonl")
            relations = self._leer_jsonl(z, "relations.jsonl")
            symbols = self._leer_jsonl(z, "symbols.jsonl")
            # El paquete trae más de lo que se guardaba: el índice del libro, sus
            # figuras y las preguntas que el texto permite responder. Descartarlos
            # dejaba fuera justo lo que un plan de estudio necesita para decir qué
            # capítulo leer, y lo que un ejercicio necesita para salir del libro y
            # no de la imaginación del modelo.
            figuras = self._leer_jsonl(z, "figures.jsonl")
            preguntas = self._leer_json(z, "questions.json") or []
            indice = self._normalizar_indice(
                self._leer_json(z, "outline.json") or {}, source_id)

        with self.kb.conectar() as c:
            existia = c.execute("SELECT 1 FROM books WHERE source_id = ?;",
                                (source_id,)).fetchone() is not None
            if existia:
                self._borrar_libro(c, source_id)

            c.execute("""INSERT OR REPLACE INTO books
                (source_id, title, domain, sha256, pages, model_used,
                 claims_verified, imported_at) VALUES (?,?,?,?,?,?,?,?);""",
                (source_id, manifest.get("title", source_id), dominio,
                 manifest.get("book_sha256"), manifest.get("pages"),
                 manifest.get("model_used"), len(claims), datetime.now().isoformat()))

            # Las afirmaciones entran con el nombre de concepto SIN canonizar; la
            # unificación posterior las reapunta al concepto canónico.
            for cl in claims:
                nombres = cl.get("concepts") or []
                primer = normalizar_nombre(nombres[0]) if nombres else ""
                c.execute("""INSERT OR REPLACE INTO claims
                    (claim_id, concept_id, source_id, domain, type, text, quote,
                     page, confidence, code_language, latex, bridges_to)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?);""",
                    (cl["claim_id"], f"tmp:{primer}", source_id, dominio,
                     cl.get("type", "DEFINITION"), cl.get("text", ""), cl.get("quote", ""),
                     cl.get("page"), float(cl.get("confidence", 0.7) or 0.7),
                     cl.get("code_language", "none"), cl.get("latex", ""),
                     json.dumps(cl.get("bridges_to") or [])))
                c.execute("""INSERT INTO claims_fts (claim_id, text, quote, concept_names)
                             VALUES (?,?,?,?);""",
                          (cl["claim_id"], cl.get("text", ""), cl.get("quote", ""),
                           " ".join(nombres)))

            # Los conceptos del paquete se guardan como alias provisionales
            for co in concepts:
                norm = normalizar_nombre(co.get("name", ""))
                if not norm:
                    continue
                c.execute("""INSERT OR REPLACE INTO aliases
                             (norm, concept_id, surface, source_id, is_primary)
                             VALUES (?,?,?,?,1);""",
                          (norm, f"tmp:{norm}", co.get("name"), source_id))
                for alias in co.get("aliases") or []:
                    na = normalizar_nombre(alias)
                    if na and na != norm:
                        c.execute("""INSERT OR REPLACE INTO aliases
                                     (norm, concept_id, surface, source_id, is_primary)
                                     VALUES (?,?,?,?,0);""",
                                  (na, f"tmp:{norm}", alias, source_id))

            for r in relations:
                ns = normalizar_nombre(r.get("source", ""))
                nt = normalizar_nombre(r.get("target", ""))
                if not ns or not nt:
                    continue
                c.execute("""INSERT INTO relations
                    (source_concept, target_concept, type, quote, source_id, page, cross_domain)
                    VALUES (?,?,?,?,?,?,0);""",
                    (f"tmp:{ns}", f"tmp:{nt}", r.get("type", "REQUIRES"),
                     r.get("quote", ""), source_id, r.get("page")))

            # -- índice del libro ---------------------------------------
            for cap in (indice.get("chapters") or []):
                c.execute("""INSERT OR REPLACE INTO sections
                    (section_id, source_id, chapter_id, numero, titulo,
                     pagina_inicio, pagina_fin, es_capitulo, temas, resumen,
                     prerrequisitos) VALUES (?,?,?,?,?,?,?,1,?,?,?);""",
                    (cap.get("chapter_id") or f"{source_id}_cap{cap.get('chapter_num')}",
                     source_id, cap.get("chapter_id"), str(cap.get("chapter_num", "")),
                     cap.get("title", ""), cap.get("start_page"), cap.get("end_page"),
                     json.dumps(cap.get("key_topics") or [], ensure_ascii=False),
                     cap.get("summary", ""),
                     json.dumps(cap.get("prerequisites") or [], ensure_ascii=False)))
            for sec in (indice.get("sections") or []):
                c.execute("""INSERT OR REPLACE INTO sections
                    (section_id, source_id, chapter_id, numero, titulo,
                     pagina_inicio, pagina_fin, es_capitulo, temas, resumen,
                     prerrequisitos) VALUES (?,?,?,?,?,?,?,0,?,?,?);""",
                    (sec.get("section_id") or f"{source_id}_sec{sec.get('section_num')}",
                     source_id, sec.get("chapter_id"), str(sec.get("section_num", "")),
                     sec.get("title", ""), sec.get("start_page"), sec.get("end_page"),
                     json.dumps(sec.get("key_topics") or [], ensure_ascii=False),
                     sec.get("summary", ""),
                     json.dumps(sec.get("prerequisites") or [], ensure_ascii=False)))

            for fg in figuras:
                c.execute("""INSERT INTO figures (source_id, label, caption, tipo, page)
                             VALUES (?,?,?,?,?);""",
                          (source_id, fg.get("label", ""), fg.get("caption", ""),
                           fg.get("type") or fg.get("tipo") or "figura", fg.get("page")))

            for pr in preguntas:
                texto = pr if isinstance(pr, str) else (pr or {}).get("texto", "")
                if texto:
                    c.execute("""INSERT INTO questions (source_id, texto, page, concept_id)
                                 VALUES (?,?,?,?);""",
                              (source_id, texto,
                               (pr or {}).get("page") if isinstance(pr, dict) else None,
                               None))

            for sy in symbols:
                c.execute("""INSERT INTO symbols
                    (symbol, meaning, concept_id, source_id, domain, page)
                    VALUES (?,?,?,?,?,?);""",
                    (sy.get("symbol", ""), sy.get("meaning", ""), None,
                     source_id, dominio, sy.get("page")))
            c.commit()

        return {
            "source_id": source_id,
            "title": manifest.get("title"),
            "domain": dominio,
            "reemplazado": existia,
            "claims": len(claims), "concepts": len(concepts),
            "relations": len(relations), "symbols": len(symbols),
            "figuras": len(figuras), "preguntas": len(preguntas),
            "capitulos": len(indice.get("chapters") or []),
            "secciones": len(indice.get("sections") or []),
            "avisos": verif["problemas"],
        }

    @staticmethod
    def _borrar_libro(c, source_id: str):
        """ Borra TODO lo de un libro, índice de texto incluido """
        for cid, in c.execute("SELECT claim_id FROM claims WHERE source_id = ?;",
                              (source_id,)).fetchall():
            c.execute("DELETE FROM claims_fts WHERE claim_id = ?;", (cid,))
        for tabla in ("claims", "relations", "symbols", "aliases",
                      "sections", "figures", "questions"):
            c.execute(f"DELETE FROM {tabla} WHERE source_id = ?;", (source_id,))

    def importar_carpeta(self, carpeta: str) -> Dict[str, Any]:
        packs = [os.path.join(carpeta, f) for f in sorted(os.listdir(carpeta))
                 if f.endswith(".prigpack")]
        importados, fallidos = [], []
        for p in packs:
            try:
                importados.append(self.importar(p))
            except Exception as err:
                fallidos.append({"pack": os.path.basename(p), "error": str(err)})
        return {"importados": importados, "fallidos": fallidos, "total": len(packs)}

    # ==================================================================
    # 2 · Unificar conceptos entre libros  (la fase "reduce")
    # ==================================================================

    def unificar(self) -> Dict[str, Any]:
        """ Convierte los conceptos provisionales de cada libro en canónicos.

        Sin esto, cien libros son cien islas: cada uno guarda sus propios nombres y
        el modelo no puede saber que el "weight decay" del libro de deep learning es
        la "regularización L2" del de machine learning.

        Se puede relanzar tras cada importación; el resultado solo depende del
        contenido de la base, no de en qué orden entraron los libros.
        """
        uf = UnionFind()
        # norm -> {texto original: [veces_como_principal, veces_como_alias]}
        superficies: Dict[str, Dict[str, List[int]]] = {}

        with self.kb.conectar() as c:
            # a) Cada libro ya declaró qué nombres apuntan al mismo concepto
            grupos_libro: Dict[str, List[str]] = {}
            for fila in c.execute(
                    "SELECT norm, concept_id, surface, is_primary FROM aliases;"):
                norm, cid, surface = fila["norm"], fila["concept_id"], fila["surface"]
                uf.buscar(norm)
                grupos_libro.setdefault(cid, []).append(norm)
                if surface:
                    cuenta = superficies.setdefault(norm, {}).setdefault(surface, [0, 0])
                    cuenta[0 if fila["is_primary"] else 1] += 1
            for norms in grupos_libro.values():
                for otro in norms[1:]:
                    uf.unir(norms[0], otro)

            # b) Los extremos de las relaciones también son conceptos, aunque el libro
            #    nunca llegase a definirlos. Si no se registran aquí, la relación
            #    apunta a una fila que no existe y queda huérfana.
            for columna in ("source_concept", "target_concept"):
                for fila in c.execute(
                        f"SELECT DISTINCT {columna} AS v FROM relations;").fetchall():
                    norm = norm_de_id(fila["v"])
                    if norm:
                        uf.buscar(norm)

            # c) Nombres idénticos tras normalizar ya quedan unidos por construcción
            #    (comparten `norm`), así que el grafo está completo.
            #    Los puentes conocidos NO se siembran como conceptos: solo aportan
            #    dominios a los que sí existen (paso f). Sembrarlos crearía conceptos
            #    vacíos marcados como puente sin una sola afirmación detrás.
            grupos = uf.grupos()

            # d) Mapa norm -> concept_id definitivo
            mapa: Dict[str, str] = {}
            conceptos: Dict[str, Dict[str, Any]] = {}
            for raiz, miembros in grupos.items():
                canonico = self._nombre_canonico(miembros, superficies)
                # El id sale del nombre canónico, no de la raíz interna del
                # Union-Find: "c:regularizacion l2" se lee en la base y en los
                # registros, "c:ridg" no. Sigue siendo único porque la forma
                # normalizada del canónico es siempre un miembro del grupo.
                cid = "c:" + (normalizar_nombre(canonico) or raiz)
                for m in miembros:
                    mapa[m] = cid
                conceptos[cid] = {"norm": raiz, "canonical_name": canonico,
                                  "miembros": miembros}

            # e) Reapuntar todo lo provisional
            c.execute("DELETE FROM concepts;")
            reapuntadas = 0
            for fila in c.execute("SELECT claim_id, concept_id FROM claims;").fetchall():
                viejo = fila["concept_id"] or ""
                nuevo = mapa.get(norm_de_id(viejo))
                if nuevo and nuevo != viejo:
                    c.execute("UPDATE claims SET concept_id = ? WHERE claim_id = ?;",
                              (nuevo, fila["claim_id"]))
                    reapuntadas += 1

            for fila in c.execute("SELECT DISTINCT concept_id FROM aliases;").fetchall():
                viejo = fila["concept_id"] or ""
                nuevo = mapa.get(norm_de_id(viejo))
                if nuevo and nuevo != viejo:
                    # OR REPLACE porque dos alias de libros distintos pueden colisionar
                    c.execute("""UPDATE OR REPLACE aliases SET concept_id = ?
                                 WHERE concept_id = ?;""", (nuevo, viejo))

            for columna in ("source_concept", "target_concept"):
                for fila in c.execute(
                        f"SELECT DISTINCT {columna} AS v FROM relations;").fetchall():
                    viejo = fila["v"] or ""
                    nuevo = mapa.get(norm_de_id(viejo))
                    if nuevo and nuevo != viejo:
                        c.execute(f"UPDATE relations SET {columna} = ? WHERE {columna} = ?;",
                                  (nuevo, viejo))

            # f) Estadísticas por concepto: en qué campos vive y cuánto pesa
            puentes_norm = {normalizar_nombre(n): d for n, d in KNOWN_BRIDGES.items()}
            n_puentes = 0
            for cid, info in conceptos.items():
                filas = c.execute("""SELECT domain, source_id FROM claims
                                     WHERE concept_id = ?;""", (cid,)).fetchall()
                dominios = sorted({f["domain"] for f in filas if f["domain"]})
                libros = len({f["source_id"] for f in filas})
                # El puente lo demuestran las afirmaciones, no la lista sembrada:
                # un concepto solo es puente si libros de campos distintos hablan
                # de él. La lista conocida solo añade campos a conceptos que ya
                # tienen contenido, para que el tutor sepa dónde más buscarlo.
                es_puente = 1 if len(dominios) >= 2 else 0
                sembrado = puentes_norm.get(info["norm"])
                if sembrado and filas:
                    dominios = sorted(set(dominios) | set(sembrado))
                n_puentes += es_puente
                c.execute("""INSERT OR REPLACE INTO concepts
                    (concept_id, canonical_name, norm, domains, is_bridge, mentions, books)
                    VALUES (?,?,?,?,?,?,?);""",
                    (cid, info["canonical_name"], info["norm"], json.dumps(dominios),
                     es_puente, len(filas), libros))

            # g) Marcar las relaciones que cruzan campos: son las que permiten
            #    explicar un tema apoyándose en otro que el alumno ya domina.
            cruzadas = 0
            dom_por_cid = {r["concept_id"]: json.loads(r["domains"] or "[]")
                           for r in c.execute("SELECT concept_id, domains FROM concepts;")}
            for fila in c.execute("""SELECT rowid, source_concept, target_concept
                                     FROM relations;""").fetchall():
                ds = set(dom_por_cid.get(fila["source_concept"], []))
                dt = set(dom_por_cid.get(fila["target_concept"], []))
                if ds and dt and not (ds & dt):
                    c.execute("UPDATE relations SET cross_domain = 1 WHERE rowid = ?;",
                              (fila["rowid"],))
                    cruzadas += 1

            # h) Los símbolos se enganchan a su concepto por el significado
            enganchados = 0
            for fila in c.execute("""SELECT rowid, meaning FROM symbols
                                     WHERE concept_id IS NULL;""").fetchall():
                cid = mapa.get(normalizar_nombre(fila["meaning"] or ""))
                if cid:
                    c.execute("UPDATE symbols SET concept_id = ? WHERE rowid = ?;",
                              (cid, fila["rowid"]))
                    enganchados += 1

            c.execute("INSERT OR REPLACE INTO meta VALUES ('unified_at', ?);",
                      (datetime.now().isoformat(),))
            c.commit()

        fusionados = sum(1 for g in grupos.values() if len(g) > 1)
        return {"conceptos": len(conceptos), "fusionados": fusionados,
                "afirmaciones_reapuntadas": reapuntadas, "puentes": n_puentes,
                "relaciones_cruzadas": cruzadas, "simbolos_enganchados": enganchados}

    @staticmethod
    def _nombre_canonico(miembros: List[str],
                         superficies: Dict[str, Dict[str, List[int]]]) -> str:
        """ El nombre que se le enseña al alumno.

        Manda cómo TITULAN el concepto los libros, no cómo lo mencionan de pasada:
        "ridge" y "weight decay" son alias de "regularización L2", y elegir el más
        corto haría que el tutor llamase al concepto por su apodo.
        """
        conteo: Dict[str, List[int]] = {}
        for m in miembros:
            for texto, (principal, alias) in superficies.get(m, {}).items():
                acumulado = conteo.setdefault(texto, [0, 0])
                acumulado[0] += principal
                acumulado[1] += alias
        if not conteo:
            return miembros[0]
        # 1) el que más libros usan como nombre principal
        # 2) a igualdad, el más mencionado en total
        # 3) a igualdad, el más corto: suele ser el término y no la frase entera
        return sorted(conteo.items(),
                      key=lambda kv: (-kv[1][0], -(kv[1][0] + kv[1][1]), len(kv[0])))[0][0]

    # ==================================================================
    # 3 · Dosieres: todo lo que se sabe de un concepto, ya reunido
    # ==================================================================

    def construir_dosieres(self, minimo_afirmaciones: int = 1) -> Dict[str, Any]:
        """ Precomputa por concepto lo que el tutor necesitaría buscar en 6 consultas.

        Se hace una vez al importar en lugar de en cada pregunta del alumno: cuando
        el modelo pide "explícame gradiente", el dosier ya trae la definición, la
        intuición, la fórmula, el código, los prerrequisitos y los puentes a otros
        campos, y solo queda razonar.
        """
        # Orden de preferencia al recortar: primero lo que explica, luego lo que formaliza
        PRIORIDAD = ["DEFINITION", "INTUITION", "THEOREM", "FORMULA", "PROPERTY",
                     "ALGORITHM", "CODE_PATTERN", "EXAMPLE", "PITFALL"]
        construidos = 0
        with self.kb.conectar() as c:
            # Un concepto puede cambiar de id al reunificarse (otro libro aporta un
            # nombre mejor). Sin esta limpieza el dosier viejo sobrevive y el tutor
            # acabaría citando un concepto que ya no existe.
            huerfanos = c.execute("""DELETE FROM dossiers WHERE concept_id NOT IN
                                     (SELECT concept_id FROM concepts);""").rowcount
            conceptos = c.execute("""SELECT * FROM concepts
                                     WHERE mentions >= ? ORDER BY mentions DESC;""",
                                  (minimo_afirmaciones,)).fetchall()
            titulos = {r["source_id"]: r["title"]
                       for r in c.execute("SELECT source_id, title FROM books;")}

            for con in conceptos:
                cid = con["concept_id"]
                afirmaciones = c.execute(
                    """SELECT type, text, quote, page, source_id, domain,
                              code_language, latex, confidence
                       FROM claims WHERE concept_id = ?
                       ORDER BY confidence DESC;""", (cid,)).fetchall()

                por_tipo: Dict[str, List[dict]] = {}
                for a in afirmaciones:
                    por_tipo.setdefault(a["type"] or "DEFINITION", []).append({
                        "text": a["text"], "quote": a["quote"], "page": a["page"],
                        "book": titulos.get(a["source_id"], a["source_id"]),
                        "source_id": a["source_id"], "domain": a["domain"],
                        "code_language": a["code_language"], "latex": a["latex"],
                    })

                prerrequisitos = [dict(r) for r in c.execute(
                    """SELECT co.canonical_name AS nombre, co.concept_id, r.type,
                              r.cross_domain
                       FROM relations r JOIN concepts co ON co.concept_id = r.target_concept
                       WHERE r.source_concept = ? AND r.type IN ('REQUIRES','GENERALIZES')
                       LIMIT 12;""", (cid,))]
                relacionados = [dict(r) for r in c.execute(
                    """SELECT co.canonical_name AS nombre, co.concept_id, r.type,
                              r.cross_domain
                       FROM relations r JOIN concepts co ON co.concept_id = r.target_concept
                       WHERE r.source_concept = ? AND r.type NOT IN ('REQUIRES','GENERALIZES')
                       LIMIT 12;""", (cid,))]
                simbolos = [dict(r) for r in c.execute(
                    "SELECT symbol, meaning, domain FROM symbols WHERE concept_id = ? LIMIT 8;",
                    (cid,))]
                # Dos libros pueden escribir el mismo nombre con y sin tilde; para
                # el alumno son el mismo alias, así que se queda la grafía más
                # cuidada (la que conserva mayúsculas y acentos) y no ambas.
                mejores: Dict[str, str] = {}
                for r in c.execute("""SELECT surface FROM aliases
                                      WHERE concept_id = ? AND surface IS NOT NULL;""", (cid,)):
                    clave = normalizar_nombre(r["surface"])
                    previo = mejores.get(clave)
                    if previo is None or _mas_cuidada(r["surface"], previo):
                        mejores[clave] = r["surface"]
                canonico_norm = normalizar_nombre(con["canonical_name"])
                alias = [v for k, v in mejores.items() if k != canonico_norm][:12]

                dominios = json.loads(con["domains"] or "[]")
                dosier = {
                    "concept_id": cid,
                    "nombre": con["canonical_name"],
                    "alias": alias,
                    "dominios": dominios,
                    "es_puente": bool(con["is_bridge"]),
                    "libros": con["books"],
                    "menciones": con["mentions"],
                    "por_tipo": {t: por_tipo[t] for t in PRIORIDAD if t in por_tipo},
                    "prerrequisitos": prerrequisitos,
                    "relacionados": relacionados,
                    "simbolos": simbolos,
                    # Cómo explicarlo apoyándose en otro campo: la carta bajo la manga
                    "analogias": self._analogias(dominios, por_tipo),
                }
                c.execute("INSERT OR REPLACE INTO dossiers VALUES (?,?,?);",
                          (cid, json.dumps(dosier, ensure_ascii=False),
                           datetime.now().isoformat()))
                construidos += 1
            c.commit()
        return {"dosieres": construidos, "obsoletos_borrados": max(0, huerfanos)}

    @staticmethod
    def _analogias(dominios: List[str], por_tipo: Dict[str, List[dict]]) -> List[dict]:
        """ Si el concepto vive en varios campos, cada campo es una forma de contarlo """
        if len(dominios) < 2:
            return []
        salida = []
        for d in dominios:
            for tipo in ("INTUITION", "DEFINITION", "EXAMPLE"):
                cands = [a for a in por_tipo.get(tipo, []) if a.get("domain") == d]
                if cands:
                    salida.append({"dominio": d, "tipo": tipo,
                                   "texto": cands[0]["text"], "libro": cands[0]["book"]})
                    break
        return salida

    # ==================================================================
    # 4 · Verificación: ¿quedó bien guardado cada libro?
    # ==================================================================

    def verificar_integridad(self) -> Dict[str, Any]:
        """ Informe libro a libro: lo que dice el manifiesto contra lo que hay en la base.

        Es la comprobación que importa tras una corrida de cien libros — un libro que
        entró a medias no da error, simplemente contesta menos, y eso no se nota hasta
        que el alumno pregunta algo que sí estaba en el PDF.
        """
        libros, problemas = [], []
        with self.kb.conectar() as c:
            for b in c.execute("SELECT * FROM books ORDER BY title;").fetchall():
                sid = b["source_id"]
                n_claims = c.execute("SELECT COUNT(*) FROM claims WHERE source_id = ?;",
                                     (sid,)).fetchone()[0]
                n_fts = c.execute("""SELECT COUNT(*) FROM claims_fts f
                                     JOIN claims c2 ON c2.claim_id = f.claim_id
                                     WHERE c2.source_id = ?;""", (sid,)).fetchone()[0]
                sin_concepto = c.execute("""SELECT COUNT(*) FROM claims
                    WHERE source_id = ? AND (concept_id IS NULL
                          OR concept_id LIKE 'tmp:%');""", (sid,)).fetchone()[0]
                sin_cita = c.execute("""SELECT COUNT(*) FROM claims
                    WHERE source_id = ? AND (quote IS NULL OR quote = '');""",
                    (sid,)).fetchone()[0]
                n_conceptos = c.execute("""SELECT COUNT(DISTINCT concept_id) FROM claims
                                           WHERE source_id = ?;""", (sid,)).fetchone()[0]
                n_rel = c.execute("SELECT COUNT(*) FROM relations WHERE source_id = ?;",
                                  (sid,)).fetchone()[0]
                huerfanas = c.execute("""SELECT COUNT(*) FROM relations r
                    WHERE r.source_id = ? AND (
                        NOT EXISTS (SELECT 1 FROM concepts WHERE concept_id = r.source_concept)
                     OR NOT EXISTS (SELECT 1 FROM concepts WHERE concept_id = r.target_concept));""",
                    (sid,)).fetchone()[0]
                n_sym = c.execute("SELECT COUNT(*) FROM symbols WHERE source_id = ?;",
                                  (sid,)).fetchone()[0]

                fallos = []
                if n_claims == 0:
                    fallos.append("sin afirmaciones")
                if n_fts != n_claims:
                    fallos.append(f"índice de texto descuadrado ({n_fts}/{n_claims})")
                if b["claims_verified"] and n_claims != b["claims_verified"]:
                    fallos.append(f"faltan {b['claims_verified'] - n_claims} afirmaciones")
                if sin_concepto:
                    fallos.append(f"{sin_concepto} sin concepto canónico (falta unificar)")
                if sin_cita:
                    fallos.append(f"{sin_cita} sin cita textual")
                if huerfanas:
                    fallos.append(f"{huerfanas} relaciones huérfanas")
                if b["domain"] not in DOMAINS:
                    fallos.append(f"dominio inválido: {b['domain']}")

                libros.append({
                    "source_id": sid, "titulo": b["title"], "dominio": b["domain"],
                    "paginas": b["pages"], "modelo": b["model_used"],
                    "afirmaciones": n_claims, "conceptos": n_conceptos,
                    "relaciones": n_rel, "simbolos": n_sym,
                    "importado": b["imported_at"],
                    "ok": not fallos, "fallos": fallos,
                })
                if fallos:
                    problemas.append({"titulo": b["title"], "fallos": fallos})

            total_claims = c.execute("SELECT COUNT(*) FROM claims;").fetchone()[0]
            total_fts = c.execute("SELECT COUNT(*) FROM claims_fts;").fetchone()[0]
            huerfanas_fts = c.execute("""SELECT COUNT(*) FROM claims_fts f
                WHERE NOT EXISTS (SELECT 1 FROM claims c2 WHERE c2.claim_id = f.claim_id);"""
                ).fetchone()[0]
            unificado = c.execute("SELECT valor FROM meta WHERE clave='unified_at';").fetchone()

        if not libros:
            # Una base vacía no tiene nada malo: está esperando su primer paquete.
            return {"libros": [], "total_libros": 0, "libros_ok": 0, "problemas": [],
                    "problemas_globales": [], "integro": True, "vacia": True,
                    "unificado_en": unificado[0] if unificado else None}

        globales = []
        if huerfanas_fts:
            globales.append(f"{huerfanas_fts} entradas de texto sin afirmación (basura de "
                            f"una reimportación)")
        if total_fts != total_claims:
            globales.append(f"índice global descuadrado: {total_fts} vs {total_claims}")
        if not unificado:
            globales.append("los conceptos nunca se han unificado")

        return {
            "libros": libros,
            "total_libros": len(libros),
            "libros_ok": sum(1 for l in libros if l["ok"]),
            "problemas": problemas,
            "problemas_globales": globales,
            "integro": not problemas and not globales,
            "unificado_en": unificado[0] if unificado else None,
        }

    # ==================================================================
    # Todo de una vez
    # ==================================================================

    def procesar(self, carpeta: str) -> Dict[str, Any]:
        """ Importar carpeta → unificar → dosieres → verificar """
        imp = self.importar_carpeta(carpeta)
        uni = self.unificar()
        dos = self.construir_dosieres()
        ver = self.verificar_integridad()
        return {"importacion": imp, "unificacion": uni, "dosieres": dos,
                "verificacion": ver}


def _grafia(texto: str) -> Tuple[int, int]:
    """ Cuánto cuida un texto la ortografía: tildes y mayúsculas que conserva.

    Entre "Regularización L2" y "regularizacion l2" se muestra la primera; son el
    mismo alias y enseñar las dos solo ensucia la ficha del concepto.
    """
    acentos = sum(1 for c in unicodedata.normalize("NFD", texto)
                  if unicodedata.category(c) == "Mn")
    return acentos, sum(1 for c in texto if c.isupper())


def _mas_cuidada(nueva: str, actual: str) -> bool:
    return _grafia(nueva) > _grafia(actual)


def informe_texto(ver: Dict[str, Any]) -> str:
    """ El mismo informe, legible en consola """
    if ver.get("vacia"):
        return ("BASE DE CONOCIMIENTO vacía.\n"
                "Deja los .prigpack en ~/.prig_books/packs e impórtalos desde Biblioteca.")
    lineas = [f"BASE DE CONOCIMIENTO — {ver['libros_ok']}/{ver['total_libros']} libros correctos"]
    if ver["unificado_en"]:
        lineas.append(f"Conceptos unificados: {ver['unificado_en'][:19]}")
    lineas.append("")
    for l in ver["libros"]:
        marca = "OK  " if l["ok"] else "FALLA"
        lineas.append(f"{marca} {(l['titulo'] or '')[:44]:<44} [{l['dominio']}]")
        lineas.append(f"      {l['afirmaciones']:>5} afirmaciones · {l['conceptos']:>4} conceptos"
                      f" · {l['relaciones']:>4} relaciones · {l['simbolos']:>3} símbolos")
        for f in l["fallos"]:
            lineas.append(f"      ! {f}")
    if ver["problemas_globales"]:
        lineas.append("\nProblemas generales:")
        lineas += [f"  ! {p}" for p in ver["problemas_globales"]]
    return "\n".join(lineas)
