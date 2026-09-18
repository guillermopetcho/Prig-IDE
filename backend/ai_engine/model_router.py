import os
import requests
from enum import Enum
from typing import Dict, Any, Optional

class ModelTierEnum(str, Enum):
    FAST = "FAST"          # Router, UI, resúmenes rápidos (~2-3 GB VRAM)
    REASONING = "REASONING"# Razonamiento, síntesis de evidencias (~5 GB VRAM)
    CODE = "CODE"          # Código PyTorch/Python (~3-5 GB VRAM)

class ModelRouter:
    """ Enrutador inteligente de modelos Ollama optimizado para hardware GPU (6 GB VRAM + 64 GB RAM) """

    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self.ollama_url = ollama_url
        self.tier_map = {
            ModelTierEnum.FAST: "qwen2.5-coder:7b",
            ModelTierEnum.REASONING: "qwen2.5-coder:7b",
            ModelTierEnum.CODE: "qwen2.5-coder:7b"
        }

    def get_available_models(self) -> list:
        try:
            res = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if res.status_code == 200:
                data = res.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return ["qwen2.5-coder:7b"]

    def resolve_model(self, tier: ModelTierEnum, requested_model: Optional[str] = None) -> str:
        if requested_model and requested_model.strip():
            return requested_model.strip()

        available = self.get_available_models()
        preferred = self.tier_map.get(tier, "qwen2.5-coder:7b")

        if preferred in available:
            return preferred

        # Fallback inteligente al primer modelo disponible en Ollama
        return available[0] if available else "qwen2.5-coder:7b"

    def update_tier_mapping(self, new_mapping: Dict[str, str]):
        for k, v in new_mapping.items():
            if k in self.tier_map:
                self.tier_map[k] = v
