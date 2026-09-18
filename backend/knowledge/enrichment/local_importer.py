import os
import json
from typing import Dict, Any, List
from ..indexing.db_catalog import DBCatalog

from .package_validator import EnrichmentPackageValidator

class LocalEnrichmentImporter:
    """ Importador y Validador Local de Paquetes de Enriquecimiento (Kaggle / Remote Workers) """

    def __init__(self, catalog: DBCatalog = None):
        self.catalog = catalog or DBCatalog()

    def import_enrichment_package(self, package_dir: str) -> Dict[str, Any]:
        abs_pkg = os.path.abspath(package_dir)
        validation = EnrichmentPackageValidator.validate_package(abs_pkg)
        if not validation["is_valid"]:
            raise ValueError(f"Paquete de enriquecimiento inválido: {validation['error']}")

        manifest = validation["manifest"]
        claims_path = os.path.join(abs_pkg, "claims.jsonl")


        imported_claims = 0
        if os.path.exists(claims_path):
            with open(claims_path, 'r', encoding='utf-8') as f:
                with self.catalog.get_connection() as conn:
                    cursor = conn.cursor()
                    for line in f:
                        if line.strip():
                            c_data = json.loads(line)

                            # Garantizar que el concept_id existe en la tabla concepts (FK constraint)
                            cursor.execute("""
                            INSERT OR IGNORE INTO concepts (concept_id, name, created_at)
                            VALUES (?, ?, ?);
                            """, (c_data["concept_id"], c_data["concept_id"].replace("conc_", "").title(), c_data.get("created_at")))

                            cursor.execute("""
                            INSERT OR REPLACE INTO claims (
                                claim_id, concept_id, statement, claim_type, status, evidence_ids_json, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                            """, (
                                c_data["claim_id"], c_data["concept_id"], c_data["statement"],
                                c_data.get("claim_type", "DECLARATIVE"), c_data.get("status", "VERIFIED"),
                                json.dumps(c_data.get("evidence_ids", [])), c_data["created_at"], c_data["updated_at"]
                            ))
                            imported_claims += 1


                    conn.commit()

        return {
            "status": "IMPORTED",
            "job_id": manifest.job_id,
            "model_used": manifest.model_used,
            "imported_claims_count": imported_claims,
            "message": f"✨ Paquete de enriquecimiento ({manifest.job_id}) fusionado con éxito en catalog.db local."
        }

