from typing import List, Dict, Any, Tuple
from .db_catalog import DBCatalog


def _rs():
    from nativo_rust import rust
    return rust().indices


class BM25Index:
    """ Índice léxico BM25Okapi reconstruible 100% desde SQLite catalog.db.

    El índice y la búsqueda están en Rust (backend-rust/crates/prig-biblioteca, indices.rs): cada término guarda los
    fragmentos que lo contienen y una búsqueda solo toca esos; las puntuaciones salen con los mismos bits. """

    def __init__(self, catalog: DBCatalog = None, k1: float = 1.5, b: float = 0.75):
        self.catalog = catalog or DBCatalog()
        self.k1 = k1
        self.b = b
        self.corpus: List[Dict[str, Any]] = []
        self._indice = None
        self.build_index()

    def tokenize(self, text: str) -> List[str]:
        return _rs().tokenizar(text)

    def build_index(self):
        with self.catalog.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT chunk_id, source_id, chapter_id, section_id, content, content_type, page_start FROM chunks;")
            self.corpus = [dict(r) for r in cursor.fetchall()]
        self._indice = _rs().Bm25([d["content"] for d in self.corpus], self.k1, self.b) if self.corpus else None

    def search(self, query: str, top_k: int = 30) -> List[Tuple[Dict[str, Any], float]]:
        if not self.corpus:
            return []
        return [(self.corpus[i], puntos) for i, puntos in self._indice.buscar(query, top_k)]
