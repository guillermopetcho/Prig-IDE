import uuid
from typing import List, Dict, Any
from ..indexing.db_catalog import DBCatalog

class EvidenceBuilder:
    """ Generador determinista de Evidencias a 3 Niveles (Fuente, Dependencias, Razón Pedagógica) para el botón WHY? """

    def __init__(self, catalog: DBCatalog = None):
        self.catalog = catalog or DBCatalog()

    def build_evidence(self, reranked_chunks: List[Dict[str, Any]], concept_name: str) -> Dict[str, Any]:
        if not reranked_chunks:
            return {
                "concept_name": concept_name,
                "has_evidence": False,
                "evidence_strength": "INSUFFICIENT_EVIDENCE",
                "summary": "No se encontraron fragmentos con suficiente solidez en la biblioteca."
            }

        top_chunk = reranked_chunks[0]
        chunk_ids = [c["chunk_id"] for c in reranked_chunks[:3]]
        pages = list(set([c["page_start"] for c in reranked_chunks[:3]]))

        # Antes se quitaba el prefijo del source_id y se buscaba por sha256, pero el
        # source_id solo lleva los primeros 16 caracteres del hash: la búsqueda por
        # sha256 completo nunca casaba y la cita mostraba "book_a3f9..." en vez del título.
        source_info = self.catalog.get_book_by_source_id(top_chunk.get("source_id", "")) or {}
        source_title = source_info.get("title") or top_chunk.get("source_id", "Biblioteca")

        evidence_id = f"ev_{uuid.uuid4().hex[:8]}"

        return {
            "evidence_id": evidence_id,
            "concept_name": concept_name,
            "has_evidence": True,
            "evidence_strength": "MULTI_SOURCE" if len(reranked_chunks) > 1 else "DIRECT",
            "level_1_source": {
                "source_id": top_chunk["source_id"],
                "source_title": source_title,
                "source_path": source_info.get("relative_path", ""),
                "original_filename": source_info.get("original_filename", ""),
                "chapter_num": top_chunk.get("chapter_id"),
                "pages": pages,
                "chunk_ids": chunk_ids,
                "location_summary": f"Libro: {source_title} (Páginas {', '.join(map(str, pages))})"
            },
            "level_2_dependencies": [
                "Prerrequisitos conceptuales del capítulo",
                "Matemáticas y código enlazado"
            ],
            "level_3_pedagogical_reason": f"Ubicado en el plan de estudio porque {concept_name} requiere la fundamentación extraída en los fragmentos de la biblioteca.",
            "top_reasons": top_chunk.get("reasons", []),
            "confidence": top_chunk.get("final_score", 0.95)
        }
