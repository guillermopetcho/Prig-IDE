"""
Puente entre la biblioteca de archivos (~/.prig_books) y el motor de conocimiento.

Hasta ahora había dos sistemas paralelos que se ignoraban: `book_service`, que
manejaba ficheros sueltos y mandaba el texto crudo al modelo, y el paquete
`knowledge`, que tenía catálogo, fragmentación y recuperación pero al que nadie
llamaba fuera de los tests. Este servicio es la tubería que faltaba y el único
punto por el que se indexa y se consulta el conocimiento.
"""

import os
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

from knowledge.indexing.db_catalog import DBCatalog
from knowledge.ingestion.book_ingestor import BookIngestor
from knowledge.retrieval.hybrid_retriever import HybridRetriever
from knowledge.retrieval.reranker import ExplicableReranker
from knowledge.retrieval.context_distiller import ContextDistiller
from knowledge.evidence.evidence_builder import EvidenceBuilder

# Extensiones que merece la pena indexar como conocimiento
INDEXABLE_EXTENSIONS = {
    ".pdf": "book",
    ".md": "documentation",
    ".txt": "documentation",
    ".rst": "documentation",
    ".ipynb": "notebook",
    ".py": "code",
    ".js": "code",
    ".sql": "code",
}

# Un archivo enorme bloquea la indexación y aporta poco; se avisa y se salta.
MAX_INDEXABLE_BYTES = 80 * 1024 * 1024


