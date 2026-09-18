import os
import json
import shutil
import unittest
from datetime import datetime
from backend.knowledge.indexing.db_catalog import DBCatalog
from backend.knowledge.ingestion.book_ingestor import BookIngestor
from backend.knowledge.enrichment.enrichment_queue import EnrichmentQueue
from backend.knowledge.enrichment.package_validator import EnrichmentPackageValidator
from backend.knowledge.enrichment.local_importer import LocalEnrichmentImporter

class TestEnrichmentPipeline(unittest.TestCase):
    def setUp(self):
        self.test_dir = "/tmp/test_prig_enrichment_v2"
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
        os.makedirs(self.test_dir, exist_ok=True)

        db_path = os.path.join(self.test_dir, "catalog.db")
        self.catalog = DBCatalog(db_path)
        self.ingestor = BookIngestor(self.catalog)
        self.queue = EnrichmentQueue(self.catalog)
        self.importer = LocalEnrichmentImporter(self.catalog)

        # Ingerir documento de prueba
        self.sample_file = os.path.join(self.test_dir, "pytorch_book.txt")
        with open(self.sample_file, "w", encoding="utf-8") as f:
            f.write("Capítulo 1: PyTorch Autograd\n\nloss.backward()\noptimizer.step()\n")
        self.ingest_res = self.ingestor.ingest_document(self.sample_file, category_type="book")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_enrichment_queue_lease_and_timeout(self):
        job_id = "job_2026_test_lease"
        chunks = self.catalog.get_chunks_by_source(self.ingest_res["source_id"])
        chunk_ids = [c["chunk_id"] for c in chunks]

        # 1. Encolar tareas PENDING
        self.queue.enqueue_job(job_id, chunk_ids, task_type="CLAIM_EXTRACTION")
        
        # 2. Arrendar tareas (LEASED) por 1 segundo
        leased = self.queue.lease_tasks("worker_kaggle_01", job_id, limit=5, lease_duration_sec=1)
        self.assertEqual(len(leased), len(chunk_ids))
        self.assertEqual(leased[0]["status"], "LEASED")
        self.assertEqual(leased[0]["worker_id"], "worker_kaggle_01")

        # 3. Completar tarea
        self.queue.complete_task(leased[0]["task_id"])
        stats = self.queue.count_queue_stats(job_id)
        self.assertEqual(stats.get("COMPLETED"), 1)

    def test_package_validation_and_import(self):
        pkg_dir = os.path.join(self.test_dir, "prig_enrichment_job")
        os.makedirs(pkg_dir, exist_ok=True)

        # Crear manifest Pydantic v2 válido
        manifest = {
            "job_id": "job_2026_test_valid",
            "input_manifest_sha256": "sha256_canonical_manifest_12345",
            "schema_version": "2.1",
            "worker_version": "1.0.0",
            "model_used": "qwen2.5-coder:14b",
            "model_quantization": "Q4",
            "chunks_processed": 1
        }
        with open(os.path.join(pkg_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)

        # Crear claims.jsonl
        now_str = datetime.now().isoformat()
        claim_item = {
            "claim_id": "clm_test_001",
            "concept_id": "conc_autograd",
            "statement": "PyTorch Autograd calcula gradientes automáticamente con loss.backward().",
            "claim_type": "DECLARATIVE",
            "status": "VERIFIED",
            "evidence_ids": ["ev_test_001"],
            "created_at": now_str,
            "updated_at": now_str
        }
        with open(os.path.join(pkg_dir, "claims.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps(claim_item) + "\n")

        # 1. Validar paquete
        val_res = EnrichmentPackageValidator.validate_package(pkg_dir)
        self.assertTrue(val_res["is_valid"])

        # 2. Importar paquete
        res = self.importer.import_enrichment_package(pkg_dir)
        self.assertEqual(res["status"], "IMPORTED")
        self.assertEqual(res["imported_claims_count"], 1)

        counts = self.catalog.count_all()
        self.assertEqual(counts["claims"], 1)

if __name__ == "__main__":
    unittest.main()
