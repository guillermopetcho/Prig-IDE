from typing import List, Dict, Any, Tuple
from .db_catalog import DBCatalog


def _rs():
    from nativo_rust import rust
    return rust().indices


class VectorIndex:
    """ Índice vectorial semántico TF-IDF / Cosine Similarity reconstruible 100% desde SQLite catalog.db.

    El índice y la búsqueda están en Rust (backend-rust/crates/prig-biblioteca, indices.rs), con los mismos bits
    (también la suma compensada de `sum()` de Python 3.12). """

    def __init__(self, catalog: DBCatalog = None):
        self.catalog = catalog or DBCatalog()
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
        self._indice = _rs().Vectorial([d["content"] for d in self.corpus]) if self.corpus else None

    def search(self, query: str, top_k: int = 30) -> List[Tuple[Dict[str, Any], float]]:
        if not self.corpus:
            return []
        return [(self.corpus[i], puntos) for i, puntos in self._indice.buscar(query, top_k)]
