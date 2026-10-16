from typing import Dict, Any


class StructureDetector:
    """ Clasificador determinista de contenido de fragmentos (TEXT, MATHEMATICS, CODE, ALGORITHM, DEFINITION, PROOF,
    EXAMPLE, EXERCISE). En Rust (prig-biblioteca, troceado.rs); los símbolos salen por orden de aparición. """

    @classmethod
    def detect_structure(cls, text_block: str) -> Dict[str, Any]:
        from nativo_rust import rust
        return rust().troceado.clasificar(text_block)
