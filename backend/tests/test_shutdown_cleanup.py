import os
import sys
import json
import time
import signal
import unittest
import subprocess

# Asegurar que backend/ esté en el path
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from runner import CodeRunner
from kernel_session import KernelSession, KernelSessionManager
from knowledge_service import KnowledgeService
from ai_engine import AIEngine
from agent_flows import FlowEngine


class TestShutdownCleanup(unittest.TestCase):
    def test_runner_cancel_all(self):
        """ Verifica que cancel_all() mate los procesos registrados y vacíe _active """
        runner = CodeRunner()
        # Lanzar un proceso durmiente
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True
        )
        run_id = "test_run_123"
        runner._register(run_id, proc)

        self.assertIn(run_id, runner._active)
        self.assertIsNone(proc.poll())  # Debe estar vivo

        # Ejecutar cancel_all
        runner.cancel_all()

        # Esperar brevemente a que el sistema operativo registre la señal
        time.sleep(0.3)

        self.assertEqual(len(runner._active), 0)
        self.assertIsNotNone(proc.poll())  # Debe haber terminado

    def test_kernel_session_shutdown(self):
        """ Verifica que KernelSession.shutdown termine el proceso del kernel y elimine su archivo driver """
        session = KernelSession(cwd=os.getcwd())
        self.assertTrue(session.is_alive())
        driver_path = session._driver_path
        self.assertTrue(os.path.exists(driver_path))

        # Apagar sesión
        session.shutdown()
        time.sleep(0.3)

        self.assertFalse(session.is_alive())
        self.assertFalse(os.path.exists(driver_path))

    def test_kernel_session_manager_shutdown_all(self):
        """ Verifica que shutdown_all cierre todas las sesiones persistentes registradas """
        mgr = KernelSessionManager()
        s1 = mgr.get("notebook_1.ipynb", cwd=os.getcwd())
        s2 = mgr.get("notebook_2.ipynb", cwd=os.getcwd())

        self.assertTrue(s1.is_alive())
        self.assertTrue(s2.is_alive())

        mgr.shutdown_all()
        time.sleep(0.3)

        self.assertFalse(s1.is_alive())
        self.assertFalse(s2.is_alive())
        self.assertEqual(len(mgr._sessions), 0)

    def test_ai_engine_cancel_active_requests(self):
        """ Verifica que cancel_active_requests cierre todos los streams y los vacíe """
        ai = AIEngine()

        class DummyResponse:
            def __init__(self):
                self.closed = False
            def close(self):
                self.closed = True

        r1 = DummyResponse()
        r2 = DummyResponse()
        with ai._streams_lock:
            ai._active_streams.add(r1)
            ai._active_streams.add(r2)

        count = ai.cancel_active_requests()
        self.assertEqual(count, 2)
        self.assertTrue(r1.closed)
        self.assertTrue(r2.closed)
        self.assertEqual(len(ai._active_streams), 0)

    def test_knowledge_service_stop(self):
        """ Verifica que stop() active la señal de interrupción en KnowledgeService """
        ks = KnowledgeService(books_dir=os.path.join(BACKEND_DIR, "tests"))
        self.assertFalse(ks._stop_event.is_set())
        ks.stop()
        self.assertTrue(ks._stop_event.is_set())

    def test_flow_engine_detener(self):
        """ Verifica que detener() active la señal de interrupción en FlowEngine """
        ai = AIEngine()
        fe = FlowEngine(ai_engine=ai)
        self.assertFalse(fe._stop_event.is_set())
        fe.detener()
        self.assertTrue(fe._stop_event.is_set())

    def test_app_cleanup_all_processes(self):
        """ Verifica que cleanup_all_processes se ejecute de extremo a extremo sin errores """
        from app import cleanup_all_processes
        cleanup_all_processes()

    def test_ai_resource_options_and_catalog(self):
        """ Verifica que AIEngine configure num_thread, low_vram, f16_kv, num_predict y que el catálogo contenga qwen3:14b """
        # En un archivo temporal: update_config guarda en disco, y esta prueba
        # sobrescribía la configuración de IA real del usuario (~/.prig_ai_config.json)
        # con contexto 2048, 20 capas y keep_alive 0 cada vez que se pasaba la suite.
        import tempfile
        from unittest import mock
        import ai_engine.ai_engine_class as motor_mod
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        parche = mock.patch.object(motor_mod, "CONFIG_PATH", os.path.join(tmp.name, "cfg.json"))
        parche.start()
        self.addCleanup(parche.stop)
        ai = AIEngine()
        self.assertTrue(ai.config_path.startswith(tmp.name))
        ai.update_config({
            "num_ctx": 2048,
            "num_gpu": 20,
            "num_thread": 6,
            "num_predict": 1024,
            "low_vram": True,
            "f16_kv": False,
            "keep_alive": "0",
            "temperature": 0.2
        })

        # Opciones de los modelos aisladas: nunca las del usuario
        parche_modelos = mock.patch.dict(os.environ, {"PRIG_MODELOS_ARCHIVO": os.path.join(tmp.name, "modelos.json")})
        parche_modelos.start()
        self.addCleanup(parche_modelos.stop)

        opts = ai._build_options()
        self.assertEqual(opts.get("num_ctx"), 2048)
        self.assertEqual(opts.get("num_gpu"), 20)
        self.assertEqual(opts.get("num_thread"), 6)
        self.assertEqual(opts.get("num_predict"), 1024)
        # Medido en Ollama 0.34.1: low_vram y f16_kv se aceptan pero no llegan al
        # motor, así que no se envían. Y la temperatura global no pisa la del modelo
        # salvo que el usuario lo pida.
        self.assertNotIn("low_vram", opts)
        self.assertNotIn("f16_kv", opts)
        self.assertNotIn("temperature", opts)
        ai.update_config({"muestreo_del_modelo": False})
        self.assertEqual(ai._build_options().get("temperature"), 0.2)
        self.assertEqual(ai.config.get("keep_alive"), "0")

        # Verificar que qwen3:14b está presente en el catálogo de agent_flows
        import agent_flows
        self.assertIn("qwen3:14b", agent_flows.MODELOS)
        m14 = agent_flows.MODELOS["qwen3:14b"]
        self.assertEqual(m14.get("vram_gb"), 9.3)
        self.assertEqual(m14.get("familia"), "Qwen3")

        # Verificar endpoint /api/ai/catalog
        from fastapi.testclient import TestClient
        from app import app
        client = TestClient(app)
        res = client.get("/api/ai/catalog")
        self.assertEqual(res.status_code, 200)
        catalog = res.json().get("catalog", [])
        names = [m["name"] for m in catalog]
        self.assertIn("qwen3:14b", names)
        self.assertTrue(len(catalog) >= 20)

    def test_ollama_version_and_update_endpoints(self):
        """ Verifica que /api/ai/ollama/version-info y /api/ai/ollama/update funcionen correctamente """
        from fastapi.testclient import TestClient
        from app import app, _version_ollama
        client = TestClient(app)

        # 1. Comprobar _version_ollama (debe devolver versión o '?' sin romperse)
        ver = _version_ollama()
        self.assertIsInstance(ver, str)
        self.assertTrue(len(ver) > 0)

        # 2. Comprobar endpoint version-info
        res = client.get("/api/ai/ollama/version-info")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("current_version", data)
        self.assertIn("latest_version", data)
        self.assertIn("has_update", data)
        self.assertIn("curl", data.get("command", ""))

        # 3. Endpoint update: streaming ndjson con etapa inicial.
        #
        # SIN RED Y SIN INSTALAR NADA. Esta prueba llamaba al endpoint de verdad:
        # descargaba Ollama, lo desempaquetaba sobre Prig, reiniciaba el servidor y
        # abría una terminal con `curl … install.sh | sh`. Una prueba nunca puede
        # tocar el binario de Ollama del usuario.
        from unittest import mock
        with mock.patch("requests.get", side_effect=ConnectionError("sin red en pruebas")):
            res_update = client.post("/api/ai/ollama/update")
        self.assertEqual(res_update.status_code, 200)
        lines = [line for line in res_update.text.strip().split("\n") if line.strip()]
        self.assertTrue(len(lines) >= 1)
        first_event = json.loads(lines[0])
        self.assertIn("stage", first_event)
        self.assertEqual(first_event["stage"], "inicio")
        self.assertEqual(json.loads(lines[-1])["stage"], "error")

        # 4. Endpoint launch-terminal-update, sin abrir ninguna terminal
        with mock.patch("subprocess.Popen") as popen:
            res_term = client.post("/api/ai/ollama/launch-terminal-update")
        self.assertEqual(res_term.status_code, 200)
        self.assertIn("status", res_term.json())
        for llamada in popen.call_args_list:
            self.assertIn("install.sh", " ".join(map(str, llamada.args[0])))


if __name__ == "__main__":
    unittest.main()



