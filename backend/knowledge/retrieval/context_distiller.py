import json
from typing import List, Dict, Any

class ContextDistiller:
    """ Empaquetador y condensador de contexto que entrega únicamente evidencia destilada limpia al Reasoning Engine """

    # Aproximación conservadora para español/código: ~3.5 caracteres por token.
    CHARS_PER_TOKEN = 3.5

    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        return int(len(text) / cls.CHARS_PER_TOKEN) + 1

    @classmethod
    def distill_context(
        cls,
        reranked_chunks: List[Dict[str, Any]],
        query: str,
        max_tokens: int = 1800,
        max_chunks: int = 15
    ) -> Dict[str, Any]:
        """ Empaqueta las evidencias respetando un presupuesto de tokens.

        Antes metía 15 fragmentos sin medir nada: con ~500 tokens por fragmento eso
        son ~7500 tokens, que por sí solos ya desbordan una ventana de 4096 y dejan
        fuera la pregunta del usuario y el prompt de sistema.
        """
        distilled_chunks = []
        dropped = 0
        used_tokens = 0

        for c in reranked_chunks[:max_chunks]:
            content = c["content"]
            cost = cls.estimate_tokens(content)

            if used_tokens + cost > max_tokens:
                # Aún cabe recortado y merece la pena si es de los mejores
                remaining = max_tokens - used_tokens
                if remaining > 120 and not distilled_chunks:
                    content = content[: int(remaining * cls.CHARS_PER_TOKEN)] + " […]"
                    cost = cls.estimate_tokens(content)
                else:
                    dropped += 1
                    continue

            distilled_chunks.append({
                "chunk_id": c["chunk_id"],
                "source_id": c["source_id"],
                "content_type": c["content_type"],
                "page": c["page_start"],
                "content": content,
                "score": c.get("final_score"),
                "reasons": c.get("reasons", [])
            })
            used_tokens += cost

        summary_prompt = (
            f"CONTEXTO EXTRAÍDO Y VERIFICADO DE LA BIBLIOTECA ({len(distilled_chunks)} fragmentos destilados):\n\n"
        )
        for idx, item in enumerate(distilled_chunks):
            summary_prompt += f"--- FRAGMENTO [{idx+1}] ({item['chunk_id']} | Tipo: {item['content_type']} | Pág: {item['page']}) ---\n"
            summary_prompt += f"{item['content']}\n\n"

        return {
            "query": query,
            "total_chunks_distilled": len(distilled_chunks),
            "chunks_dropped_by_budget": dropped,
            "estimated_tokens": used_tokens,
            "token_budget": max_tokens,
            "formatted_context_prompt": summary_prompt.strip(),
            "distilled_chunks": distilled_chunks
        }
