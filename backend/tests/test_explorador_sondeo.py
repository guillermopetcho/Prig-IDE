"""
Pruebas del explorador de carpetas y del sondeo previo.

El sondeo existe porque extraer un libro son horas y hay cosas que cambian por
completo cómo hay que procesarlo y no se ven en el título. Lo que más importa
proteger aquí es la discriminación entre matemáticas y código, porque el fallo es
sutil y caro: en un libro de matemáticas «f(b)» parece una llamada a función y una
fórmula centrada parece una línea indentada. Un teorema entero llegó a puntuar como
código, y ese libro se habría configurado para extraer lenguajes de programación en
vez de fórmulas.
"""

import os
import sys
import json
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from explorador import Explorador, EXTENSIONES
from sondeo_libro import SondeoLibro


MATEMATICAS = """Teorema 3.2. Sea f una funcion continua en [a,b] y derivable en (a,b).
Entonces existe c en (a,b) tal que f(b) - f(a) = f'(c)(b-a).
Demostracion. Definimos g(x) = f(x) - f(a) - ((f(b)-f(a))/(b-a))(x-a).
Se tiene g(a) = g(b) = 0, y por el teorema de Rolle existe c con g'(c) = 0.
El gradiente ∇J(θ) = ∇L(θ) + λw determina la direccion de maximo descenso.
Corolario. Si f'(x) = 0 para todo x en (a,b), entonces f es constante."""

CODIGO = """def entrenar(modelo, datos, epocas=10):
    optimizador = torch.optim.Adam(modelo.parameters(), lr=1e-3)
    for epoca in range(epocas):
        perdida = F.cross_entropy(modelo(x), y)
        perdida.backward()
        optimizador.step()
    return modelo"""

CPP = """template <typename T>
class Vector {
public:
    Vector(size_t n) : datos_(new T[n]), tam_(n) {}
    T& operator[](size_t i) { return datos_[i]; }
private:
    T* datos_;
};"""

PROSA = """El algodon es una fibra natural que se obtiene de la planta del mismo nombre.
Su cultivo requiere suelos profundos y bien drenados, con temperaturas templadas
durante todo el ciclo. La siembra se realiza en primavera, cuando el suelo ha
alcanzado una temperatura estable superior a los quince grados centigrados."""

INGLES = """The gradient of a scalar field is the vector whose components are the
partial derivatives of the function. This vector points in the direction of the
steepest increase, and its magnitude is the rate of change in that direction."""


class PruebaDetectores(unittest.TestCase):
    """ Umbrales por página: 10 para matemáticas, 15 para código. """

    def setUp(self):
        self.s = SondeoLibro()

    def veredicto(self, texto):
        mat, cod, _ = self.s._densidades(texto)
        return ("matemática" if mat >= 10 else "") + ("código" if cod >= 15 else "") or "prosa"

    def test_un_teorema_es_matematicas_no_codigo(self):
        """ f(b) y g(x) parecen llamadas a función; no deben contar como código. """
        mat, cod, _ = self.s._densidades(MATEMATICAS)
        self.assertGreaterEqual(mat, 10, "una demostración debe puntuar como matemáticas")
        self.assertLess(cod, 15, "una demostración NO debe puntuar como código")

    def test_python_es_codigo(self):
        self.assertEqual(self.veredicto(CODIGO), "código")

    def test_cpp_es_codigo(self):
        self.assertEqual(self.veredicto(CPP), "código")

    def test_la_prosa_no_es_ninguna_de_las_dos(self):
        self.assertEqual(self.veredicto(PROSA), "prosa")

    def test_la_prosa_tecnica_en_ingles_tampoco(self):
        """ Hablar de gradientes no convierte un párrafo en matemáticas. """
        self.assertEqual(self.veredicto(INGLES), "prosa")

    def test_detecta_el_idioma(self):
        import re
        for texto, esperado in ((PROSA, "es"), (INGLES, "en")):
            palabras = re.findall(r"[a-zA-Z_]{2,}", texto.lower())
            self.assertEqual(self.s._idioma(palabras), esperado)


class PruebaMedicionPorPagina(unittest.TestCase):
    """ Se mide página a página, no en promedio: un libro con un tercio de código
    y dos tercios de prosa da media baja y parecería un libro de texto normal. """

    def setUp(self):
        self.s = SondeoLibro()

    def test_una_minoria_de_paginas_de_codigo_se_detecta(self):
        paginas = [CODIGO] + [PROSA] * 3
        r = self.s._analizar_paginas(paginas, "")
        self.assertGreaterEqual(r["fraccion_paginas_codigo"], 0.2)
        self.assertEqual(r["fraccion_paginas_matematicas"], 0.0)

    def test_el_promedio_solo_habria_diluido(self):
        r = self.s._analizar_paginas([CODIGO] + [PROSA] * 5, "")
        self.assertGreater(r["pico_codigo"], r["densidad_codigo"],
                           "el pico debe destacar sobre la media")

    def test_sin_paginas_no_inventa_nada(self):
        r = self.s._analizar_paginas([], "")
        self.assertEqual(r["densidad_codigo"], 0.0)
        self.assertEqual(r["idioma"], "?")


