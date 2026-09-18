"""
Pruebas de la cadena que va a la GPU externa.

Protegen los fallos que se descubrieron al simular una corrida de Kaggle completa,
todos de la misma familia: **no daban error, daban menos conocimiento**.

  · un reparto entre dos GPU empaquetaba medio libro en un .prigpack que parecía
    correcto, porque declaraba exactamente las afirmaciones que contenía;
  · las palabras clave de dominio eran solo en español, así que "Deep Learning.pdf"
    puntuaba cero en todo y caía en el dominio por defecto;
  · "~/.prig_books/x.pdf" se convertía en una carpeta relativa inexistente y el
    libro se omitía con un aviso;
  · el mismo libro en dos carpetas se procesaba dos veces, al doble de coste.
"""

import os
import sys
import json
import zipfile
import tempfile
import shutil
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(os.path.dirname(RAIZ), "kaggle_worker"))

from domains import (DOMAINS, sugerir_dominio, sugerir_dominio_con_confianza,
                     KNOWN_BRIDGES)
from knowledge_base import KnowledgeBase
from pack_importer import PackImporter, PackImportError


class PruebaClasificadorDeDominio(unittest.TestCase):
    """ El dominio decide con qué otros libros se cruza cada concepto: si se falla,
    los puentes entre campos se construyen mal y el diseño entero deja de servir. """

    TITULOS_REALES = [
        ("Goodfellow_Deep_Learning.pdf", "deep_learning"),
        ("Bishop - Pattern Recognition and Machine Learning.pdf", "machine_learning"),
        ("Apostol_Calculus_Vol1.pdf", "math"),
        ("Effective_Modern_Cpp_Meyers.pdf", "cpp"),
        ("Fluent_Python_2nd_Edition.pdf", "python"),
        ("Griffiths_Introduction_to_Quantum_Mechanics.pdf", "physics"),
        ("Strang_Linear_Algebra.pdf", "math"),
        ("Hands_On_Machine_Learning_Geron.pdf", "machine_learning"),
        ("Dive_into_Deep_Learning.pdf", "deep_learning"),
        ("Elements_of_Statistical_Learning.pdf", "machine_learning"),
        ("Fundamentos_Redes_Neuronales.md", "deep_learning"),
        ("Calculo_Vectorial_Apostol.pdf", "math"),
        ("Guia_Fundamentos_Deep_Learning.md", "deep_learning"),
        ("Sedgewick_Algorithms_in_Cpp.pdf", "cpp"),
        ("Thermodynamics_and_Statistical_Mechanics.pdf", "physics"),
        ("Convex_Optimization_Boyd.pdf", "math"),
    ]

    def test_clasifica_titulos_reales(self):
        fallos = [(n, sugerir_dominio("", n), e)
                  for n, e in self.TITULOS_REALES if sugerir_dominio("", n) != e]
        self.assertEqual(fallos, [], f"{len(fallos)} títulos mal clasificados")

    def test_los_titulos_en_ingles_puntuan(self):
        """ Con listas solo en español todos daban cero y caían en el valor por
        defecto, que parece una clasificación y es un encogimiento de hombros. """
        for nombre in ("Deep Learning.pdf", "Machine Learning.pdf", "Calculus.pdf",
                       "Modern C++.pdf", "Python Cookbook.pdf", "Quantum Physics.pdf"):
            r = sugerir_dominio_con_confianza("", nombre)
            self.assertGreater(r["puntos"], 0, f"'{nombre}' no puntúa en ningún campo")

    def test_avisa_cuando_no_sabe(self):
        r = sugerir_dominio_con_confianza("", "apuntes_varios_2019.pdf")
        self.assertFalse(r["seguro"])
        self.assertTrue(r["motivo"])

    def test_todo_dominio_conocido_existe(self):
        for nombre, dominios in KNOWN_BRIDGES.items():
            for d in dominios:
                self.assertIn(d, DOMAINS, f"'{nombre}' apunta a un campo inexistente")


def escribir_pack(carpeta, source_id, titulo, dominio, n_claims,
                  procesados, esperados, completo=None):
    import hashlib
    sha = lambda t: hashlib.sha256(t.encode()).hexdigest()
    claims = [{"claim_id": f"c{i}", "type": "DEFINITION", "concepts": ["x"],
               "text": f"t{i}", "quote": f"cita numero {i}", "page": i,
               "confidence": 0.8} for i in range(n_claims)]
    cont = {
        "manifest.json": json.dumps({
            "schema_version": "3.1", "source_id": source_id, "title": titulo,
            "domain": dominio, "claims_verified": n_claims,
            "chunks_processed": procesados, "chunks_expected": esperados,
            "complete": (procesados >= esperados) if completo is None else completo,
            "chunks_failed": 0}),
        "claims.jsonl": "\n".join(json.dumps(c) for c in claims),
        "concepts.jsonl": json.dumps({"name": "x", "aliases": []}),
        "relations.jsonl": "", "symbols.jsonl": "",
    }
    cont["checksums.json"] = json.dumps({k: sha(v) for k, v in cont.items()})
    ruta = os.path.join(carpeta, f"{source_id}.prigpack")
    with zipfile.ZipFile(ruta, "w") as z:
        for k, v in cont.items():
            z.writestr(k, v)
    return ruta


