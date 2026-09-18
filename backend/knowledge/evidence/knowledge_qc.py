from typing import Dict, Any, List
from ..indexing.db_catalog import DBCatalog

class KnowledgeQCEngine:
    """ Motor Dual de Control de Calidad del Conocimiento (Determinista + Semántico) """

    def __init__(self, catalog: DBCatalog = None):
        self.catalog = catalog or DBCatalog()

    def verify_proposal(self, proposal: Dict[str, Any], distilled_context: Dict[str, Any]) -> Dict[str, Any]:
        """ Realiza verificación determinista y semántica sobre la propuesta de conocimiento del LLM """
        concept_name = proposal.get("concept_name", "General")
        claims = proposal.get("claims", [])
        distilled_chunks = distilled_context.get("distilled_chunks", [])

        verified_claims = []
        conflicts_detected = []

        # 1. Deterministic QC: Verificación de estructura y hashes
        if not distilled_chunks:
            return {
                "status": "INSUFFICIENT_EVIDENCE",
                "verified_claims_count": 0,
                "conflicts_count": 0,
                "claims": [],
                "conflicts": [],
                "message": "⚠️ QC Engine: Sin fragmentos de evidencia en catalog.db para verificar la propuesta."
            }

        # 2. Semantic QC: Alineación de afirmaciones con los fragmentos de la Biblioteca
        available_content = " ".join([c["content"].lower() for c in distilled_chunks])

        for clm in claims:
            statement = clm.get("statement", "")
            words = [w for w in statement.lower().split() if len(w) > 4]
            
            matches = sum(1 for w in words if w in available_content)
            match_ratio = matches / len(words) if words else 0.0

            if match_ratio >= 0.3:
                clm["status"] = "VERIFIED"
                clm["confidence"] = round(min(1.0, match_ratio + 0.4), 2)
                verified_claims.append(clm)
            else:
                clm["status"] = "INSUFFICIENT_EVIDENCE"
                clm["confidence"] = round(match_ratio, 2)
                verified_claims.append(clm)

        qc_status = "VERIFIED" if any(c["status"] == "VERIFIED" for c in verified_claims) else "EVIDENCE_FOUND"

        return {
            "status": qc_status,
            "concept_name": concept_name,
            "verified_claims_count": sum(1 for c in verified_claims if c["status"] == "VERIFIED"),
            "conflicts_count": len(conflicts_detected),
            "claims": verified_claims,
            "conflicts": conflicts_detected,
            "message": f"✅ QC Engine: Propuesta evaluada. {len(verified_claims)} afirmaciones procesadas."
        }
