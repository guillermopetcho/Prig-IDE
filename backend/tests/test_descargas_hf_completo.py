"""
Pruebas para el sistema de descarga completa de modelos y configuraciones desde Hugging Face.
Verifica clasificación de configs vs pesos, inspección de repositorios,
descarga por streaming, generación de manifiesto de respaldo y Modelfile.
"""

import os
import json
import shutil
import tempfile
import unittest
from unittest import mock

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import descargas_hf_completo as dhf
import descargas_modelos as dm
from buscador_modelos import ErrorBuscador


DATOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "datos_buscador")


def leer_json_prueba(nombre):
    with open(os.path.join(DATOS_DIR, nombre), "r", encoding="utf-8") as f:
        return json.load(f)


class PruebaDescargasHFCompleto(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="prig_test_hf_")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_limpiar_repo_hf(self):
        """Verifica la normalización de URLs y referencias de Hugging Face."""
        casos = [
            ("https://huggingface.co/unsloth/Qwen3-8B-GGUF", ("unsloth/Qwen3-8B-GGUF", None)),
            ("hf.co/unsloth/Qwen3-8B-GGUF:Q4_K_M", ("unsloth/Qwen3-8B-GGUF", "Q4_K_M")),
            ("huggingface.co/meta-llama/Llama-3-8B:Q8_0", ("meta-llama/Llama-3-8B", "Q8_0")),
            ("Qwen/Qwen2.5-Coder-7B", ("Qwen/Qwen2.5-Coder-7B", None)),
            ("https://hf.co/Qwen/Qwen2.5-Coder-7B/tree/main", ("Qwen/Qwen2.5-Coder-7B", None)),
        ]
        for entrada, esperado in casos:
            res = dhf.limpiar_repo_hf(entrada)
            self.assertEqual(res, esperado, f"Fallo al normalizar {entrada}")

    def test_es_archivo_config(self):
        """Distingue con precisión archivos de configuración de archivos pesados."""
        configs = [
            ("config.json", 754),
            ("generation_config.json", 300),
            ("tokenizer.json", 7000000),
            ("tokenizer_config.json", 2000),
            ("special_tokens_map.json", 500),
            ("vocab.json", 1500000),
            ("merges.txt", 1200000),
            ("chat_template.json", 1500),
            ("README.md", 25000),
            (".gitattributes", 3000),
            ("params", 178),
            ("template", 1482),
            ("imatrix_unsloth.dat", 5000000),
        ]
        for nom, tam in configs:
            self.assertTrue(dhf.es_archivo_config(nom, tam), f"Debería ser config: {nom}")

        pesos = [
            ("Qwen3-8B-Q4_K_M.gguf", 5000000000),
            ("model.safetensors", 15000000000),
            ("pytorch_model.bin", 15000000000),
            ("huge_archive.zip", 80000000),
        ]
        for nom, tam in pesos:
            self.assertFalse(dhf.es_archivo_config(nom, tam), f"NO debería ser config: {nom}")

    def test_inspeccionar_modelo_hf(self):
        """Verifica la inspección y partición en configs y pesos a partir de mock de API HF."""
        datos_repo = leer_json_prueba("hf_repo.json")
        mock_resp = mock.Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = datos_repo

        with mock.patch("requests.get", return_value=mock_resp):
            info = dhf.inspeccionar_modelo_hf("unsloth/Qwen3-8B-GGUF", variante="Q4_K_M")

            self.assertTrue(info["ok"])
            self.assertEqual(info["repo_id"], "unsloth/Qwen3-8B-GGUF")
            self.assertEqual(info["variante_elegida"], "Q4_K_M")

            # Archivos de configuración deben incluir config.json, README.md, etc.
            nombres_conf = [c["nombre"] for c in info["archivos_config"]]
            self.assertIn("config.json", nombres_conf)
            self.assertIn("README.md", nombres_conf)
            self.assertIn(".gitattributes", nombres_conf)

            # Archivos de pesos seleccionados deben contener Q4_K_M
            nombres_pesos = [p["nombre"] for p in info["archivos_pesos_seleccionados"]]
            self.assertTrue(any("Q4_K_M" in p for p in nombres_pesos))
            self.assertEqual(len(nombres_pesos), 1)

    def test_inspeccionar_modelo_hf_solo_configs(self):
        """Verifica que con variante='solo_configs' solo se seleccionen configuraciones."""
        datos_repo = leer_json_prueba("hf_repo.json")
        mock_resp = mock.Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = datos_repo

        with mock.patch("requests.get", return_value=mock_resp):
            info = dhf.inspeccionar_modelo_hf("unsloth/Qwen3-8B-GGUF", variante="solo_configs")
            self.assertTrue(info["ok"])
            self.assertEqual(len(info["archivos_pesos_seleccionados"]), 0)
            self.assertGreater(len(info["archivos_config"]), 0)

    def test_ejecutar_descarga_completa_hf_genera_manifiesto_y_modelfile(self):
        """Ejecuta simulación de descarga y valida que se cree la copia completa con configs."""
        datos_repo = {
            "siblings": [
                {"rfilename": "config.json", "size": 100},
                {"rfilename": "tokenizer.json", "size": 200},
                {"rfilename": "README.md", "size": 150},
                {"rfilename": "modelo-Q4_K_M.gguf", "size": 500},
            ],
            "gguf": {"architecture": "qwen", "chat_template": "{{ messages }}"}
        }

        # Mock de requests.get para la API y para la descarga de los archivos
        def mock_get(url, *args, **kwargs):
            r = mock.Mock()
            if "/api/models/" in url:
                r.status_code = 200
                r.json.return_value = datos_repo
                return r
            # Descarga de archivos individuales
            r.status_code = 200
            r.iter_content = lambda chunk_size: [b"dummy data chunk"]
            r.close = lambda: None
            return r

        with mock.patch("requests.get", side_effect=mock_get):
            resultado = dhf.ejecutar_descarga_completa_hf(
                repo_id="test-autor/test-modelo",
                variante="Q4_K_M",
                carpeta_destino=self.tmp_dir,
                workspace_dir=self.tmp_dir
            )

            self.assertTrue(resultado["ok"])
            
            # Verificar existencia de archivos descargados
            self.assertTrue(os.path.isfile(os.path.join(self.tmp_dir, "config.json")))
            self.assertTrue(os.path.isfile(os.path.join(self.tmp_dir, "tokenizer.json")))
            self.assertTrue(os.path.isfile(os.path.join(self.tmp_dir, "README.md")))
            self.assertTrue(os.path.isfile(os.path.join(self.tmp_dir, "modelo-Q4_K_M.gguf")))

            # Verificar manifiesto de respaldo
            ruta_manifiesto = os.path.join(self.tmp_dir, "prig_backup_manifest.json")
            self.assertTrue(os.path.isfile(ruta_manifiesto))
            with open(ruta_manifiesto, "r", encoding="utf-8") as f:
                manifiesto = json.load(f)
            self.assertEqual(manifiesto["repo_id"], "test-autor/test-modelo")
            self.assertTrue(manifiesto["preservado_contra_borrado"])
            self.assertIn("config.json", manifiesto["archivos_configuracion"])

            # Verificar Modelfile para Ollama local
            ruta_modelfile = os.path.join(self.tmp_dir, "Modelfile")
            self.assertTrue(os.path.isfile(ruta_modelfile))
            with open(ruta_modelfile, "r", encoding="utf-8") as f:
                contenido_mf = f.read()
            self.assertIn("FROM ./modelo-Q4_K_M.gguf", contenido_mf)

    def test_integracion_cola_descargas_tipo_hf_completo(self):
        """Verifica que la cola de descargas procese ítems de tipo hf_completo."""
        cola = dm.Descargas(
            base_url_fn=lambda: "http://falso",
            carpeta_modelos_fn=lambda: self.tmp_dir,
            workspace_dir_fn=lambda: self.tmp_dir
        )

        datos_repo = {
            "siblings": [
                {"rfilename": "config.json", "size": 50},
                {"rfilename": "modelo-Q4_K_M.gguf", "size": 100},
            ]
        }

        def mock_get(url, *args, **kwargs):
            r = mock.Mock()
            if "/api/models/" in url:
                r.status_code = 200
                r.json.return_value = datos_repo
                return r
            r.status_code = 200
            r.iter_content = lambda chunk_size: [b"test chunk"]
            r.close = lambda: None
            return r

        with mock.patch("requests.get", side_effect=mock_get):
            item = cola.encolar(
                ref="hf.co/autor/modelo:Q4_K_M",
                titulo="Respaldo Test",
                tipo="hf_completo",
                variante="Q4_K_M"
            )
            self.assertEqual(item["tipo"], "hf_completo")
            
            # Esperar a que el hilo complete la descarga
            import time
            inicio = time.time()
            while time.time() - inicio < 3.0:
                act = next(i for i in cola.lista() if i["id"] == item["id"])
                if act["estado"] in ("completado", "error"):
                    break
                time.sleep(0.05)
                
            self.assertEqual(act["estado"], "completado")


if __name__ == "__main__":
    unittest.main()
