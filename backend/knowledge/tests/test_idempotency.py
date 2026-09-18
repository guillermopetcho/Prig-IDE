import os
import shutil
import unittest
from backend.knowledge.indexing.db_catalog import DBCatalog
from backend.knowledge.ingestion.book_ingestor import BookIngestor

class TestIdempotency(unittest.TestCase):
    def setUp(self):
        self.test_dir = "/tmp/test_prig_idempotency"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir, exist_ok=True)

        db_path = os.path.join(self.test_dir, "catalog.db")
        self.catalog = DBCatalog(db_path)
        self.ingestor = BookIngestor(self.catalog)

        # Archivo A
        self.file_a = os.path.join(self.test_dir, "documento.pdf")
        with open(self.file_a, "w", encoding="utf-8") as f:
            f.write("Contenido idéntico de prueba de Deep Learning PyTorch.")

        # Archivo B (Mismo contenido, nombre renombrado)
        self.file_b = os.path.join(self.test_dir, "documento (1).pdf")
        with open(self.file_b, "w", encoding="utf-8") as f:
            f.write("Contenido idéntico de prueba de Deep Learning PyTorch.")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_idempotency_same_sha256(self):
        res1 = self.ingestor.ingest_document(self.file_a, category_type="book")
        self.assertEqual(res1["status"], "INGESTED")

        res2 = self.ingestor.ingest_document(self.file_b, category_type="book")
        self.assertEqual(res2["status"], "ALREADY_EXISTS")
        self.assertEqual(res1["source_id"], res2["source_id"])

        # Verificar que solo hay 1 libro en SQLite catalog.db
        counts = self.catalog.count_all()
        self.assertEqual(counts["books"], 1)

if __name__ == "__main__":
    unittest.main()
