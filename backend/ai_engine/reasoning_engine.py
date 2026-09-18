import time
import requests
import json
from typing import Dict, Any, Optional
try:
    from backend.ai_engine.model_router import ModelRouter, ModelTierEnum
    from backend.knowledge.indexing.db_catalog import DBCatalog
    from backend.knowledge.retrieval.hybrid_retriever import HybridRetriever
    from backend.knowledge.retrieval.reranker import ExplicableReranker
    from backend.knowledge.retrieval.context_distiller import ContextDistiller
    from backend.knowledge.evidence.evidence_builder import EvidenceBuilder
    from backend.knowledge.evidence.knowledge_qc import KnowledgeQCEngine
except ImportError:
    from ai_engine.model_router import ModelRouter, ModelTierEnum
    from knowledge.indexing.db_catalog import DBCatalog
    from knowledge.retrieval.hybrid_retriever import HybridRetriever
    from knowledge.retrieval.reranker import ExplicableReranker
    from knowledge.retrieval.context_distiller import ContextDistiller
    from knowledge.evidence.evidence_builder import EvidenceBuilder
    from knowledge.evidence.knowledge_qc import KnowledgeQCEngine


class ReasoningEngine:
    """ Motor de Razonamiento Desacoplado: Inferencia Eficiente impulsada por la Memoria de catalog.db SQLite """

    def __init__(self, catalog: DBCatalog = None, router: ModelRouter = None):
        self.catalog = catalog or DBCatalog()
        self.router = router or ModelRouter()
        self.retriever = HybridRetriever(self.catalog)
        self.reranker = ExplicableReranker(self.catalog)
        self.evidence_builder = EvidenceBuilder(self.catalog)
        self.qc_engine = KnowledgeQCEngine(self.catalog)

    def process_query(self, query: str, user_model: Optional[str] = None) -> Dict[str, Any]:
        start_t = time.time()

        # 1. Recuperación Híbrida (BM25 + Vector + Metadata)
        candidates = self.retriever.retrieve(query, top_k=20)
        retrieval_t = round(time.time() - start_t, 4)

        # 2. Re-ranking Explicable
        t_rerank = time.time()
        reranked = self.reranker.rerank(candidates, query, top_k=10)
        rerank_t = round(time.time() - t_rerank, 4)

        # 3. Generación de Evidencias a 3 Niveles
        evidence = self.evidence_builder.build_evidence(reranked, query)

        # 4. Destilación de Contexto
        distilled = ContextDistiller.distill_context(reranked, query)

        # 5. Selección de Modelo según Tipo de Consulta
        q_analysis = candidates[0].get("query_analysis", {}) if candidates else {}
        p_type = q_analysis.get("primary_type", "CONCEPTUAL")

        if p_type == "CODE":
            tier = ModelTierEnum.CODE
        elif p_type in ["MATHEMATICAL", "MULTI_HOP", "PROCEDURAL"]:
            tier = ModelTierEnum.REASONING
        else:
            tier = ModelTierEnum.FAST

        model_name = self.router.resolve_model(tier, user_model)

        # 6. Llamada al LLM solo con el contexto destilado (5-10 chunks max)
        sys_prompt = (
            "Eres el REASONING ENGINE de Prig IDE. Tu objetivo es proporcionar una respuesta clara, "
            "rigurosa y didáctica respaldada estrictamente por la evidencia de la biblioteca proporcionada.\n"
            "Muestra fórmulas LaTeX en $...$ o $$...$$ cuando aplique, y bloques de código Python limpios."
        )

        prompt = f"CONSULTA DEL USUARIO: '{query}'\n\n{distilled['formatted_context_prompt']}"

        t_llm = time.time()
        response_text = ""
        try:
            url = f"{self.router.ollama_url}/api/generate"
            payload = {
                "model": model_name,
                "prompt": prompt,
                "system": sys_prompt,
                "stream": False,
                "options": {"temperature": 0.3}
            }
            res = requests.post(url, json=payload, timeout=60)
            if res.status_code == 200:
                response_text = res.json().get("response", "")
            else:
                response_text = f"Respuesta basada en evidencia ({len(reranked)} fragmentos recuperados)."
        except Exception as err:
            response_text = f"Respuesta basada en evidencia ({len(reranked)} fragmentos recuperados)."

        llm_t = round(time.time() - t_llm, 4)
        total_t = round(time.time() - start_t, 4)

        # 7. Pasar por el Knowledge QC Engine
        proposal = {
            "concept_name": query,
            "claims": [
                {"statement": line.strip(), "claim_type": "DECLARATIVE"}
                for line in response_text.split('\n') if len(line.strip()) > 30
            ][:5]
        }
        qc_result = self.qc_engine.verify_proposal(proposal, distilled)

        return {
            "query": query,
            "response": response_text,
            "model_used": model_name,
            "tier_used": tier.value,
            "evidence": evidence,
            "qc_result": qc_result,
            "distilled_context": distilled,
            "metrics": {
                "retrieval_time_sec": retrieval_t,
                "rerank_time_sec": rerank_t,
                "llm_time_sec": llm_t,
                "total_time_sec": total_t,
                "chunks_analyzed": len(candidates),
                "chunks_delivered": len(reranked)
            }
        }
