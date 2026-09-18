import os
import shutil
import unittest
from backend.knowledge.indexing.db_catalog import DBCatalog
from backend.knowledge.ingestion.book_ingestor import BookIngestor
from backend.knowledge.retrieval.hybrid_retriever import HybridRetriever
from backend.knowledge.retrieval.reranker import ExplicableReranker
from backend.knowledge.retrieval.context_distiller import ContextDistiller
from backend.knowledge.evidence.evidence_builder import EvidenceBuilder

class TestRetrievalEngine(unittest.TestCase):
    def setUp(self):
        self.test_dir = "/tmp/test_prig_retrieval_engine"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir, exist_ok=True)

        db_path = os.path.join(self.test_dir, "catalog.db")
        self.catalog = DBCatalog(db_path)
        self.ingestor = BookIngestor(self.catalog)

        # Ingerir documento de prueba con texto, código y ecuaciones
        self.sample_file = os.path.join(self.test_dir, "pytorch_guide.txt")
        with open(self.sample_file, "w", encoding="utf-8") as f:
            f.write(
                "Capítulo 1: Fundamentos de PyTorch\n\n"
                "Sección 1.1 Autograd y Backpropagation\n"
                "Backpropagation calcula la derivada parcial \\frac{\\partial L}{\\partial w} usando la regla de la cadena.\n"
                "Se utiliza para optimizar redes neuronales profundas mediante gradiente descendente.\n\n"
                "def backward_pass(loss):\n"
                "    loss.backward()\n"
                "    optimizer.step()\n\n"
                "Capítulo 2: Redes Convolucionales (CNN)\n\n"
                "Sección 2.1 Convoluciones en 2D\n"
                "Las capas convolucionales procesan imágenes aplicando filtros de kernel.\n"
            )
        self.ingestor.ingest_document(self.sample_file, category_type="book")

        self.retriever = HybridRetriever(self.catalog)
        self.reranker = ExplicableReranker(self.catalog)
        self.evidence_builder = EvidenceBuilder(self.catalog)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_full_retrieval_pipeline(self):
        query = "Cómo funciona la derivada de backpropagation y cómo se implementa en PyTorch"
        
        # 1. Recuperación híbrida (BM25 + Vector)
        candidates = self.retriever.retrieve(query, top_k=10)
        self.assertGreater(len(candidates), 0)

        # 2. Re-ranking explicable
        reranked = self.reranker.rerank(candidates, query, top_k=5)
        self.assertGreater(len(reranked), 0)
        self.assertIn("bm25_score", reranked[0])
        self.assertIn("vector_score", reranked[0])
        self.assertIn("structure_score", reranked[0])
        self.assertIn("reasons", reranked[0])

        # 3. Construcción de Evidencia
        ev = self.evidence_builder.build_evidence(reranked, "Backpropagation")
        self.assertTrue(ev["has_evidence"])
        self.assertEqual(ev["evidence_strength"], "DIRECT")

        # 4. Destilación de Contexto
        distilled = ContextDistiller.distill_context(reranked, query)
        self.assertGreater(distilled["total_chunks_distilled"], 0)
        self.assertIn("CONTEXTO EXTRAÍDO Y VERIFICADO", distilled["formatted_context_prompt"])

        # 5. Verificar Registro de Auditoría en SQLite (retrieval_runs & retrieval_results)
        counts = self.catalog.count_all()
        self.assertGreater(counts["retrieval_runs"], 0)
        self.assertGreater(counts["retrieval_results"], 0)

if __name__ == "__main__":
    unittest.main()
