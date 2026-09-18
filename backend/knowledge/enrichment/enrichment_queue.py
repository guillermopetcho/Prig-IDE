import uuid
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from ..indexing.db_catalog import DBCatalog

class EnrichmentQueue:
    """ Gestor determinista de la cola de tareas con Arrendamiento (Lease & Heartbeat) en catalog.db SQLite """

    def __init__(self, catalog: DBCatalog = None):
        self.catalog = catalog or DBCatalog()
        self.init_queue_table()

    def init_queue_table(self):
        with self.catalog.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS enrichment_queue (
                task_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                priority INTEGER DEFAULT 1,
                status TEXT DEFAULT 'PENDING',
                worker_id TEXT,
                lease_until TEXT,
                heartbeat_at TEXT,
                attempts INTEGER DEFAULT 0,
                model_name TEXT,
                prompt_version TEXT DEFAULT 'v1.0',
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON enrichment_queue(status, lease_until);")
            conn.commit()

    def enqueue_job(self, job_id: str, chunk_ids: List[str], task_type: str = "CLAIM_EXTRACTION", priority: int = 1):
        now_str = datetime.now().isoformat()
        with self.catalog.get_connection() as conn:
            cursor = conn.cursor()
            for chk_id in chunk_ids:
                task_id = f"tsk_{uuid.uuid4().hex[:12]}"
                cursor.execute("""
                INSERT OR IGNORE INTO enrichment_queue (
                    task_id, job_id, chunk_id, task_type, priority, status, attempts, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'PENDING', 0, ?, ?);
                """, (task_id, job_id, chk_id, task_type, priority, now_str, now_str))
            conn.commit()

    def lease_tasks(self, worker_id: str, job_id: str, limit: int = 10, lease_duration_sec: int = 300) -> List[Dict[str, Any]]:
        self.release_expired_leases()
        now_dt = datetime.now()
        now_str = now_dt.isoformat()
        lease_until_str = (now_dt + timedelta(seconds=lease_duration_sec)).isoformat()

        leased = []
        with self.catalog.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM enrichment_queue
            WHERE job_id = ? AND status = 'PENDING'
            ORDER BY priority DESC, created_at ASC
            LIMIT ?;
            """, (job_id, limit))
            pending_rows = cursor.fetchall()

            for r in pending_rows:
                task_dict = dict(r)
                task_id = task_dict["task_id"]
                cursor.execute("""
                UPDATE enrichment_queue
                SET status = 'LEASED', worker_id = ?, lease_until = ?, heartbeat_at = ?, attempts = attempts + 1, updated_at = ?
                WHERE task_id = ? AND status = 'PENDING';
                """, (worker_id, lease_until_str, now_str, now_str, task_id))
                
                if cursor.rowcount > 0:
                    task_dict["status"] = "LEASED"
                    task_dict["worker_id"] = worker_id
                    task_dict["lease_until"] = lease_until_str
                    leased.append(task_dict)

            conn.commit()
        return leased

    def release_expired_leases(self):
        now_str = datetime.now().isoformat()
        with self.catalog.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE enrichment_queue
            SET status = 'PENDING', worker_id = NULL, lease_until = NULL, updated_at = ?
            WHERE status = 'LEASED' AND lease_until < ?;
            """, (now_str, now_str))
            conn.commit()

    def complete_task(self, task_id: str):
        now_str = datetime.now().isoformat()
        with self.catalog.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE enrichment_queue
            SET status = 'COMPLETED', completed_at = ?, updated_at = ?
            WHERE task_id = ?;
            """, (now_str, now_str, task_id))
            conn.commit()

    def count_queue_stats(self, job_id: str) -> Dict[str, int]:
        with self.catalog.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT status, COUNT(*) as cnt FROM enrichment_queue
            WHERE job_id = ? GROUP BY status;
            """, (job_id,))
            return {r["status"]: r["cnt"] for r in cursor.fetchall()}
