import re
from typing import List, Dict, Any
from ..indexing.db_catalog import DBCatalog

class MacroRetriever:
    """ Filtro Macro Level 0 / Level 1 que descarta el 90% de libros/capítulos irrelevantes """

    def __init__(self, catalog: DBCatalog = None):
        self.catalog = catalog or DBCatalog()

    def filter_candidate_sources(self, query: str, top_books: int = 5) -> List[str]:
        q_words = set(re.findall(r'\w+', query.lower()))
        if not q_words:
            return []

        with self.catalog.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT source_id, title, key_topics_json, summary FROM chapters;")
            rows = cursor.fetchall()

        source_scores: Dict[str, float] = {}
        for r in rows:
            src_id = r["source_id"]
            text = f"{r['title']} {r['summary']} {r['key_topics_json']}".lower()
            matches = sum(1 for w in q_words if w in text)
            if matches > 0:
                source_scores[src_id] = source_scores.get(src_id, 0.0) + matches

        sorted_sources = sorted(source_scores.items(), key=lambda x: x[1], reverse=True)
        return [src for src, score in sorted_sources[:top_books]]
