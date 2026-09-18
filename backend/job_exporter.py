"""
Prepara el trabajo de extracción que se ejecutará en una GPU externa.

El troceado se hace AQUÍ, en local, por tres razones:
  · es determinista y no necesita GPU,
  · el resultado es mucho más pequeño que los PDF,
  · y así no hace falta subir los libros originales a ninguna plataforma.

Sale una carpeta lista para subir como dataset:

    prig_job_<id>/
        manifest.json     qué libros, con su sha256 y su recuento
        chunks.jsonl      un fragmento por línea, con su libro y su página
        outline.json      el índice detectado de cada libro
"""

import os
import json
import uuid
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kaggle_worker"))
from domains import DOMAINS, sugerir_dominio  # noqa: E402

from knowledge.ingestion.pdf_parser import PDFParser
from knowledge.ingestion.toc_extractor import TOCExtractor
from knowledge.ingestion.semantic_chunker import SemanticChunker

SCHEMA_VERSION = "3.1"


class JobExporter:
    def __init__(self, books_dir: Optional[str] = None):
        self.books_dir = os.path.abspath(books_dir or os.path.expanduser("~/.prig_books"))

    # ------------------------------------------------------------------

    def preparar(self, rutas, destino: str,
                 max_chunk_tokens: int = 500,
                 min_chars: int = 120,
                 progreso=None) -> Dict[str, Any]:
        """ `rutas` admite str o (ruta, dominio). Sin dominio se propone uno por
        palabras clave, pero conviene revisarlo: un libro mal clasificado contamina
        todo lo que salga de él. """
        """ Trocea los libros indicados y deja el trabajo listo para subir.

        `min_chars` descarta fragmentos demasiado cortos (números de página sueltos,
        encabezados): procesarlos gasta GPU y no producen conocimiento.
        """
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        destino = os.path.abspath(os.path.expanduser(destino))
        os.makedirs(destino, exist_ok=True)

        libros: List[Dict[str, Any]] = []
        outlines: Dict[str, Any] = {}
        total_chunks = 0
        descartados = 0
        # El mismo libro puede estar guardado en dos carpetas de la biblioteca.
        # Procesarlo dos veces duplica los fragmentos dentro del paquete y gasta
        # el doble de GPU para no aportar nada.
        vistos: Dict[str, str] = {}
        repetidos: List[str] = []
        # Un libro que no se puede leer no debe tumbar el trabajo entero: se anota
        # y se sigue. Con veinte libros seleccionados, abortar por el tercero
        # significa volver a empezar y esperar otra vez lo ya hecho.
        fallidos: List[Dict[str, str]] = []

        def avisar(**datos):
            if progreso:
                try:
                    progreso(datos)
                except Exception:
                    pass

        ruta_chunks = os.path.join(destino, "chunks.jsonl")
        with open(ruta_chunks, "w", encoding="utf-8") as salida:
            for numero, item in enumerate(rutas, 1):
                # Admite "ruta", ("ruta", "dominio") o un diccionario con ajustes
                # propios: el tamaño de fragmento que le conviene a un libro de
                # matemáticas no es el mismo que el de uno de programación.
                ajustes = {}
                if isinstance(item, dict):
                    ruta = item.get("path") or item.get("ruta")
                    dominio = item.get("domain") or item.get("dominio")
                    ajustes = item.get("ajustes") or {}
                elif isinstance(item, (tuple, list)):
                    ruta, dominio = item[0], (item[1] if len(item) > 1 else None)
                else:
                    ruta, dominio = item, None
                tope = int(ajustes.get("max_chunk_tokens") or max_chunk_tokens)
                avisar(tipo="libro", n=numero, total=len(rutas),
                       nombre=os.path.basename(str(ruta)))
                # expanduser antes que abspath: sin esto "~/.prig_books/x.pdf" se
                # convierte en una carpeta relativa que no existe y el libro se
                # omite con un aviso fácil de pasar por alto.
                abs_ruta = os.path.abspath(os.path.expanduser(str(ruta)))
                if not os.path.isfile(abs_ruta):
                    fallidos.append({"ruta": str(ruta), "motivo": "no existe"})
                    avisar(tipo="fallo", nombre=os.path.basename(str(ruta)),
                           motivo="no existe")
                    continue

                try:
                    parsed = PDFParser.parse_document(abs_ruta)
                except Exception as err:
                    fallidos.append({"ruta": str(ruta), "motivo": f"no se pudo leer: {err}"})
                    avisar(tipo="fallo", nombre=os.path.basename(str(ruta)),
                           motivo=str(err)[:160])
                    continue

                # Un PDF escaneado no tiene texto que trocear. Sin esta comprobación
                # entra en el trabajo como un libro más y produce cero fragmentos
                # útiles, gastando GPU en nada.
                con_texto = sum(1 for pg in parsed["pages"] if len(pg.get("text") or "") > 120)
                if parsed["total_pages"] > 5 and con_texto < parsed["total_pages"] * 0.3:
                    fallidos.append({"ruta": str(ruta),
                                     "motivo": "parece escaneado: casi no tiene texto "
                                               "extraíble. Necesita OCR."})
                    avisar(tipo="fallo", nombre=os.path.basename(str(ruta)),
                           motivo="parece escaneado, necesita OCR")
                    continue

                if not dominio or dominio not in DOMAINS:
                    muestra = " ".join(p["text"] for p in parsed["pages"][:4])
                    dominio = sugerir_dominio(muestra, parsed["filename"])

                source_id = f"book_{parsed['sha256'][:16]}"
                if source_id in vistos:
                    repetidos.append(os.path.basename(abs_ruta))
                    avisar(tipo="repetido", nombre=os.path.basename(abs_ruta),
                           ya_como=os.path.basename(vistos[source_id]))
                    continue
                vistos[source_id] = abs_ruta
                estructura = TOCExtractor.extract_structure(parsed, source_id)
                chunks = SemanticChunker.chunk_document(
                    parsed, estructura, source_id, max_chunk_tokens=tope
                )

                escritos = 0
                for c in chunks:
                    texto = (c.get("content") or "").strip()
                    if len(texto) < min_chars:
                        descartados += 1
                        continue
                    salida.write(json.dumps({
                        "chunk_id": c["chunk_id"],
                        "source_id": source_id,
                        "book_title": parsed["filename"],
                        "domain": dominio,
                        "page": c.get("page_start", 1),
                        "page_end": c.get("page_end", c.get("page_start", 1)),
                        "content_type": c.get("content_type", "TEXT"),
                        "section_id": c.get("section_id"),
                        "chapter_id": c.get("chapter_id"),
                        "text": texto,
                    }, ensure_ascii=False) + "\n")
                    escritos += 1

                libros.append({
                    "source_id": source_id,
                    "title": parsed["filename"],
                    "domain": dominio,
                    "sha256": parsed["sha256"],
                    "pages": parsed["total_pages"],
                    "file_size": parsed["file_size"],
                    "chunks": escritos,
                    "max_chunk_tokens": tope,
                    "indice": estructura.get("origen", "heuristica_texto"),
                    "capitulos": len(estructura.get("chapters") or []),
                })
                outlines[source_id] = {
                    "chapters": estructura.get("chapters", []),
                    "sections": estructura.get("sections", []),
                }
                total_chunks += escritos
                avisar(tipo="listo", nombre=parsed["filename"], dominio=dominio,
                       fragmentos=escritos, paginas=parsed["total_pages"],
                       capitulos=len(estructura.get("chapters") or []))

        with open(os.path.join(destino, "outline.json"), "w", encoding="utf-8") as f:
            json.dump(outlines, f, ensure_ascii=False, indent=2)

        manifest = {
            "job_id": job_id,
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now().isoformat(),
            "books": libros,
            "total_books": len(libros),
            "total_chunks": total_chunks,
            "domains": sorted({b["domain"] for b in libros}),
            "discarded_short_chunks": descartados,
            "duplicates_skipped": repetidos,
            "failed": fallidos,
            "max_chunk_tokens": max_chunk_tokens,
            # Ata el paquete de salida a exactamente esta entrada
            "chunks_sha256": self._sha256(ruta_chunks),
        }
        with open(os.path.join(destino, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        manifest["output_dir"] = os.path.abspath(destino)
        manifest["estimated_mb"] = round(os.path.getsize(ruta_chunks) / (1024 * 1024), 2)
        return manifest

    @staticmethod
    def _sha256(ruta: str) -> str:
        h = hashlib.sha256()
        with open(ruta, "rb") as f:
            for bloque in iter(lambda: f.read(65536), b""):
                h.update(bloque)
        return h.hexdigest()

    # ------------------------------------------------------------------

    def libros_disponibles(self) -> List[Dict[str, Any]]:
        """ PDF y documentos de la biblioteca que se pueden enviar a extraer """
        encontrados = []
        for raiz, dirs, ficheros in os.walk(self.books_dir):
            dirs[:] = [d for d in dirs if d not in (".index", "metadata") and not d.startswith(".")]
            for nombre in sorted(ficheros):
                ext = os.path.splitext(nombre)[1].lower()
                if ext not in (".pdf", ".md", ".txt", ".rst"):
                    continue
                ruta = os.path.join(raiz, nombre)
                encontrados.append({
                    "path": ruta,
                    "name": nombre,
                    "size_mb": round(os.path.getsize(ruta) / (1024 * 1024), 2),
                })
        return encontrados
