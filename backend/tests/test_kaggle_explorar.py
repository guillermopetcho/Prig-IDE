"""
Explorar Kaggle: datasets, competiciones, descargas, vista previa y notebooks ejecutables.

Contra un servidor falso con las respuestas medidas de la API (tests/kaggle_falso.py).
Lo que se protege:

  · los datasets se exploran y descargan SIN cuenta; las competiciones la piden;
  · los campos repetidos de la API («title», «titleNullable», «hasTitle») se normalizan;
  · la descarga queda en kaggle_datos/<slug>/ (lo que Kaggle monta en /kaggle/input/<slug>/),
    un zip malicioso no escribe fuera, y una competición sin reglas aceptadas lo explica;
  · la vista previa resume cada columna (tipo, faltantes, rango, frecuentes) y no lee
    archivos fuera de los datos descargados;
  · al guardar un notebook en el proyecto, sus rutas de Kaggle apuntan a los datos locales;
  · el profesor recibe las cifras reales cuando los datos están descargados.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kaggle_explorar as ke  # noqa: E402
import kaggle_falso  # noqa: E402
import kaggle_lector as kl  # noqa: E402

URL, _SERVIDOR = kaggle_falso.arrancar()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, "ws")
        os.makedirs(self.ws)
        entorno = {"HOME": os.path.join(self.tmp, "home"), "PRIG_KAGGLE_DIR": os.path.join(self.tmp, "prig_kaggle"),
                   "PRIG_KAGGLE_CREDENCIALES": os.path.join(self.tmp, "cred.json"),
                   "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"), "KAGGLE_CONFIG_DIR": os.path.join(self.tmp, "nada")}
        self.entorno = mock.patch.dict(os.environ, entorno)
        self.entorno.start()
        for v in ("KAGGLE_API_TOKEN", "KAGGLE_USERNAME", "KAGGLE_KEY"):
            os.environ.pop(v, None)
        self.api = mock.patch.object(kl, "API", URL)
        self.api.start()
        ke._cache.clear()
        kl._cache.clear()
        kaggle_falso.Manejador.peticiones.clear()

    def tearDown(self):
        self.api.stop()
        self.entorno.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def con_cuenta(self):
        os.environ["KAGGLE_API_TOKEN"] = "KGAT_token_de_prueba_123456"


class TestReferencias(unittest.TestCase):
    def test_enlaces_de_datasets_y_competiciones(self):
        self.assertEqual(ke.ref_dataset("https://www.kaggle.com/datasets/yasserh/titanic-dataset/data"), "yasserh/titanic-dataset")
        self.assertEqual(ke.ref_dataset("yasserh/titanic-dataset"), "yasserh/titanic-dataset")
        self.assertEqual(ke.ref_competicion("https://www.kaggle.com/competitions/titanic/overview"), "titanic")
        self.assertEqual(ke.ref_competicion("https://www.kaggle.com/c/house-prices"), "house-prices")
        for malo in ("", "https://google.com/a/b", "../../etc"):
            with self.assertRaises(ke.ErrorKaggle):
                ke.ref_dataset(malo)
        with self.assertRaises(ke.ErrorKaggle):
            ke.ref_competicion("../x")


class TestDatasets(Base):
    def test_buscar_sin_cuenta_y_normalizado(self):
        r = ke.buscar_datasets("titanic", "votos", 1, "csv")
        p = kaggle_falso.Manejador.peticiones[0]
        self.assertFalse(p["auth"])
        self.assertEqual((p["params"]["sortBy"], p["params"]["filetype"], p["params"]["search"]), ("votes", "csv", "titanic"))
        d = r["datasets"][0]
        self.assertEqual((d["titulo"], d["usabilidad"], d["bytes"], d["etiquetas"]), ("Titanic Dataset", 10.0, 61194, ["tabular", "beginner"]))
        self.assertNotIn("titleNullable", d)

    def test_filtro_desconocido_no_se_manda(self):
        ke.buscar_datasets("x", "raro", 1, "exe")
        p = kaggle_falso.Manejador.peticiones[0]["params"]
        self.assertEqual(p["sortBy"], "hottest")
        self.assertNotIn("filetype", p)

    def test_ficha_con_archivos_y_sin_datos_locales(self):
        f = ke.dataset("https://www.kaggle.com/datasets/yasserh/titanic-dataset", self.ws)
        self.assertEqual(f["tipo"], "dataset")
        self.assertIn("Titanic", f["descripcion"])
        self.assertEqual([a["nombre"] for a in f["archivos"]], ["Titanic-Dataset.csv"])
        self.assertIsNone(f["local"])

    def test_descargar_sin_cuenta_y_registrar(self):
        eventos = []
        loc = ke.descargar("dataset", "yasserh/titanic-dataset", self.ws, eventos.append)
        self.assertEqual(loc["relativa"], os.path.join("kaggle_datos", "titanic-dataset"))
        self.assertEqual([a["relativa"] for a in loc["archivos"]], ["Titanic-Dataset.csv"])
        self.assertEqual(eventos[-1]["mensaje"], "Descomprimiendo…")
        self.assertFalse(any(n.endswith(".parcial") for n in os.listdir(os.path.join(self.ws, "kaggle_datos"))))
        self.assertIsNotNone(ke.dataset("yasserh/titanic-dataset", self.ws)["local"])
        mis = ke.mis_datos(self.ws)
        self.assertEqual((mis[0]["tipo"], mis[0]["ref"], len(mis[0]["archivos"])), ("dataset", "yasserh/titanic-dataset", 1))

    def test_zip_malicioso_no_escribe_fuera(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../../fuera.txt", "malo")
            z.writestr("bien.csv", "a\n1\n")
        ruta = os.path.join(self.tmp, "x.zip")
        with open(ruta, "wb") as f:
            f.write(buf.getvalue())
        destino = os.path.join(self.ws, "kaggle_datos", "x")
        ke._descomprimir(ruta, destino)
        self.assertTrue(os.path.exists(os.path.join(destino, "bien.csv")))
        self.assertFalse(os.path.exists(os.path.join(self.ws, "fuera.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "fuera.txt")))


class TestCompeticiones(Base):
    def test_piden_cuenta(self):
        with self.assertRaisesRegex(ke.ErrorKaggle, "cuenta"):
            ke.buscar_competiciones()
        with self.assertRaisesRegex(ke.ErrorKaggle, "cuenta"):
            ke.descargar("competicion", "titanic", self.ws)

    def test_buscar_y_ficha(self):
        self.con_cuenta()
        r = ke.buscar_competiciones("", "gettingStarted", "premio")
        p = kaggle_falso.Manejador.peticiones[0]["params"]
        self.assertEqual((p["category"], p["sortBy"]), ("gettingStarted", "prize"))
        c = r["competiciones"][0]
        self.assertEqual((c["ref"], c["abierta"], c["premio"]), ("titanic", True, "Knowledge"))
        f = ke.competicion("https://www.kaggle.com/competitions/titanic", self.ws)
        self.assertEqual((f["tipo"], f["metrica"], [a["nombre"] for a in f["archivos"]]),
                         ("competicion", "Categorization Accuracy", ["train.csv", "test.csv"]))
        self.assertTrue(f["reglas"].endswith("/titanic/rules"))

    def test_categoria_invalida_no_se_manda(self):
        self.con_cuenta()
        ke.buscar_competiciones("", "all")          # Kaggle responde 400 a «all»
        self.assertNotIn("category", kaggle_falso.Manejador.peticiones[0]["params"])

    def test_descarga_y_reglas_sin_aceptar(self):
        self.con_cuenta()
        loc = ke.descargar("competicion", "titanic", self.ws)
        self.assertEqual(sorted(a["relativa"] for a in loc["archivos"]), ["test.csv", "train.csv"])
        with self.assertRaisesRegex(ke.ErrorKaggle, "aceptar las reglas"):
            ke.descargar("competicion", "con-reglas", self.ws)
        self.assertFalse(os.path.exists(os.path.join(self.ws, "kaggle_datos", "con-reglas.zip.parcial")))


class TestVistaPrevia(Base):
    def setUp(self):
        super().setUp()
        self.loc = ke.descargar("dataset", "yasserh/titanic-dataset", self.ws)
        self.csv = self.loc["archivos"][0]["ruta"]

    def test_resumen_por_columna(self):
        p = ke.vista_previa(self.csv, self.ws)
        self.assertEqual((p["total_filas"], len(p["filas"]), p["separador"]), (40, 15, ","))
        col = {c["nombre"]: c for c in p["columnas"]}
        self.assertEqual(col["Age"]["tipo"], "número")
        self.assertEqual((col["Age"]["faltan"], col["Age"]["faltan_pct"]), (8, 20.0))
        self.assertEqual((col["Age"]["min"], col["Age"]["max"]), (21.0, 59.0))
        self.assertEqual(col["Sex"]["tipo"], "texto")
        self.assertEqual({f["valor"] for f in col["Sex"]["frecuentes"]}, {"male", "female"})
        self.assertEqual(col["PassengerId"]["frecuentes"], [])      # todo distinto: no aporta
        self.assertEqual(col["Cabin"]["faltan"], 30)

    def test_no_lee_fuera_de_los_datos(self):
        secreto = os.path.join(self.ws, "secreto.csv")
        with open(secreto, "w") as f:
            f.write("a\n1\n")
        for ruta in (secreto, "/etc/passwd", os.path.join(self.ws, "kaggle_datos", "..", "secreto.csv")):
            with self.assertRaises(ke.ErrorKaggle):
                ke.vista_previa(ruta, self.ws)

    def test_contexto_del_profesor_con_cifras_reales(self):
        f = ke.dataset("yasserh/titanic-dataset", self.ws)
        ctx = ke.contexto_datos(f, ke.previas_para_modelo(f, self.ws))
        self.assertIn("TABLA Titanic-Dataset.csv — 40 filas, 6 columnas", ctx)
        self.assertIn("Age [número] faltan 20.0%", ctx)
        self.assertIn(os.path.join("kaggle_datos", "titanic-dataset", "Titanic-Dataset.csv"), ctx)
        # La explicación con datos descargados es otra que sin ellos
        sin = dict(f, local=None)
        self.assertNotEqual(ke.huella(f), ke.huella(sin))

    def test_explicar_datos_usa_el_sistema_y_guarda(self):
        from test_kaggle_lector import ModeloFalso, consumir
        f = ke.dataset("yasserh/titanic-dataset", self.ws)
        ai = ModeloFalso("## Qué contiene\nPasajeros.")
        texto, _ = consumir(ke.explicar_datos(ai, "qwen", f, self.ws))
        self.assertIn("Pasajeros", texto)
        self.assertIn("Por dónde empezar", ai.prompts[0]["sistema"])
        self.assertIn("PRIMERAS FILAS", ai.prompts[0]["prompt"])
        ke.guardar_explicacion_datos("dataset", f["ref"], "qwen", ke.huella(f), texto)
        self.assertEqual(ke.explicacion_datos("dataset", f["ref"], "qwen", ke.huella(f)), texto)
        self.assertIsNone(ke.explicacion_datos("dataset", f["ref"], "otro", ke.huella(f)))


class TestNotebookEjecutable(Base):
    def test_rutas_de_kaggle_apuntan_al_proyecto(self):
        local = os.path.join(self.ws, "kaggle_datos") + "/"
        self.assertEqual(ke.reescribir_rutas("pd.read_csv('/kaggle/input/titanic/train.csv')", self.ws),
                         f"pd.read_csv('{local}titanic/train.csv')")
        self.assertEqual(ke.reescribir_rutas("open('../input/x/a.csv')", self.ws), f"open('{local}x/a.csv')")
        self.assertEqual(ke.reescribir_rutas("ruta = 'otra/../input/x'", self.ws), "ruta = 'otra/../input/x'")

    def test_guardar_en_el_proyecto_reescribe_y_dice_que_falta(self):
        r = kl.guardar_en_workspace("alexisbcook/titanic-tutorial", self.ws)
        with open(r["ruta"]) as f:
            nb = json.load(f)
        codigo = "".join(nb["cells"][1]["source"])
        self.assertIn(os.path.join(self.ws, "kaggle_datos", "titanic", "train.csv"), codigo)
        self.assertEqual(r["celdas_con_rutas"], 2)
        self.assertEqual({(d["ref"], d["descargado"]) for d in r["datos"]},
                         {("titanic", False), ("yasserh/titanic-dataset", False)})
        self.assertIn("titanic", r["aviso"])
        ke.descargar("dataset", "yasserh/titanic-dataset", self.ws)
        r = kl.guardar_en_workspace("alexisbcook/titanic-tutorial", self.ws)
        self.assertEqual({(d["ref"], d["descargado"]) for d in r["datos"]},
                         {("titanic", False), ("yasserh/titanic-dataset", True)})


if __name__ == "__main__":
    unittest.main()
