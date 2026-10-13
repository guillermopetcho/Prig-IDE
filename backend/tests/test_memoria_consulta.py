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
        # Con el método delante, como lo escribe el modelo: antes devolvía vacío
        self.assertEqual(salida, self.correr('P.api("GET /api/estado")')["salida"])
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


SERVICIO = '''class Servicio:
    def procesar(self):
        return 1


servicio = Servicio()
'''

USO = '''import servicio as s


def por_instancia():
    return s.servicio.procesar()


def aplicar(fn):
    return fn()


def por_valor():
    return aplicar(s.servicio.procesar)
'''


class TestHuecosDelGrafo(unittest.TestCase):
    """ Lo que el estudio del banco encontró (docs/estudio-banco.md): llamadas por una instancia global o una
    función pasada como valor que el grafo no resuelve; el modelo consultaba P.llamadores, recibía [] y
    concluía «nadie la llama». Ahora P.llamadores agrega lo que encuentra en el texto, marcado. """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="prig_huecos_")
        raiz = os.path.join(cls.tmp, "p")
        os.makedirs(raiz)
        for rel, texto in (("servicio.py", SERVICIO), ("uso.py", USO)):
            with open(os.path.join(raiz, rel), "w") as f:
                f.write(texto)
        cls.banco = bp.BancoProyecto(raiz, carpeta=os.path.join(cls.tmp, "banco"))
        cls.banco.sincronizar()
        import sqlite3
        cls.conexion = sqlite3.connect(f"file:{cls.banco.ruta_db}?mode=ro", uri=True, check_same_thread=False)
        cls.conexion.row_factory = sqlite3.Row
        cls.api = mc.API(cls.conexion, raiz, lambda *a, **k: None)

    @classmethod
    def tearDownClass(cls):
        cls.conexion.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_llamadores_incluye_lo_que_el_grafo_no_resuelve(self):
        quienes = {x["s"]: x for x in self.api.llamadores("Servicio.procesar")}
        self.assertIn("por_instancia", quienes)
        self.assertIn("por_valor", quienes)
        for x in quienes.values():
            if str(x["confianza"]).startswith("texto"):
                self.assertIn("procesar", x["codigo"])               # la línea, para que el modelo la juzgue

    def test_hechos_de_la_pregunta(self):
        texto = mc.hechos_de_la_pregunta(self.banco, "¿Quién llama a `Servicio.procesar` (en `servicio.py`)?")
        self.assertIn("FACTS FROM THE PROJECT BANK", texto)
        self.assertIn("por_instancia", texto)
        self.assertIn("defined:", texto)
        self.assertEqual(mc.hechos_de_la_pregunta(self.banco, "¿Qué tal estás?"), "")

    def test_terminos_de(self):
        self.assertEqual(mc.terminos_de("¿Quién lee la clave `truncar` y llama a `POST /api/x/{id}` en `backend/x.py`?"),
                         ["POST /api/x/{id}", "truncar"])
        self.assertIn("ruta_http_canonica", mc.terminos_de("¿qué devuelve ruta_http_canonica con un id?"))


SERVICIO_T7 = '''class Servicio:
    def procesar(self):
        return 1


class Otro:
    def procesar(self):
        return 2


servicio = Servicio()


def fabrica() -> Servicio:
    return servicio


def otra_fabrica() -> Otro:
    return Otro()
'''

HERRAMIENTAS_T7 = '''def procesar():
    return 3
'''

USO_T7 = '''import herramientas
from servicio import Servicio, Otro, fabrica, otra_fabrica


local = Servicio()
otro = Otro()


class Maquina:
    def __init__(self, fn):
        self.fn = fn


def por_local():
    return local.procesar()


def por_otro():
    return otro.procesar()


def por_modulo():
    return herramientas.procesar()


def copiar(maq):
    return Maquina(maq.procesar)


def aplicar(fn):
    return fn()


def intermedio():
    return aplicar(len)


def inicio():
    return intermedio()


def por_fabrica():
    return fabrica().procesar()


def por_otra_fabrica():
    return otra_fabrica().procesar()
'''

