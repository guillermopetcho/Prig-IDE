import os
import json
import uuid
import shutil
import urllib.parse
from datetime import datetime
from typing import List, Dict, Any, Optional

try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

# Extensiones que la biblioteca muestra. Deben ser un superconjunto de las que
# indexa knowledge_service: si aquí aparece algo que allí no, el elemento se queda
# en "no indexado" para siempre sin que nadie explique por qué.
VIEWABLE_EXTENSIONS = {
    'pdf', 'md', 'txt', 'rst', 'ipynb', 'py', 'js', 'sql',
    'json', 'html', 'css', 'cpp', 'c', 'csv', 'tsv', 'parquet',
}

# Subconjunto que el motor de conocimiento sabe fragmentar e indexar
INDEXABLE_EXTENSIONS = {'pdf', 'md', 'txt', 'rst', 'ipynb', 'py', 'js', 'sql'}

CATEGORIES = {
    "books": {"name": "BOOKS", "label": "Libros & E-books", "icon": "fa-book"},
    "documentation": {"name": "DOCUMENTATION", "label": "Documentación & Manuales", "icon": "fa-file-lines"},
    "papers": {"name": "PAPERS", "label": "Papers & Investigaciones", "icon": "fa-newspaper"},
    "code": {"name": "CODE", "label": "Código Fuente", "icon": "fa-code"},
    "notebooks": {"name": "NOTEBOOKS", "label": "Jupyter Notebooks", "icon": "fa-book-bookmark"},
    "datasets": {"name": "DATASETS", "label": "Datasets & Datos", "icon": "fa-database"},
    "projects": {"name": "PROJECTS", "label": "Proyectos & Repositorios", "icon": "fa-folder-tree"}
}

