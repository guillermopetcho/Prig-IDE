import os
from datetime import datetime
from typing import Dict, Any
from .pdf_parser import PDFParser
from .toc_extractor import TOCExtractor
from .semantic_chunker import SemanticChunker
from ..indexing.db_catalog import DBCatalog

class BookIngestor:
    """ Orquestador completo de Ingestión + Estructuración + Persistencia determinista en catalog.db """

    def __init__(self, catalog: DBCatalog = None):
        self.catalog = catalog or DBCatalog()

    def ingest_document(self, file_path: str, category_type: str = "book") -> Dict[str, Any]:
        # 1. Parsing inicial y cálculo determinista de SHA256
        parsed = PDFParser.parse_document(file_path)
        sha256 = parsed["sha256"]

        # 2. Verificar Idempotencia (¿Ya está en SQLite catalog.db?)
        existing = self.catalog.get_book_by_sha256(sha256)
        if existing:
            chunks = self.catalog.get_chunks_by_source(existing["source_id"])
            return {
                "status": "ALREADY_EXISTS",
                "source_id": existing["source_id"],
                "book": existing,
                "chunks_count": len(chunks),
                "message": f"🔒 Archivo idéntico pre-existente detectado ({existing['source_id']}). Reutilizando índice catalog.db."
            }

        # 3. Construir source_id tipificado + sha256_16
        source_prefix = f"{category_type}_{sha256[:16]}"
        source_id = source_prefix

        # 4. Extracción de Estructura (Chapters & Sections)
        structure = TOCExtractor.extract_structure(parsed, source_id)
        chapters = structure["chapters"]
        sections = structure["sections"]

        # 5. Fragmentación Semántica Inteligente (Level 3 Semantic Chunks)
        chunks = SemanticChunker.chunk_document(parsed, structure, source_id)

        now_str = datetime.now().isoformat()
        rel_path = f"{category_type.upper()}/{parsed['filename']}"

        book_data = {
            "source_id": source_id,
            "source_type": category_type,
            "title": parsed["filename"],
            "original_filename": parsed["filename"],
            "relative_path": rel_path,
            "sha256": sha256,
            "file_size": parsed["file_size"],
            "authors": [],
            "total_pages": parsed["total_pages"],
            "document_version": 1,
            "index_version": 1,
            # abs_path permite emparejar de forma exacta un archivo de la biblioteca
            # con su entrada del catálogo; por nombre sería ambiguo entre categorías.
            "metadata": {"ext": parsed["ext"], "abs_path": parsed["abs_path"]},
            "created_at": now_str,
            "modified_at": now_str
        }

        # Completar timestamps en capítulos y secciones
        for ch in chapters:
            ch["created_at"] = now_str
        for sec in sections:
            sec["created_at"] = now_str

        # 6. Persistir todo atómicamente en SQLite catalog.db
        self.catalog.insert_book(book_data)
        self.catalog.insert_chapters(chapters)
        self.catalog.insert_sections(sections)
        self.catalog.insert_chunks(chunks)

        return {
            "status": "INGESTED",
            "source_id": source_id,
            "book": book_data,
            "chapters_count": len(chapters),
            "sections_count": len(sections),
            "chunks_count": len(chunks),
            "message": f"✨ Documento procesado y persistido exitosamente en catalog.db SQLite ({source_id})"
        }
