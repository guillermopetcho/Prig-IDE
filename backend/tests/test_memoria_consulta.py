"""
Memoria de consulta (memoria_consulta.py): la consola aislada donde el modelo consulta el banco.
Un proyecto temporal; P.llm con un generador falso.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import banco_proyecto as bp
import memoria_consulta as mc
from herramientas_chat import Herramientas

APP = '''from fastapi import FastAPI
import os
app = FastAPI()


class Servicio:
    def __init__(self, config):
        self.config = config
        self.limite = config.get("limite_gpu")

    def procesar(self):
        if not self.limite:
            raise ValueError("sin limite")
        return calcular(self.limite)


def calcular(x):
    return x * int(os.environ.get("FACTOR", "2"))


@app.get("/api/estado")
def estado():
    return Servicio({}).procesar()


@app.post("/api/olvidado")
def olvidado():
    return 1


@app.delete("/api/nota/{id_nota}")
def borrar_nota(id_nota: int):
    return id_nota
'''

JS = '''async function pintar() {
  const d = await fetch('/api/estado?x=1');
  document.getElementById('panel').textContent = d;
}

async function borrar(id) {
  await json(`/api/nota/${id}`, { method: 'DELETE' });
}
'''

HTML = '<div id="panel"></div>\n'


class TestConsola(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="prig_consola_")
        raiz = os.path.join(cls.tmp, "p")
        for rel, texto in (("app.py", APP), ("web/panel.js", JS), ("web/index.html", HTML)):
            os.makedirs(os.path.dirname(os.path.join(raiz, rel)), exist_ok=True)
            with open(os.path.join(raiz, rel), "w") as f:
                f.write(texto)
        cls.banco = bp.BancoProyecto(raiz, carpeta=os.path.join(cls.tmp, "banco"))
        cls.banco.sincronizar()
        cls.llm = []

        def generar(pregunta, contexto, max_tokens):
            cls.llm.append((pregunta, contexto, max_tokens))
            return f"resumen de {len(contexto)} caracteres"
        cls.consola = mc.Consola(cls.banco, generar=generar)

    @classmethod
    def tearDownClass(cls):
        cls.consola.cerrar()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def correr(self, codigo):
        return self.consola.ejecutar(codigo)

    def test_hechos_del_grafo(self):
        hechos = {(h["s"], h["r"], h["o"]) for h in self.banco_hechos()}
        self.assertIn(("estado", "expone", "GET /api/estado"), hechos)
        self.assertIn(("olvidado", "expone", "POST /api/olvidado"), hechos)
        self.assertIn(("Servicio.__init__", "lee_config", "limite_gpu"), hechos)
        self.assertIn(("calcular", "lee_entorno", "FACTOR"), hechos)
        self.assertIn(("Servicio.procesar", "lanza", "ValueError"), hechos)
        self.assertIn(("Servicio", "atributo", "limite"), hechos)
        self.assertIn(("pintar", "llama_api", "/api/estado"), hechos)
        self.assertIn(("borrar_nota", "expone", "DELETE /api/nota/*"), hechos)
        self.assertIn(("borrar", "llama_api", "/api/nota/*"), hechos)
        self.assertIn(("pintar", "usa_dom", "panel"), hechos)
        self.assertIn(("web/index.html", "define_dom", "panel"), hechos)

    def banco_hechos(self):
        with self.banco.conectar() as c:
            return [dict(f) for f in c.execute("SELECT s, r, o FROM grafo")]

    def test_consultas_y_variables_persistentes(self):
        r = self.correr('eps = {h["o"].split(" ", 1)[1] for h in P.hechos(r="expone")}\n'
                        'usados = {h["o"] for h in P.hechos(r="llama_api")}\n'
                        'sorted(eps - usados)')
        self.assertIsNone(r["error"])
        self.assertIn("/api/olvidado", r["salida"])
        self.assertNotIn("/api/estado", r["salida"])
        self.assertIn("eps", r["variables"])
        self.assertEqual(self.correr("len(eps)")["salida"].strip(), "3")
        self.assertNotIn("/api/nota/*", self.correr("sorted(eps - usados)")["salida"])

    def test_camino_api_y_codigo(self):
        self.assertIn("calcular (app.py:", self.correr('P.camino("estado", "calcular")')["salida"])
        salida = self.correr('P.api("/api/estado")')["salida"]
        self.assertIn("pintar", salida)
        self.assertIn('"estado"', salida)
        self.assertIn("def calcular(x):", self.correr('print(P.codigo("calcular"))')["salida"])
        self.assertIn("app.py", self.correr('[f["ruta"] for f in P.archivos(lenguaje="python")]')["salida"])
        self.assertIn("raise ValueError", self.correr('P.grep(r"raise")[0]["texto"]')["salida"])

    def test_llm_escribir_y_guardar(self):
        r = self.correr('P.llm("¿qué hace?", P.codigo("calcular"), max_tokens=100)')
        self.assertIn("resumen de", r["salida"])
        self.assertEqual(self.llm[-1][2], 100)
        self.assertIsNone(self.correr('P.anotar("definicion", "factor", "Multiplicador del entorno.", ["app.py"])')["error"])
        self.assertIn("factor", [k["titulo"] for k in self.banco.listar_conocimiento()])
        self.assertIsNone(self.correr('P.afirmar("calcular", "depende_de", "FACTOR")')["error"])
        self.assertIn('"depende_de"', self.correr('P.hechos(r="depende_de")')["salida"])
        self.correr('P.guardar("analisis", {"endpoints": 2})')
        otra = mc.Consola(self.banco)
        try:
            self.assertIn('"endpoints": 2', otra.ejecutar('P.recuperar("analisis")')["salida"])
        finally:
            otra.cerrar()

    def test_limite_de_subllamadas(self):
        r = self.correr('[P.llm("x", "y") for _ in range(20)]')
        self.assertIn("Máximo", r["error"])

    def test_aislamiento(self):
        for codigo, esperado in (("import os", "No se puede importar"),
                                 ("import subprocess", "No se puede importar"),
                                 ("P._c", "«_»"),
                                 ("().__class__.__bases__", "«_»"),
                                 ("open('/etc/passwd')", "No está permitido"),
                                 ("eval('1')", "No está permitido"),
                                 ("getattr(P, '_c')", "No está permitido"),
                                 ("P.sql('DELETE FROM archivos')", "Solo consultas SELECT"),
                                 ("P.sql('SELECT 1; DELETE FROM archivos')", "Error")):
            r = self.correr(codigo)
            self.assertIsNotNone(r["error"], codigo)
            self.assertIn(esperado, r["error"], codigo)
        self.assertEqual(self.banco.estado()["archivos"], 3)

    def test_salida_recortada(self):
        r = self.correr('print("x" * 20000)')
        self.assertIn("salida recortada", r["salida"])
        self.assertLess(len(r["salida"]), mc.MAX_SALIDA + 300)

    def test_herramienta_consola(self):
        h = Herramientas(banco=self.banco, consola=self.consola)
        self.assertIn("consola", {d["function"]["name"] for d in h.definiciones()})
        self.assertIn("app.py", h.ejecutar("consola", {"codigo": "P.archivos()[0]['ruta']"}))

    def test_donde(self):
        r = self.correr('P.donde("limite_gpu")')
        self.assertIsNone(r["error"])
        self.assertIn("Servicio.__init__", r["salida"])            # quien la lee
        self.assertIn("lee_config", r["salida"])
        r = self.correr('P.donde("/api/estado")')
        self.assertIn("pintar", r["salida"])                       # quien lo consume
        self.assertIn('"estado"', r["salida"])                     # quien lo implementa
        self.assertIn("FACTOR", self.correr('P.donde("FACTOR")')["salida"])

    def test_plazo_real_por_ejecucion(self):
        """ Una ejecución colgada se corta en su plazo (antes readline() podía esperar sin límite) """
        import time
        t0 = time.time()
        r = self.consola.ejecutar("while True: pass", timeout=2)
        self.assertLess(time.time() - t0, 10)
        self.assertIn("reinició", r["error"])
        self.assertEqual(self.correr("1 + 1")["salida"].strip(), "2")       # se recupera sola

    def test_subllamada_lenta_no_dispara_la_alarma(self):
        """ La alarma de 30 s mide el cómputo propio, no la espera a Prig """
        import time
        lenta = mc.Consola(self.banco, generar=lambda p, c, m: (time.sleep(2), "ok")[1])
        try:
            with mock.patch.object(mc, "TIEMPO_POR_EJECUCION", 1):
                r = lenta.ejecutar('P.llm("x", "y")')
            self.assertIsNone(r["error"])
            self.assertIn("ok", r["salida"])
        finally:
            lenta.cerrar()

    def test_presupuesto_de_subllamadas_por_respuesta(self):
        otra = mc.Consola(self.banco, generar=lambda p, c, m: "ok")
        try:
            self.assertIsNone(otra.ejecutar('[P.llm("x", "y") for _ in range(12)]')["error"])
            self.assertIsNone(otra.ejecutar('[P.llm("x", "y") for _ in range(12)]')["error"])
            r = otra.ejecutar('P.llm("x", "y")')
            self.assertIn("Se agotaron", r["error"])
        finally:
            otra.cerrar()

    def test_revisar(self):
        with self.assertRaises(mc.CodigoNoPermitido):
            mc.revisar("x.__dict__")
        mc.revisar("import re\nre.findall('a', 'aa')")



class TestResolucion(unittest.TestCase):
    """ Cada llamada va al símbolo exacto: no a cualquier función que se llame igual """

    ARCHIVOS = {
        "motor/__init__.py": "",
        "motor/nucleo.py": '''import requests


class Motor:
    def estado(self):
        return self.post("x")

    def post(self, url):
        return requests.post(url)


def crear() -> "Motor":
    return Motor()
''',
        "otro.py": '''class Panel:
    def estado(self):
        return 1

    def pintar(self):
        return self.estado()
''',
        "cliente.py": '''from motor import nucleo as nc
from motor.nucleo import crear


def usar():
    m = crear()
    crear().estado()
    return nc.crear()
''',
        "web/app.js": '''function post(x) { return x; }
function asegurar() { return post(1); }
''',
    }

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="prig_resolucion_")
        raiz = os.path.join(cls.tmp, "p")
        for rel, texto in cls.ARCHIVOS.items():
            os.makedirs(os.path.dirname(os.path.join(raiz, rel)), exist_ok=True)
            with open(os.path.join(raiz, rel), "w") as f:
                f.write(texto)
        cls.banco = bp.BancoProyecto(raiz, carpeta=os.path.join(cls.tmp, "banco"))
        cls.banco.sincronizar()
        with cls.banco.conectar() as c:
            cls.aristas = {(f["desde"], f["a_ruta"], f["a_nombre"]) for f in c.execute("SELECT * FROM llamadas")}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def destinos(self, desde):
        return {(r, n) for d, r, n in self.aristas if d == desde}

    def test_self_va_a_la_misma_clase(self):
        self.assertEqual(self.destinos("Motor.estado"), {("motor/nucleo.py", "Motor.post")})
        self.assertEqual(self.destinos("Panel.pintar"), {("otro.py", "Panel.estado")})

    def test_librerias_no_se_confunden_con_el_proyecto(self):
        self.assertEqual(self.destinos("Motor.post"), set())          # requests.post no es Motor.post

    def test_alias_de_import_y_tipo_de_retorno(self):
        d = self.destinos("usar")
        self.assertIn(("motor/nucleo.py", "crear"), d)                 # from … import crear y nc.crear()
        self.assertIn(("motor/nucleo.py", "Motor.estado"), d)          # crear() -> "Motor", luego .estado()
        self.assertNotIn(("otro.py", "Panel.estado"), d)

    def test_no_cruza_lenguajes(self):
        self.assertEqual(self.destinos("asegurar"), {("web/app.js", "post")})
        self.assertFalse(any(r.endswith(".py") for d, r, n in self.aristas if d == "asegurar"))


if __name__ == "__main__":
    unittest.main()
