""" El catálogo de modelos que usa el servidor de Rust (prig-ia/src/catalogo_modelos.json) es una copia de
agent_flows.MODELOS y MODELOS_EMBEDDING: si se cambia uno, hay que regenerar el otro. """

import json
import os
import unittest

import agent_flows

RUTA = os.path.join(os.path.dirname(__file__), "..", "..", "backend-rust", "crates", "prig-ia", "src",
                    "catalogo_modelos.json")


class PruebaCatalogoRust(unittest.TestCase):
    def test_igual_que_agent_flows(self):
        with open(RUTA, encoding="utf-8") as f:
            copia = json.load(f)
        self.assertEqual(copia["modelos"], agent_flows.MODELOS,
                         "Regenera catalogo_modelos.json desde agent_flows.MODELOS")
        self.assertEqual(copia["embedding"], agent_flows.MODELOS_EMBEDDING)
        self.assertEqual(list(copia["modelos"]), list(agent_flows.MODELOS))     # mismo orden


if __name__ == "__main__":
    unittest.main()
