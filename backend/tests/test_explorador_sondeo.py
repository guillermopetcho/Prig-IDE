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
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from explorador import Explorador, EXTENSIONES


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


# Los detectores, la medición por página, medir archivos y la recomendación del sondeo: prig-biblioteca/src/sondeo.rs


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
