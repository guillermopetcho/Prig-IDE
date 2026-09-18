"""
Colecciones, filtros avanzados y PDF de notebooks explicados.

  · Filtros: los que Kaggle respeta viajan a la API (autor, licencia, tamaño, copias de
    un notebook, «mis competiciones»); los que ignora se aplican aquí (tipo, votos
    mínimos, antigüedad, GPU) y se dice cuántos quedaron fuera.
  · Colecciones: crear, renombrar, sin nombres repetidos, un elemento en varias,
    notas, quitar, borrar; lo guardado se ve sin red y se marca en las tarjetas.
  · PDF: el notebook con sus explicaciones; solo se imprime la explicación que
    corresponde al código actual; el markdown se convierte; una colección entera
    va en un solo PDF.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kaggle_colecciones as kc  # noqa: E402
import kaggle_explorar as ke  # noqa: E402
import kaggle_falso  # noqa: E402
import kaggle_lector as kl  # noqa: E402
import kaggle_pdf  # noqa: E402

URL, _SERVIDOR = kaggle_falso.arrancar()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, "ws")
        os.makedirs(self.ws)
        self.entorno = mock.patch.dict(os.environ, {
            "HOME": os.path.join(self.tmp, "home"), "PRIG_KAGGLE_DIR": os.path.join(self.tmp, "k"),
            "PRIG_KAGGLE_CREDENCIALES": os.path.join(self.tmp, "cred.json"),
            "XDG_CONFIG_HOME": os.path.join(self.tmp, "config"), "KAGGLE_CONFIG_DIR": os.path.join(self.tmp, "nada"),
            "KAGGLE_API_TOKEN": "KGAT_token_de_prueba_123456"})
        self.entorno.start()
        self.api = mock.patch.object(kl, "API", URL)
        self.api.start()
        kl._cache.clear()
        ke._cache.clear()
        kaggle_falso.Manejador.peticiones.clear()

    def tearDown(self):
        self.api.stop()
        self.entorno.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def params(self, i=-1):
        return kaggle_falso.Manejador.peticiones[i]["params"]


class TestFiltros(Base):
    def test_filtros_que_viajan_a_kaggle(self):
        kl.buscar("eda", "nuevos", usuario="alexisbcook", padre="https://www.kaggle.com/code/alexisbcook/titanic-tutorial")
        p = self.params()
        self.assertEqual((p["sortBy"], p["user"], p["parentKernel"]), ("dateCreated", "alexisbcook", "alexisbcook/titanic-tutorial"))
        ke.buscar_datasets("casas", licencia="cc", tamano="mediano", usuario="yasserh")
        p = self.params()
        self.assertEqual((p["license"], p["minSize"], p["maxSize"], p["user"]), ("cc", str(1 << 20), str(100 << 20), "yasserh"))
        ke.buscar_datasets("x", licencia="rara", tamano="enorme")
        p = self.params()
        self.assertNotIn("license", p)
        self.assertEqual(p["minSize"], str(1 << 30))
        self.assertNotIn("maxSize", p)
        ke.buscar_competiciones(grupo="mias")
        self.assertEqual(self.params()["group"], "entered")
        ke.buscar_competiciones(grupo="general")
        self.assertNotIn("group", self.params())

    def test_filtros_locales(self):
        ahora = datetime.now(timezone.utc)
        lista = [
            {"ref": "a/viejo", "title": "Viejo", "totalVotes": 500, "kernelType": "notebook", "language": "python",
             "lastRunTime": (ahora - timedelta(days=400)).isoformat()},
            {"ref": "a/nuevo", "title": "Nuevo", "totalVotes": 3, "kernelType": "script", "language": "python",
             "lastRunTime": (ahora - timedelta(days=2)).isoformat(), "enableGpu": True},
            {"ref": "a/medio", "title": "Medio", "totalVotes": 50, "kernelType": "notebook", "language": "python",
             "lastRunTime": (ahora - timedelta(days=20)).isoformat()},
        ]
        with mock.patch.object(kl, "_pedir", return_value=lista) as pedir:
            r = kl.buscar("x", votos_min=10)
            self.assertEqual([n["ref"] for n in r["notebooks"]], ["a/viejo", "a/medio"])
            self.assertEqual(r["ocultos"], 1)
            self.assertEqual(pedir.call_args.args[1]["pageSize"], 50)       # con filtros locales, páginas grandes
            self.assertEqual([n["ref"] for n in kl.buscar("x", dias=30)["notebooks"]], ["a/nuevo", "a/medio"])
            self.assertEqual([n["ref"] for n in kl.buscar("x", tipo="script")["notebooks"]], ["a/nuevo"])
            self.assertEqual([n["ref"] for n in kl.buscar("x", gpu=True)["notebooks"]], ["a/nuevo"])
            self.assertEqual(len(kl.buscar("x")["notebooks"]), 3)


class TestColecciones(Base):
    def test_ciclo_completo(self):
        c = kc.crear("  Visión   por computador ", "Para el TFM")
        self.assertEqual(c["nombre"], "Visión por computador")
        with self.assertRaisesRegex(kl.ErrorKaggle, "Ya tienes"):
            kc.crear("visión POR computador")
        with self.assertRaisesRegex(kl.ErrorKaggle, "nombre"):
            kc.crear("   ")
        otra = kc.crear("Titanic")
        self.assertNotEqual(c["color"], otra["color"])
        datos = {"titulo": "Titanic Tutorial", "autor": "alexisbcook", "votos": 30000, "ignorado": "x"}
        kc.anadir(c["id"], "notebook", "alexisbcook/titanic-tutorial", datos)
        kc.anadir(otra["id"], "notebook", "alexisbcook/titanic-tutorial", datos)
        kc.anadir(c["id"], "dataset", "yasserh/titanic-dataset", {"titulo": "Titanic Dataset", "imagen": "http://img"})
        kc.anadir(c["id"], "competicion", "https://www.kaggle.com/competitions/titanic", {"titulo": "Titanic"})
        # Repetir no duplica, actualiza
        kc.anadir(c["id"], "notebook", "alexisbcook/titanic-tutorial", {"titulo": "Titanic Tutorial v2"})
        detalle = kc.obtener(c["id"])
        self.assertEqual(detalle["total"], 3)
        self.assertEqual(detalle["cuenta"], {"notebook": 1, "dataset": 1, "competicion": 1})
        self.assertEqual(detalle["portadas"], ["http://img"])
        nb = next(i for i in detalle["items"] if i["tipo"] == "notebook")
        self.assertEqual((nb["titulo"], nb["autor"]), ("Titanic Tutorial v2", "alexisbcook"))
        self.assertNotIn("ignorado", nb)
        comp = next(i for i in detalle["items"] if i["tipo"] == "competicion")
        self.assertEqual(comp["ref"], "titanic")
        self.assertEqual(sorted(kc.donde_esta("notebook", "alexisbcook/titanic-tutorial")), sorted([c["id"], otra["id"]]))
        self.assertIn("dataset:yasserh/titanic-dataset", kc.guardados())
        kc.anotar(c["id"], "dataset", "yasserh/titanic-dataset", "Usar para practicar limpieza")
        self.assertEqual(next(i for i in kc.obtener(c["id"])["items"] if i["tipo"] == "dataset")["nota"], "Usar para practicar limpieza")
        kc.quitar(c["id"], "dataset", "yasserh/titanic-dataset")
        self.assertEqual(kc.obtener(c["id"])["total"], 2)
        kc.editar(c["id"], nombre="CV", color="#a6e3a1")
        self.assertEqual((kc.obtener(c["id"])["nombre"], kc.obtener(c["id"])["color"]), ("CV", "#a6e3a1"))
        with self.assertRaisesRegex(kl.ErrorKaggle, "Ya tienes"):
            kc.editar(c["id"], nombre="titanic")
        # La tocada más recientemente va primero
        self.assertEqual(kc.listar()[0]["id"], c["id"])
        self.assertEqual(kc.recientes(1)[0]["coleccion"], "CV")
        kc.borrar(otra["id"])
        self.assertEqual([x["id"] for x in kc.listar()], [c["id"]])
        with self.assertRaisesRegex(kl.ErrorKaggle, "no existe"):
            kc.obtener(otra["id"])

    def test_validacion(self):
        c = kc.crear("A")
        for tipo, ref in (("modelo", "a/b"), ("notebook", "../x"), ("dataset", "sin-barra")):
            with self.assertRaises(kl.ErrorKaggle):
                kc.anadir(c["id"], tipo, ref)
        with self.assertRaisesRegex(kl.ErrorKaggle, "no está"):
            kc.anotar(c["id"], "notebook", "a/b", "x")


EXPLICACION = """### Qué hace
Carga el CSV con `pd.read_csv` y lo guarda en **df** → un *DataFrame* ✅.