class PruebaMedirArchivos(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.s = SondeoLibro()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def escribir(self, nombre, contenido):
        ruta = os.path.join(self.tmp, nombre)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(contenido)
        return ruta

    def test_mide_un_markdown(self):
        ruta = self.escribir("libro.md", "# Capítulo 1\n\n" + PROSA * 60)
        m = self.s.medir(ruta)
        self.assertGreater(m["paginas"], 1)
        self.assertTrue(m["tiene_indice"])
        self.assertEqual(m["idioma"], "es")

    def test_detecta_un_libro_de_programacion(self):
        ruta = self.escribir("curso.md", (CODIGO + "\n\n") * 30)
        m = self.s.medir(ruta)
        self.assertIn("de programación", " ".join(m["naturaleza"]))

    def test_detecta_un_libro_matematico(self):
        ruta = self.escribir("analisis.md", (MATEMATICAS + "\n\n") * 30)
        m = self.s.medir(ruta)
        self.assertIn("matemático", " ".join(m["naturaleza"]))

    def test_lee_un_cuaderno_sin_ahogarse_en_el_json(self):
        nb = {"cells": [{"cell_type": "code", "source": [CODIGO]},
                        {"cell_type": "markdown", "source": ["# Título\n", PROSA]}]}
        ruta = self.escribir("nb.ipynb", json.dumps(nb))
        m = self.s.medir(ruta)
        self.assertGreater(m["fraccion_paginas_codigo"], 0)

    def test_un_archivo_que_no_existe_lo_dice(self):
        with self.assertRaises(FileNotFoundError):
            self.s.medir(os.path.join(self.tmp, "fantasma.pdf"))

    def test_estima_el_tamano_y_el_coste(self):
        m = self.s.medir(self.escribir("largo.md", PROSA * 400))
        self.assertGreater(m["fragmentos_estimados"], 0)
        self.assertIn(m["tamano"], ("corto", "normal", "largo", "enorme"))


class PruebaRecomendacion(unittest.TestCase):

    def setUp(self):
        self.s = SondeoLibro()

    def base(self, **kw):
        m = {"paginas": 300, "fraccion_paginas_matematicas": 0.0,
             "fraccion_paginas_codigo": 0.0, "imagenes_por_pagina": 0.1,
             "tiene_indice": True, "idioma": "es", "escaneado": False,
             "fragmentos_estimados": 200, "horas_estimadas_local": 2.0}
        m.update(kw)
        return m

    def test_un_escaneado_se_bloquea(self):
        """ Sin texto no hay nada que extraer, y ningún modelo lo arregla. """
        r = self.s.recomendar(self.base(escaneado=True))
        self.assertFalse(r["se_puede_extraer"])
        self.assertTrue(any("OCR" in b for b in r["bloqueos"]))

    def test_mucha_matematica_pide_latex(self):
        r = self.s.recomendar(self.base(fraccion_paginas_matematicas=0.4))
        self.assertTrue(r["ajustes_extraccion"]["pedir_latex"])

    def test_mucho_codigo_pide_el_lenguaje(self):
        r = self.s.recomendar(self.base(fraccion_paginas_codigo=0.25))
        self.assertTrue(r["ajustes_extraccion"]["pedir_lenguaje_codigo"])

    def test_un_libro_muy_matematico_usa_fragmentos_mas_cortos(self):
        """ Cortar una derivación por la mitad da afirmaciones que no se sostienen. """
        normal = self.s.recomendar(self.base())["ajustes_extraccion"]["max_chunk_tokens"]
        mates = self.s.recomendar(
            self.base(fraccion_paginas_matematicas=0.5))["ajustes_extraccion"]["max_chunk_tokens"]
        self.assertLess(mates, normal)

    def test_un_libro_enorme_avisa_de_partirlo(self):
        r = self.s.recomendar(self.base(paginas=1200))
        self.assertTrue(any("pártelo" in a for a in r["avisos"]))

    def test_un_libro_corto_no_merece_la_ficha_de_siete_pasos(self):
        r = self.s.recomendar(self.base(paginas=40))
        self.assertEqual(r["flujo_recomendado"], "plantilla_libro")

    def test_un_libro_normal_si_la_merece(self):
        self.assertEqual(self.s.recomendar(self.base())["flujo_recomendado"],
                         "plantilla_ficha_libro")

    def test_sin_indice_avisa(self):
        r = self.s.recomendar(self.base(tiene_indice=False))
        self.assertTrue(any("Sin índice" in a for a in r["avisos"]))

    def test_estima_el_coste_en_los_dos_sitios(self):
        c = self.s.recomendar(self.base())["coste"]
        self.assertGreater(c["horas_en_local"], 0)
        self.assertGreater(c["minutos_en_dos_T4"], 0)
        self.assertLess(c["minutos_en_dos_T4"] / 60, c["horas_en_local"],
                        "dos T4 tienen que salir más rápido que el equipo local")


class PruebaExplorador(unittest.TestCase):

    def setUp(self):
        self.casa = tempfile.mkdtemp()
        self.ex = Explorador()
        self.ex.raiz = self.casa      # se acota la navegación al temporal
        os.makedirs(os.path.join(self.casa, "Libros", "mates"))
        os.makedirs(os.path.join(self.casa, ".oculta"))
        os.makedirs(os.path.join(self.casa, "node_modules"))
        for ruta in ("Libros/uno.pdf", "Libros/dos.md", "Libros/mates/apuntes.pdf",
                     "Libros/no_es_libro.zip"):
            completa = os.path.join(self.casa, ruta)
            with open(completa, "w") as f:
                f.write("x")

    def tearDown(self):
        shutil.rmtree(self.casa, ignore_errors=True)

    def test_lista_libros_y_carpetas(self):
        d = self.ex.listar(os.path.join(self.casa, "Libros"))
        self.assertEqual({l["nombre"] for l in d["libros"]}, {"uno.pdf", "dos.md"})
        self.assertEqual([c["nombre"] for c in d["carpetas"]], ["mates"])

    def test_ignora_lo_que_no_es_un_libro(self):
        d = self.ex.listar(os.path.join(self.casa, "Libros"))
        self.assertNotIn("no_es_libro.zip", [l["nombre"] for l in d["libros"]])

    def test_esconde_carpetas_ocultas_y_de_sistema(self):
        nombres = [c["nombre"] for c in self.ex.listar(self.casa)["carpetas"]]
        self.assertNotIn(".oculta", nombres)
        self.assertNotIn("node_modules", nombres)

    def test_cuenta_los_libros_de_cada_carpeta(self):
        """ Para no entrar a ciegas en veinte carpetas buscando dónde están. """
        carpeta = next(c for c in self.ex.listar(self.casa)["carpetas"]
                       if c["nombre"] == "Libros")
        self.assertEqual(carpeta["libros_dentro"], 2)

    def test_en_recursivo_trae_los_de_las_subcarpetas(self):
        d = self.ex.listar(os.path.join(self.casa, "Libros"), recursivo=True)
        self.assertIn("apuntes.pdf", [l["nombre"] for l in d["libros"]])

    def test_no_deja_salir_de_la_raiz(self):
        """ Sin esto la API se convertiría en un lector de archivos arbitrario. """
        with self.assertRaises(PermissionError):
            self.ex.listar("/etc")

    def test_un_enlace_que_apunta_fuera_tampoco_vale(self):
        destino = tempfile.mkdtemp()
        try:
            enlace = os.path.join(self.casa, "atajo")
            os.symlink(destino, enlace)
            self.assertFalse(self.ex.permitida(enlace),
                             "un enlace a otro sitio no debe abrir el disco entero")
        finally:
            shutil.rmtree(destino, ignore_errors=True)

    def test_busca_por_nombre_en_todo_el_arbol(self):
        r = self.ex.buscar("apuntes", desde=self.casa)
        self.assertEqual([x["nombre"] for x in r], ["apuntes.pdf"])

    def test_busca_con_varias_palabras_en_cualquier_orden(self):
        with open(os.path.join(self.casa, "Libros", "Machine Learning con Python.pdf"), "w") as f:
            f.write("x")
        r = self.ex.buscar("python machine", desde=self.casa)
        self.assertEqual(len(r), 1)

    def test_las_migas_permiten_volver_atras(self):
        d = self.ex.listar(os.path.join(self.casa, "Libros", "mates"))
        self.assertEqual([m["nombre"] for m in d["migas"]][-2:], ["Libros", "mates"])

    def test_todas_las_extensiones_tienen_nombre_legible(self):
        for ext, nombre in EXTENSIONES.items():
            self.assertTrue(ext.startswith(".") and nombre)

    def test_import_file_mismo_archivo_no_falla(self):
        from book_service import BookService
        bs_dir = tempfile.mkdtemp()
        try:
            bs = BookService(books_dir=bs_dir)
            fpath = os.path.join(self.casa, "Libros", "uno.pdf")
            r1 = bs.import_file(fpath)
            self.assertNotIn("error", r1)
            # Reimportar desde el destino mismo
            r2 = bs.import_file(r1["path"])
            self.assertNotIn("error", r2)
            self.assertEqual(r2["filename"], "uno.pdf")
        finally:
            shutil.rmtree(bs_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
