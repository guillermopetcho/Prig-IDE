import os
import shutil
import unittest
from backend.knowledge.indexing.db_catalog import DBCatalog
from backend.knowledge.ingestion.book_ingestor import BookIngestor
from backend.ai_engine.reasoning_engine import ReasoningEngine

class TestBenchmarkPhase4A(unittest.TestCase):
    def setUp(self):
        self.test_dir = "/tmp/test_prig_benchmark_phase4a"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir, exist_ok=True)

        db_path = os.path.join(self.test_dir, "catalog.db")
        self.catalog = DBCatalog(db_path)
        self.ingestor = BookIngestor(self.catalog)

        # Ingerir libro real de prueba
        self.sample_file = os.path.join(self.test_dir, "pytorch_deep_learning.txt")
        with open(self.sample_file, "w", encoding="utf-8") as f:
            f.write(
                "Capítulo 1: Fundamentos de PyTorch y Autograd\n\n"
                "Sección 1.1 Regla de la Cadena y Backpropagation\n"
                "El algoritmo de backpropagation utiliza la regla de la cadena para calcular gradientes $\\frac{\\partial L}{\\partial w}$.\n"
                "Permite optimizar modelos de aprendizaje profundo en PyTorch.\n\n"
                "def backward_step(loss, optimizer):\n"
                "    loss.backward()\n"
                "    optimizer.step()\n\n"
                "Capítulo 2: Redes Convolucionales\n\n"
                "Sección 2.1 Capas Convolucionales en Visión 2D\n"
                "Las capas nn.Conv2d aplican filtros sobre mapas de características.\n"
            )
        self.ingestor.ingest_document(self.sample_file, category_type="book")
        self.reasoning = ReasoningEngine(self.catalog)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_benchmark_5_query_categories(self):
        queries = [
            ("CONCEPTUAL", "¿Qué es el aprendizaje profundo y PyTorch?"),
            ("MATHEMATICAL", "Cómo se calcula la derivada con la regla de la cadena en backpropagation"),
            ("CODE", "Cómo implementar loss.backward() y optimizer.step() en PyTorch"),
            ("PROCEDURAL", "Pasos paso a paso para ejecutar un paso de entrenamiento"),
            ("MULTI_HOP", "Diferencia entre convolución 2D y propagación de gradiente en redes neuronales")
        ]

        print("\n=== 📊 PRIG KNOWLEDGE BENCHMARK (Fase 4A - 6GB VRAM / 64GB RAM) ===")
        for cat, q in queries:
            res = self.reasoning.process_query(q)
            m = res["metrics"]
            ev = res["evidence"]

            self.assertIsNotNone(res["response"])
            self.assertIn("total_time_sec", m)
            self.assertGreater(m["chunks_delivered"], 0)

            print(
                f"  • [{cat:12s}] Total: {m['total_time_sec']:.3f}s | "
                f"Retrival: {m['retrieval_time_sec']:.3f}s | Rerank: {m['rerank_time_sec']:.3f}s | "
                f"LLM: {m['llm_time_sec']:.3f}s | Modelo: {res['model_used']}"
            )

        print("=== BENCHMARK COMPLETADO CON ÉXITO ===\n")

if __name__ == "__main__":
    unittest.main()
