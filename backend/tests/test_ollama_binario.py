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


# La decisión de reiniciar un Ollama roto (try_autostart_ollama) está en Rust con sus pruebas: prig_ia::ollama::decidir


class PruebaMensaje(unittest.TestCase):

    ERROR_REAL = ("error starting llama-server: llama-server binary not found (checked: /usr/local/lib/ollama/llama-server, "
                  "/usr/local/bin/build/lib/ollama/llama-server). Run 'cmake -S llama/server --preset cpu && cmake --build --preset cpu' first")

    def test_error_real_explicado(self):
        texto = aec.explicar_error_motor(self.ERROR_REAL)
        self.assertIn("llama-server", texto)
        self.assertIn("Reinicia Ollama desde Prig", texto)
        self.assertIsNone(aec.explicar_error_motor("model requires more system memory"))
        self.assertIsNone(aec.explicar_error_motor(None))

    def test_en_la_prueba_de_recursos(self):
        # (la cola de descargas, ya en Rust, lo prueba en prig_ia::descargas)
        # La prueba de recursos explica el error del motor igual: un motor que falla con el error real
        # devuelve el mensaje explicado (sin GPU, sin Ollama y con un almacén temporal)
        from recursos import calibracion

        def generar(cuerpo):
            raise RuntimeError(self.ERROR_REAL)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"PRIG_RECURSOS_ARCHIVO": os.path.join(tmp, "r.json")}), \
                mock.patch.object(calibracion, "estado_gpu", return_value=None), \
                mock.patch.object(calibracion, "descargar"):
            r = calibracion.probar({"nombre": "m", "capas": 28}, {"num_ctx": 4096}, generar=generar, ps=lambda m: None)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], aec.MENSAJE_RUNTIME_INCOMPLETO[:500])


if __name__ == "__main__":
    unittest.main()
