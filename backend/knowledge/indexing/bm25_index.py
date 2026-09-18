import math
import re
from typing import List, Dict, Any, Tuple
from .db_catalog import DBCatalog

class BM25Index:
    """ Índice léxico BM25Okapi reconstruible 100% desde SQLite catalog.db """

    def __init__(self, catalog: DBCatalog = None, k1: float = 1.5, b: float = 0.75):
        self.catalog = catalog or DBCatalog()
        self.k1 = k1
        self.b = b
        self.corpus: List[Dict[str, Any]] = []
        self.doc_len: List[int] = []
        self.avg_doc_len: float = 0.0
        self.doc_freqs: List[Dict[str, int]] = []
        self.idf: Dict[str, float] = {}
        self.build_index()

    def tokenize(self, text: str) -> List[str]:
        return re.findall(r'\w+', text.lower())

    def build_index(self):
        with self.catalog.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT chunk_id, source_id, chapter_id, section_id, content, content_type, page_start FROM chunks;")
            self.corpus = [dict(r) for r in cursor.fetchall()]

        if not self.corpus:
            return

        self.doc_len = []
        self.doc_freqs = []
        total_len = 0
        df_counts: Dict[str, int] = {}

        for doc in self.corpus:
            tokens = self.tokenize(doc["content"])
            t_len = len(tokens)
            self.doc_len.append(t_len)
            total_len += t_len

            freqs: Dict[str, int] = {}
            for t in tokens:
                freqs[t] = freqs.get(t, 0) + 1
            self.doc_freqs.append(freqs)

            for t in freqs.keys():
                df_counts[t] = df_counts.get(t, 0) + 1

        N = len(self.corpus)
        self.avg_doc_len = total_len / N if N > 0 else 0.0

        self.idf = {}
        for word, freq in df_counts.items():
            self.idf[word] = math.log((N - freq + 0.5) / (freq + 0.5) + 1.0)

    def search(self, query: str, top_k: int = 30) -> List[Tuple[Dict[str, Any], float]]:
        if not self.corpus:
            return []

        q_tokens = self.tokenize(query)
        scores = []

        for idx, doc in enumerate(self.corpus):
            score = 0.0
            doc_f = self.doc_freqs[idx]
            d_len = self.doc_len[idx]

            for qt in q_tokens:
                if qt not in doc_f:
                    continue
                freq = doc_f[qt]
                idf_val = self.idf.get(qt, 0.0)
                numerator = idf_val * freq * (self.k1 + 1)
                denominator = freq + self.k1 * (1 - self.b + self.b * (d_len / self.avg_doc_len))
                score += numerator / denominator

            if score > 0:
                scores.append((doc, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
