"""
Modo frío: modelos en RAM sin calentar la CPU.

  · el controlador ajusta la parte de cada ciclo en que trabajan los motores de los modelos en
    RAM según la temperatura de la CPU: arranca suave, sube y baja en rampas, nunca se para del
    todo, y en reposo no lee sensores;
  · el pausador congela y reanuda un proceso real en la proporción pedida, nunca lo deja
    congelado, y por pidfd no toca a otro proceso si el motor terminó;
  · apagado o sin modelos en RAM, no pausa nada;
  · el ayudante de root (recursos/nativo/prig-energia) valida sus argumentos, apaga el turbo,
    pasa a ahorro, pone el tope de potencia y lo deshace todo; con auto-cpufreq se lo pide a él
    en lugar de escribir el turbo por debajo (su demonio lo volvería a encender).

Sin hardware ni root: /sys falso en una carpeta temporal; el ayudante se ejecuta como usuario con
PRIG_ENERGIA_RAIZ.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from recursos import energia, frio  # noqa: E402

AYUDANTE = os.path.join(RAIZ, "recursos", "nativo", "prig-energia")


class PausadorFalso:
    def __init__(self):
        self.llamadas = []
        self.procesos = {}

    def fijar(self, pids, fraccion):
        self.llamadas.append((set(pids), fraccion))

    def cerrar(self):
        pass


class TestControlador(unittest.TestCase):
    def setUp(self):
        self.temps = [40.0]
        self.lecturas = 0
        self.t = [0.0]
        self.ajustes = {"activo": True, "objetivo_c": 60}
        self.en_ram = {111}
        self.cpu = {111: 0.0}
        self.pausador = PausadorFalso()

        def leer_temp():
            self.lecturas += 1
            return self.temps[0]
        self.turbo_apagado = False
        self.c = frio.ControladorFrio(lambda: self.ajustes, leer_temp, lambda: self.en_ram,
                                      pausador=self.pausador, reloj=lambda: self.t[0],
                                      sin_turbo=lambda: self.turbo_apagado)
        self.tiempo = mock.patch.object(frio.Proceso, "tiempo_cpu", lambda p: self.cpu.get(p.pid))
        self.tiempo.start()

    def tearDown(self):
        self.tiempo.stop()

    def paso(self, nucleos_sin_pausa):
        """ Un segundo en el que el motor querría usar `nucleos_sin_pausa` (se le descuenta la pausa) """
        self.t[0] += 1.0
        self.cpu[111] += nucleos_sin_pausa * (self.c.fraccion or 1.0)
        return self.c.paso()

    def test_reposo_arranque_suave_sin_leer_sensores(self):
        self.paso(0)
        r = self.paso(0)
        self.assertFalse(r["generando"])
        self.assertEqual(r["fraccion"], frio.INICIO)
        self.assertEqual(self.pausador.llamadas[-1], ({111}, frio.INICIO))
        self.assertEqual(self.lecturas, 0)                                      # en reposo no se mide nada

    def test_frio_sube_en_rampa_y_caliente_baja(self):
        self.paso(0)
        self.paso(0)
        fracciones = [self.paso(4)["fraccion"] for _ in range(5)]
        self.assertAlmostEqual(fracciones[0], frio.INICIO + self.c.SUBIDA, places=6)   # no salta: sube de a poco
        self.assertTrue(all(b - a <= self.c.SUBIDA + 1e-9 for a, b in zip(fracciones, fracciones[1:])))
        self.temps[0] = 90.0
        bajando = [self.paso(4)["fraccion"] for _ in range(12)]
        self.assertTrue(all(a - b <= self.c.BAJADA + 1e-9 for a, b in zip([fracciones[-1]] + bajando, bajando)))
        self.assertEqual(bajando[-1], frio.MINIMO)                              # nunca se para del todo
        self.assertTrue(all(r["generando"] for r in [self.c.ultimo]))          # con pausas sigue contando como trabajo

    def test_holgura_del_motor_moe_sin_turbo(self):
        """ El motor MoE con el turbo apagado solo se pausa por encima del objetivo: a 57 °C (objetivo
        60) trabaja sin pausas; a 66 °C sí se le frena """
        self.c.holgura = lambda pids: frio.HOLGURA_MOE_SIN_TURBO_C if pids == {111} else 0.0
        self.turbo_apagado = True
        self.temps[0] = 57.0
        self.paso(0)
        fracciones = [self.paso(4)["fraccion"] for _ in range(4)]
        self.assertEqual(fracciones, [1.0] * 4)
        self.assertEqual(self.c.ultimo["objetivo_efectivo_c"], 60 + frio.HOLGURA_MOE_SIN_TURBO_C)
        self.temps[0] = 66.0
        frenado = [self.paso(4)["fraccion"] for _ in range(6)]
        self.assertLess(frenado[-1], 1.0)
        self.c.holgura = lambda pids: 0.0                     # otro motor en RAM: sin holgura
        self.temps[0] = 57.0
        self.paso(0)
        self.paso(0)
        self.assertLess(self.paso(4)["fraccion"], 1.0)

    def test_sin_turbo_arranca_sin_rampa(self):
        """ Sin turbo no hay salto de temperatura: la respuesta arranca con lo que permite la
        temperatura del momento, no desde el 30 % (con la CPU fresca, sin pausas) """
        self.turbo_apagado = True
        self.temps[0] = 48.0                                                    # objetivo 60: sin pausas
        self.paso(0)
        self.assertEqual(self.paso(0)["fraccion"], 1.0)
        self.assertEqual(self.paso(4)["fraccion"], 1.0)
        self.temps[0] = 57.0                                                    # cerca del objetivo: baja en rampa
        f = [self.paso(4)["fraccion"] for _ in range(4)]
        self.assertTrue(all(a - b <= self.c.BAJADA + 1e-9 for a, b in zip([1.0] + f, f)))
        self.assertLess(f[-1], 1.0)
        self.paso(0)
        self.temps[0] = 58.0                                                    # respuesta nueva, CPU tibia
        self.paso(0)
        self.assertAlmostEqual(self.paso(4)["fraccion"],
                               frio.ControladorFrio.fraccion_objetivo(58.0, 60.0), places=3)

    def test_termostato_proporcional(self):
        f = frio.ControladorFrio.fraccion_objetivo
        self.assertEqual(f(None, 60), 1.0)
        self.assertEqual(f(45, 60), 1.0)
        self.assertEqual(f(60, 60), frio.MINIMO)
        self.assertEqual(f(80, 60), frio.MINIMO)
        valores = [f(t, 60) for t in range(50, 62)]
        self.assertEqual(valores, sorted(valores, reverse=True))

    def test_sin_modelos_en_ram_o_apagado_no_pausa(self):
        self.en_ram = set()
        r = self.paso(4)
        self.assertEqual(r["en_ram"], 0)
        self.assertEqual(self.pausador.llamadas[-1], (set(), 1.0))
        self.en_ram = {111}
        self.ajustes["activo"] = False
        self.paso(4)
        self.assertEqual(self.pausador.llamadas[-1], (set(), 1.0))


class TestPausador(unittest.TestCase):
    """ Con un proceso de verdad: congelar y reanudar por ciclos """

    def ocupado(self):
        import subprocess
        return subprocess.Popen([sys.executable, "-c", "while True: pass"])

    def estado(self, pid):
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0]

    def test_al_50_por_ciento_usa_la_mitad_y_nunca_queda_congelado(self):
        import time
        p = self.ocupado()
        pausador = frio.Pausador()
        try:
            time.sleep(0.3)
            t0, c0 = time.time(), frio.Proceso(p.pid).tiempo_cpu()
            pausador.fijar({p.pid}, 0.5)
            time.sleep(2.0)
            uso = (frio.Proceso(p.pid).tiempo_cpu() - c0) / (time.time() - t0)
            self.assertGreater(uso, 0.3)
            self.assertLess(uso, 0.7)
            pausador.cerrar()
            time.sleep(0.1)
            self.assertNotEqual(self.estado(p.pid), "T")                         # quedó trabajando
        finally:
            pausador.cerrar()
            p.kill()
            p.wait()

    def test_quitarlo_de_la_lista_lo_reanuda(self):
        import time
        p = self.ocupado()
        pausador = frio.Pausador()
        try:
            pausador.fijar({p.pid}, 0.2)
            time.sleep(0.5)
            pausador.fijar(set(), 1.0)
            time.sleep(0.1)
            self.assertNotEqual(self.estado(p.pid), "T")
        finally:
            pausador.cerrar()
            p.kill()
            p.wait()

    @unittest.skipUnless(hasattr(os, "pidfd_open"), "sin pidfd")
    def test_un_proceso_terminado_no_recibe_nada(self):
        """ Por pidfd: si el motor termina, su número no apunta a otro proceso """
        import subprocess
        p = subprocess.Popen(["sleep", "30"])
        proc = frio.Proceso(p.pid)
        p.kill()
        p.wait()
        self.assertFalse(proc.senal(0))
        proc.cerrar()

    def test_reanudar_huerfanos(self):
        import subprocess, signal as sig, time
        p = self.ocupado()
        try:
            os.kill(p.pid, sig.SIGSTOP)
            time.sleep(0.1)
            self.assertEqual(self.estado(p.pid), "T")
            with mock.patch.object(frio, "motores_de_prig", return_value=[{"pid": p.pid, "blob": "x", "estado": "stopped"}]):
                self.assertEqual(frio.reanudar_huerfanos(), 1)
            time.sleep(0.1)
            self.assertNotEqual(self.estado(p.pid), "T")
        finally:
            os.kill(p.pid, sig.SIGCONT)
            p.kill()
            p.wait()


class TestAyudanteEnergia(unittest.TestCase):
    """ El script que corre como root, ejecutado como usuario sobre un /sys falso """

    def setUp(self):
        self.raiz = tempfile.mkdtemp()
        self.escribir("/sys/devices/system/cpu/intel_pstate/no_turbo", "0")
        rapl = "/sys/class/powercap/intel-rapl:0"
        self.escribir(f"{rapl}/constraint_0_power_limit_uw", "45000000")
        self.escribir(f"{rapl}/constraint_0_max_power_uw", "55000000")
        for n in range(4):
            self.escribir(f"/sys/devices/system/cpu/cpu{n}/cpufreq/scaling_governor", "performance")
        self.env = mock.patch.dict(os.environ, {"PRIG_ENERGIA_RAIZ": self.raiz, "PRIG_ENERGIA_AYUDANTE": AYUDANTE,
                                                "PRIG_ENERGIA_SIN_PKEXEC": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.raiz, ignore_errors=True)

    def escribir(self, ruta, texto):
        p = self.raiz + ruta
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(texto + "\n")

    def leer(self, ruta):
        with open(self.raiz + ruta) as f:
            return f.read().strip()

    def test_frio_y_normal_sin_auto_cpufreq(self):
        e = energia.estado()
        self.assertEqual((e["turbo"], e["pl1_w"], e["modo"], e["gobernador"]), (True, 45, "normal", "performance"))
        e = energia.frio(20)
        self.assertEqual((e["turbo"], e["pl1_w"], e["modo"], e["gobernador"]), (False, 20, "frio", "powersave"))
        self.assertEqual(self.leer("/sys/devices/system/cpu/cpu3/cpufreq/scaling_governor"), "powersave")
        self.assertEqual(self.leer("/run/prig-energia/pl1_original"), "45000000")
        energia.frio(25)                                                        # repetir no pisa el original
        self.assertEqual(self.leer("/run/prig-energia/pl1_original"), "45000000")
        e = energia.normal()
        self.assertEqual((e["turbo"], e["pl1_w"], e["modo"], e["gobernador"]), (True, 45, "normal", "performance"))

    def test_valida_los_argumentos(self):
        for malo in (5, 70, "20"):
            with self.assertRaises(energia.ErrorEnergia):
                energia.frio(malo)
        # El propio script también valida (corre como root: no se fía de nadie)
        import subprocess
        for args in (["frio", "abc"], ["frio", "5"], ["frio", "60"], ["frio"], ["borrar"], ["frio", "20; rm -rf /"]):
            r = subprocess.run([AYUDANTE, *args], capture_output=True, text=True, env={**os.environ})
            self.assertNotEqual(r.returncode, 0, args)
            self.assertFalse(json.loads(r.stdout)["ok"])
        self.assertEqual(self.leer("/sys/devices/system/cpu/intel_pstate/no_turbo"), "0")   # nada cambió

    def test_con_auto_cpufreq_se_lo_pide_a_el(self):
        registro = os.path.join(self.raiz, "llamadas.txt")
        falso = self.raiz + "/snap/bin/auto-cpufreq"
        os.makedirs(os.path.dirname(falso))
        with open(falso, "w") as f:
            f.write(f'#!/bin/sh\necho "$@" >> "{registro}"\n')
        os.chmod(falso, 0o755)
        energia.frio(20)
        energia.normal()
        with open(registro) as f:
            llamadas = f.read().split("\n")
        self.assertEqual(llamadas[:4], ["--turbo=never", "--force=powersave", "--turbo=auto", "--force=reset"])
        # El turbo no se tocó por debajo: lo gestiona auto-cpufreq
        self.assertEqual(self.leer("/sys/devices/system/cpu/intel_pstate/no_turbo"), "0")
        self.assertTrue(energia.estado()["auto_cpufreq"])

    def test_sin_instalar_pide_instalar(self):
        with mock.patch.dict(os.environ, {"PRIG_ENERGIA_AYUDANTE": ""}), \
                mock.patch.object(energia, "AYUDANTE", os.path.join(self.raiz, "no-existe")):
            self.assertFalse(energia.instalacion()["instalado"])
            with self.assertRaises(energia.ErrorEnergia):
                energia.frio(20)

    def test_ayudante_ajeno_no_se_usa(self):
        """ Un ayudante que el usuario podría modificar no se ejecuta con root """
        falso = os.path.join(self.raiz, "prig-energia")
        shutil.copy(AYUDANTE, falso)
        politica = os.path.join(self.raiz, "politica.policy")
        open(politica, "w").write("x")
        with mock.patch.dict(os.environ, {"PRIG_ENERGIA_AYUDANTE": ""}), \
                mock.patch.object(energia, "AYUDANTE", falso), mock.patch.object(energia, "POLITICA", politica):
            inst = energia.instalacion()
            self.assertTrue(inst["instalado"])
            self.assertFalse(inst["seguro"])                                     # es del usuario, no de root
            with self.assertRaises(energia.ErrorEnergia):
                energia.frio(20)

    def test_la_politica_pide_contrasena(self):
        with open(energia.FUENTE_POLITICA) as f:
            texto = f.read()
        self.assertIn("<allow_active>auth_admin_keep</allow_active>", texto)
        self.assertIn("<allow_any>no</allow_any>", texto)
        self.assertIn(energia.AYUDANTE, texto)


if __name__ == "__main__":
    unittest.main()
