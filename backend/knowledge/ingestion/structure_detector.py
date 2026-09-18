import re
from typing import Dict, Any

class StructureDetector:
    """ Clasificador determinista de contenido de fragmentos (TEXT, MATHEMATICS, CODE, ALGORITHM, DEFINITION, PROOF, EXAMPLE, EXERCISE) """

    @classmethod
    def detect_structure(cls, text_block: str) -> Dict[str, Any]:
        has_equation = bool(re.search(r'(\$\$|\$.*?\$|\\[a-zA-Z]+|\∂|\∑|\∫|=|\\begin\{equation\})', text_block))
        has_code = bool(re.search(r'(def\s+\w+|class\s+\w+|import\s+\w+|from\s+\w+|return\s+|for\s+.*in\s+|torch\.|nn\.|np\.)', text_block))

        content_type = "TEXT"

        if has_code:
            content_type = "CODE"
        elif has_equation and re.search(r'(demostración|proof|teorema|lemma|\$$\s*\\begin)', text_block, re.IGNORECASE):
            content_type = "PROOF"
        elif has_equation:
            content_type = "MATHEMATICS"
        elif re.search(r'^(definición|definition|se define como)', text_block, re.IGNORECASE):
            content_type = "DEFINITION"
        elif re.search(r'(algoritmo|algorithm|paso 1|step 1)', text_block, re.IGNORECASE):
            content_type = "ALGORITHM"
        elif re.search(r'(ejemplo|example|por ejemplo)', text_block, re.IGNORECASE):
            content_type = "EXAMPLE"
        elif re.search(r'(ejercicio|exercise|problema)', text_block, re.IGNORECASE):
            content_type = "EXERCISE"

        # Extraer símbolos clave
        symbols = list(set(re.findall(r'(\\[a-zA-Z]+|def\s+\w+|class\s+\w+|torch\.\w+)', text_block)))

        return {
            "content_type": content_type,
            "contains_equation": has_equation,
            "contains_code": has_code,
            "symbols": symbols[:10]
        }
