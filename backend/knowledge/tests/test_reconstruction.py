import os
import shutil
import unittest
from backend.knowledge.indexing.db_catalog import DBCatalog
from backend.knowledge.ingestion.book_ingestor import BookIngestor

class TestReconstruction(unittest.TestCase):
    def setUp(self):
        self.test_dir = "/tmp/test_prig_reconstruction"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir, exist_ok=True)

        db_path = os.path.join(self.test_dir, "catalog.db")
        self.catalog = DBCatalog(db_path)
        self.ingestor = BookIngestor(self.catalog)

        self.sample_file = os.path.join(self.test_dir, "sample_code.py")
        with open(self.sample_file, "w", encoding="utf-8") as f:
            f.write(
                "import torch\n"
                "import torch.nn as nn\n\n"
                "class SimpleModel(nn.Module):\n"
                "    def __init__(self):\n"
                "        super().__init__()\n"
                "        self.fc = nn.Linear(10, 2)\n\n"
                "    def forward(self, x):\n"
                "        return self.fc(x)\n"
            )

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_reconstruct_chunks_from_catalog(self):
        res = self.ingestor.ingest_document(self.sample_file, category_type="code")
        source_id = res["source_id"]

        # Recuperar fragmentos desde SQLite catalog.db como Fuente Única de Verdad
        chunks_from_db = self.catalog.get_chunks_by_source(source_id)
        self.assertGreater(len(chunks_from_db), 0)

        # Simular reconstrucción de índice ficticio
        reconstructed_corpus = [c["content"] for c in chunks_from_db]
        self.assertEqual(len(reconstructed_corpus), len(chunks_from_db))
        self.assertIn("SimpleModel", reconstructed_corpus[0])

if __name__ == "__main__":
    unittest.main()
