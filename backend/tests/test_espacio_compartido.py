""" El espacio de trabajo lo abre el servidor de Rust y lo guarda en ~/.prig_config.json: el backend de Python lo
toma en su siguiente petición y reapunta sus servicios (rebind_workspace). Solo con una carpeta que exista. """

import json
import os
import shutil
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

import app


class PruebaEspacioCompartido(unittest.TestCase):
    def setUp(self):
        self.cliente = TestClient(app.app)
        self.base = app.file_mgr.base_dir
        self.cfg = app.file_mgr.config_path
        self.copia = open(self.cfg).read() if os.path.exists(self.cfg) else None
        self.nueva = tempfile.mkdtemp(prefix="prig_espacio_")
        self.cliente.get("/api/workspace")                       # que vea la configuración de partida

    def tearDown(self):
        if self.copia is None:
            if os.path.exists(self.cfg):
                os.remove(self.cfg)
        else:
            with open(self.cfg, "w") as f:
                f.write(self.copia)
        app.file_mgr.base_dir = self.base
        app.rebind_workspace(self.base)
        shutil.rmtree(self.nueva, ignore_errors=True)

    def escribir(self, datos):
        time.sleep(0.01)
        with open(self.cfg, "w") as f:
            json.dump(datos, f)

    def test_toma_la_carpeta_que_abrio_rust(self):
        self.escribir({"last_workspace": self.nueva, "segunda_carpeta": self.nueva})
        r = self.cliente.get("/api/workspace").json()
        self.assertEqual(r["path"], self.nueva)
        self.assertEqual(app.file_mgr.segunda_dir, self.nueva)
        self.assertEqual(app.explorador.workspace, os.path.abspath(self.nueva))

    def test_una_carpeta_que_no_existe_no_se_toma(self):
        antes = self.cliente.get("/api/workspace").json()["path"]
        self.escribir({"last_workspace": "/no/existe/prig"})
        self.assertEqual(self.cliente.get("/api/workspace").json()["path"], antes)


if __name__ == "__main__":
    unittest.main()