### Paso a paso
1. Importa pandas.
2. Lee el archivo.
   - Cada fila es un pasajero.

```python
df = pd.read_csv('train.csv')
```

| Columna | Tipo |
|---|---|
| Age | float |

> Ojo con las rutas.

<div style="color:red">HTML <b>suelto</b></div>"""


class TestPdf(Base):
    def setUp(self):
        super().setUp()
        self.nb = kl.abrir("alexisbcook/titanic-tutorial")

    def texto(self, ruta):
        from pypdf import PdfReader
        return "\n".join(p.extract_text() for p in PdfReader(ruta).pages)

    def test_notebook_explicado(self):
        kl.guardar_explicacion(self.nb, 1, "intermedio", "qwen", EXPLICACION)
        kl.guardar_explicacion(self.nb, None, "", "qwen", "## De qué trata\nSupervivencia en el Titanic.")
        r = kaggle_pdf.pdf_notebook("alexisbcook/titanic-tutorial", self.ws,
                                    {"chat": [{"rol": "usuario", "texto": "¿Qué es df?"}, {"rol": "profesor", "texto": "Una tabla."}]})
        self.assertEqual(r["relativa"], os.path.join("kaggle_pdf", "titanic-tutorial.pdf"))
        self.assertEqual((r["explicadas"], r["celdas"]), (1, 5))
        self.assertGreaterEqual(r["paginas"], 3)
        t = self.texto(r["ruta"])
        for esperado in ("Titanic Tutorial", "alexisbcook", "Guía de lectura", "Supervivencia en el Titanic",
                         "CELDA 1", "PROFESOR", "Qué hace", "pd.read_csv", "Paso a paso", "Cada fila es un pasajero",
                         "Age", "Ojo con las rutas", "HTML suelto", "Preguntas al profesor", "¿Qué es df?", "Una tabla",
                         "Apache 2.0"):
            self.assertIn(esperado, t, esperado)
        self.assertNotIn("<div", t)
        self.assertNotIn("**", t)
        self.assertNotIn("✅", t)
        self.assertFalse(os.path.exists(r["ruta"] + ".tmp"))

    def test_solo_explicadas_y_explicacion_obsoleta(self):
        with self.assertRaisesRegex(kl.ErrorKaggle, "todavía no tiene"):
            kaggle_pdf.pdf_notebook("alexisbcook/titanic-tutorial", self.ws, {"solo_explicadas": True})
        kl.guardar_explicacion(self.nb, 2, "intermedio", "qwen", "Muestra las primeras filas.")
        viejo = json.loads(json.dumps(self.nb))
        viejo["celdas"][1]["fuente"] = "codigo_antiguo = 1"
        kl.guardar_explicacion(viejo, 1, "intermedio", "qwen", "EXPLICACION DE UNA VERSION VIEJA")
        por_celda, _ = kaggle_pdf.elegir_explicaciones(self.nb)
        self.assertEqual(list(por_celda), [2])
        r = kaggle_pdf.pdf_notebook("alexisbcook/titanic-tutorial", self.ws, {"solo_explicadas": True})
        t = self.texto(r["ruta"])
        self.assertIn("Muestra las primeras filas", t)
        self.assertNotIn("VERSION VIEJA", t)
        self.assertNotIn("CELDA 0", t)

    def test_prefiere_el_nivel_pedido(self):
        kl.guardar_explicacion(self.nb, 1, "principiante", "qwen", "EXPLICACION FACIL")
        time.sleep(1.1)
        kl.guardar_explicacion(self.nb, 1, "avanzado", "qwen", "EXPLICACION DIFICIL")
        self.assertEqual(kaggle_pdf.elegir_explicaciones(self.nb)[0][1]["texto"], "EXPLICACION DIFICIL")
        self.assertEqual(kaggle_pdf.elegir_explicaciones(self.nb, "principiante")[0][1]["texto"], "EXPLICACION FACIL")

    def test_coleccion_en_un_pdf(self):
        c = kc.crear("Titanic")
        kc.anadir(c["id"], "notebook", "alexisbcook/titanic-tutorial", {"titulo": "Titanic Tutorial"})
        kc.anadir(c["id"], "notebook", "a/uno", {"titulo": "Uno"})
        kc.anadir(c["id"], "notebook", "x/no-existe", {"titulo": "Borrado"})
        kc.anadir(c["id"], "dataset", "yasserh/titanic-dataset", {"titulo": "Datos"})
        kl.guardar_explicacion(self.nb, 1, "intermedio", "qwen", "Carga los datos.")
        r = kaggle_pdf.pdf_coleccion(kc.obtener(c["id"]), self.ws)
        self.assertEqual((r["notebooks"], r["explicadas"]), (2, 1))
        self.assertEqual(len(r["no_incluidos"]), 1)
        t = self.texto(r["ruta"])
        for esperado in ("COLECCIÓN", "Contenido", "Titanic Tutorial", "Uno", "Carga los datos", "No incluidos"):
            self.assertIn(esperado, t)
        vacia = kc.crear("Vacía")
        with self.assertRaisesRegex(kl.ErrorKaggle, "no tiene notebooks"):
            kaggle_pdf.pdf_coleccion(kc.obtener(vacia["id"]), self.ws)

    def test_markdown_raro_no_rompe(self):
        est = (kaggle_pdf._registrar_fuentes(), kaggle_pdf._estilos())[1]
        raros = ["**sin cerrar", "a < b & c > d", "```\nsin cerrar", "| a |\n|---|\n| 1 | 2 | 3 |", "- \n-", "#",
                 "<script>alert(1)</script>ok", "[enlace](javascript:alert(1))", "x" * 5000, "\t\tcódigo"]
        for texto in raros:
            fl = kaggle_pdf.markdown(texto, est)
            self.assertIsInstance(fl, list, texto)
        kl.guardar_explicacion(self.nb, 1, "intermedio", "qwen", "\n\n".join(raros))
        r = kaggle_pdf.pdf_notebook("alexisbcook/titanic-tutorial", self.ws)
        t = self.texto(r["ruta"])
        self.assertIn("a < b & c > d", t)
        self.assertNotIn("alert(1)</script>", t)


if __name__ == "__main__":
    unittest.main()
