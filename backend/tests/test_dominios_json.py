"""
`catalogos/dominios.json` es la copia que lee el servidor de Rust de la taxonomía de `kaggle_worker/domains.py` (el
trabajador de Kaggle necesita su módulo autónomo). Si se cambia uno, hay que regenerar el otro:

    .venv/bin/python -c "import sys,json; sys.path.insert(0,'kaggle_worker'); import domains as d; ..."

(ver docs/plan-prig-rust.md, tanda 34).
"""

import json
import os
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(RAIZ, "kaggle_worker"))

import domains  # noqa: E402


class PruebaDominiosJson(unittest.TestCase):
    def test_la_copia_de_rust_es_igual(self):
        with open(os.path.join(RAIZ, "backend", "catalogos", "dominios.json"), encoding="utf-8") as f:
            datos = json.load(f)
        self.assertEqual(datos["DOMAINS"], domains.DOMAINS)
        self.assertEqual([tuple(e) for e in datos["DOMAIN_EDGES"]], domains.DOMAIN_EDGES)
        self.assertEqual(datos["KNOWN_BRIDGES"], domains.KNOWN_BRIDGES)
        self.assertEqual(datos["CODE_LANGUAGES"], domains.CODE_LANGUAGES)


if __name__ == "__main__":
    unittest.main()
