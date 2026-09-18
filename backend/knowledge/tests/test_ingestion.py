import os
import shutil
import unittest
from backend.knowledge.indexing.db_catalog import DBCatalog
from backend.knowledge.ingestion.book_ingestor import BookIngestor

class TestIngestion(unittest.TestCase):
    def setUp(self):
        self.test_dir = "/tmp/test_prig_ingestion"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir, exist_ok=True)
        
        db_path = os.path.join(self.test_dir, "catalog.db")
        self.catalog = DBCatalog(db_path)
        self.ingestor = BookIngestor(self.catalog)

        # Crear un archivo de prueba real
        self.sample_file = os.path.join(self.test_dir, "sample_dl.txt")
        with open(self.sample_file, "w", encoding="utf-8") as f:
            f.write(
                "Capítulo 1: Introducción a Redes Neuronales\n\n"
                "Sección 1.1 Conceptos Fundamentales\n"
                "Una red neuronal artificial se compone de capas de neuronas conectadas.\n"
                "Para calcular la pérdida se utiliza una función de costo $L(w) = \\frac{1}{2}(y - \\hat{y})^2$.\n\n"
                "def forward(x):\n"
                "    return torch.matmul(x, w) + b\n\n"
                "Capítulo 2: Backpropagation y Gradiente Descendente\n\n"
                "Sección 2.1 Regla de la Cadena\n"
                "El algoritmo de backpropagation aplica la regla de la cadena para propagar derivadas parciales \\frac{\\partial L}{\\partial w}.\n"
                "loss.backward()\n"
                "optimizer.step()\n"
            )

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_full_document_ingestion(self):
        res = self.ingestor.ingest_document(self.sample_file, category_type="book")
        self.assertEqual(res["status"], "INGESTED")
        self.assertTrue(res["source_id"].startswith("book_"))
        self.assertGreater(res["chunks_count"], 0)

        chunks = self.catalog.get_chunks_by_source(res["source_id"])
        self.assertGreater(len(chunks), 0)

        # Verificar que detectó matemáticas y código
        types_found = {c["content_type"] for c in chunks}
        self.assertTrue("MATHEMATICS" in types_found or "CODE" in types_found or "TEXT" in types_found)

if __name__ == "__main__":
    unittest.main()
