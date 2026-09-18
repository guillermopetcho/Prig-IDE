import re
from typing import Dict, Any, List

class TOCExtractor:
    """ Extractor determinista de Tabla de Contenidos (TOC) y jerarquía de Capítulos / Secciones """

    # Un libro con un solo marcador no tiene índice, tiene una portada marcada.
    MINIMO_MARCADORES = 3

    @classmethod
    def _desde_marcadores(cls, outline: List[Dict[str, Any]], source_id: str,
                          total_paginas: int) -> Dict[str, Any]:
        """ Construye capítulos y secciones a partir de los marcadores del PDF.

        El nivel 0 son capítulos y el resto secciones. La página de fin de cada uno
        es la de inicio del siguiente del mismo nivel o superior: sin eso no se
        puede decir "lee las páginas 181 a 240", que es justo lo que un plan de
        estudio necesita.
        """
        entradas = [e for e in outline if e.get("page")]
        if len(entradas) < cls.MINIMO_MARCADORES:
            return {}

        capitulos, secciones = [], []
        n_cap = n_sec = 0
        for i, e in enumerate(entradas):
            # El fin es donde empieza el siguiente hermano o un antepasado
            fin = total_paginas or e["page"]
            for siguiente in entradas[i + 1:]:
                if siguiente["level"] <= e["level"]:
                    fin = max(e["page"], siguiente["page"] - 1)
                    break
            comun = {
                "source_id": source_id,
                "title": e["title"],
                "start_page": e["page"],
                "end_page": fin,
                "key_topics": [e["title"]],
                "prerequisites": [],
                "created_at": "",
            }
            if e["level"] == 0:
                n_cap += 1
                capitulos.append({**comun,
                                  "chapter_id": f"chp_{source_id}_{n_cap:02d}",
                                  "chapter_num": n_cap,
                                  "summary": e["title"]})
            else:
                n_sec += 1
                secciones.append({**comun,
                                  "section_id": f"sec_{source_id}_{n_sec:03d}",
                                  "chapter_id": (capitulos[-1]["chapter_id"]
                                                 if capitulos else None),
                                  "section_num": f"{n_cap}.{n_sec}",
                                  "level": e["level"],
                                  "summary": e["title"]})

        if not capitulos and secciones:
            # Todos al mismo nivel: son capítulos, no subsecciones de nada
            return cls._desde_marcadores(
                [{**e, "level": 0} for e in entradas], source_id, total_paginas)

        return {"source_id": source_id, "chapters": capitulos, "sections": secciones,
                "origen": "marcadores_pdf"}

    @classmethod
    def extract_structure(cls, parsed_doc: Dict[str, Any], source_id: str) -> Dict[str, Any]:
        # Si el PDF trae marcadores, son el índice de verdad: título, nivel y página
        # exacta, puestos por quien maquetó el libro. Buscar "Capítulo N" en el texto
        # extraído es lo que hay que hacer cuando no los hay, no la primera opción.
        desde_marcadores = cls._desde_marcadores(parsed_doc.get("outline") or [],
                                                 source_id,
                                                 parsed_doc.get("total_pages") or 0)
        if desde_marcadores:
            return desde_marcadores

        pages = parsed_doc.get("pages", [])
        chapters = []
        sections = []

        current_chapter = None
        current_section = None

        chapter_pattern = re.compile(r'^(?:Capítulo|Chapter)\s+(\d+)[:\.\s]+(.+)$', re.IGNORECASE)
        section_pattern = re.compile(r'^(\d+\.\d+)\s+(.+)$')

        line_num = 0
        for p in pages:
            page_num = p["page_num"]
            lines = p["text"].split('\n')
            
            for line in lines:
                line_str = line.strip()
                if not line_str:
                    continue

                ch_match = chapter_pattern.match(line_str)
                if ch_match:
                    ch_num = int(ch_match.group(1))
                    ch_title = ch_match.group(2).strip()
                    ch_id = f"chp_{source_id}_{ch_num:02d}"

                    current_chapter = {
                        "chapter_id": ch_id,
                        "source_id": source_id,
                        "chapter_num": ch_num,
                        "title": ch_title,
                        "start_page": page_num,
                        "end_page": page_num,
                        "summary": f"Capítulo {ch_num}: {ch_title}",
                        "key_topics": [ch_title],
                        "prerequisites": [],
                        "created_at": ""
                    }
                    chapters.append(current_chapter)
                    continue

                sec_match = section_pattern.match(line_str)
                if sec_match and current_chapter:
                    sec_num = sec_match.group(1)
                    sec_title = sec_match.group(2).strip()
                    sec_id = f"sec_{source_id}_{current_chapter['chapter_num']:02d}_{sec_num.replace('.', '_')}"

                    current_section = {
                        "section_id": sec_id,
                        "chapter_id": current_chapter["chapter_id"],
                        "source_id": source_id,
                        "section_num": sec_num,
                        "title": sec_title,
                        "start_page": page_num,
                        "end_page": page_num,
                        "summary": f"Sección {sec_num}: {sec_title}",
                        "created_at": ""
                    }
                    sections.append(current_section)
                    continue

                if current_chapter:
                    current_chapter["end_page"] = page_num
                if current_section:
                    current_section["end_page"] = page_num

        # Si no se detectaron capítulos estructurados explícitos, crear 1 capítulo por defecto
        if not chapters:
            ch_id = f"chp_{source_id}_01"
            default_ch = {
                "chapter_id": ch_id,
                "source_id": source_id,
                "chapter_num": 1,
                "title": parsed_doc.get("filename", "Contenido Principal"),
                "start_page": 1,
                "end_page": parsed_doc.get("total_pages", 1),
                "summary": f"Contenido completo de {parsed_doc.get('filename')}",
                "key_topics": [parsed_doc.get("filename")],
                "prerequisites": [],
                "created_at": ""
            }
            chapters.append(default_ch)

            sec_id = f"sec_{source_id}_01_1"
            default_sec = {
                "section_id": sec_id,
                "chapter_id": ch_id,
                "source_id": source_id,
                "section_num": "1.0",
                "title": "Sección General",
                "start_page": 1,
                "end_page": parsed_doc.get("total_pages", 1),
                "summary": "Sección única del documento",
                "created_at": ""
            }
            sections.append(default_sec)

        return {
            "chapters": chapters,
            "sections": sections
        }
