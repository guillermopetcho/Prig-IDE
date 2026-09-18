import uuid
from typing import List, Dict, Any
from ..indexing.db_catalog import DBCatalog

class ExplicableReranker:
    """ Reranker explicable multidimensional que reordena candidatos y registra razones explícitas """

    def __init__(self, catalog: DBCatalog = None):
        self.catalog = catalog or DBCatalog()

    def rerank(self, candidates: List[Dict[str, Any]], query: str, top_k: int = 15) -> List[Dict[str, Any]]:
        if not candidates:
            return []

        q_analysis = candidates[0].get("query_analysis", {})
        is_math_req = q_analysis.get("is_math_required", False)
        is_code_req = q_analysis.get("is_code_required", False)
        is_proc_req = q_analysis.get("is_procedural_required", False)

        reranked = []

        for cand in candidates:
            doc = cand["chunk"]
            bm25_s = cand["bm25_score"]
            vec_s = cand["vector_score"]
            c_type = doc.get("content_type", "TEXT")

            structure_s = 0.5
            reasons = []

            # 1. Evaluación de Coincidencia de Estructura / Tipo de Contenido
            if is_math_req and c_type in ["MATHEMATICS", "PROOF"]:
                structure_s += 0.4
                reasons.append("Contiene ecuaciones y fórmulas matemáticas relevantes")
            if is_code_req and c_type == "CODE":
                structure_s += 0.4
                reasons.append("Contiene bloques de código Python ejecutables")
            if is_proc_req and c_type in ["ALGORITHM", "DEFINITION"]:
                structure_s += 0.3
                reasons.append("Contiene definición o pasos procedimentales del algoritmo")

            if not reasons:
                reasons.append("Coincidencia textual y semántica con la consulta")

            structure_s = min(1.0, structure_s)
            topic_s = round((bm25_s + vec_s) / 2.0, 4)
            context_s = 0.8 if doc.get("section_id") else 0.5

            # Cálculo ponderado del Reranker Score
            reranker_s = round((bm25_s * 0.3) + (vec_s * 0.35) + (structure_s * 0.25) + (context_s * 0.10), 4)
            final_s = round((reranker_s * 0.85) + (topic_s * 0.15), 4)

            reranked.append({
                "chunk_id": doc["chunk_id"],
                "source_id": doc["source_id"],
                "chapter_id": doc.get("chapter_id"),
                "section_id": doc.get("section_id"),
                "content": doc["content"],
                "content_type": c_type,
                "page_start": doc.get("page_start", 1),
                "bm25_score": bm25_s,
                "vector_score": vec_s,
                "structure_score": round(structure_s, 4),
                "topic_score": topic_s,
                "context_score": context_s,
                "reranker_score": reranker_s,
                "final_score": final_s,
                "reasons": reasons
            })

        # Ordenar por final_score descendente
        reranked.sort(key=lambda x: x["final_score"], reverse=True)
        final_list = reranked[:top_k]

        # Asignar rangos (rank: 1, 2, 3...)
        for idx, item in enumerate(final_list):
            item["rank"] = idx + 1

        # Registrar Auditoría en SQLite (retrieval_runs & retrieval_results)
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        run_data = {
            "run_id": run_id,
            "query": query,
            "query_type": q_analysis.get("primary_type", "CONCEPTUAL"),
            "candidate_count": len(candidates),
            "final_count": len(final_list)
        }
        try:
            self.catalog.log_retrieval_run(run_data, final_list)
        except Exception as err:
            print("Advertencia al auditar retrieval run:", err)

        return final_list
