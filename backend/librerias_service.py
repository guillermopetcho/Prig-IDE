"""
Las citas de las librerías para el chat del tutor (que sigue en Python). Todo lo demás del analista de librerías
(la lista, dar de alta, guardar, borrar, exportar y analizar con IA) es del servidor de Rust
(backend-rust/crates/prig-server/src/routes/librerias.rs), que escribe estos mismos archivos.
"""

import os
import json
from typing import List, Dict, Any, Optional


def _carpeta() -> str:
    base = os.environ.get("PRIG_BOOKS_DIR") or os.path.expanduser("~/.prig_books")
    return os.path.join(os.path.abspath(base), "librerias")


def get_all_library_citations_for_ai(query: Optional[str] = None, max_results: int = 10) -> List[Dict[str, Any]]:
    """ Recolecta citas de librerías para alimentar el razonamiento de los modelos en el chat """
    results = []
    if not os.path.isdir(_carpeta()):
        return []

    q_terms = [t.lower() for t in (query or "").split() if len(t) > 2]

    for fname in os.listdir(_carpeta()):
        if not fname.endswith(".json") or fname == "lista_librerias.json":
            continue
        fpath = os.path.join(_carpeta(), fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                lib_data = json.load(f)
            lname = lib_data.get("nombre") or lib_data.get("libreria") or fname
            for c in lib_data.get("citas", []):
                item = {
                    "tipo": "libreria",
                    "libreria": lname,
                    "modulo": c.get("modulo", ""),
                    "funcion": c.get("funcion", ""),
                    "tema": c.get("tema", ""),
                    "snippet": c.get("snippet", ""),
                    "explicacion": c.get("explicacion", ""),
                    "parametros": c.get("parametros_clave", []),
                    "tags": c.get("tags", []),
                    "id": c.get("id", "")
                }
                if not q_terms:
                    results.append(item)
                else:
                    match_count = sum(1 for term in q_terms if term in item["funcion"].lower() or term in item["tema"].lower() or term in item["explicacion"].lower() or term in item["libreria"].lower() or any(term in str(tg).lower() for tg in item["tags"]))
                    if match_count > 0:
                        item["_score"] = match_count
                        results.append(item)
        except Exception:
            continue

    if q_terms:
        results.sort(key=lambda x: x.get("_score", 0), reverse=True)
    return results[:max_results]
