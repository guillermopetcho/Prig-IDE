import os
import hashlib
from typing import Dict, Any, List

def _extraer_rango(args):
    """ Texto de un rango de páginas. A nivel de módulo porque cada proceso hijo
    tiene que poder importarla; una función anidada no se puede enviar. """
    import logging
    import pypdf
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    ruta, desde, hasta = args
    lector = pypdf.PdfReader(ruta)
    salida = []
    for i in range(desde, min(hasta, len(lector.pages))):
        try:
            texto = lector.pages[i].extract_text() or ""
        except Exception:
            texto = ""
        salida.append({"page_num": i + 1, "text": texto.strip()})
    return salida


class PDFParser:
    """ Parser determinista para extraer texto, páginas y metadatos de archivos PDF y texto/código """

    @staticmethod
    def calculate_sha256(file_path: str) -> str:
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(65536), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    # Arrancar procesos cuesta unas décimas: por debajo de este tamaño sale más
    # a cuenta hacerlo en serie.
    PAGINAS_PARA_PARALELIZAR = 80

    @classmethod
    def _extraer_paginas(cls, ruta: str, total: int) -> list:
        """ Texto de todas las páginas, en paralelo si el libro es grande.

        Medido sobre un libro de 195 páginas: 1,9 s en serie contra 0,5 s con
        cuatro procesos, con el texto byte a byte idéntico. La extracción de texto
        de pypdf es trabajo de CPU puro, así que los hilos no servirían: hacen
        falta procesos.
        """
        import pypdf
        if total < cls.PAGINAS_PARA_PARALELIZAR:
            lector = pypdf.PdfReader(ruta)
            salida = []
            for i in range(total):
                try:
                    texto = lector.pages[i].extract_text() or ""
                except Exception:
                    texto = ""
                salida.append({"page_num": i + 1, "text": texto.strip()})
            return salida

        try:
            from concurrent.futures import ProcessPoolExecutor
            trabajadores = min(4, os.cpu_count() or 2)
            trozo = total // trabajadores + 1
            tareas = [(ruta, i, i + trozo) for i in range(0, total, trozo)]
            with ProcessPoolExecutor(max_workers=trabajadores) as pool:
                partes = list(pool.map(_extraer_rango, tareas))
            paginas = [p for parte in partes for p in parte]
            paginas.sort(key=lambda x: x["page_num"])
            if len(paginas) == total:
                return paginas
        except Exception as err:
            print(f"Extracción en paralelo no disponible ({err}); se hace en serie.")

        lector = pypdf.PdfReader(ruta)
        return [{"page_num": i + 1,
                 "text": (lector.pages[i].extract_text() or "").strip()}
                for i in range(total)]

    @staticmethod
    def _extract_outline(reader) -> list:
        """ Marcadores del PDF, con su nivel y la página a la que apuntan """
        salida = []

        def recorrer(nodos, nivel=0):
            for n in nodos:
                if isinstance(n, list):
                    recorrer(n, nivel + 1)
                    continue
                try:
                    pagina = reader.get_destination_page_number(n) + 1
                except Exception:
                    pagina = None
                try:
                    titulo = str(n.title).strip()
                except Exception:
                    continue
                if titulo:
                    salida.append({"title": titulo, "level": nivel, "page": pagina})

        try:
            recorrer(reader.outline)
        except Exception:
            return []
        return salida

    @classmethod
    def parse_document(cls, file_path: str) -> Dict[str, Any]:
        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"El archivo no existe: {file_path}")

        sha256 = cls.calculate_sha256(abs_path)
        file_size = os.path.getsize(abs_path)
        filename = os.path.basename(abs_path)
        ext = filename.split('.')[-1].lower() if '.' in filename else ''

        pages_content = []
        outline = []

        if ext == 'pdf':
            try:
                import pypdf
                reader = pypdf.PdfReader(abs_path)
                pages_content = cls._extraer_paginas(abs_path, len(reader.pages))
                # Los marcadores del PDF son el índice REAL cuando existen: traen
                # título, nivel y página exacta. Deducirlo del texto con expresiones
                # regulares, que es lo único que se hacía, detectaba un capítulo en
                # un libro que traía 172 entradas en sus marcadores.
                outline = cls._extract_outline(reader)
            except Exception as err:
                print(f"Advertencia pypdf en {filename}: {err}")
                # Fallback texto básico si pypdf falla
                pages_content.append({"page_num": 1, "text": f"Contenido PDF: {filename}"})
        elif ext == 'ipynb':
            # Un cuaderno indexado como JSON crudo llena el índice de comillas y
            # metadatos. Se extraen las celdas y cada una actúa como "página".
            try:
                import json as _json
                with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                    nb = _json.load(f)
                for idx, cell in enumerate(nb.get('cells', []), start=1):
                    src = cell.get('source', [])
                    text = "".join(src) if isinstance(src, list) else str(src)
                    if text.strip():
                        prefix = "# " if cell.get('cell_type') == 'markdown' else ""
                        pages_content.append({"page_num": idx, "text": f"{prefix}{text.strip()}"})
            except Exception as err:
                print(f"Advertencia al leer cuaderno {filename}: {err}")
            if not pages_content:
                pages_content.append({"page_num": 1, "text": ""})
        else:
            # Archivo de texto, python o markdown
            try:
                with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                pages_content.append({"page_num": 1, "text": content.strip()})
            except Exception as err:
                pages_content.append({"page_num": 1, "text": ""})

        return {
            "abs_path": abs_path,
            "filename": filename,
            "ext": ext,
            "sha256": sha256,
            "file_size": file_size,
            "total_pages": len(pages_content),
            "pages": pages_content,
            "outline": outline,
        }