API_T7 = '''from fastapi import FastAPI
import uso

app = FastAPI()


@app.get("/api/inicio")
def ver_inicio():
    return envolver(uso.intermedio, 1)


def envolver(fn, n):
    return fn()
'''

CONFIG_T7 = '''DEFECTOS = {"tamano_maximo": 10}


def leer(ajustes):
    return ajustes.get("tamano_maximo", 5)


def tope(ajustes):
    return ajustes["tamano_maximo"] * 2


def guardar(ajustes, valor):
    ajustes["tamano_maximo"] = valor


def preparar(ajustes):
    return ajustes.get("tamano_maximos") or 1
'''

RITMO_T7 = '''# la opción activa: si está activa, activa el ritmo (la palabra, no la clave)
class Ritmo:
    def __init__(self, ajustes):
        self.ajustes = ajustes

    def activo(self):
        return bool(self.ajustes.get("activa"))

    def fijar(self, valor):
        self.ajustes["activo"] = valor
        return {"activo": valor}
'''

PROCESO_T7 = '''import subprocess


def correr(cmd):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    try:
        return p.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        return p.communicate()


def correr_bien(cmd):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    try:
        return p.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
        return p.communicate()


def avisar():
    return 1


def usar_aviso():
    print(f"hay que avisar (pronto)")
'''

PICOS_T7 = '''class Tramo:
    def __init__(self):
        self.pico = None
        self.pausa = None

    def pico_real(self):
        picos = [p for p in (self.pico, self.pausa) if p is not None]
        return max(picos)

    def pico_seguro(self):
        picos = [p for p in (self.pico, self.pausa) if p is not None]
        return max(picos) if picos else None


def mas_cercana(lista):
    if lista:
        vecinas = [v for v in lista[:2] if v is not None]
        return min(vecinas)
'''

RECURSOS_T7 = '''import os
import sqlite3
from contextlib import contextmanager


@contextmanager
def abrir(ruta):
    c = sqlite3.connect(ruta)
    yield c
    c.commit()


@contextmanager
def abrir_bien(ruta):
    c = sqlite3.connect(ruta)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def dentro(abs_path, root):
    return abs_path.startswith(root)


def dentro_bien(abs_path, root):
    return abs_path == root or abs_path.startswith(root + os.sep)


def es_postgres(database_url, scheme):
    return database_url.startswith(scheme)
'''

LECTOR_T7 = '''def ajustes_de(cfg):
    return cfg.get("modo_lector")


def leer_de(origen):
    e = origen.datos()
    return e.get("modo_lector", 1)
'''

MEDIDAS_T7 = '''def _medir(x):
    import servicio
    return len(x)


def total(xs):
    return sum(_medir(x) for x in xs)
'''

TEST_T7 = '''from servicio import servicio


def test_procesar():
    assert servicio.procesar() == 1
'''


