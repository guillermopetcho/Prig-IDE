import math
import re
from typing import List, Dict, Any, Tuple
from .db_catalog import DBCatalog

class VectorIndex:
    """ Índice vectorial semántico TF-IDF / Cosine Similarity reconstruible 100% desde SQLite catalog.db """

    def __init__(self, catalog: DBCatalog = None):
        self.catalog = catalog or DBCatalog()
        self.corpus: List[Dict[str, Any]] = []
        self.vectors: List[Dict[str, float]] = []
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

        # Generar vectores TF-IDF de subpalabras/términos
        self.vectors = []
        N = len(self.corpus)
        doc_freqs = {}

        for doc in self.corpus:
            tokens = self.tokenize(doc["content"])
            unique_t = set(tokens)
            for t in unique_t:
                doc_freqs[t] = doc_freqs.get(t, 0) + 1

        for doc in self.corpus:
            tokens = self.tokenize(doc["content"])
            tf = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            
            vector = {}
            norm = 0.0
            for t, freq in tf.items():
                idf = math.log((N + 1.0) / (doc_freqs.get(t, 1) + 1.0))
                val = (freq / len(tokens)) * idf
                vector[t] = val
                norm += val * val
            
            norm = math.sqrt(norm) if norm > 0 else 1.0
            normalized_vec = {k: v / norm for k, v in vector.items()}
            self.vectors.append(normalized_vec)

    def search(self, query: str, top_k: int = 30) -> List[Tuple[Dict[str, Any], float]]:
        if not self.corpus:
            return []

        q_tokens = self.tokenize(query)
        if not q_tokens:
            return []

        q_tf = {}
        for t in q_tokens:
            q_tf[t] = q_tf.get(t, 0) + 1
        
        q_norm = math.sqrt(sum(v*v for v in q_tf.values())) or 1.0
        q_vec = {k: v / q_norm for k, v in q_tf.items()}

        scores = []
        for idx, doc in enumerate(self.corpus):
            doc_vec = self.vectors[idx]
            dot_product = sum(q_vec[t] * doc_vec[t] for t in q_vec if t in doc_vec)
            if dot_product > 0:
                scores.append((doc, dot_product))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
