"""
Pruebas del importador de paquetes de conocimiento.

Lo que se protege aquí son las tres cosas que ya fallaron una vez:

  · reimportar un libro duplicaba conceptos, porque los identificadores ya
    canónicos (`c:…`) se leían como si fuesen nombres nuevos;
  · reimportar BORRABA la atribución de otros libros, porque la clave de `aliases`
    no incluía el libro;
  · un alias corto ("ridge") desbancaba al nombre real del concepto.

Ninguna de las tres daba error: la base seguía respondiendo, solo que peor.
"""

import os
import sys
import json
import zipfile
import hashlib
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knowledge_base import KnowledgeBase, normalizar_nombre
from pack_importer import PackImporter, PackImportError, norm_de_id


def sha(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def hacer_pack(carpeta, source_id, title, domain, claims, concepts,
               relations=(), symbols=(), romper_checksum=False):
    cl = [{"claim_id": f"clm_{sha(q)[:12]}", "type": t, "concepts": [co], "text": tx,
           "quote": q, "page": p, "confidence": 0.8, "code_language": "none",
           "latex": "", "bridges_to": []} for t, co, tx, q, p in claims]
    co = [{"concept_id": f"conc_{sha(n)[:12]}", "name": n, "aliases": list(a),
           "pages": [], "defined_in_pages": [], "also_known_in": [], "mentions": 1}
          for n, a in concepts]
    rel = [{"source": s, "target": t, "type": ty, "quote": q, "page": 1}
           for s, t, ty, q in relations]
    sym = [{"symbol": s, "meaning": m, "page": p} for s, m, p in symbols]
    man = {"schema_version": "3.1", "source_id": source_id, "title": title,
           "domain": domain, "book_sha256": sha(title), "pages": 100,
           "model_used": "prueba", "claims_verified": len(cl), "concepts": len(co)}
    cont = {"manifest.json": json.dumps(man),
            "claims.jsonl": "\n".join(json.dumps(x) for x in cl),
            "concepts.jsonl": "\n".join(json.dumps(x) for x in co),
            "relations.jsonl": "\n".join(json.dumps(x) for x in rel),
            "symbols.jsonl": "\n".join(json.dumps(x) for x in sym)}
    checks = {k: sha(v) for k, v in cont.items()}
    if romper_checksum:
        checks["claims.jsonl"] = sha("otra cosa")
    cont["checksums.json"] = json.dumps(checks)
    ruta = os.path.join(carpeta, f"{source_id}.prigpack")
    with zipfile.ZipFile(ruta, "w") as z:
        for k, v in cont.items():
            z.writestr(k, v)
    return ruta


class PruebaImportador(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.packs = os.path.join(self.tmp, "packs")
        os.makedirs(self.packs)
        self.kb = KnowledgeBase(os.path.join(self.tmp, "k.db"))
        self.imp = PackImporter(self.kb)

        hacer_pack(self.packs, "bk_math", "Calculo", "math",
                   claims=[("DEFINITION", "gradiente",
                            "Vector de derivadas parciales.",
                            "el vector de las derivadas parciales", 10),
                           ("DEFINITION", "regla de la cadena",
                            "Derivada de una composicion.", "(f o g)' = f'(g) g'", 20)],
                   concepts=[("gradiente", ["grad", "vector gradiente"]),
                             ("regla de la cadena", ["chain rule"])],
                   relations=[("gradiente", "derivada parcial", "REQUIRES", "se construye con ellas")],
                   symbols=[("nabla", "gradiente", 10)])
        hacer_pack(self.packs, "bk_dl", "Deep Learning", "deep_learning",
                   claims=[("INTUITION", "gradiente",
                            "Cuanto cambia la perdida al mover un peso.",
                            "gradiente de la perdida", 80),
                           ("DEFINITION", "regularizacion L2",
                            "Penaliza la norma de los pesos.", "norma L2 de los pesos", 90)],
                   concepts=[("gradiente", ["gradientes"]),
                             ("regularizacion L2", ["weight decay"])])
        hacer_pack(self.packs, "bk_ml", "Bishop", "machine_learning",
                   claims=[("DEFINITION", "regularizacion L2",
                            "Se conoce como ridge.", "known as ridge regression", 5)],
                   concepts=[("regularizacion L2", ["ridge", "ridge regression"])])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _conteos(self):
        with self.kb.conectar() as c:
            return {t: c.execute(f"SELECT COUNT(*) FROM {t};").fetchone()[0]
                    for t in ("books", "claims", "claims_fts", "relations",
                              "symbols", "aliases", "concepts", "dossiers")}

    # -- prefijos -----------------------------------------------------

    def test_norm_de_id_quita_ambos_prefijos(self):
        self.assertEqual(norm_de_id("tmp:gradient"), "gradient")
        self.assertEqual(norm_de_id("c:gradient"), "gradient")
        self.assertEqual(norm_de_id("gradient"), "gradient")

    # -- importación --------------------------------------------------

    def test_importa_los_tres_libros(self):
        r = self.imp.importar_carpeta(self.packs)
        self.assertEqual(len(r["importados"]), 3)
        self.assertEqual(r["fallidos"], [])
        self.assertEqual(self._conteos()["claims"], 5)

    def test_rechaza_paquete_corrupto(self):
        ruta = hacer_pack(self.packs, "bk_malo", "Roto", "math",
                          claims=[("DEFINITION", "x", "t", "q", 1)],
                          concepts=[("x", [])], romper_checksum=True)
        v = self.imp.verificar(ruta)
        self.assertFalse(v["ok"])
        self.assertTrue(any("checksum" in p for p in v["problemas"]))
        with self.assertRaises(PackImportError):
            self.imp.importar(ruta)

    def test_forzar_importa_pese_a_los_avisos(self):
        ruta = hacer_pack(self.packs, "bk_malo", "Roto", "math",
                          claims=[("DEFINITION", "x", "t", "q", 1)],
                          concepts=[("x", [])], romper_checksum=True)
        r = self.imp.importar(ruta, forzar=True)
        self.assertTrue(r["avisos"])
        self.assertEqual(r["claims"], 1)

    # -- unificación --------------------------------------------------

    def test_une_alias_entre_libros(self):
        self.imp.procesar(self.packs)
        for nombre in ("weight decay", "ridge", "regularizacion L2", "Regularización L2"):
            con = self.kb.resolver(nombre)
            self.assertIsNotNone(con, f"no resuelve '{nombre}'")
            self.assertEqual(con["concept_id"], "c:regularizacion l2",
                             f"'{nombre}' cae en otro concepto")

    def test_el_nombre_canonico_no_es_el_alias_corto(self):
        self.imp.procesar(self.packs)
        self.assertEqual(self.kb.resolver("ridge")["canonical_name"], "regularizacion L2")
        self.assertEqual(self.kb.resolver("grad")["canonical_name"], "gradiente")

    def test_marca_puentes_solo_con_evidencia(self):
        self.imp.procesar(self.packs)
        gradiente = self.kb.resolver("gradiente")
        self.assertTrue(gradiente["is_bridge"])
        self.assertEqual(sorted(gradiente["domains"]), ["deep_learning", "math"])
        # un concepto de un solo campo no es puente
        self.assertFalse(self.kb.resolver("regla de la cadena")["is_bridge"])

    def test_no_crea_conceptos_sin_afirmaciones_como_puente(self):
        self.imp.procesar(self.packs)
        with self.kb.conectar() as c:
            vacios = c.execute("""SELECT canonical_name FROM concepts
                                  WHERE is_bridge = 1 AND mentions = 0;""").fetchall()
        self.assertEqual([r[0] for r in vacios], [])

    def test_los_extremos_de_relacion_existen_como_concepto(self):
        self.imp.procesar(self.packs)
        v = self.imp.verificar_integridad()
        self.assertTrue(v["integro"], v["problemas"])

    # -- idempotencia -------------------------------------------------

    def test_reimportar_no_cambia_nada(self):
        self.imp.procesar(self.packs)
        base = self._conteos()
        for _ in range(3):
            self.imp.procesar(self.packs)
            self.assertEqual(self._conteos(), base)

    def test_reimportar_no_borra_los_alias_de_otros_libros(self):
        self.imp.procesar(self.packs)
        def atribuciones():
            with self.kb.conectar() as c:
                return sorted((r["source_id"], r["surface"]) for r in c.execute(
                    "SELECT source_id, surface FROM aliases WHERE concept_id='c:gradient';"))
        antes = atribuciones()
        self.assertIn(("bk_math", "gradiente"), antes)
        self.assertIn(("bk_dl", "gradiente"), antes)
        self.imp.importar(os.path.join(self.packs, "bk_dl.prigpack"))
        self.imp.unificar()
        self.assertEqual(atribuciones(), antes)

    def test_el_indice_de_texto_no_acumula_basura(self):
        self.imp.procesar(self.packs)
        for _ in range(3):
            self.imp.importar(os.path.join(self.packs, "bk_dl.prigpack"))
        with self.kb.conectar() as c:
            huerfanas = c.execute("""SELECT COUNT(*) FROM claims_fts f WHERE NOT EXISTS
                (SELECT 1 FROM claims c2 WHERE c2.claim_id = f.claim_id);""").fetchone()[0]
            total_fts = c.execute("SELECT COUNT(*) FROM claims_fts;").fetchone()[0]
            total = c.execute("SELECT COUNT(*) FROM claims;").fetchone()[0]
        self.assertEqual(huerfanas, 0)
        self.assertEqual(total_fts, total)

    # -- verificación por libro ---------------------------------------

    def test_informe_por_libro_completo(self):
        self.imp.procesar(self.packs)
        v = self.imp.verificar_integridad()
        self.assertEqual(v["total_libros"], 3)
        self.assertEqual(v["libros_ok"], 3)
        por_titulo = {l["titulo"]: l for l in v["libros"]}
        self.assertEqual(por_titulo["Calculo"]["afirmaciones"], 2)
        self.assertEqual(por_titulo["Bishop"]["afirmaciones"], 1)
        self.assertEqual(por_titulo["Calculo"]["dominio"], "math")

    def test_detecta_libro_incompleto(self):
        self.imp.procesar(self.packs)
        with self.kb.conectar() as c:   # simular una afirmación perdida
            c.execute("DELETE FROM claims WHERE source_id='bk_ml';")
            c.commit()
        v = self.imp.verificar_integridad()
        self.assertFalse(v["integro"])
        fallos = " ".join(next(l for l in v["libros"] if l["titulo"] == "Bishop")["fallos"])
        self.assertIn("sin afirmaciones", fallos)

    # -- dosieres -----------------------------------------------------

    def test_el_dosier_reune_varios_libros(self):
        self.imp.procesar(self.packs)
        with self.kb.conectar() as c:
            d = json.loads(c.execute(
                "SELECT json FROM dossiers WHERE concept_id='c:regularizacion l2';"
            ).fetchone()[0])
        self.assertEqual(d["libros"], 2)
        self.assertTrue(d["es_puente"])
        libros = {a["book"] for items in d["por_tipo"].values() for a in items}
        self.assertEqual(libros, {"Deep Learning", "Bishop"})
        self.assertTrue(d["analogias"], "un concepto puente debe traer analogía entre campos")

    def test_borra_los_dosieres_obsoletos(self):
        self.imp.procesar(self.packs)
        with self.kb.conectar() as c:
            c.execute("INSERT OR REPLACE INTO dossiers VALUES ('c:inventado','{}','');")
            c.commit()
        r = self.imp.construir_dosieres()
        self.assertEqual(r["obsoletos_borrados"], 1)
        with self.kb.conectar() as c:
            self.assertIsNone(c.execute(
                "SELECT 1 FROM dossiers WHERE concept_id='c:inventado';").fetchone())


if __name__ == "__main__":
    unittest.main(verbosity=2)