class TestHechosT7(unittest.TestCase):
    """ Lo que la medición corta T7 encontró (docs/estudio-banco.md, «Texto primero: medición corta»): los
    recorridos negados (el camino estaba en el grafo), la clave que «aparece como texto» tomada por lectura,
    la clave mal escrita que nadie vio, y el ruido de los llamadores por texto (el atributo de un objeto, el
    método homónimo de otra clase, los tests) """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="prig_t7_")
        raiz = os.path.join(cls.tmp, "p")
        os.makedirs(os.path.join(raiz, "tests"))
        for rel, texto in (("servicio.py", SERVICIO_T7), ("herramientas.py", HERRAMIENTAS_T7), ("uso.py", USO_T7),
                           ("config.py", CONFIG_T7), ("tests/test_servicio.py", TEST_T7), ("api.py", API_T7),
                           ("ritmo_t7.py", RITMO_T7), ("proceso_t7.py", PROCESO_T7), ("medidas_t7.py", MEDIDAS_T7),
                           ("lector_t7.py", LECTOR_T7), ("picos_t7.py", PICOS_T7),
                           ("recursos_t7.py", RECURSOS_T7)):
            with open(os.path.join(raiz, rel), "w") as f:
                f.write(texto)
        cls.banco = bp.BancoProyecto(raiz, carpeta=os.path.join(cls.tmp, "banco"))
        cls.banco.sincronizar()
        import sqlite3
        cls.conexion = sqlite3.connect(f"file:{cls.banco.ruta_db}?mode=ro", uri=True, check_same_thread=False)
        cls.conexion.row_factory = sqlite3.Row
        cls.api = mc.API(cls.conexion, raiz, lambda *a, **k: None)

    @classmethod
    def tearDownClass(cls):
        cls.conexion.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_llamadores_por_texto_sin_ruido(self):
        quienes = {x["s"]: x for x in self.api.llamadores("Servicio.procesar")}
        self.assertIn("por_local", quienes)
        if str(quienes["por_local"]["confianza"]).startswith("texto"):
            self.assertIn("instancia de Servicio", quienes["por_local"]["confianza"])
        self.assertNotIn("por_otro", quienes)        # `otro = Otro()`: es Otro.procesar
        self.assertNotIn("por_modulo", quienes)      # `herramientas.procesar()`: la función de otro módulo
        self.assertNotIn("copiar", quienes)          # `Maquina(maq.procesar)`: el atributo de un objeto local
        self.assertIn("por_fabrica", quienes)        # `fabrica() -> Servicio`
        self.assertNotIn("por_otra_fabrica", quienes)  # `otra_fabrica() -> Otro`: es Otro.procesar

    def test_los_tests_van_aparte(self):
        texto = mc.hechos_de_la_pregunta(self.banco, "¿Quién llama a `Servicio.procesar` (en `servicio.py`)?")
        self.assertIn("callers in tests: 1 (test_servicio.py)", texto)
        posibles = [l for l in texto.splitlines() if "possible callers" in l]
        self.assertFalse(any("test_servicio.py" in l for l in posibles))

    def test_camino_entre_dos_nombres(self):
        texto = mc.hechos_de_la_pregunta(self.banco, "¿Por qué funciones pasa la ejecución desde `inicio` hasta llegar a `aplicar`?")
        camino = [l for l in texto.splitlines() if l.strip().startswith("call path (graph):")]
        self.assertEqual(len(camino), 1)
        self.assertIn("inicio → intermedio → aplicar", camino[0])
        # Cada salto con la línea de su llamada (con la cadena sola, el modelo la negó 3 de 4 veces)
        self.assertRegex(texto, r"→ calls intermedio \(uso\.py:\d+\) at uso\.py:\d+: return intermedio\(\)")
        self.assertRegex(texto, r"→ calls aplicar \(uso\.py:\d+\) at uso\.py:\d+: return aplicar\(len\)")
        self.assertEqual([s["simbolo"] for s in self.api.camino_con_llamadas("inicio", "aplicar")], ["inicio", "intermedio", "aplicar"])
        self.assertEqual(len(self.api.camino("inicio", "aplicar")), 3)                     # P.camino, igual que antes
        # …y el código de la función del medio, con su número de línea (0b5f: el paquete no la traía)
        self.assertRegex(texto, r"code of the functions in the middle[^\n]*\n\s+intermedio \(uso\.py:\d+\):\n\s+\d+\s+def intermedio\(\):")

    def test_endpoints_a_dos_llamadas_por_texto(self):
        # aplicar ← intermedio (grafo) ← ver_inicio (texto: `envolver(uso.intermedio, 1)`) → GET /api/inicio
        alcance = self.api.alcance_por_texto("uso.py:aplicar")
        self.assertIn({"endpoint": "GET /api/inicio", "via": ["intermedio", "ver_inicio"]}, alcance)
        texto = mc.hechos_de_la_pregunta(self.banco, "Si cambio `aplicar` (en `uso.py`), ¿qué endpoints se ven afectados?")
        self.assertIn("GET /api/inicio (vía intermedio → ver_inicio)", texto)

    def test_una_clave_lectura_escritura_y_literal(self):
        texto = mc.hechos_de_la_pregunta(self.banco, "¿Qué funciones leen la clave de configuración `tamano_maximo`?")
        lineas = {l.strip().split(":", 1)[0]: l for l in texto.splitlines()}
        lee = lineas["reads the key (x.get / x[...])"]
        self.assertIn("leer (config.py:", lee)
        self.assertIn("tope (config.py:", lee)
        self.assertNotIn("guardar", lee)
        self.assertIn("guardar (config.py:", lineas["writes the key (x[...] = …)"])
        self.assertIn("DEFECTOS", lineas["only as a key in a dict literal (a default or a returned value, not a read)"])
        self.assertNotIn("possible misspelled key", texto)

    def test_clave_mal_escrita(self):
        texto = mc.hechos_de_la_pregunta(self.banco, "Revisa `preparar` en `config.py`. ¿Tiene algún error?")
        self.assertIn("reads config keys: tamano_maximos (config.py:", texto)
        self.assertIn("possible misspelled key: `tamano_maximos` appears only at config.py:", texto)
        self.assertIn("`tamano_maximo` (one letter apart) appears in 4 places", texto)
        self.assertNotIn("misspelled", mc.hechos_de_la_pregunta(self.banco, "Revisa `leer` en `config.py`."))

    def test_clave_mal_escrita_cuenta_cadenas_no_palabras(self):
        # E8, B5: «activa» es una palabra común (y una clase CSS en el JS): entre comillas, en Python, aparece una vez
        texto = mc.hechos_de_la_pregunta(self.banco, "Revisa `Ritmo.activo` en `ritmo_t7.py`. ¿Tiene algún error?")
        self.assertIn("possible misspelled key: `activa` appears only at ritmo_t7.py:", texto)
        self.assertIn("`activo` (one letter apart) appears in 2 places", texto)

    def test_trampa_de_timeout_sin_kill(self):
        # E8, B8: communicate() en el except TimeoutExpired sin matar al hijo espera para siempre
        mal = mc.hechos_de_la_pregunta(self.banco, "Revisa `correr` en `proceso_t7.py`. ¿Tiene algún error?")
        self.assertIn("known pitfalls in `correr`", mal)
        self.assertIn("`p.communicate()` runs without `p.kill()` first", mal)
        bien = mc.hechos_de_la_pregunta(self.banco, "Revisa `correr_bien` en `proceso_t7.py`. ¿Tiene algún error?")
        self.assertNotIn("known pitfalls", bien)
        sin_revision = mc.hechos_de_la_pregunta(self.banco, "¿Quién llama a `correr` (en `proceso_t7.py`)?")
        self.assertNotIn("known pitfalls", sin_revision)               # solo en preguntas de revisión

    def test_codigo_en_revision_literal(self):
        # E8, B4: el modelo citó de memoria la versión correcta de la función y razonó sobre su cita
        texto = mc.hechos_de_la_pregunta(self.banco, "Revisa `total` en `medidas_t7.py`. ¿Tiene algún error?")
        self.assertIn("code under review, literal from the project (medidas_t7.py:6-7", texto)
        self.assertIn("    7      return sum(_medir(x) for x in xs)", texto)
        self.assertLess(texto.index("code under review"), texto.index("· `total`"))      # antes que el resto
        self.assertNotIn("code under review", mc.hechos_de_la_pregunta(self.banco, "¿Quién llama a `total`?"))

    def test_trampa_max_de_una_lista_filtrada(self):
        # E8, B4: max() de una lista filtrada que puede quedar vacía; con la cita correcta, el modelo no lo veía
        revisa = lambda f: mc.hechos_de_la_pregunta(self.banco, f"Revisa `{f}` en `picos_t7.py`. ¿Tiene algún error?")
        self.assertIn("`max(picos)` — `picos` is a filtered list", revisa("Tramo.pico_real"))
        self.assertNotIn("known pitfalls", revisa("Tramo.pico_seguro"))     # `if picos else None`
        self.assertNotIn("known pitfalls", revisa("mas_cercana"))           # `if lista:` protege lo filtrado de lista

    def test_trampas_contextmanager_y_rutas(self):
        # E8, B7 y B3: en modo unidad, «no tiene ningún error» / «startswith es seguro» en 1 de cada 3 o 4
        revisa = lambda f: mc.hechos_de_la_pregunta(self.banco, f"Revisa `{f}` en `recursos_t7.py`. ¿Tiene algún error?")
        self.assertIn("the `yield` is not inside try/finally", revisa("abrir"))
        self.assertIn("nothing ever closes what it opened", revisa("abrir"))
        self.assertNotIn("known pitfalls", revisa("abrir_bien"))
        self.assertIn("`abs_path.startswith(root)` as a path containment check", revisa("dentro"))
        self.assertNotIn("known pitfalls", revisa("dentro_bien"))
        self.assertNotIn("known pitfalls", revisa("es_postgres"))          # una URL, no una ruta

    def test_sugiere_ejecutar(self):
        self.assertTrue(mc.sugiere_ejecutar(self.banco, "Revisa `total` en `medidas_t7.py`. ¿Tiene algún error?"))
        self.assertFalse(mc.sugiere_ejecutar(self.banco, "Revisa `Ritmo.activo` en `ritmo_t7.py`. ¿Tiene algún error?"))
        self.assertFalse(mc.sugiere_ejecutar(self.banco, "¿Quién llama a `total` (en `medidas_t7.py`)?"))

    def test_pista_para_ejecutarla(self):
        texto = mc.hechos_de_la_pregunta(self.banco, "Revisa `total` en `medidas_t7.py`. ¿Tiene algún error?")
        self.assertIn('m = P.cargar("medidas_t7.py", sustituir={"_medir": ...}); m.total(...)', texto)
        # un método (hay que construirlo) o algo con E/S no recibe la pista
        self.assertNotIn("P.cargar", mc.hechos_de_la_pregunta(self.banco, "Revisa `Ritmo.activo` en `ritmo_t7.py`. ¿Tiene algún error?"))
        self.assertNotIn("P.cargar", mc.hechos_de_la_pregunta(self.banco, "Revisa `correr` en `proceso_t7.py`. ¿Tiene algún error?"))

    def test_hechos_de_una_clave_suma_las_lecturas_literales(self):
        # a84a: P.hechos(r="lee_config") daba las lectoras del grafo y no la directa (`e.get("k")` con `e` sin nombre
        # de configuración); el modelo respondía solo con eso
        filas = {f["s"]: f for f in self.api.hechos(r="lee_config", o="modo_lector")}
        self.assertNotIn("confianza", filas["ajustes_de"])                       # del grafo
        self.assertEqual(filas["leer_de"]["confianza"], "texto: lectura literal de la clave")

    def test_una_frase_en_una_cadena_no_es_un_llamador(self):
        quienes = {x["s"] for x in self.api.llamadores("avisar")}
        self.assertNotIn("usar_aviso", quienes)                         # f"hay que avisar (pronto)"

    def test_constante_de_modulo_con_su_linea(self):
        # T7: el valor bien y la línea mal en todas las muestras (las constantes no son símbolos del banco)
        texto = mc.hechos_de_la_pregunta(self.banco, "¿Cuánto vale `DEFECTOS` en `config.py`?")
        self.assertIn('assigned at module level: config.py:1: DEFECTOS = {"tamano_maximo": 10}', texto)
        self.assertIn("assigned at module level: uso.py:5: local = Servicio()",
                      mc.hechos_de_la_pregunta(self.banco, "¿Qué es `local`?"))

    def test_nombres_importados(self):
        self.assertEqual(mc._nombres_importados(["import os, sys as s", "from a.b import (c,", "    d as e)",
                                                 "    from x import y  # adentro de una función",
                                                 "import * as M from './m.js'", "import {f, g as h} from 'n'",
                                                 "const R = require('r')"]),
                         {"os", "s", "c", "e", "y", "M", "f", "h", "R"})


