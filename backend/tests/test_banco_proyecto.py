"""
Banco del proyecto (banco_proyecto.py): índice, cambios, memoria, contexto por pregunta,
herramientas del modelo y su paso por el chat. Carpetas temporales y un embebedor falso: nada
toca Ollama ni los bancos reales.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import zlib
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import banco_proyecto as bp
from herramientas_chat import Herramientas

MOTOR = '''"""Motor térmico: decide cuántos expertos caben en la GPU."""
import os
from util import leer_vram


class Motor:
    """Lanza el servidor con los expertos calientes."""

    def asegurar(self, libre):
        n = calientes_para(libre)
        return self.lanzar(n)

    def lanzar(self, n):
        return f"lanzado con {n}"


def calientes_para(vram_libre_mb):
    """Cuántos expertos calientes caben en la VRAM libre."""
    base = leer_vram()
    return max(0, int((vram_libre_mb - base) // 68))
'''

UTIL = '''def leer_vram():
    """Memoria base del modelo en MB."""
    return 2600
'''

JS = '''import { ayuda } from "./ayuda.js";

export class Carrito {
  constructor() {
    this.items = [];
  }

  agregarProducto(producto) {
    this.items.push(producto);
    return ayuda(this.items);
  }
}

export function totalCarrito(items) {
  return items.reduce((s, x) => s + x.precio, 0);
}

const formatearPrecio = (n) => `$${n.toFixed(2)}`;
'''

CPP = '''#include "vram.h"

// Reparte los expertos entre GPU y CPU
struct Reparto {
    int calientes;
    int frios;
};

static int contar_expertos(const Reparto * r) {
    return r->calientes + r->frios;
}

namespace moe {
int decidir(int libre) {
    Reparto r{libre / 68, 256 - libre / 68};
    return contar_expertos(&r);
}
}
'''

DOC = '''# Modo frío

## Pausas por ciclos
El modo frío pausa el proceso con SIGSTOP durante una fracción de cada ciclo para bajar la temperatura.

## Rampa
Al arrancar sube en rampa.
'''

TEST = '''from motor import calientes_para

def test_calientes_para():
    assert calientes_para(5000) > 0
'''


class EmbebedorFalso:
    """ Vector de palabras por hash: textos con las mismas palabras se parecen """

    def __init__(self):
        self.llamadas = 0
        self.textos = 0

    def __call__(self, textos):
        self.llamadas += 1
        self.textos += len(textos)
        salida = []
        for t in textos:
            v = [0.0] * 64
            for palabra in bp.terminos(t):
                v[hash(palabra) % 64] += 1.0
            v[0] += 0.01
            salida.append(v)
        return salida

    def en_gpu(self):
        return True


def escribir(raiz, rel, texto):
    ruta = os.path.join(raiz, rel)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(texto)
    # mtime distinto aunque la prueba escriba dos veces en el mismo instante
    st = os.stat(ruta)
    os.utime(ruta, (st.st_atime, st.st_mtime + 0.5 + time.time() % 1))


class BaseBanco(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_banco_")
        self.raiz = os.path.join(self.tmp, "proyecto")
        self.datos = os.path.join(self.tmp, "bancos")
        escribir(self.raiz, "motor.py", MOTOR)
        escribir(self.raiz, "util.py", UTIL)
        escribir(self.raiz, "web/carrito.js", JS)
        escribir(self.raiz, "web/ayuda.js", "export function ayuda(x) { return x.length; }\n")
        escribir(self.raiz, "nativo/moe.cpp", CPP)
        escribir(self.raiz, "nativo/vram.h", "int vram_libre();\n")
        escribir(self.raiz, "docs/modo-frio.md", DOC)
        escribir(self.raiz, "tests/test_motor.py", TEST)
        escribir(self.raiz, "node_modules/x/index.js", "function no() {}\n")
        escribir(self.raiz, "datos.bin", "\0\0binario")
        self.emb = EmbebedorFalso()
        self.banco = bp.BancoProyecto(self.raiz, carpeta=self.datos, embeber=self.emb)
        self.r0 = self.banco.sincronizar()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestIndice(BaseBanco):
    def test_indexado_inicial_ignora_dependencias_y_binarios(self):
        self.assertTrue(self.r0["inicial"])
        with self.banco.conectar() as c:
            rutas = {f["ruta"] for f in c.execute("SELECT ruta FROM archivos")}
        self.assertIn("motor.py", rutas)
        self.assertIn("web/carrito.js", rutas)
        self.assertNotIn("node_modules/x/index.js", rutas)
        self.assertNotIn("datos.bin", rutas)
        self.assertEqual(self.banco.cambios_desde(0), [])     # lo inicial no son «cambios»

    def test_sin_cambios_no_relee(self):
        with mock.patch.object(bp.BancoProyecto, "_indexar_archivo") as indexar:
            r = self.banco.sincronizar()
        indexar.assert_not_called()
        self.assertEqual(r["modificados"] + r["borrados"], 0)
        self.assertEqual(r["version"], self.r0["version"])

    def test_simbolos_python(self):
        with self.banco.conectar() as c:
            s = {f["nombre"]: dict(f) for f in c.execute("SELECT * FROM simbolos WHERE ruta = 'motor.py'")}
        self.assertEqual(set(s), {"Motor", "Motor.asegurar", "Motor.lanzar", "calientes_para"})
        self.assertEqual(s["calientes_para"]["tipo"], "funcion")
        self.assertEqual(s["Motor.asegurar"]["tipo"], "metodo")
        self.assertIn("VRAM libre", s["calientes_para"]["doc"])
        self.assertEqual(s["calientes_para"]["firma"], "def calientes_para(vram_libre_mb)")

    def test_simbolos_js_y_cpp(self):
        with self.banco.conectar() as c:
            js = {f["nombre"] for f in c.execute("SELECT nombre FROM simbolos WHERE ruta = 'web/carrito.js'")}
            cpp = {f["nombre"]: dict(f) for f in c.execute("SELECT * FROM simbolos WHERE ruta = 'nativo/moe.cpp'")}
        self.assertTrue({"Carrito", "Carrito.agregarProducto", "totalCarrito", "formatearPrecio"} <= js, js)
        self.assertIn("Reparto", cpp)
        self.assertIn("contar_expertos", cpp)
        self.assertIn("moe.decidir", cpp)
        self.assertIn("Reparte los expertos", cpp["Reparto"]["doc"])

    def test_grafo_de_usos_e_importaciones(self):
        with self.banco.conectar() as c:
            llama = {f["nombre"] for f in c.execute("SELECT nombre FROM usos WHERE dentro = 'Motor.asegurar'")}
            imports = {(f["ruta"], f["destino"]) for f in c.execute("SELECT * FROM importaciones")}
        self.assertTrue({"calientes_para", "lanzar"} <= llama)
        self.assertIn(("motor.py", "util.py"), imports)
        self.assertIn(("web/carrito.js", "web/ayuda.js"), imports)
        self.assertIn(("nativo/moe.cpp", "nativo/vram.h"), imports)

    def test_markdown_por_secciones_sin_duplicar(self):
        with self.banco.conectar() as c:
            frags = [dict(f) for f in c.execute("SELECT simbolo, texto FROM fragmentos WHERE ruta = 'docs/modo-frio.md'")]
        pausas = [f for f in frags if f["simbolo"] == "Pausas por ciclos"][0]
        self.assertIn("SIGSTOP", pausas["texto"])
        self.assertNotIn("Rampa", pausas["texto"])


class TestCambios(BaseBanco):
    def test_modificacion_con_diff_y_simbolos(self):
        escribir(self.raiz, "motor.py", MOTOR.replace("// 68", "// 70") + "\n\ndef nueva():\n    return 1\n")
        r = self.banco.sincronizar()
        self.assertEqual(r["modificados"], 1)
        cambios = self.banco.cambios_desde(self.r0["version"])
        self.assertEqual(len(cambios), 1)
        ch = cambios[0]
        self.assertEqual(ch["ruta"], "motor.py")
        self.assertIn("calientes_para", ch["simbolos"]["modificados"])
        self.assertIn("nueva", ch["simbolos"]["nuevos"])
        self.assertIn("-    return max(0, int((vram_libre_mb - base) // 68))", ch["diff"])
        self.assertIn("+    return max(0, int((vram_libre_mb - base) // 70))", ch["diff"])

    def test_nuevo_y_borrado(self):
        escribir(self.raiz, "extra.py", "def extra():\n    pass\n")
        os.remove(os.path.join(self.raiz, "util.py"))
        self.banco.sincronizar()
        tipos = {c["ruta"]: c["tipo"] for c in self.banco.cambios_desde(self.r0["version"])}
        self.assertEqual(tipos, {"extra.py": "nuevo", "util.py": "borrado"})
        with self.banco.conectar() as c:
            self.assertIsNone(c.execute("SELECT 1 FROM simbolos WHERE ruta = 'util.py'").fetchone())

    def test_solo_se_reembebe_lo_que_cambio(self):
        self.banco.indexar_vectores(maximo=10000)
        antes = self.emb.textos
        self.assertEqual(self.banco.vectores_pendientes(), 0)
        escribir(self.raiz, "motor.py", MOTOR.replace("// 68", "// 70"))
        self.banco.sincronizar()
        self.assertEqual(self.banco.vectores_pendientes(), 1)     # solo calientes_para cambió
        self.banco.indexar_vectores(maximo=10000)
        self.assertEqual(self.emb.textos - antes, 1)

    def test_conocimiento_se_marca_para_revisar(self):
        self.banco.anotar("definicion", "experto caliente", "Experto que vive en la GPU.", ["motor.py"])
        self.banco.anotar("decision", "sin ramp", "No hay rampa con turbo apagado.", ["docs/modo-frio.md"])
        escribir(self.raiz, "motor.py", MOTOR + "\n# cambio\n")
        self.banco.sincronizar()
        estado = {k["titulo"]: k["revisar"] for k in self.banco.listar_conocimiento()}
        self.assertGreater(estado["experto caliente"], 0)
        self.assertEqual(estado["sin ramp"], 0)
        # Reescribirla la da por revisada
        self.banco.anotar("definicion", "experto caliente", "Experto en la GPU (actualizado).", ["motor.py"])
        self.assertEqual({k["titulo"]: k["revisar"] for k in self.banco.listar_conocimiento()}["experto caliente"], 0)


class TestBusquedaYContexto(BaseBanco):
    def test_buscar_por_nombre_y_por_palabras(self):
        r = self.banco.buscar("¿qué hace calientes_para?", k=3)
        self.assertEqual(r[0]["simbolo"], "calientes_para")
        r = self.banco.buscar("cómo se pausa con SIGSTOP en el modo frío", k=3)
        self.assertEqual(r[0]["ruta"], "docs/modo-frio.md")
        r = self.banco.buscar("agregar producto al carrito", k=3)
        self.assertEqual(r[0]["simbolo"], "Carrito.agregarProducto")

    def test_tests_pesan_menos_salvo_que_se_pidan(self):
        r = self.banco.buscar("calientes_para", k=10)
        rutas = [f["ruta"] for f in r]
        self.assertLess(rutas.index("motor.py"), rutas.index("tests/test_motor.py"))

    def test_vecinos_del_grafo(self):
        r = self.banco.buscar("Motor.asegurar", k=1)
        vecinos = self.banco.vecinos(r)
        nombres = {v["nombre"] for v in vecinos}
        self.assertIn("calientes_para", nombres)

    def test_componer_respeta_presupuesto_y_trae_cambios_memoria_y_resoluciones(self):
        self.banco.indexar_vectores(maximo=10000)
        self.banco.anotar("definicion", "experto caliente", "Experto que se calcula en la GPU.", ["motor.py"])
        self.banco.registrar_resolucion("¿cuántos expertos calientes caben en la VRAM?",
                                        "Lo decide calientes_para en motor.py restando la base.", "m")
        escribir(self.raiz, "motor.py", MOTOR.replace("// 68", "// 70"))
        self.banco.sincronizar()
        r = self.banco.componer("¿cuántos expertos calientes caben en la VRAM libre?", presupuesto=1500)
        self.assertLessEqual(r["tokens"], 1700)
        texto = r["texto"]
        self.assertIn("Cambios en el proyecto desde tu última respuesta", texto)
        self.assertIn("motor.py: modificado", texto)
        self.assertIn("experto caliente", texto)
        self.assertIn("puede estar desactualizado", texto)
        self.assertIn("Preguntas parecidas ya resueltas", texto)
        self.assertIn("después cambiaron: motor.py", texto)
        self.assertIn("motor.py:", texto)
        self.assertIn("calientes_para", texto)

    def test_registrar_resolucion_marca_lo_visto(self):
        escribir(self.raiz, "util.py", UTIL + "\n# x\n")
        self.banco.sincronizar()
        self.assertEqual(self.banco.componer("vram", 2000)["cambios"], 1)
        i = self.banco.registrar_resolucion("¿qué devuelve leer_vram?", "### Archivo: util.py\nDevuelve 2600.", "m")
        self.assertEqual(self.banco.resolucion(i)["rutas"], ["util.py"])
        self.assertEqual(self.banco.componer("vram", 2000)["cambios"], 0)

    def test_mapa_estable_y_dentro_del_presupuesto(self):
        mapa = self.banco.mapa(2000)
        self.assertIn("motor.py", mapa)
        self.assertIn("calientes_para", mapa)
        self.assertIn("Motor térmico", mapa)
        escribir(self.raiz, "motor.py", MOTOR.replace("// 68", "// 70"))     # editar sin tocar la estructura
        self.banco.sincronizar()
        self.assertEqual(self.banco.mapa(2000), mapa)
        pequeño = self.banco.mapa(120)
        self.assertLessEqual(bp.estimar_tokens(pequeño), 200)

    def test_analisis_con_ia_solo_lo_que_cambio(self):
        vistos = []

        def generar(prompt):
            vistos.append(prompt)
            return json.dumps({"resumen": "Hace cosas.",
                               "definiciones": [{"termino": "reparto", "definicion": "División GPU/CPU."}],
                               "decisiones": ["Se usa 68 MB por experto porque así se midió."]})
        r = self.banco.analizar(generar)
        self.assertEqual(r["errores"], 0)
        self.assertEqual(r["pendientes"], 0)
        hechos = r["hechos"]
        self.assertGreater(hechos, 3)
        self.assertIn("Hace cosas.", self.banco.mapa(3000))
        titulos = [k["titulo"] for k in self.banco.listar_conocimiento()]
        self.assertIn("reparto", titulos)
        escribir(self.raiz, "util.py", UTIL + "\n# x\n")
        self.banco.sincronizar()
        vistos.clear()
        self.assertEqual(self.banco.analizar(generar)["hechos"], 1)
        self.assertIn("util.py", vistos[0])

    def test_sintesis_jerarquica_solo_rehace_lo_que_cambia(self):
        pedidos = []

        def generar(prompt):
            pedidos.append(prompt)
            if "Folder:" in prompt:
                carpeta = prompt.split("Folder: ", 1)[1].split("\n", 1)[0]
                return json.dumps({"resumen": f"Resumen de {carpeta}", "relaciones": "Se conecta con motor.py."})
            return json.dumps({"resumen": "Proyecto de prueba con motor, web y nativo."})
        r = self.banco.sintetizar(generar)
        self.assertEqual(r["errores"], 0)
        with self.banco.conectar() as c:
            carpetas = {f["clave"]: f["texto"] for f in c.execute("SELECT clave, texto FROM resumenes WHERE nivel = 'carpeta'")}
        self.assertTrue({"web", "nativo", "docs", "tests"} <= set(carpetas), carpetas)
        self.assertIn("Resumen de web", carpetas["web"])
        mapa = self.banco.mapa(3000)
        self.assertIn("Proyecto de prueba", mapa)
        self.assertEqual(self.banco.trabajo_pendiente()["carpetas"], 0)
        pedidos.clear()
        self.assertEqual(self.banco.sintetizar(generar)["carpetas"], 0)      # nada cambió
        self.assertEqual(pedidos, [])
        escribir(self.raiz, "web/nuevo.js", "export function nuevo() { return 1; }\n")
        self.banco.sincronizar()
        self.assertEqual(self.banco.trabajo_pendiente()["carpetas"], 1)
        self.banco.sintetizar(generar)
        self.assertTrue(any("Folder: web/" in p for p in pedidos))
        self.assertFalse(any("Folder: nativo/" in p for p in pedidos))

    def test_guardia_hace_esperar(self):
        motivos = ["el chat está respondiendo", None]
        progreso = []
        with mock.patch("time.sleep"):
            ok = bp.BancoProyecto._esperar(lambda: motivos.pop(0) if motivos else None, None, progreso.append)
        self.assertTrue(ok)
        self.assertEqual(progreso[0], {"esperando": "el chat está respondiendo"})
        cancelar = threading.Event()
        cancelar.set()
        self.assertFalse(bp.BancoProyecto._esperar(lambda: "calor", cancelar, None))

    def test_resumir_respuesta(self):
        r = bp.resumir_respuesta("Se arregla cambiando el divisor.\n\n### Archivo: motor.py\n```python\n"
                                 "def calientes_para(x):\n    return x\n```\nListo.")
        self.assertIn("Se arregla cambiando el divisor.", r)
        self.assertIn("Archivos: motor.py", r)
        self.assertIn("Código: calientes_para", r)


class TestHerramientas(BaseBanco):
    def test_herramientas_del_banco(self):
        h = Herramientas(banco=self.banco)
        nombres = {d["function"]["name"] for d in h.definiciones()}
        self.assertTrue({"ver_simbolo", "anotar"} <= nombres)
        self.assertNotIn("buscar_proyecto", nombres)            # duplicaba P.buscar
        self.assertNotIn("consola", nombres)                    # sin sesión de consola no se ofrece
        self.assertIn("return max(0", h.ejecutar("ver_simbolo", {"nombre": "calientes_para"}))
        self.assertIn("Guardado", h.ejecutar("anotar", {"tipo": "teoria", "titulo": "MoE",
                                                        "texto": "Mezcla de expertos.", "rutas": ["motor.py"]}))
        self.assertIn("Mezcla de expertos", self.banco.recordar("MoE expertos"))
        self.assertEqual(h.rutas_consultadas, [])

    def test_sin_banco_no_se_ofrecen(self):
        h = Herramientas()
        self.assertNotIn("ver_simbolo", {d["function"]["name"] for d in h.definiciones() if d})
        self.assertIn("no disponible", h.ejecutar("ver_simbolo", {"nombre": "x"}))


class TestRegistro(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_bancos_")
        self.raiz = os.path.join(self.tmp, "p")
        escribir(self.raiz, "a.py", "def a():\n    return 1\n")
        self.entorno = mock.patch.dict(os.environ, {"PRIG_BANCOS": os.path.join(self.tmp, "bancos")})
        self.entorno.start()

    def tearDown(self):
        self.entorno.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_vigilante_ve_los_cambios_solo(self):
        bancos = bp.Bancos(intervalo=0.05)
        banco = bancos.para(self.raiz)
        banco.sincronizar()
        bancos.vigilar(self.raiz)
        try:
            escribir(self.raiz, "b.py", "def b():\n    return 2\n")
            limite = time.time() + 5
            while time.time() < limite and not banco.cambios_desde(0):
                time.sleep(0.05)
            self.assertEqual([c["ruta"] for c in banco.cambios_desde(0)], ["b.py"])
        finally:
            bancos.detener()

    def test_borrar(self):
        bancos = bp.Bancos()
        bancos.para(self.raiz).sincronizar()
        self.assertTrue(bancos.existe(self.raiz))
        self.assertTrue(bancos.borrar(self.raiz))
        self.assertFalse(bancos.existe(self.raiz))

    def test_embebedor_elige_gpu_o_cpu(self):
        pedidos = []

        class Respuesta:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"embeddings": [[1.0, 0.0]]}).encode()

        def abrir(req, timeout=0):
            pedidos.append(json.loads(req.data))
            return Respuesta()
        usada = []
        libre = [True]
        e = bp.Embebedor(gpu_libre=lambda: libre[0], al_usar_gpu=lambda: usada.append(1))
        with mock.patch("urllib.request.urlopen", abrir):
            e(["x"])
            libre[0] = False
            e(["y"])
        self.assertEqual(pedidos[0]["options"], {"num_gpu": 999})
        self.assertEqual(usada, [1])
        self.assertEqual(pedidos[1]["options"], {"num_gpu": 0})


class TestChat(unittest.TestCase):
    """ El chat con el banco: contexto, mapa, herramientas y la resolución guardada """

    def setUp(self):
        import app as main_app
        self.app = main_app
        self.tmp = tempfile.mkdtemp(prefix="prig_banco_chat_")
        self.raiz = os.path.join(self.tmp, "proyecto")
        escribir(self.raiz, "motor.py", MOTOR)
        escribir(self.raiz, "util.py", UTIL)
        self.parches = [
            mock.patch.dict(os.environ, {"PRIG_BANCOS": os.path.join(self.tmp, "bancos")}),
            mock.patch.object(main_app.file_mgr, "base_dir", self.raiz),
            mock.patch.object(main_app, "bancos", bp.Bancos(intervalo=3600)),
        ]
        for p in self.parches:
            p.start()

    def tearDown(self):
        self.app.bancos.detener()
        for p in reversed(self.parches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_chat_con_banco(self):
        vistos = {}

        def chat_eventos(mensajes, modelo, uso, **kw):
            vistos["mensajes"] = mensajes
            vistos["herramientas"] = kw.get("herramientas")
            vistos["max_rondas"] = kw.get("max_rondas")
            yield {"t": "texto", "v": "Lo decide calientes_para en motor.py."}
        req = self.app.AIChatRequest(prompt="¿Qué hace calientes_para?", model="qwen2.5-coder:7b",
                                     eventos=True, banco=True)
        with mock.patch.object(self.app.ai_engine, "chat_eventos", chat_eventos), \
                mock.patch.object(self.app.ai_engine, "capacidades", lambda m: ["completion", "tools"]):
            res = self.app.ai_chat(req)
            import asyncio

            async def leer():
                return [c async for c in res.body_iterator]
            lineas = [json.loads(x) for x in "".join(
                (c.decode() if isinstance(c, bytes) else c) for c in asyncio.run(leer())).splitlines() if x.strip()]
        info = [e["v"] for e in lineas if e["t"] == "banco"][0]
        self.assertGreater(info["fragmentos"], 0)
        self.assertIn("motor.py", info["archivos"])
        sistema = vistos["mensajes"][0]["content"]
        pregunta = vistos["mensajes"][-1]["content"]
        self.assertIn("BANCO DEL PROYECTO", sistema)
        self.assertIn("MAPA DEL PROYECTO", pregunta)
        self.assertIn("def calientes_para", pregunta)
        self.assertIsNotNone(vistos["herramientas"])
        self.assertIsNotNone(vistos["herramientas"].banco)
        self.assertEqual(vistos["max_rondas"], 16)
        self.assertIn("MEMORIA DE CONSULTA", sistema)
        self.assertIsNotNone(vistos["herramientas"].consola)
        self.assertIn("consola", {d["function"]["name"] for d in vistos["herramientas"].definiciones()})
        self.assertIsNone(vistos["herramientas"].consola._proc)      # cerrada al terminar
        banco = self.app.bancos.para(self.raiz)
        resoluciones = banco.listar_resoluciones()
        self.assertEqual(len(resoluciones), 1)
        self.assertEqual(resoluciones[0]["rutas"], ["motor.py"])

    def test_modo_unidad(self):
        """ Si el enrutador elige una unidad leída, la conversación usa su prefijo guardado y las
        herramientas fijas de la lectura """
        vistos = {}

        def chat_eventos(mensajes, modelo, uso, **kw):
            vistos["mensajes"] = mensajes
            vistos["herramientas"] = kw.get("herramientas")
            yield {"t": "texto", "v": "Vale 0.3."}

        class LectorFalso:
            def mensajes(self, u):
                return [{"role": "system", "content": "LECTOR"}, {"role": "user", "content": "UNIDAD " + u["nombre"]}]
        unidad = {"orden": 3, "nombre": "nucleo", "cuota": 0.8, "lector": LectorFalso(), "datos": {"nombre": "nucleo"}}
        req = self.app.AIChatRequest(prompt="¿Cuánto vale X?", model="qwen3.6-35b-moe:prig", eventos=True, banco=True)
        with mock.patch.object(self.app.ai_engine, "chat_eventos", chat_eventos), \
                mock.patch.object(self.app.ai_engine, "capacidades", lambda m: ["completion", "tools"]), \
                mock.patch.object(self.app, "_unidad_para", lambda *a: unidad):
            res = self.app.ai_chat(req)
            import asyncio

            async def leer():
                return [c async for c in res.body_iterator]
            eventos = [json.loads(x) for x in "".join((c.decode() if isinstance(c, bytes) else c)
                                                       for c in asyncio.run(leer())).splitlines() if x.strip()]
        self.assertEqual([m["content"] for m in vistos["mensajes"]], ["LECTOR", "UNIDAD nucleo", "¿Cuánto vale X?"])
        import lectura_unidades
        self.assertEqual(vistos["herramientas"].solo, list(lectura_unidades.HERRAMIENTAS_UNIDAD))
        info = [e["v"] for e in eventos if e["t"] == "banco"][0]
        self.assertEqual(info["modo"], "unidad")
        self.assertEqual(info["unidad"], "nucleo")

    def test_empujon_si_anuncia_sin_hacer(self):
        llamadas = []

        def chat_eventos(mensajes, modelo, uso, **kw):
            llamadas.append(mensajes)
            if len(llamadas) == 1:
                yield {"t": "texto", "v": "La llama crear. Ahora busco qué endpoints llaman a crear."}
            else:
                yield {"t": "texto", "v": "Los endpoints son POST /api/crear."}
        req = self.app.AIChatRequest(prompt="¿Qué endpoints afecta crear?", model="qwen2.5-coder:7b",
                                     eventos=True, banco=True)
        with mock.patch.object(self.app.ai_engine, "chat_eventos", chat_eventos), \
                mock.patch.object(self.app.ai_engine, "capacidades", lambda m: ["completion", "tools"]):
            res = self.app.ai_chat(req)
            import asyncio

            async def leer():
                return [c async for c in res.body_iterator]
            texto = "".join(json.loads(x)["v"] for x in "".join(
                (c.decode() if isinstance(c, bytes) else c) for c in asyncio.run(leer())).splitlines()
                if x.strip() and json.loads(x)["t"] == "texto")
        self.assertEqual(len(llamadas), 2)
        self.assertEqual(llamadas[1][-1]["content"], self.app.EMPUJON)
        self.assertEqual(llamadas[1][-2]["role"], "assistant")
        self.assertIn("POST /api/crear", texto)

    def test_endpoints(self):
        from starlette.testclient import TestClient
        cliente = TestClient(self.app.app)
        self.assertFalse(cliente.get("/api/banco").json()["existe"])
        self.assertEqual(cliente.get("/api/banco/conocimiento").status_code, 404)
        r = cliente.post("/api/banco/activar").json()
        self.assertEqual(r["banco"]["archivos"], 2)
        self.assertEqual(cliente.post("/api/banco/conocimiento", json={
            "tipo": "definicion", "titulo": "base", "texto": "VRAM del modelo sin expertos.",
            "rutas": ["util.py"]}).status_code, 200)
        self.assertEqual(len(cliente.get("/api/banco/conocimiento").json()["conocimiento"]), 1)
        resultados = cliente.get("/api/banco/buscar", params={"q": "leer_vram"}).json()["resultados"]
        self.assertEqual(resultados[0]["ruta"], "util.py")
        self.assertIn("MAPA DEL PROYECTO", cliente.get("/api/banco/mapa").json()["texto"])
        r = cliente.post("/api/banco/consola", json={"codigo": "n = len(P.archivos())\nn"}).json()
        self.assertEqual(r["salida"].strip(), "2")
        self.assertEqual(cliente.post("/api/banco/consola", json={"codigo": "n * 10"}).json()["salida"].strip(), "20")
        self.app._consola_usuario["consola"].cerrar()
        self.assertTrue(cliente.delete("/api/banco").json()["borrado"])


if __name__ == "__main__":
    unittest.main()
