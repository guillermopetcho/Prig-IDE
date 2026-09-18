"""
Motor suave: el modo suave dentro del proceso del modelo.

  · el envoltorio se instala y se retira dejando el llama-server original byte a byte,
    sobrevive a que Ollama se actualice y solo actúa al cargar un modelo;
  · la biblioteca nativa (contra una libcudart falsa compilada aquí):
      - espera con un evento bloqueante en vez de girar (salvo PRIG_SUAVE_GIRO),
      - encuentra libcudart aunque esté cargada en un ámbito local,
      - dosifica en la proporción pedida y deja de hacerlo si el control caduca,
      - escribe su estado para que Prig sepa que está actuando;
  · el controlador convierte temperatura y actividad en la fracción de trabajo;
  · con el motor dosificando, el gobernador no corta peticiones por ritmo.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from recursos import motor_suave as ms  # noqa: E402
from recursos import ritmo as rt  # noqa: E402

GCC = shutil.which("gcc") or shutil.which("cc")
ELF = b"\x7fELF\x02\x01\x01lanzador original de ollama"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lib = os.path.join(self.tmp, "lib", "ollama")
        os.makedirs(self.lib)
        with open(os.path.join(self.lib, "llama-server"), "wb") as f:
            f.write(ELF)
        os.chmod(os.path.join(self.lib, "llama-server"), 0o755)
        self.entorno = mock.patch.dict(os.environ, {
            "PRIG_OLLAMA_LIB": self.lib, "PRIG_SUAVE_SO": os.path.join(self.tmp, "prig", "prig_suave.so"),
            "PRIG_SUAVE_CONTROL": os.path.join(self.tmp, "control")})
        self.entorno.start()

    def tearDown(self):
        self.entorno.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


@unittest.skipUnless(GCC, "hace falta gcc")
class TestInstalar(Base):
    def test_instalar_y_desinstalar_exacto(self):
        r = ms.instalar()
        self.assertTrue(r["ok"] and r["instalado"] and r["cambiado"])
        self.assertTrue(os.path.exists(os.environ["PRIG_SUAVE_SO"]))
        with open(os.path.join(self.lib, "llama-server.real"), "rb") as f:
            self.assertEqual(f.read(), ELF)
        with open(os.path.join(self.lib, "llama-server")) as f:
            guion = f.read()
        self.assertIn(ms.MARCA_ENVOLTORIO, guion)
        self.assertIn(os.environ["PRIG_SUAVE_SO"], guion)
        self.assertIn("--poll 0", guion)
        self.assertTrue(ms.instalado())
        self.assertFalse(ms.instalar()["cambiado"])                  # idempotente
        ms.desinstalar()
        with open(os.path.join(self.lib, "llama-server"), "rb") as f:
            self.assertEqual(f.read(), ELF)
        self.assertFalse(os.path.exists(os.path.join(self.lib, "llama-server.real")))
        self.assertFalse(ms.instalado())

    def test_ollama_se_actualiza(self):
        ms.instalar()
        nuevo = b"\x7fELF version nueva"
        with open(os.path.join(self.lib, "llama-server"), "wb") as f:   # la actualización pisa el envoltorio
            f.write(nuevo)
        ms.instalar()
        with open(os.path.join(self.lib, "llama-server.real"), "rb") as f:
            self.assertEqual(f.read(), nuevo)
        self.assertTrue(ms.instalado())

    def test_sin_ollama_propio(self):
        os.remove(os.path.join(self.lib, "llama-server"))
        r = ms.instalar()
        self.assertFalse(r["ok"])
        self.assertIn("propio Ollama", r["motivo"])

    def test_el_envoltorio_solo_actua_al_cargar_un_modelo(self):
        ms.instalar()
        falso = os.path.join(self.lib, "llama-server.real")
        with open(falso, "w") as f:
            f.write('#!/bin/sh\necho "PRELOAD=$LD_PRELOAD CONTROL=$PRIG_SUAVE_CONTROL ARGS=$*"\n')
        os.chmod(falso, 0o755)
        envoltorio = os.path.join(self.lib, "llama-server")
        salida = subprocess.run([envoltorio, "--model", "/m/blob", "-c", "4096"], capture_output=True, text=True).stdout
        self.assertIn(f"PRELOAD={os.environ['PRIG_SUAVE_SO']}", salida)
        self.assertIn("ARGS=--model /m/blob -c 4096 --poll 0", salida)
        salida = subprocess.run([envoltorio, "--version"], capture_output=True, text=True).stdout
        self.assertIn("PRELOAD= ", salida)
        self.assertIn("ARGS=--version", salida)
        salida = subprocess.run([envoltorio, "--model", "x"], capture_output=True, text=True,
                                env={**os.environ, "PRIG_SUAVE_DESACTIVADO": "1"}).stdout
        self.assertNotIn("--poll", salida)


CUDART_FALSA = r"""
#include <stdio.h>
#include <time.h>
static int n_sync = 0, n_evento = 0, flags = -1;
static void trabajar(void) { struct timespec t = {0, 2000000}; nanosleep(&t, NULL); }   /* 2 ms de «GPU» */
int cudaStreamSynchronize(void *s) { n_sync++; trabajar(); return 0; }
int cudaEventCreateWithFlags(void **e, unsigned f) { static int x; *e = &x; flags = (int)f; return 0; }
int cudaEventRecord(void *e, void *s) { return 0; }
int cudaEventSynchronize(void *e) { n_evento++; trabajar(); return 0; }
void cuenta(int *a, int *b, int *c) { *a = n_sync; *b = n_evento; *c = flags; }
"""

PROGRAMA = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <time.h>
int main(int argc, char **argv) {
    /* libcudart en ámbito LOCAL, como la carga el motor */
    void *h = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    int (*sync)(void *) = dlsym(RTLD_DEFAULT, "cudaStreamSynchronize");    /* la de prig_suave */
    void (*cuenta)(int *, int *, int *) = dlsym(h, "cuenta");
    if (!sync) { printf("sin interposicion\n"); return 1; }
    struct timespec a, b; clock_gettime(CLOCK_MONOTONIC, &a);
    for (int i = 0; i < 100; i++) sync(0);
    clock_gettime(CLOCK_MONOTONIC, &b);
    int s, e, f; cuenta(&s, &e, &f);
    printf("%.3f %d %d %d\n", (b.tv_sec - a.tv_sec) + (b.tv_nsec - a.tv_nsec) / 1e9, s, e, f);
    return 0;
}
"""