CORTE_T7 = '''import os
from typing import List


def _medir(lineas: List[str]) -> int:
    import banco_proyecto
    return banco_proyecto.medir(lineas)


def cortar(lineas: List[str], tope: int) -> List[List[str]]:
    """ Corta en bloques de hasta `tope` líneas (con un error: pierde la línea del corte) """
    bloques, actual = [], []
    for i, linea in enumerate(lineas):
        if len(actual) >= tope:
            bloques.append(actual)
            actual = []
            continue
        actual.append(linea)
    if actual:
        bloques.append(actual)
    return bloques


def leer_disco(ruta):
    return open(ruta).read()


def escapar(x):
    return getattr(x, "y")


def por_dentro(x):
    return x.__class__


def con_os():
    return os.listdir(".")
'''


class TestCargar(unittest.TestCase):
    """ P.cargar: ejecutar una función del proyecto con un caso, con las mismas reglas que el código del modelo
    (E8, B2: revisando, el modelo solo podía reescribirla y elegía mal el caso) """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="prig_cargar_")
        raiz = os.path.join(cls.tmp, "p")
        os.makedirs(raiz)
        with open(os.path.join(raiz, "corte.py"), "w") as f:
            f.write(CORTE_T7)
        cls.banco = bp.BancoProyecto(raiz, carpeta=os.path.join(cls.tmp, "banco"))
        cls.banco.sincronizar()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_ejecuta_la_funcion_real_y_muestra_el_error(self):
        consola = mc.Consola(self.banco, escribir=False)
        try:
            r = consola.ejecutar('m = P.cargar("corte.py")\n'
                                 'b = m.cortar([str(i) for i in range(7)], 3)\n'
                                 'print(b, sum(len(x) for x in b))\n'
                                 'print(sorted(m.omitidos))')
        finally:
            consola.cerrar()
        self.assertIsNone(r["error"])
        self.assertIn("[['0', '1', '2'], ['4', '5', '6']] 6", r["salida"])      # se pierde la línea '3'
        # lo que no pasa la revisión de la consola no se carga: open, getattr, «__», os, el import del proyecto
        self.assertIn("['_medir', 'escapar', 'leer_disco', 'por_dentro']", r["salida"])

    def test_sustituir_y_lo_omitido_no_corre(self):
        consola = mc.Consola(self.banco, escribir=False)
        try:
            r = consola.ejecutar('m = P.cargar("corte.py", sustituir={"_medir": lambda lineas: len(lineas)})\n'
                                 'print("_medir" in m.cargados, "_medir" in m.omitidos)\n'
                                 'm.con_os()')
        finally:
            consola.cerrar()
        self.assertIn("True False", r["salida"])
        self.assertIn("NameError", r["error"] or "")                               # `os` no se importó

    def test_fuera_de_la_consola_no_carga(self):
        import sqlite3
        c = sqlite3.connect(f"file:{self.banco.ruta_db}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        try:
            with self.assertRaises(RuntimeError):
                mc.API(c, self.banco.raiz, lambda *a, **k: None).cargar("corte.py")
        finally:
            c.close()


class TestLimpiezaYMemoria(unittest.TestCase):
    def test_limpiar_codigo(self):
        # visto en el estudio: «print(P.api(...))» seguido de una «etiqueta de cierre» inventada
        self.assertEqual(mc.limpiar_codigo('```python\nprint(P.api("/x"))\n</print(P.api("/x"))\n```'), 'print(P.api("/x"))')
        self.assertEqual(mc.limpiar_codigo("a = 1 < 2\nprint(a)"), "a = 1 < 2\nprint(a)")

    def test_sin_memoria_la_consola_no_escribe(self):
        tmp = tempfile.mkdtemp(prefix="prig_sinmemoria_")
        try:
            raiz = os.path.join(tmp, "p")
            os.makedirs(raiz)
            with open(os.path.join(raiz, "a.py"), "w") as f:
                f.write("def f():\n    return 1\n")
            banco = bp.BancoProyecto(raiz, carpeta=os.path.join(tmp, "banco"))
            banco.sincronizar()
            consola = mc.Consola(banco, escribir=False)
            try:
                r = consola.ejecutar('print(P.anotar("nota", "t", "x", ["a.py"]))')
            finally:
                consola.cerrar()
            self.assertIn("memoria desactivada", r["salida"])
            with banco.conectar() as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM conocimiento").fetchone()[0], 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
