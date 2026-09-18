import os
import json
import hashlib
from typing import Dict, Any, List
from .worker_contracts import KaggleJobManifest
from ..models.claim import Claim

class EnrichmentPackageValidator:
    """ Validador de Paquetes de Mutación Remotos (claims.jsonl, manifest.json, checksums.json) """

    @classmethod
    def validate_package(cls, package_dir: str) -> Dict[str, Any]:
        abs_pkg = os.path.abspath(package_dir)
        manifest_path = os.path.join(abs_pkg, "manifest.json")
        claims_path = os.path.join(abs_pkg, "claims.jsonl")

        if not os.path.exists(manifest_path):
            return {"is_valid": False, "error": f"Falta manifest.json en {abs_pkg}"}

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                raw_manifest = json.load(f)
            manifest = KaggleJobManifest.model_validate(raw_manifest)
        except Exception as err:
            return {"is_valid": False, "error": f"Error de esquema en manifest.json: {str(err)}"}

        valid_claims_count = 0
        if os.path.exists(claims_path):
            with open(claims_path, 'r', encoding='utf-8') as f:
                for line_idx, line in enumerate(f):
                    if line.strip():
                        try:
                            claim_dict = json.loads(line)
                            Claim.model_validate(claim_dict)
                            valid_claims_count += 1
                        except Exception as err:
                            return {"is_valid": False, "error": f"Línea {line_idx+1} inválida en claims.jsonl: {str(err)}"}

        return {
            "is_valid": True,
            "job_id": manifest.job_id,
            "manifest": manifest,
            "valid_claims_count": valid_claims_count
        }
