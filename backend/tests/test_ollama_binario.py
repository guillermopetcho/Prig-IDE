"""
Qué Ollama arranca Prig.

Caso real: había dos Ollama 0.34.1 idénticos, el de Prig (bin/ollama, con su carpeta
lib/ollama) y uno en /usr/local/bin copiado sin lib/ollama. A igual versión ganaba el
último de la lista, Prig arrancaba el incompleto y todo modelo fallaba con
«llama-server binary not found» (y sin GPU). Lo que se protege:

  · un Ollama sin su llama-server nunca gana a uno completo, aunque sea más nuevo;
  · a igual versión y estado gana el primero de la lista (el de Prig);
  · si ya hay un Ollama roto respondiendo, se reinicia con el completo;
  · el error se explica en castellano con qué hacer.
"""

import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_engine import AIEngine
from ai_engine import ai_engine_class as aec


class _Instalaciones(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prig_ollama_bin_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ejecutable(self, ruta, contenido):
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w") as f:
            f.write(contenido)
        os.chmod(ruta, os.stat(ruta).st_mode | stat.S_IEXEC)
        return ruta

    def ollama(self, nombre, version, motor="completo"):
        """ <tmp>/<nombre>/bin/ollama con lib/ollama completo, incompleto o sin carpeta """
        raiz = os.path.join(self.tmp, nombre)
        binario = self.ejecutable(os.path.join(raiz, "bin", "ollama"), f"#!/bin/sh\necho 'ollama version is {version}'\n")
        lib = os.path.join(raiz, "lib", "ollama")
        if motor == "completo":
            self.ejecutable(os.path.join(lib, "llama-server"), "#!/bin/sh\n")
        elif motor == "incompleto":
            os.makedirs(os.path.join(lib, "cuda_v12"))
            open(os.path.join(lib, "LLAMA_CPP_LICENSE"), "w").close()
        return binario


class PruebaEstadoRuntime(_Instalaciones):

    def test_completo_incompleto_y_desconocido(self):
        self.assertEqual(aec.estado_runtime_ollama(self.ollama("prig", "0.34.1")), aec.RUNTIME_COMPLETO)
        self.assertEqual(aec.estado_runtime_ollama(self.ollama("usr", "0.34.1", "incompleto")), aec.RUNTIME_INCOMPLETO)
        self.assertEqual(aec.estado_runtime_ollama(self.ollama("viejo", "0.3.0", "sin_lib")), aec.RUNTIME_DESCONOCIDO)

    def test_llama_server_sin_permiso_de_ejecucion_no_cuenta(self):
        binario = self.ollama("raro", "0.34.1", "sin_lib")
        motor = os.path.join(self.tmp, "raro", "lib", "ollama", "llama-server")
        os.makedirs(os.path.dirname(motor))
        open(motor, "w").close()
        self.assertEqual(aec.estado_runtime_ollama(binario), aec.RUNTIME_INCOMPLETO)

    def test_enlace_simbolico_se_resuelve(self):
        """ /usr/local/bin/ollama → /opt/ollama/bin/ollama busca lib junto al destino """
        real = self.ollama("opt", "0.34.1")
        enlace = os.path.join(self.tmp, "otro", "bin", "ollama")
        os.makedirs(os.path.dirname(enlace))
        os.symlink(real, enlace)
        self.assertEqual(aec.estado_runtime_ollama(enlace), aec.RUNTIME_COMPLETO)


class PruebaElegirBinario(_Instalaciones):

    def elegir(self, candidatos):
        with mock.patch.object(AIEngine, "_candidatos_ollama", return_value=candidatos):
            return AIEngine().get_best_ollama_binary()

    def test_caso_real_mismo_binario_sin_lib_en_usr_local(self):
        prig = self.ollama("prig", "0.34.1")
        usr = self.ollama("usr", "0.34.1", "incompleto")
        self.assertEqual(self.elegir([prig, usr]), (prig, "0.34.1"))
        self.assertEqual(self.elegir([usr, prig]), (prig, "0.34.1"))

    def test_incompleto_no_gana_aunque_sea_mas_nuevo(self):
        prig = self.ollama("prig", "0.34.1")
        nuevo_roto = self.ollama("usr", "0.40.0", "incompleto")
        self.assertEqual(self.elegir([prig, nuevo_roto]), (prig, "0.34.1"))

    def test_a_igual_estado_gana_la_version_y_luego_el_primero(self):
        prig = self.ollama("prig", "0.34.1")
        local = self.ollama("local", "0.35.0")
        otro = self.ollama("otro", "0.34.1")
        self.assertEqual(self.elegir([prig, local, otro]), (local, "0.35.0"))
        self.assertEqual(self.elegir([prig, otro]), (prig, "0.34.1"))

    def test_si_solo_hay_incompleto_se_usa(self):
        """ Mejor avisar con el error explicado que no arrancar nada """
        usr = self.ollama("usr", "0.34.1", "incompleto")
        self.assertEqual(self.elegir(["", "/no/existe/ollama", usr]), (usr, "0.34.1"))
        self.assertIsNone(self.elegir(["", "/no/existe/ollama"]))

    def test_mismo_archivo_por_dos_rutas_cuenta_una_vez(self):
        prig = self.ollama("prig", "0.34.1")
        enlace = os.path.join(self.tmp, "enlace-ollama")
        os.symlink(prig, enlace)
        with mock.patch.object(aec.subprocess, "run", wraps=aec.subprocess.run) as run:
            self.elegir([prig, enlace])
        self.assertEqual(run.call_count, 1)


class PruebaReiniciarSiEstaRoto(_Instalaciones):

    def arrancar(self, en_marcha, mejor, version_activa="0.34.1"):
        motor = AIEngine()
        respuesta = mock.Mock(status_code=200)
        respuesta.json.return_value = {"version": version_activa}
        with mock.patch.object(AIEngine, "get_best_ollama_binary", return_value=(mejor, "0.34.1")), \
                mock.patch.object(AIEngine, "binario_ollama_en_marcha", return_value=en_marcha), \
                mock.patch.object(aec.requests, "get", return_value=respuesta), \
                mock.patch.object(AIEngine, "kill_ollama_processes") as matar, \
                mock.patch.object(aec.subprocess, "Popen") as popen, \
                mock.patch.object(aec.time, "sleep"):
            motor.try_autostart_ollama()
        return matar, popen

    def test_ollama_roto_en_marcha_se_cambia_por_el_completo(self):
        prig = self.ollama("prig", "0.34.1")
        usr = self.ollama("usr", "0.34.1", "incompleto")
        matar, popen = self.arrancar(en_marcha=usr, mejor=prig)
        matar.assert_called_once()
        self.assertEqual(popen.call_args.args[0], [prig, "serve"])

    def test_ollama_sano_en_marcha_no_se_toca(self):
        prig = self.ollama("prig", "0.34.1")
        otro = self.ollama("otro", "0.34.1")
        for en_marcha in (prig, otro, None):          # None: no se ve el proceso (otro usuario, servicio)
            matar, popen = self.arrancar(en_marcha=en_marcha, mejor=prig)
            matar.assert_not_called()
            popen.assert_not_called()

    def test_si_el_mejor_tambien_esta_roto_no_se_reinicia_en_bucle(self):
        usr = self.ollama("usr", "0.34.1", "incompleto")
        usr2 = self.ollama("usr2", "0.34.1", "incompleto")
        matar, popen = self.arrancar(en_marcha=usr, mejor=usr2)
        matar.assert_not_called()


class PruebaMensaje(unittest.TestCase):

    ERROR_REAL = ("error starting llama-server: llama-server binary not found (checked: /usr/local/lib/ollama/llama-server, "
                  "/usr/local/bin/build/lib/ollama/llama-server). Run 'cmake -S llama/server --preset cpu && cmake --build --preset cpu' first")

    def test_error_real_explicado(self):
        texto = aec.explicar_error_motor(self.ERROR_REAL)
        self.assertIn("llama-server", texto)
        self.assertIn("Reinicia Ollama desde Prig", texto)
        self.assertIsNone(aec.explicar_error_motor("model requires more system memory"))
        self.assertIsNone(aec.explicar_error_motor(None))

    def test_en_la_cola_de_descargas_y_en_la_prueba_de_recursos(self):
        import descargas_modelos
        self.assertEqual(descargas_modelos.explicar_error(self.ERROR_REAL), aec.MENSAJE_RUNTIME_INCOMPLETO)
        from recursos import calibracion
        import inspect
        self.assertIn("explicar_error_motor", inspect.getsource(calibracion.probar))


if __name__ == "__main__":
    unittest.main()