class PruebaPaqueteIncompleto(unittest.TestCase):
    """ El fallo más peligroso de toda la cadena: un libro a medias no se distingue
    de uno completo salvo por el recuento de fragmentos. """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.imp = PackImporter(KnowledgeBase(os.path.join(self.tmp, "k.db")))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rechaza_el_libro_a_medias(self):
        ruta = escribir_pack(self.tmp, "bk_medio", "Medio libro", "math",
                             n_claims=5, procesados=40, esperados=100)
        v = self.imp.verificar(ruta)
        self.assertFalse(v["ok"])
        self.assertTrue(any("incompleto" in p for p in v["problemas"]), v["problemas"])
        with self.assertRaises(PackImportError):
            self.imp.importar(ruta)

    def test_acepta_el_libro_entero(self):
        ruta = escribir_pack(self.tmp, "bk_entero", "Libro entero", "math",
                             n_claims=5, procesados=100, esperados=100)
        self.assertTrue(self.imp.verificar(ruta)["ok"])
        self.assertEqual(self.imp.importar(ruta)["claims"], 5)

    def test_confia_en_la_marca_complete_aunque_cuadren_los_numeros(self):
        """ Si el extractor dice que no está completo, se le cree. """
        ruta = escribir_pack(self.tmp, "bk_raro", "Raro", "math",
                             n_claims=5, procesados=100, esperados=100, completo=False)
        self.assertFalse(self.imp.verificar(ruta)["ok"])

    def test_paquete_antiguo_sin_los_campos_nuevos_sigue_valiendo(self):
        """ Los paquetes de una versión anterior no traen chunks_expected; no se
        puede saber si están completos, pero rechazarlos sería peor. """
        import hashlib
        sha = lambda t: hashlib.sha256(t.encode()).hexdigest()
        cont = {"manifest.json": json.dumps({"schema_version": "3.0",
                                             "source_id": "bk_viejo", "title": "Viejo",
                                             "domain": "math", "claims_verified": 1}),
                "claims.jsonl": json.dumps({"claim_id": "c0", "type": "DEFINITION",
                                            "concepts": ["x"], "text": "t",
                                            "quote": "una cita cualquiera", "page": 1}),
                "concepts.jsonl": json.dumps({"name": "x", "aliases": []}),
                "relations.jsonl": "", "symbols.jsonl": ""}
        cont["checksums.json"] = json.dumps({k: sha(v) for k, v in cont.items()})
        ruta = os.path.join(self.tmp, "viejo.prigpack")
        with zipfile.ZipFile(ruta, "w") as z:
            for k, v in cont.items():
                z.writestr(k, v)
        self.assertTrue(self.imp.verificar(ruta)["ok"])


class PruebaPreparacionDelTrabajo(unittest.TestCase):

    def setUp(self):
        # Bajo el directorio del usuario a propósito: la prueba de la virgulilla
        # solo tiene sentido si la ruta se puede escribir como "~/…".
        base = os.path.join(os.path.expanduser("~"), ".prig_pruebas")
        os.makedirs(base, exist_ok=True)
        self.tmp = tempfile.mkdtemp(dir=base)
        from job_exporter import JobExporter
        self.ex = JobExporter(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _libro(self, nombre, texto="Contenido de prueba. " * 40, sub=""):
        carpeta = os.path.join(self.tmp, sub) if sub else self.tmp
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, nombre)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(texto)
        return ruta

    def test_expande_la_virgulilla(self):
        """ "~/x.pdf" pasaba por abspath sin expandir y quedaba como carpeta
        relativa inexistente: el libro se omitía con un aviso discreto. """
        ruta = self._libro("libro.md")
        casa = os.path.expanduser("~")
        con_virgulilla = "~" + ruta[len(casa):]
        self.assertTrue(con_virgulilla.startswith("~/"))
        m = self.ex.preparar([con_virgulilla], "~" + os.path.join(self.tmp, "job")[len(casa):])
        self.assertEqual(m["total_books"], 1,
                         "una ruta con ~ debe leerse igual que la absoluta")

    def test_no_procesa_dos_veces_el_mismo_libro(self):
        texto = "Un texto identico guardado en dos carpetas. " * 40
        a = self._libro("libro.md", texto)
        b = self._libro("libro.md", texto, sub="documentation")
        m = self.ex.preparar([a, b], os.path.join(self.tmp, "job"))
        self.assertEqual(m["total_books"], 1)
        self.assertEqual(len(m["duplicates_skipped"]), 1)

    def test_el_destino_tambien_admite_virgulilla(self):
        ruta = self._libro("libro.md")
        destino = os.path.join(self.tmp, "job_destino")
        m = self.ex.preparar([ruta], destino)
        self.assertTrue(os.path.isfile(os.path.join(destino, "chunks.jsonl")))
        self.assertTrue(os.path.isfile(os.path.join(destino, "manifest.json")))
        self.assertTrue(m["chunks_sha256"])

    def test_el_manifiesto_ata_la_entrada(self):
        """ chunks_sha256 permite saber si un paquete salió de estos fragmentos. """
        ruta = self._libro("libro.md")
        m1 = self.ex.preparar([ruta], os.path.join(self.tmp, "j1"))
        m2 = self.ex.preparar([ruta], os.path.join(self.tmp, "j2"))
        self.assertEqual(m1["chunks_sha256"], m2["chunks_sha256"],
                         "el troceado debe ser determinista")


if __name__ == "__main__":
    unittest.main(verbosity=2)