class BookService:
    def __init__(self, books_dir: str = None):
        if not books_dir:
            books_dir = os.environ.get("PRIG_BOOKS_DIR", os.path.expanduser("~/.prig_books"))
        self.books_dir = os.path.abspath(books_dir)
        os.makedirs(self.books_dir, exist_ok=True)

        # Crear subdirectorios de categorías del Repository
        for cat in CATEGORIES.keys():
            os.makedirs(os.path.join(self.books_dir, cat), exist_ok=True)

        self.metadata_dir = os.path.join(self.books_dir, "metadata")
        os.makedirs(self.metadata_dir, exist_ok=True)

        self.citas_dir = os.path.join(self.books_dir, "citas")
        os.makedirs(self.citas_dir, exist_ok=True)
        self.edits_dir = os.path.join(self.citas_dir, "ediciones")
        os.makedirs(self.edits_dir, exist_ok=True)

        snippets_env = os.environ.get("PRIG_SNIPPETS_FILE")
        self.snippets_file = snippets_env if snippets_env else os.path.join(self.books_dir, "snippets.json")
        self._init_sample_books()

    def _init_sample_books(self):
        """ Crea la guía de muestra UNA sola vez en la vida de la biblioteca.

        Comprobar solo si el archivo existe la recreaba en cada arranque; comprobar
        si la biblioteca está vacía la recreaba también en cuanto el usuario borraba
        la guía y no tenía nada más. Un marcador deja claro que ya se ofreció y que
        borrarla es una decisión que se respeta.
        """
        marker = os.path.join(self.books_dir, ".index", ".sample_created")
        if os.path.exists(marker) or self._library_has_content():
            return

        sample_doc = os.path.join(self.books_dir, "documentation", "Guia_Fundamentos_Deep_Learning.md")
        if not os.path.exists(sample_doc):
            try:
                with open(sample_doc, "w", encoding="utf-8") as f:
                    f.write(
                        "# Guía de Fundamentos de Deep Learning\n\n"
                        "## 1. Redes Neuronales y Tensores\n"
                        "Un Tensor es una matriz multidimensional. La capa lineal realiza la operación:\n"
                        "$$y = \\sigma(W \\cdot x + b)$$\n\n"
                        "## 2. Optimizadores\n"
                        "Adam ajusta la tasa de aprendizaje para cada parámetro individualmente:\n"
                        "$$\\theta_{t+1} = \\theta_t - \\frac{\\eta}{\\sqrt{\\hat{v}_t} + \\epsilon} \\hat{m}_t$$\n"
                    )
            except Exception as e:
                print(f"Error creando muestra de repositorio: {e}")

        try:
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            with open(marker, "w", encoding="utf-8") as f:
                f.write("La guía de muestra ya se creó una vez; no se vuelve a generar.\n")
        except Exception:
            pass

    def _library_has_content(self) -> bool:
        """ ¿Hay algún archivo de usuario en la biblioteca? """
        for root, dirs, files in os.walk(self.books_dir):
            dirs[:] = [d for d in dirs if d not in ("metadata", ".index") and not d.startswith(".")]
            for name in files:
                if not name.startswith("."):
                    return True
        return False

    def detect_category(self, filename_or_path: str) -> str:
        ext = os.path.splitext(filename_or_path)[1].lower()
        fname = os.path.basename(filename_or_path).lower()

        # La comprobación de carpeta va primero: iba al final y una carpeta llamada
        # "analisis.py" se clasificaba como código en vez de como proyecto.
        if os.path.isdir(filename_or_path):
            return "projects"

        if 'paper' in fname or 'arxiv' in fname or 'biorxiv' in fname:
            return "papers"
        elif ext == '.pdf':
            return "books"
        elif ext == '.ipynb':
            return "notebooks"
        elif ext in ['.py', '.js', '.cpp', '.c', '.rs', '.go', '.html', '.css']:
            return "code"
        elif ext in ['.csv', '.parquet', '.tsv']:
            return "datasets"
        elif ext in ['.md', '.txt', '.rst']:
            return "documentation"
        return "books"

    @staticmethod
    def _fallback_title(fname: str) -> str:
        """ Título legible derivado del nombre de archivo """
        stem = fname.rsplit('.', 1)[0] if '.' in fname else fname
        return stem.replace('_', ' ').replace('-', ' ').strip() or fname

    def list_books(self, category_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        items = []

        # 1. Escanear directorio raíz y carpetas de categorías
        scan_dirs = []
        if category_filter and category_filter.lower() in CATEGORIES:
            scan_dirs.append((os.path.join(self.books_dir, category_filter.lower()), category_filter.lower()))
        else:
            scan_dirs.append((self.books_dir, None))
            for cat in CATEGORIES.keys():
                scan_dirs.append((os.path.join(self.books_dir, cat), cat))

        seen_paths = set()

        for sdir, cat_name in scan_dirs:
            if not os.path.isdir(sdir):
                continue
            try:
                entries = sorted(os.listdir(sdir))
            except OSError as e:
                print(f"No se pudo leer {sdir}: {e}")
                continue

            for fname in entries:
                fpath = os.path.join(sdir, fname)
                # .index guarda el catálogo SQLite y metadata los JSON del
                # analizador: son infraestructura, no elementos de la biblioteca.
                if fname in ("metadata", ".index") or fname.startswith(".") or fpath in seen_paths:
                    continue
                # Las carpetas de categoría son contenedores, no elementos:
                # aparecían en la lista como si fueran libros llamados "books",
                # "code", "datasets"...
                if sdir == self.books_dir and fname in CATEGORIES:
                    continue

                # Cada elemento va en su propio try: antes un solo archivo
                # problemático (enlace roto, sin permisos, borrado a media lectura)
                # abortaba el bucle entero y la biblioteca aparecía VACÍA.
                try:
                    is_dir = os.path.isdir(fpath)
                    ext = os.path.splitext(fname)[1].lower().lstrip('.') if not is_dir else 'dir'

                    if not is_dir and ext not in VIEWABLE_EXTENSIONS:
                        continue

                    seen_paths.add(fpath)
                    item_category = cat_name or self.detect_category(fpath)
                    size_mb = round(os.path.getsize(fpath) / (1024 * 1024), 2) if not is_dir else 0.0

                    meta = self.get_metadata(fpath)
                    # El título nunca puede ser None: el frontend hace
                    # b.title.toLowerCase() al buscar y rompía la biblioteca entera
                    # si el modelo devolvía una ficha sin campo "title".
                    title = (meta or {}).get("title") or self._fallback_title(fname)

                    items.append({
                        "id": fname,
                        "uid": os.path.relpath(fpath, self.books_dir),
                        "category": item_category.upper(),
                        "category_id": item_category,
                        "title": title,
                        "filename": fname,
                        "path": fpath,
                        "ext": ext,
                        "size_mb": size_mb,
                        "indexable": (not is_dir) and ext in INDEXABLE_EXTENSIONS,
                        "analyzed": bool(meta) and not (meta or {}).get("analysis_failed"),
                        "analysis_failed": bool((meta or {}).get("analysis_failed")),
                        "metadata": meta
                    })
                except OSError as e:
                    print(f"Elemento omitido de la biblioteca ({fname}): {e}")
                    continue

        return items

    def _resolve_item(self, book_id: str) -> Optional[str]:
        """ Localiza un elemento dentro de la biblioteca.

        Se valida que el resultado quede dentro de books_dir: antes un book_id con
        una ruta absoluta o con '..' permitía leer cualquier archivo del sistema.
        """
        if not book_id:
            return None

        candidates = []
        if os.path.isabs(book_id):
            candidates.append(book_id)
        candidates.append(os.path.join(self.books_dir, book_id))
        candidates += [os.path.join(self.books_dir, cat, book_id) for cat in CATEGORIES.keys()]

        for candidate in candidates:
            abs_candidate = os.path.abspath(candidate)
            try:
                inside = os.path.commonpath([abs_candidate, self.books_dir]) == self.books_dir
            except ValueError:
                inside = False
            if inside and os.path.exists(abs_candidate):
                return abs_candidate
        return None

    def get_book_content(self, book_id: str) -> Dict[str, Any]:
        fpath = self._resolve_item(book_id)
        if not fpath:
            return {"error": f"Elemento no encontrado en el Knowledge Repository: {book_id}"}

        ext = os.path.splitext(fpath)[1].lower()
        meta = self.get_metadata(os.path.basename(fpath))

        if ext == '.pdf':
            extracted_text = self.extract_pdf_text(fpath, max_pages=5)
            return {
                "id": os.path.basename(fpath),
                "type": "pdf",
                "path": fpath,
                "url": f"/api/raw-file?path={urllib.parse.quote(fpath, safe='')}",
                "preview_text": extracted_text[:2000],
                "metadata": meta
            }
        else:
            try:
                # Tope de lectura: sin él, un .csv o un log de 50 MB se enviaba entero
                # al navegador y colgaba la interfaz.
                max_chars = 400_000
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read(max_chars + 1)

                truncated = len(text) > max_chars
                if truncated:
                    text = text[:max_chars]

                return {
                    "id": os.path.basename(fpath),
                    "type": "text",
                    "path": fpath,
                    "content": text,
                    "truncated": truncated,
                    "size_bytes": os.path.getsize(fpath),
                    "metadata": meta
                }
            except Exception as e:
                return {"error": f"Error leyendo elemento: {str(e)}"}

    def extract_pdf_text(self, pdf_path: str, max_pages: int = 25) -> str:
        if not PYPDF_AVAILABLE:
            return "pypdf no disponible para extracción de PDF."
        try:
            reader = pypdf.PdfReader(pdf_path)
            extracted = []
            num_pages = min(len(reader.pages), max_pages)
            for i in range(num_pages):
                txt = reader.pages[i].extract_text()
                if txt:
                    extracted.append(f"--- Página {i+1} ---\n{txt}")
            return "\n\n".join(extracted)
        except Exception as e:
            return f"Error extrayendo texto del PDF: {str(e)}"

    def extract_document_text(self, fpath: str, max_chars: int = 15000) -> str:
        ext = os.path.splitext(fpath)[1].lower()
        if ext == '.pdf':
            return self.extract_pdf_text(fpath)[:max_chars]
        elif ext == '.ipynb':
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    nb = json.load(f)
                cells_text = []
                for cell in nb.get('cells', []):
                    c_type = cell.get('cell_type', '')
                    src = "".join(cell.get('source', []))
                    if src.strip():
                        cells_text.append(f"[{c_type.upper()}]\n{src}")
                return "\n\n".join(cells_text)[:max_chars]
            except Exception:
                pass
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()[:max_chars]
        except Exception as e:
            return f"Error leyendo documento: {str(e)}"

    def _metadata_key(self, book_id_or_path: str) -> Optional[str]:
        """ Clave única de metadatos basada en la ruta relativa dentro de la biblioteca.

        Antes la clave era solo el nombre del archivo, así que 'books/notas.md' y
        'documentation/notas.md' compartían ficha y el análisis de uno pisaba el del
        otro.
        """
        abs_path = book_id_or_path if os.path.isabs(book_id_or_path) else self._resolve_item(book_id_or_path)
        if not abs_path:
            return None
        try:
            rel = os.path.relpath(abs_path, self.books_dir)
        except ValueError:
            return None
        return rel.replace(os.sep, "__")

    def get_metadata(self, book_id_or_path: str) -> Optional[Dict[str, Any]]:
        candidates = []
        key = self._metadata_key(book_id_or_path)
        if key:
            candidates.append(f"{key}.json")
        # Compatibilidad con fichas guardadas con el esquema antiguo (solo nombre)
        candidates.append(f"{os.path.basename(book_id_or_path)}.json")

        for name in candidates:
            meta_file = os.path.join(self.metadata_dir, name)
            if os.path.exists(meta_file):
                try:
                    with open(meta_file, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except Exception:
                    continue
        return None

    def save_metadata(self, book_id_or_path: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        key = self._metadata_key(book_id_or_path) or os.path.basename(book_id_or_path)
        meta_file = os.path.join(self.metadata_dir, f"{key}.json")
        try:
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error guardando metadatos para {book_id_or_path}: {e}")
        return metadata

    def import_file(self, source_path: str, target_category: Optional[str] = None) -> Dict[str, Any]:
        abs_src = os.path.abspath(os.path.expanduser(source_path))
        if not os.path.exists(abs_src):
            return {"error": f"El archivo u origen no existe: {source_path}"}
        
        filename = os.path.basename(abs_src)
        category = target_category.lower() if target_category and target_category.lower() in CATEGORIES else self.detect_category(abs_src)
        target_dir = os.path.join(self.books_dir, category)
        dest_path = os.path.join(target_dir, filename)
        
        try:
            if os.path.abspath(abs_src) != os.path.abspath(dest_path):
                if os.path.isdir(abs_src):
                    # dirs_exist_ok en lugar de rmtree: borrar la carpeta destino hacía
                    # desaparecer sin aviso el trabajo previo del usuario.
                    shutil.copytree(abs_src, dest_path, dirs_exist_ok=True)
                else:
                    shutil.copy2(abs_src, dest_path)

            size_mb = round(os.path.getsize(dest_path) / (1024 * 1024), 2) if os.path.isfile(dest_path) else 0.0
            ext = os.path.splitext(filename)[1].lower().replace('.', '')
            return {
                "id": filename,
                "uid": os.path.relpath(dest_path, self.books_dir),
                "category": category.upper(),
                "category_id": category,
                "title": self._fallback_title(filename),
                "filename": filename,
                "path": dest_path,
                "ext": ext,
                "size_mb": size_mb,
                "analyzed": False
            }
        except Exception as e:
            return {"error": f"Error importando elemento: {str(e)}"}

    def analyze_document(self, book_id_or_path: str, ai_engine, model: str = "qwen2.5-coder:7b") -> Dict[str, Any]:
        fpath = self._resolve_item(book_id_or_path)
        if not fpath:
            return {"error": f"Elemento no encontrado para análisis: {book_id_or_path}"}

        filename = os.path.basename(fpath)
        category = self.detect_category(fpath)
        doc_text = self.extract_document_text(fpath, max_chars=12000)

        prompt = (
            f"Analiza a fondo el elemento de conocimiento de la Biblioteca del repositorio titulado '{filename}'.\n"
            f"Categoría asignada: {category.upper()} (Opciones: BOOKS, DOCUMENTATION, PAPERS, CODE, NOTEBOOKS, DATASETS, PROJECTS).\n\n"
            f"CONTENIDO / CÓDIGO EXTRAÍDO DEL ELEMENTO:\n"
            f"```\n{doc_text[:10000]}\n```\n\n"
            "DEVUELVE ÚNICAMENTE UN OBJETO JSON VÁLIDO con la siguiente estructura completa (sin texto explicativo fuera del JSON):\n"
            "{\n"
            f'  "id": "{category[:3]}_{uuid.uuid4().hex[:8]}",\n'
            f'  "category": "{category.upper()}",\n'
            f'  "type": "{category[:-1] if category.endswith("s") else category}",\n'
            f'  "title": "Nombre o Título descriptivo claro del elemento",\n'
            f'  "filename": "{filename}",\n'
            '  "topics": ["tema 1", "tema 2", "tema 3"],\n'
            '  "concepts": ["concepto 1", "concepto 2", "concepto 3"],\n'
            '  "libraries": ["librería 1", "librería 2"],\n'
            '  "dataset": "Nombre del Dataset asociado si aplica o N/A",\n'
            '  "level": "beginner|intermediate|advanced",\n'
            '  "languages": ["python", "bash"],\n'
            '  "dependencies": ["prerrequisito o dependencia 1", "dependencia 2"],\n'
            '  "summary": "Resumen claro, técnico y estructurado del conocimiento contenido en 2 párrafos.",\n'
            '  "key_takeaways": ["Insight o aprendizaje clave 1", "Insight clave 2", "Insight 3"],\n'
            '  "code_examples": ["# Ejemplo práctico de código o uso derivado\\nprint(\'Práctica\')"]\n'
            "}\n"
        )

        sys_prompt = "Eres un Arquitecto de Conocimiento e Ingeniero de Software Senior. Devuelve EXCLUSIVAMENTE un objeto JSON válido estructurado sin bloques ni texto adicional fuera del JSON."

        try:
            response_text = ""
            for chunk in ai_engine.generate_response(prompt, model=model, system_prompt=sys_prompt):
                response_text += chunk

            clean_json_str = response_text.strip()
            if "```" in clean_json_str:
                start = clean_json_str.find('{')
                end = clean_json_str.rfind('}')
                if start != -1 and end != -1:
                    clean_json_str = clean_json_str[start:end+1]

            metadata = json.loads(clean_json_str)
            metadata["category"] = category.upper()
            metadata["filename"] = filename
            metadata["file_path"] = fpath
            metadata["created_at"] = datetime.now().isoformat()

            # Persistir metadatos JSON con la clave por ruta relativa
            metadata.setdefault("title", self._fallback_title(filename))
            metadata["analysis_failed"] = False
            self.save_metadata(fpath, metadata)
            return metadata

        except Exception as e:
            # El análisis falló (el modelo no devolvió JSON válido, Ollama caído...).
            # Antes se guardaba una ficha inventada con temas genéricos y el error
            # escondido dentro del resumen, de modo que un fallo quedaba marcado como
            # "analizado" y el usuario nunca sabía que los datos eran falsos.
            fallback_meta = {
                "id": f"{category[:3]}_{uuid.uuid4().hex[:8]}",
                "category": category.upper(),
                "type": category[:-1] if category.endswith("s") else category,
                "title": self._fallback_title(filename),
                "filename": filename,
                "analysis_failed": True,
                "analysis_error": str(e),
                "topics": [],
                "concepts": [],
                "libraries": [],
                "dataset": "N/A",
                "level": "unknown",
                "languages": [],
                "dependencies": [],
                "summary": f"No se pudo analizar '{filename}'. Motivo: {e}",
                "key_takeaways": [],
                "code_examples": [],
                "file_path": fpath,
                "created_at": datetime.now().isoformat()
            }
            self.save_metadata(fpath, fallback_meta)
            return fallback_meta

    def delete_item(self, book_id_or_path: str) -> Dict[str, Any]:
        """ Elimina un elemento de la biblioteca junto con su ficha de IA """
        fpath = self._resolve_item(book_id_or_path)
        if not fpath:
            return {"error": f"Elemento no encontrado: {book_id_or_path}"}

        # No permitir borrar la raíz ni las carpetas de categoría
        if os.path.abspath(fpath) == self.books_dir:
            return {"error": "No se puede eliminar la raíz de la biblioteca."}
        rel = os.path.relpath(fpath, self.books_dir)
        if rel in CATEGORIES:
            return {"error": f"'{rel}' es una carpeta de categoría y no puede eliminarse."}

        key = self._metadata_key(fpath)

        try:
            if os.path.isdir(fpath):
                shutil.rmtree(fpath)
            else:
                os.remove(fpath)
        except Exception as e:
            return {"error": f"No se pudo eliminar: {e}"}

        # Retirar también la ficha de IA (nueva y antigua) para no dejar huérfanos
        for name in filter(None, [f"{key}.json" if key else None, f"{os.path.basename(fpath)}.json"]):
            meta_file = os.path.join(self.metadata_dir, name)
            if os.path.exists(meta_file):
                try:
                    os.remove(meta_file)
                except Exception:
                    pass

        return {"success": True, "path": fpath, "relative_path": rel}

    def save_snippet(self, book_id: str, page: int, box: dict, text: str, label: str) -> Dict[str, Any]:
        snippets = self.load_snippets()
        snippet_id = f"snp_{uuid.uuid4().hex[:8]}"
        snippet_data = {
            "id": snippet_id,
            "book_id": book_id,
            "page": page,
            "box": box,
            "text": text,
            "label": label or f"Cita pág. {page}",
            "cite_tag": f"::cite[{snippet_id}]"
        }
        snippets[snippet_id] = snippet_data
        
        try:
            with open(self.snippets_file, 'w', encoding='utf-8') as f:
                json.dump(snippets, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error guardando recortes: {e}")
            
        return snippet_data

    def load_snippets(self) -> Dict[str, Any]:
        if os.path.exists(self.snippets_file):
            try:
                with open(self.snippets_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def get_snippet(self, snippet_id: str) -> Dict[str, Any]:
        snippets = self.load_snippets()
        return snippets.get(snippet_id, {"error": "Cita no encontrada"})

    # =========================================================================
    # LECTOR / EDITOR DE TEXTO PDF Y CITAS (nombre_libro.json)
    # =========================================================================

    def _book_stem(self, fpath: str) -> str:
        fname = os.path.basename(fpath)
        return os.path.splitext(fname)[0]

    def _get_page_edit_path(self, stem: str, page: int) -> str:
        return os.path.join(self.edits_dir, f"{stem}_p{page}.txt")

    def get_pdf_pages(self, book_id: str, page: Optional[int] = 1, search_query: Optional[str] = None) -> Dict[str, Any]:
        fpath = self._resolve_item(book_id)
        if not fpath:
            return {"error": f"Documento no encontrado: {book_id}"}

        stem = self._book_stem(fpath)
        meta = self.get_metadata(fpath) or {}
        title = meta.get("title") or self._fallback_title(os.path.basename(fpath))

        ext = os.path.splitext(fpath)[1].lower()
        if ext != '.pdf':
            # Para archivos de texto o markdown, tratamos el archivo completo como página 1
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read(400_000)
                return {
                    "id": os.path.basename(fpath),
                    "uid": os.path.relpath(fpath, self.books_dir),
                    "title": title,
                    "filename": os.path.basename(fpath),
                    "is_pdf": False,
                    "total_pages": 1,
                    "current_page": 1,
                    "page_text": content,
                    "has_edit": False,
                    "stem": stem
                }
            except Exception as e:
                return {"error": f"Error leyendo documento: {str(e)}"}

        if not PYPDF_AVAILABLE:
            return {"error": "pypdf no está instalado en el entorno. No se puede leer el PDF página por página."}

        try:
            reader = pypdf.PdfReader(fpath)
            total_pages = len(reader.pages)
            if total_pages == 0:
                return {"error": "El archivo PDF no contiene páginas legibles."}

            page_idx = max(1, min(int(page or 1), total_pages))
            
            # Verificar si existe una edición manual guardada de esta página
            edit_path = self._get_page_edit_path(stem, page_idx)
            has_edit = False
            page_text = ""
            if os.path.exists(edit_path):
                try:
                    with open(edit_path, 'r', encoding='utf-8') as ef:
                        page_text = ef.read()
                    has_edit = True
                except Exception:
                    pass

            if not page_text:
                try:
                    raw_text = reader.pages[page_idx - 1].extract_text() or ""
                    # Limpiar saltos de línea excesivos
                    page_text = raw_text.replace("\r\n", "\n")
                except Exception as ex:
                    page_text = f"(No se pudo extraer texto de la página {page_idx}: {ex})"

            matches = []
            if search_query and search_query.strip():
                sq = search_query.strip().lower()
                for i in range(min(total_pages, 200)):
                    try:
                        p_txt = reader.pages[i].extract_text() or ""
                        if sq in p_txt.lower():
                            pos = p_txt.lower().find(sq)
                            start = max(0, pos - 40)
                            end = min(len(p_txt), pos + len(sq) + 40)
                            snippet = p_txt[start:end].replace('\n', ' ')
                            matches.append({"page": i + 1, "snippet": f"...{snippet}..."})
                    except Exception:
                        continue

            return {
                "id": os.path.basename(fpath),
                "uid": os.path.relpath(fpath, self.books_dir),
                "title": title,
                "filename": os.path.basename(fpath),
                "is_pdf": True,
                "total_pages": total_pages,
                "current_page": page_idx,
                "page_text": page_text,
                "has_edit": has_edit,
                "stem": stem,
                "search_matches": matches
            }

        except Exception as e:
            return {"error": f"Error abriendo PDF con pypdf: {str(e)}"}

    def save_pdf_page_edit(self, book_id: str, page: int, edited_text: str) -> Dict[str, Any]:
        fpath = self._resolve_item(book_id)
        stem = self._book_stem(fpath) if fpath else self._book_stem(book_id)
        edit_path = self._get_page_edit_path(stem, page)
        try:
            with open(edit_path, 'w', encoding='utf-8') as f:
                f.write(edited_text)
            return {"success": True, "ok": True, "book_id": book_id, "page": page, "path": edit_path}
        except Exception as e:
            return {"error": f"No se pudo guardar la edición de la página: {e}"}

    def _citation_file_path(self, stem: str) -> str:
        return os.path.join(self.citas_dir, f"{stem}.json")

    def get_book_citations(self, book_id: str) -> Dict[str, Any]:
        fpath = self._resolve_item(book_id)
        stem = self._book_stem(fpath) if fpath else self._fallback_title(book_id).replace(" ", "_")
        citas_path = self._citation_file_path(stem)

        if os.path.exists(citas_path):
            try:
                with open(citas_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data
            except Exception as e:
                print(f"Error leyendo archivo de citas {citas_path}: {e}")

        # Plantilla inicial de citas si no existía aún
        meta = self.get_metadata(fpath) if fpath else None
        title = (meta or {}).get("title") or self._fallback_title(os.path.basename(fpath) if fpath else book_id)
        fname = os.path.basename(fpath) if fpath else f"{stem}.pdf"

        initial = {
            "libro": fname,
            "titulo": title,
            "stem": stem,
            "archivo_json": f"{stem}.json",
            "total_citas": 0,
            "fecha_actualizacion": datetime.now().isoformat(),
            "citas": []
        }
        try:
            with open(citas_path, 'w', encoding='utf-8') as f:
                json.dump(initial, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return initial

    def save_book_citation(self, book_id: str, citation_data: Dict[str, Any]) -> Dict[str, Any]:
        current = self.get_book_citations(book_id)
        stem = current.get("stem") or self._book_stem(book_id)
        citas_path = self._citation_file_path(stem)

        cid = citation_data.get("id") or f"cita_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:4]}"
        
        entry = {
            "id": cid,
            "pagina": int(citation_data.get("pagina", 1)),
            "capitulo": (citation_data.get("capitulo") or "").strip(),
            "texto": (citation_data.get("texto") or "").strip(),
            "nota": (citation_data.get("nota") or "").strip(),
            "tags": citation_data.get("tags") if isinstance(citation_data.get("tags"), list) else [t.strip() for t in str(citation_data.get("tags") or "").split(",") if t.strip()],
            "fecha": datetime.now().isoformat()
        }

        # Actualizar o insertar
        existing = current.get("citas", [])
        found_idx = next((i for i, c in enumerate(existing) if c.get("id") == cid), None)
        if found_idx is not None:
            existing[found_idx] = entry
        else:
            existing.append(entry)

        # Ordenar por número de página
        existing.sort(key=lambda x: (x.get("pagina", 0), x.get("id", "")))
        current["citas"] = existing
        current["total_citas"] = len(existing)
        current["fecha_actualizacion"] = datetime.now().isoformat()

        try:
            with open(citas_path, 'w', encoding='utf-8') as f:
                json.dump(current, f, indent=2, ensure_ascii=False)
        except Exception as e:
            return {"error": f"Error guardando {stem}.json: {e}"}

        return {"success": True, "ok": True, "cita": entry, "book_citations": current, "archivo_json": f"{stem}.json"}

    def delete_book_citation(self, book_id: str, citation_id: str) -> Dict[str, Any]:
        current = self.get_book_citations(book_id)
        stem = current.get("stem") or self._book_stem(book_id)
        citas_path = self._citation_file_path(stem)

        existing = current.get("citas", [])
        initial_count = len(existing)
        existing = [c for c in existing if c.get("id") != citation_id]

        if len(existing) == initial_count:
            return {"error": f"Cita no encontrada: {citation_id}"}

        current["citas"] = existing
        current["total_citas"] = len(existing)
        current["fecha_actualizacion"] = datetime.now().isoformat()

        try:
            with open(citas_path, 'w', encoding='utf-8') as f:
                json.dump(current, f, indent=2, ensure_ascii=False)
        except Exception as e:
            return {"error": f"Error actualizando {stem}.json: {e}"}

        return {"success": True, "ok": True, "deleted_id": citation_id, "total_citas": len(existing)}

    def export_citations_to_workspace(self, book_id: str, workspace_path: str) -> Dict[str, Any]:
        current = self.get_book_citations(book_id)
        stem = current.get("stem") or self._book_stem(book_id)
        src_path = self._citation_file_path(stem)
        
        if not os.path.exists(src_path):
            return {"error": f"No hay archivo de citas para {book_id}"}

        dest_dir = os.path.abspath(workspace_path)
        os.makedirs(dest_dir, exist_ok=True)
        dest_file = os.path.join(dest_dir, f"{stem}.json")

        try:
            shutil.copy2(src_path, dest_file)
            return {
                "success": True,
                "ok": True,
                "exported_to": dest_file,
                "filename": f"{stem}.json",
                "total_citas": current.get("total_citas", 0)
            }
        except Exception as e:
            return {"error": f"Error copiando al espacio de trabajo: {e}"}

    def get_all_citations_for_ai(self, query: Optional[str] = None, max_results: int = 12) -> List[Dict[str, Any]]:
        """ Recolecta todas las citas de libros y las prepara para que el modelo razone con ellas """
        results = []
        if not os.path.isdir(self.citas_dir):
            return []

        q_terms = [t.lower() for t in (query or "").split() if len(t) > 2]

        for fname in os.listdir(self.citas_dir):
            if not fname.endswith(".json") or fname == "ediciones":
                continue
            fpath = os.path.join(self.citas_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    book_data = json.load(f)
                b_title = book_data.get("titulo") or book_data.get("libro") or fname
                b_name = book_data.get("libro") or fname
                for c in book_data.get("citas", []):
                    item = {
                        "libro": b_name,
                        "titulo": b_title,
                        "pagina": c.get("pagina", 1),
                        "capitulo": c.get("capitulo", ""),
                        "texto": c.get("texto", ""),
                        "nota": c.get("nota", ""),
                        "tags": c.get("tags", []),
                        "id": c.get("id", "")
                    }
                    if not q_terms:
                        results.append(item)
                    else:
                        match_count = sum(1 for term in q_terms if term in item["texto"].lower() or term in item["nota"].lower() or any(term in str(tg).lower() for tg in item["tags"]))
                        if match_count > 0:
                            item["_score"] = match_count
                            results.append(item)
            except Exception:
                continue

        if q_terms:
            results.sort(key=lambda x: x.get("_score", 0), reverse=True)
        return results[:max_results]