class KnowledgeService:
    def __init__(self, books_dir: Optional[str] = None):
        self.books_dir = os.path.abspath(books_dir or os.path.expanduser("~/.prig_books"))
        os.makedirs(self.books_dir, exist_ok=True)

        index_dir = os.path.join(self.books_dir, ".index")
        os.makedirs(index_dir, exist_ok=True)
        self.catalog = DBCatalog(os.path.join(index_dir, "catalog.db"))
        self.ingestor = BookIngestor(self.catalog)

        # El índice BM25/TF-IDF se reconstruye entero al instanciarlo, así que se
        # cachea y solo se invalida cuando entra contenido nuevo. Antes cada
        # consulta habría re-vectorizado la biblioteca completa.
        self._retriever: Optional[HybridRetriever] = None
        self._reranker: Optional[ExplicableReranker] = None
        self._evidence: Optional[EvidenceBuilder] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # path -> (mtime, size, sha256). Evita rehashear archivos sin cambios.
        self._sha_cache: Dict[str, Any] = {}

        self._job: Dict[str, Any] = {
            "running": False,
            "started_at": None,
            "finished_at": None,
            "total": 0,
            "processed": 0,
            "indexed": 0,
            "skipped": 0,
            "failed": 0,
            "current_file": None,
            "errors": [],
            "replaced": 0,
        }

    # ------------------------------------------------------------------
    # Ciclo de vida del índice
    # ------------------------------------------------------------------

    def _ensure_engine(self):
        with self._lock:
            if self._retriever is None:
                self._retriever = HybridRetriever(self.catalog)
                self._reranker = ExplicableReranker(self.catalog)
                self._evidence = EvidenceBuilder(self.catalog)

    def invalidate(self):
        """ Fuerza la reconstrucción del índice en la próxima consulta """
        with self._lock:
            self._retriever = None
            self._reranker = None
            self._evidence = None

    # ------------------------------------------------------------------
    # Indexación
    # ------------------------------------------------------------------

    def file_sha256(self, path: str) -> Optional[str]:
        """ sha256 con caché por (mtime, tamaño) """
        from knowledge.ingestion.pdf_parser import PDFParser
        try:
            stat = os.stat(path)
        except OSError:
            return None

        key = os.path.abspath(path)
        cached = self._sha_cache.get(key)
        if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]

        try:
            sha = PDFParser.calculate_sha256(path)
        except OSError:
            return None

        self._sha_cache[key] = (stat.st_mtime, stat.st_size, sha)
        return sha

    def discover_files(self) -> List[Dict[str, str]]:
        """ Archivos indexables presentes en la biblioteca """
        found = []
        for root, dirs, files in os.walk(self.books_dir):
            # .index guarda el catálogo y metadata los JSON del analizador de IA
            dirs[:] = [d for d in dirs if d not in (".index", "metadata") and not d.startswith(".")]
            for name in sorted(files):
                ext = os.path.splitext(name)[1].lower()
                if ext not in INDEXABLE_EXTENSIONS:
                    continue
                path = os.path.join(root, name)
                rel = os.path.relpath(path, self.books_dir)
                category = rel.split(os.sep)[0] if os.sep in rel else INDEXABLE_EXTENSIONS[ext]
                found.append({
                    "path": path,
                    "relative_path": rel,
                    "filename": name,
                    "category": category,
                    "source_type": INDEXABLE_EXTENSIONS[ext],
                })
        return found

    def _catalog_by_path(self) -> Dict[str, Dict[str, str]]:
        """ ruta absoluta -> {source_id, sha256} de lo que hay en el catálogo """
        import json as _json
        mapping: Dict[str, Dict[str, str]] = {}
        for book in self.catalog.list_books():
            try:
                meta = _json.loads(book.get("metadata_json") or "{}")
            except Exception:
                meta = {}
            known = meta.get("abs_path") or os.path.join(self.books_dir, book["relative_path"])
            mapping[os.path.abspath(known)] = {
                "source_id": book["source_id"],
                "sha256": book["sha256"],
            }
        return mapping

    def _purge_stale_version(self, abs_path: str, current_sha: Optional[str],
                             catalog_map: Optional[Dict[str, Dict[str, str]]] = None) -> bool:
        """ Elimina la versión anterior de un archivo que ha cambiado.

        Al editar un documento cambia su sha256 y se indexa como documento nuevo; sin
        esta limpieza la copia vieja se quedaba en el catálogo y el tutor podía citar
        texto que ya no existe en el archivo.
        """
        if not current_sha:
            return False
        entry = (catalog_map if catalog_map is not None else self._catalog_by_path()).get(os.path.abspath(abs_path))
        if entry and entry["sha256"] != current_sha:
            return self.catalog.delete_book(entry["source_id"])
        return False

    def index_library(self, force: bool = False) -> Dict[str, Any]:
        """ Indexa de forma síncrona todo lo indexable. Idempotente por sha256. """
        self._stop_event.clear()
        files = self.discover_files()
        known = set() if force else set(self.catalog.get_indexed_sha256s().keys())
        catalog_map = self._catalog_by_path()
        replaced = 0

        self._job.update({
            "running": True,
            "started_at": self._job.get("started_at") or datetime.now().isoformat(),
            "finished_at": None,
            "total": len(files),
            "processed": 0, "indexed": 0, "skipped": 0, "failed": 0,
            "current_file": None, "errors": [],
        })

        try:
            for item in files:
                if self._stop_event.is_set():
                    self._job["errors"].append("Indexación detenida.")
                    break
                self._job["current_file"] = item["relative_path"]
                try:
                    if os.path.getsize(item["path"]) > MAX_INDEXABLE_BYTES:
                        self._job["skipped"] += 1
                        self._job["errors"].append(f"{item['relative_path']}: demasiado grande, omitido")
                        continue

                    # Si el archivo cambió, retirar antes su versión anterior
                    if self._purge_stale_version(item["path"], self.file_sha256(item["path"]), catalog_map):
                        replaced += 1

                    result = self.ingestor.ingest_document(item["path"], item["source_type"])
                    if result.get("status") == "INGESTED":
                        self._job["indexed"] += 1
                    else:
                        self._job["skipped"] += 1
                except Exception as err:
                    self._job["failed"] += 1
                    self._job["errors"].append(f"{item['relative_path']}: {err}")
                finally:
                    self._job["processed"] += 1
        finally:
            self._job["running"] = False
            self._job["current_file"] = None
            self._job["finished_at"] = datetime.now().isoformat()
            self._job["replaced"] = replaced
            self.invalidate()

        return self.get_status()

    def index_library_async(self, force: bool = False) -> Dict[str, Any]:
        """ Indexa en segundo plano: una biblioteca grande tarda minutos y no debe
        bloquear la petición HTTP. El progreso se consulta con get_status(). """
        if self._job["running"]:
            return {"status": "already_running", "job": self._job}

        # Marcar en marcha ANTES de lanzar el hilo: si se deja que lo haga el hilo,
        # un cliente que consulte el estado de inmediato ve running=False y concluye
        # que la indexación ya terminó.
        self._job.update({
            "running": True,
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
            "total": 0, "processed": 0, "indexed": 0,
            "skipped": 0, "failed": 0,
            "current_file": None, "errors": [],
        })

        threading.Thread(target=self.index_library, args=(force,), daemon=True).start()
        return {"status": "started", "job": self._job}

    def stop(self) -> None:
        """ Solicita la detención inmediata del proceso de indexación """
        self._stop_event.set()

    def index_single(self, file_path: str, source_type: str = "book") -> Dict[str, Any]:
        """ Indexa un archivo recién importado, sin recorrer toda la biblioteca """
        self._purge_stale_version(file_path, self.file_sha256(file_path))
        result = self.ingestor.ingest_document(file_path, source_type)
        if result.get("status") == "INGESTED":
            self.invalidate()
        return result

    def remove_by_path(self, abs_path: str) -> bool:
        """ Retira del catálogo el documento correspondiente a un archivo """
        import json as _json
        target = os.path.abspath(abs_path)
        for book in self.catalog.list_books():
            try:
                meta = _json.loads(book.get("metadata_json") or "{}")
            except Exception:
                meta = {}
            known = meta.get("abs_path") or os.path.join(self.books_dir, book["relative_path"])
            if os.path.abspath(known) == target:
                return self.remove(book["source_id"])
        return False

    def remove(self, source_id: str) -> bool:
        removed = self.catalog.delete_book(source_id)
        if removed:
            self.invalidate()
        return removed

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 8,
        max_context_tokens: int = 1800,
        expansions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """ Recuperación completa: híbrida → reranking → destilado → evidencias.

        `expansions` son reformulaciones de la consulta (sinónimos, términos
        técnicos). El recuperador es puramente léxico: si preguntas "cómo evito el
        sobreajuste" y el libro dice "regularización", sin expansión no hay
        ninguna palabra en común y no encuentra nada.
        """
        self._ensure_engine()

        queries = [query] + [e for e in (expansions or []) if e and e.strip()]

        merged: Dict[str, Dict[str, Any]] = {}
        for q in queries:
            for cand in self._retriever.retrieve(q, top_k=top_k * 4):
                prev = merged.get(cand["chunk_id"])
                if prev is None or cand["fused_score"] > prev["fused_score"]:
                    merged[cand["chunk_id"]] = cand

        candidates = sorted(merged.values(), key=lambda c: c["fused_score"], reverse=True)[: top_k * 4]

        if not candidates:
            return {
                "query": query,
                "found": False,
                "chunks": [],
                "evidence": None,
                "context_prompt": "",
                "stats": {"candidates": 0, "returned": 0},
            }

        reranked = self._reranker.rerank(candidates, query, top_k=top_k)
        distilled = ContextDistiller.distill_context(reranked, query, max_tokens=max_context_tokens)
        evidence = self._evidence.build_evidence(reranked, query)

        # Resolver el título legible de cada fuente: una cita que dice
        # "documentation_2ffa5ea9" no le sirve de nada al alumno.
        titles: Dict[str, str] = {}
        for chunk in distilled["distilled_chunks"]:
            src = chunk["source_id"]
            if src not in titles:
                book = self.catalog.get_book_by_source_id(src) or {}
                titles[src] = book.get("title") or src
            chunk["source_title"] = titles[src]

        return {
            "query": query,
            "expansions_used": queries[1:],
            "found": True,
            "chunks": distilled["distilled_chunks"],
            "evidence": evidence,
            "context_prompt": distilled["formatted_context_prompt"],
            "stats": {
                "candidates": len(candidates),
                "returned": len(reranked),
                "estimated_tokens": distilled["estimated_tokens"],
                "token_budget": distilled["token_budget"],
                "chunks_dropped_by_budget": distilled["chunks_dropped_by_budget"],
            },
        }

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    def get_indexed_paths(self) -> set:
        """ Rutas absolutas ya presentes en el catálogo """
        import json as _json
        paths = set()
        for book in self.catalog.list_books():
            try:
                meta = _json.loads(book.get("metadata_json") or "{}")
            except Exception:
                meta = {}
            if meta.get("abs_path"):
                paths.add(os.path.abspath(meta["abs_path"]))
            else:
                # Entradas antiguas, indexadas antes de guardar abs_path
                paths.add(os.path.abspath(os.path.join(self.books_dir, book["relative_path"])))
        return paths

    def get_status(self) -> Dict[str, Any]:
        # El estado del trabajo se captura ANTES que los contadores y como copia.
        # Al revés, una petición que cruzaba el final de la indexación mezclaba
        # contadores viejos ("0 libros") con un trabajo ya marcado como terminado,
        # y el panel se quedaba mostrando una biblioteca vacía.
        job_snapshot = dict(self._job)

        counts = self.catalog.count_all()
        books = self.catalog.list_books()
        discovered = self.discover_files()
        indexed_shas = set(self.catalog.get_indexed_sha256s().keys())

        pending = 0
        for item in discovered:
            sha = self.file_sha256(item["path"])
            if sha is None or sha not in indexed_shas:
                pending += 1

        return {
            "books_dir": self.books_dir,
            "db_path": self.catalog.db_path,
            "counts": counts,
            "files_discovered": len(discovered),
            "files_pending": pending,
            "indexed_books": [
                {
                    "source_id": b["source_id"],
                    "title": b["title"],
                    "source_type": b["source_type"],
                    "relative_path": b["relative_path"],
                    "total_pages": b["total_pages"],
                    "chunks_count": b["chunks_count"],
                    "file_size": b["file_size"],
                    "modified_at": b["modified_at"],
                }
                for b in books
            ],
            "job": job_snapshot,
        }
