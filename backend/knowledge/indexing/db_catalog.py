import os
import sqlite3
import json
from typing import Optional, List, Dict, Any
from datetime import datetime

class DBCatalog:
    """ Gestor de la base de datos SQLite (~/.prig_books/.index/catalog.db) que actúa como Fuente Única de Verdad """

    def __init__(self, db_path: str = None):
        if not db_path:
            base_dir = os.path.expanduser("~/.prig_books/.index")
            os.makedirs(base_dir, exist_ok=True)
            db_path = os.path.join(base_dir, "catalog.db")
        
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.init_tables()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def init_tables(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Tabla books (Level 0)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS books (
                source_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                title TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                sha256 TEXT UNIQUE NOT NULL,
                file_size INTEGER NOT NULL,
                authors_json TEXT,
                total_pages INTEGER DEFAULT 0,
                document_version INTEGER DEFAULT 1,
                index_version INTEGER DEFAULT 1,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                modified_at TEXT NOT NULL
            );
            """)

            # 2. Tabla chapters (Level 1)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS chapters (
                chapter_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                chapter_num INTEGER NOT NULL,
                title TEXT NOT NULL,
                start_page INTEGER DEFAULT 1,
                end_page INTEGER DEFAULT 1,
                summary TEXT,
                key_topics_json TEXT,
                prerequisites_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES books(source_id) ON DELETE CASCADE
            );
            """)

            # 3. Tabla sections (Level 2)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS sections (
                section_id TEXT PRIMARY KEY,
                chapter_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                section_num TEXT NOT NULL,
                title TEXT NOT NULL,
                start_page INTEGER DEFAULT 1,
                end_page INTEGER DEFAULT 1,
                summary TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (chapter_id) REFERENCES chapters(chapter_id) ON DELETE CASCADE,
                FOREIGN KEY (source_id) REFERENCES books(source_id) ON DELETE CASCADE
            );
            """)

            # 4. Tabla chunks (Level 3)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                chapter_id TEXT,
                section_id TEXT,
                content TEXT NOT NULL,
                content_type TEXT NOT NULL,
                token_count INTEGER DEFAULT 0,
                previous_chunk_id TEXT,
                next_chunk_id TEXT,
                contains_equation INTEGER DEFAULT 0,
                contains_code INTEGER DEFAULT 0,
                topics_json TEXT,
                concepts_json TEXT,
                symbols_json TEXT,
                page_start INTEGER DEFAULT 1,
                page_end INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES books(source_id) ON DELETE CASCADE
            );
            """)

            # 5. Tabla concepts
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS concepts (
                concept_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT DEFAULT 'FOUNDATIONAL',
                declarative_summary TEXT,
                procedural_summary TEXT,
                created_at TEXT NOT NULL
            );
            """)

            # 6. Tabla claims
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                claim_id TEXT PRIMARY KEY,
                concept_id TEXT NOT NULL,
                statement TEXT NOT NULL,
                claim_type TEXT DEFAULT 'DECLARATIVE',
                status TEXT DEFAULT 'PROPOSED',
                evidence_ids_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (concept_id) REFERENCES concepts(concept_id) ON DELETE CASCADE
            );
            """)

            # 7. Tabla evidence
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY,
                claim_id TEXT,
                concept_id TEXT,
                source_id TEXT NOT NULL,
                source_type TEXT DEFAULT 'book',
                source_title TEXT NOT NULL,
                chapter_num INTEGER,
                chapter_name TEXT,
                pages_json TEXT,
                chunk_ids_json TEXT,
                location_summary TEXT,
                strength TEXT DEFAULT 'DIRECT',
                confidence REAL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES books(source_id) ON DELETE CASCADE
            );
            """)

            # 8. Tabla relations
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS relations (
                relation_id TEXT PRIMARY KEY,
                from_concept_id TEXT NOT NULL,
                to_concept_id TEXT NOT NULL,
                relation_type TEXT DEFAULT 'PREREQUISITE_OF',
                confidence REAL DEFAULT 1.0,
                status TEXT DEFAULT 'PROPOSED',
                created_at TEXT NOT NULL,
                FOREIGN KEY (from_concept_id) REFERENCES concepts(concept_id) ON DELETE CASCADE,
                FOREIGN KEY (to_concept_id) REFERENCES concepts(concept_id) ON DELETE CASCADE
            );
            """)

            # 9. Tabla conflicts
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS conflicts (
                conflict_id TEXT PRIMARY KEY,
                source_a_id TEXT NOT NULL,
                source_b_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                context_a TEXT NOT NULL,
                context_b TEXT NOT NULL,
                resolution_status TEXT DEFAULT 'LOGGED',
                created_at TEXT NOT NULL
            );
            """)

            # 10. Tabla retrieval_runs (Auditoría de Búsquedas)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS retrieval_runs (
                run_id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                query_type TEXT NOT NULL,
                candidate_count INTEGER DEFAULT 0,
                final_count INTEGER DEFAULT 0,
                retriever_version TEXT DEFAULT 'v3.0',
                embedding_model TEXT DEFAULT 'tfidf-hybrid',
                reranker_version TEXT DEFAULT 'explicable-v1',
                created_at TEXT NOT NULL
            );
            """)

            # 11. Tabla retrieval_results (Resultados Explicables por Búsqueda)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS retrieval_results (
                result_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                bm25_score REAL DEFAULT 0.0,
                vector_score REAL DEFAULT 0.0,
                structure_score REAL DEFAULT 0.0,
                topic_score REAL DEFAULT 0.0,
                context_score REAL DEFAULT 0.0,
                reranker_score REAL DEFAULT 0.0,
                final_score REAL DEFAULT 0.0,
                rank INTEGER NOT NULL,
                reasons_json TEXT,
                FOREIGN KEY (run_id) REFERENCES retrieval_runs(run_id) ON DELETE CASCADE,
                FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE
            );
            """)


            # Índices de alto rendimiento para consultas
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_books_sha256 ON books(sha256);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chapters_source ON chapters(source_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sections_chapter ON sections(chapter_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks(content_type);")

            conn.commit()

    def get_book_by_sha256(self, sha256: str) -> Optional[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM books WHERE sha256 = ?;", (sha256.lower(),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_book_by_source_id(self, source_id: str) -> Optional[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM books WHERE source_id = ?;", (source_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_books(self) -> List[dict]:
        """ Libros indexados con su número de fragmentos """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT b.*, (SELECT COUNT(*) FROM chunks c WHERE c.source_id = b.source_id) AS chunks_count
                FROM books b ORDER BY b.modified_at DESC;
            """)
            return [dict(r) for r in cursor.fetchall()]

    def get_indexed_sha256s(self) -> Dict[str, str]:
        """ sha256 -> source_id de todo lo ya indexado (para saltarse lo que no cambió) """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT sha256, source_id FROM books;")
            return {r["sha256"]: r["source_id"] for r in cursor.fetchall()}

    def delete_book(self, source_id: str) -> bool:
        """ Elimina un libro y todo lo que cuelga de él """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM books WHERE source_id = ?;", (source_id,))
            if not cursor.fetchone():
                return False
            for table in ("chunks", "sections", "chapters"):
                cursor.execute(f"DELETE FROM {table} WHERE source_id = ?;", (source_id,))
            cursor.execute("DELETE FROM books WHERE source_id = ?;", (source_id,))
            conn.commit()
            return True

    def insert_book(self, book_data: dict):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO books (
                source_id, source_type, title, original_filename, relative_path, sha256,
                file_size, authors_json, total_pages, document_version, index_version, metadata_json, created_at, modified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                book_data["source_id"], book_data["source_type"], book_data["title"],
                book_data["original_filename"], book_data["relative_path"], book_data["sha256"].lower(),
                book_data["file_size"], json.dumps(book_data.get("authors", [])), book_data.get("total_pages", 0),
                book_data.get("document_version", 1), book_data.get("index_version", 1),
                json.dumps(book_data.get("metadata", {})), book_data["created_at"], book_data["modified_at"]
            ))
            conn.commit()

    def insert_chapters(self, chapters: List[dict]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for ch in chapters:
                cursor.execute("""
                INSERT OR REPLACE INTO chapters (
                    chapter_id, source_id, chapter_num, title, start_page, end_page, summary, key_topics_json, prerequisites_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    ch["chapter_id"], ch["source_id"], ch["chapter_num"], ch["title"],
                    ch.get("start_page", 1), ch.get("end_page", 1), ch.get("summary", ""),
                    json.dumps(ch.get("key_topics", [])), json.dumps(ch.get("prerequisites", [])), ch["created_at"]
                ))
            conn.commit()

    def insert_sections(self, sections: List[dict]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for sec in sections:
                cursor.execute("""
                INSERT OR REPLACE INTO sections (
                    section_id, chapter_id, source_id, section_num, title, start_page, end_page, summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    sec["section_id"], sec["chapter_id"], sec["source_id"], sec["section_num"],
                    sec["title"], sec.get("start_page", 1), sec.get("end_page", 1), sec.get("summary", ""), sec["created_at"]
                ))
            conn.commit()

    def insert_chunks(self, chunks: List[dict]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for chk in chunks:
                cursor.execute("""
                INSERT OR REPLACE INTO chunks (
                    chunk_id, source_id, chapter_id, section_id, content, content_type, token_count,
                    previous_chunk_id, next_chunk_id, contains_equation, contains_code, topics_json,
                    concepts_json, symbols_json, page_start, page_end, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    chk["chunk_id"], chk["source_id"], chk.get("chapter_id"), chk.get("section_id"),
                    chk["content"], chk["content_type"], chk.get("token_count", 0),
                    chk.get("previous_chunk_id"), chk.get("next_chunk_id"),
                    1 if chk.get("contains_equation") else 0, 1 if chk.get("contains_code") else 0,
                    json.dumps(chk.get("topics", [])), json.dumps(chk.get("concepts", [])), json.dumps(chk.get("symbols", [])),
                    chk.get("page_start", 1), chk.get("page_end", 1), chk["created_at"]
                ))
            conn.commit()

    def get_chunks_by_source(self, source_id: str) -> List[dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM chunks WHERE source_id = ? ORDER BY page_start ASC, chunk_id ASC;", (source_id,))
            return [dict(r) for r in cursor.fetchall()]

    def log_retrieval_run(self, run_data: dict, results: List[dict]):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO retrieval_runs (
                run_id, query, query_type, candidate_count, final_count,
                retriever_version, embedding_model, reranker_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                run_data["run_id"], run_data["query"], run_data["query_type"],
                run_data.get("candidate_count", 0), run_data.get("final_count", 0),
                run_data.get("retriever_version", "v3.0"), run_data.get("embedding_model", "tfidf-hybrid"),
                run_data.get("reranker_version", "explicable-v1"), datetime.now().isoformat()
            ))

            for res in results:
                cursor.execute("""
                INSERT INTO retrieval_results (
                    result_id, run_id, chunk_id, bm25_score, vector_score, structure_score,
                    topic_score, context_score, reranker_score, final_score, rank, reasons_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    f"{run_data['run_id']}_{res['rank']}", run_data["run_id"], res["chunk_id"],
                    res.get("bm25_score", 0.0), res.get("vector_score", 0.0), res.get("structure_score", 0.0),
                    res.get("topic_score", 0.0), res.get("context_score", 0.0), res.get("reranker_score", 0.0),
                    res.get("final_score", 0.0), res["rank"], json.dumps(res.get("reasons", []))
                ))
            conn.commit()

    def count_all(self) -> Dict[str, int]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            res = {}
            for table in ["books", "chapters", "sections", "chunks", "concepts", "claims", "evidence", "relations", "conflicts", "retrieval_runs", "retrieval_results"]:
                cursor.execute(f"SELECT COUNT(*) FROM {table};")
                res[table] = cursor.fetchone()[0]
            return res