@unittest.skipUnless(GCC, "hace falta gcc")
class TestBibliotecaNativa(Base):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.cudart = os.path.join(cls.dir, "libcudart.so.13")
        cls.prog = os.path.join(cls.dir, "prog")
        for nombre, codigo in (("cudart.c", CUDART_FALSA), ("prog.c", PROGRAMA)):
            with open(os.path.join(cls.dir, nombre), "w") as f:
                f.write(codigo)
        subprocess.run([GCC, "-shared", "-fPIC", "-Wl,-soname,libcudart.so.13", "-o", cls.cudart, os.path.join(cls.dir, "cudart.c")], check=True)
        subprocess.run([GCC, "-o", cls.prog, os.path.join(cls.dir, "prog.c"), "-ldl"], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def correr(self, control=None, **extra):
        so = ms.compilar()["ruta"]
        if control is not None:
            with open(os.environ["PRIG_SUAVE_CONTROL"], "w") as f:
                f.write(control)
        entorno = {**os.environ, "LD_PRELOAD": so, **extra}
        salida = subprocess.run([self.prog, self.cudart], capture_output=True, text=True, env=entorno, timeout=60).stdout.split()
        return float(salida[0]), int(salida[1]), int(salida[2]), int(salida[3])

    def test_espera_bloqueante_por_evento(self):
        dur, n_sync, n_evento, flags = self.correr()
        self.assertEqual((n_sync, n_evento), (0, 100))                # nunca la espera que gira
        self.assertEqual(flags, 0x01 | 0x02)                          # BlockingSync | DisableTiming
        self.assertLess(dur, 0.5)                                    # sin control: sin pausas (100 × 2 ms)
        _, n_sync, n_evento, _ = self.correr(PRIG_SUAVE_GIRO="1")
        self.assertEqual((n_sync, n_evento), (100, 0))

    def test_dosifica_en_la_proporcion_pedida(self):
        base, *_ = self.correr()
        dur, *_ = self.correr(control=f"0.5 0.01 {time.time():.3f}")
        # Mide tiempos reales: con la máquina cargada (la suite entera en marcha) hay ruido,
        # así que se comprueba el orden de magnitud, no el decimal
        self.assertGreater(dur / base, 1.5)                           # al 50 %: en torno al doble
        self.assertLess(dur / base, 3.0)
        dur, *_ = self.correr(control=f"0.25 0.01 {time.time():.3f}")
        self.assertGreater(dur / base, 2.8)                           # al 25 %: en torno al cuádruple

    def test_control_caducado_no_frena(self):
        base, *_ = self.correr()
        dur, *_ = self.correr(control=f"0.2 0.01 {time.time() - 60:.3f}")   # Prig cerrado hace un minuto
        self.assertLess(dur / base, 1.4)

    def test_escribe_su_estado(self):
        self.correr(control=f"0.5 0.01 {time.time():.3f}")
        e = ms.leer_estado()
        self.assertIsNotNone(e)
        self.assertAlmostEqual(e["fraccion"], 0.5)
        self.assertTrue(ms.generando(e))
        self.assertFalse(ms.generando({**e, "ultima": time.time() - 10}))


class MonitorFalso:
    def __init__(self, temp):
        self.temp = temp

    def gpu(self, max_edad=2.5):
        return self.temp

    def tendencia_gpu(self, desde=None):
        return 0.0


class TestControlador(Base):
    def escribir_estado(self, hace_s):
        with open(os.environ["PRIG_SUAVE_CONTROL"] + ".estado", "w") as f:
            f.write(f"123 {time.time() - hace_s:.3f} 1.0 0.02 800\n")

    def leer_control(self):
        with open(os.environ["PRIG_SUAVE_CONTROL"]) as f:
            d, q, marca = f.read().split()
        return float(d), float(q), float(marca)

    def test_temperatura_y_rampa_al_archivo(self):
        r = rt.Ritmo({"objetivo_c": 60, "rampa_s": 0, "ritmo_minimo": 0.3, "tramo_motor_s": 0.02})
        c = ms.Controlador(r, MonitorFalso(45))
        self.escribir_estado(0.1)
        self.assertTrue(c.paso()["generando"])
        d, q, marca = self.leer_control()
        self.assertEqual((d, q), (1.0, 0.02))
        self.assertLess(time.time() - marca, 2)
        # Calor: la fracción baja, pero despacio (BAJADA por paso) y con la temperatura suavizada
        c.monitor.temp = 62
        anteriores = [1.0]
        for _ in range(40):
            self.escribir_estado(0.1)
            c.paso()
            anteriores.append(self.leer_control()[0])
        pasos = [a - b for a, b in zip(anteriores, anteriores[1:])]
        self.assertTrue(all(-1e-9 <= p <= ms.Controlador.BAJADA + 1e-6 for p in pasos))
        self.assertAlmostEqual(anteriores[-1], 0.3, places=2)
        # Se enfría: vuelve a subir, más despacio todavía (SUBIDA por paso)
        c.monitor.temp = 40
        for _ in range(3):
            self.escribir_estado(0.1)
            c.paso()
        self.assertLessEqual(self.leer_control()[0], 0.3 + 3 * ms.Controlador.SUBIDA + 1e-6)

    def test_parado_arranca_suave(self):
        r = rt.Ritmo({"objetivo_c": 60, "rampa_s": 40, "ritmo_minimo": 0.25, "inicio_rampa": 0.2})
        c = ms.Controlador(r, MonitorFalso(40))
        self.escribir_estado(60)                                     # el motor está parado
        self.assertFalse(c.paso()["generando"])
        self.assertEqual(self.leer_control()[0], 0.25)                # arranque suave (no menos que el mínimo)

    def test_modo_suave_apagado_quita_el_control(self):
        r = rt.Ritmo({"activo": False})
        ms.escribir_control(0.5, 0.02)
        ms.Controlador(r, MonitorFalso(70)).paso()
        self.assertFalse(os.path.exists(os.environ["PRIG_SUAVE_CONTROL"]))


class TestGobernador(Base):
    def test_con_el_motor_dosificando_no_se_cortan_peticiones(self):
        from recursos.termico import Gobernador
        g = Gobernador(MonitorFalso(58), guardar=False)
        g.ajustes["limite_gpu"] = 80.0
        g.ritmo = rt.Ritmo({"objetivo_c": 60, "rampa_s": 0, "tramo_s": 1.0, "cpu_eficiente": False})
        tramo = g.empezar_tramo()
        tramo.inicio -= 1.5
        self.assertEqual(g.debe_cortar(tramo), "ritmo")               # sin motor suave: pausa la petición
        g.motor_suave = {"ok": True, "instalado": True}
        with mock.patch.object(ms, "generando", return_value=True):
            tramo = g.empezar_tramo()
            tramo.inicio -= 1.5
            self.assertIsNone(g.debe_cortar(tramo))                    # lo hace el motor por dentro
            g.monitor.temp = 80
            self.assertEqual(g.debe_cortar(tramo), "limite")          # el corte de emergencia sigue


if __name__ == "__main__":
    unittest.main()
