from typing import List, Dict, Any, Tuple
from ..indexing.db_catalog import DBCatalog
from ..indexing.bm25_index import BM25Index
from ..indexing.vector_index import VectorIndex
from .macro_retriever import MacroRetriever
from .query_analyzer import QueryAnalyzer

class HybridRetriever:
    """ Buscador Híbrido que fusiona BM25 Léxico, Búsqueda Vectorial y Filtro Macro """

    def __init__(self, catalog: DBCatalog = None):
        self.catalog = catalog or DBCatalog()
        self.bm25 = BM25Index(self.catalog)
        self.vector = VectorIndex(self.catalog)
        self.macro = MacroRetriever(self.catalog)

    # Pesos de fusión. BM25 pesa algo más porque sobre texto técnico corto es más
    # preciso que el TF-IDF, que aporta sobre todo cobertura.
    W_BM25 = 0.55
    W_VECTOR = 0.45
    MACRO_BOOST = 0.05

    def retrieve(self, query: str, top_k: int = 30, use_macro: bool = True) -> List[Dict[str, Any]]:
        # 1. Análisis de consulta
        analysis = QueryAnalyzer.analyze_query(query)

        # Se buscan bastantes más candidatos de los que se devuelven, para que la
        # fusión tenga material con el que trabajar.
        pool = max(top_k * 3, 60)

        # 2. Búsqueda léxica BM25
        bm25_results = self.bm25.search(query, top_k=pool)
        bm25_dict = {doc["chunk_id"]: (doc, score) for doc, score in bm25_results}

        # 3. Búsqueda vectorial semántica
        vector_results = self.vector.search(query, top_k=pool)
        vector_dict = {doc["chunk_id"]: (doc, score) for doc, score in vector_results}

        # 4. Filtro macro: NO descarta, solo da un empujón a los libros cuyos
        #    capítulos hablan del tema. Como filtro duro perdería documentos sin
        #    capítulos detectados (texto plano, código), que son la mayoría.
        macro_sources = set()
        if use_macro:
            try:
                macro_sources = set(self.macro.filter_candidate_sources(query))
            except Exception:
                macro_sources = set()

        # 5. Fusionar candidatos
        all_chunk_ids = set(bm25_dict.keys()).union(set(vector_dict.keys()))
        candidates = []

        max_bm25 = max([score for _, score in bm25_results], default=1.0) or 1.0
        max_vec = max([score for _, score in vector_results], default=1.0) or 1.0

        for chk_id in all_chunk_ids:
            doc = bm25_dict[chk_id][0] if chk_id in bm25_dict else vector_dict[chk_id][0]

            raw_bm25 = bm25_dict[chk_id][1] if chk_id in bm25_dict else 0.0
            raw_vec = vector_dict[chk_id][1] if chk_id in vector_dict else 0.0

            norm_bm25 = min(1.0, raw_bm25 / max_bm25)
            norm_vec = min(1.0, raw_vec / max_vec)

            fused = (norm_bm25 * self.W_BM25) + (norm_vec * self.W_VECTOR)
            if doc.get("source_id") in macro_sources:
                fused += self.MACRO_BOOST

            candidates.append({
                "chunk": doc,
                "chunk_id": chk_id,
                "bm25_score": round(norm_bm25, 4),
                "vector_score": round(norm_vec, 4),
                "fused_score": round(min(1.0, fused), 4),
                "query_analysis": analysis
            })

        # 6. ORDENAR antes de truncar.
        #    Sin esto se recortaba un `set` en orden de hash: los mejores candidatos
        #    se descartaban al azar y pedir más candidatos empeoraba el resultado.
        candidates.sort(key=lambda c: c["fused_score"], reverse=True)

        return candidates[:top_k]
