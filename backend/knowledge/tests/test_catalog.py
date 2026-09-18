import os
import shutil
import unittest
from datetime import datetime
from backend.knowledge.indexing.db_catalog import DBCatalog
from backend.knowledge.models import BookDocument, SourceTypeEnum

class TestDBCatalog(unittest.TestCase):
    def setUp(self):
        self.test_dir = "/tmp/test_prig_db_catalog"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        db_path = os.path.join(self.test_dir, "catalog.db")
        self.catalog = DBCatalog(db_path)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_schema_creation_and_insertion(self):
        book = BookDocument(
            source_id="book_a91f82c40d12e98a",
            source_type=SourceTypeEnum.BOOK,
            title="Test Book",
            original_filename="test.pdf",
            relative_path="BOOKS/test.pdf",
            sha256="a91f82c40d12e98a" * 4,
            file_size=1024
        )
        self.catalog.insert_book(book.model_dump())

        retrieved = self.catalog.get_book_by_sha256(book.sha256)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["source_id"], "book_a91f82c40d12e98a")
        self.assertEqual(retrieved["title"], "Test Book")

        counts = self.catalog.count_all()
        self.assertEqual(counts["books"], 1)

if __name__ == "__main__":
    unittest.main()
