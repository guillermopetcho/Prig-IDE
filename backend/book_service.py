import os
import json
import shutil
from typing import List, Dict, Any, Optional


# Extensiones que la biblioteca muestra. Deben ser un superconjunto de las que
# indexa knowledge_service: si aquí aparece algo que allí no, el elemento se queda
# en "no indexado" para siempre sin que nadie explique por qué.
VIEWABLE_EXTENSIONS = {
    'pdf', 'md', 'txt', 'rst', 'ipynb', 'py', 'js', 'sql',
    'json', 'html', 'css', 'cpp', 'c', 'csv', 'tsv', 'parquet',
}

# Carpetas de la raíz que son de Prig, no del usuario: las citas, los trabajos exportados, el analista de librerías y
# los paquetes de conocimiento. Se colaban en la lista como si fueran proyectos («citas», «jobs»...).
INFRAESTRUCTURA = {"metadata", ".index", "citas", "jobs", "librerias", "packs"}

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

def rutas_ocultas(books_dir: str) -> List[str]:
    """ Lo que el usuario quitó de la biblioteca (`.index/ocultos.json`, lo escribe el servidor de Rust). Quitar no
    borra el archivo: deja de verse y de indexarse hasta que se vuelve a poner. """
    try:
        with open(os.path.join(books_dir, ".index", "ocultos.json"), "r", encoding="utf-8") as f:
            datos = json.load(f)
        return [o["ruta"] for o in datos.get("ocultos", []) if isinstance(o, dict) and isinstance(o.get("ruta"), str)]
    except Exception:
        return []


def esta_oculto(ruta: str, ocultos: List[str]) -> bool:
    """ ¿Está quitado `ruta` o una carpeta que lo contiene? """
    return any(ruta == o or ruta.startswith(o.rstrip("/") + "/") for o in ocultos)


def volver_a_mostrar(books_dir: str, ruta: str) -> None:
    """ Importar de nuevo algo quitado lo vuelve a poner en la biblioteca """
    archivo = os.path.join(books_dir, ".index", "ocultos.json")
    try:
        with open(archivo, "r", encoding="utf-8") as f:
            datos = json.load(f)
        antes = datos.get("ocultos", [])
        datos["ocultos"] = [o for o in antes if not (isinstance(o, dict) and o.get("ruta") == ruta)]
        if len(datos["ocultos"]) != len(antes):
            with open(archivo, "w", encoding="utf-8") as f:
                json.dump(datos, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


class BookService:
    """ Lo que el backend de Python aún usa de la biblioteca: la lista para otras secciones, importar (con la
    indexación), las fichas de IA y las citas de los libros para el chat. Leer, analizar, los recortes, el lector de
    PDF y las citas son del servidor de Rust (backend-rust/crates/prig-server/src/routes/libros.rs). """

    def __init__(self, books_dir: str = None):
        if not books_dir:
            books_dir = os.environ.get("PRIG_BOOKS_DIR")
            if not books_dir:
                try:
                    default_path = os.path.expanduser("~/.prig_books")
                    os.makedirs(default_path, exist_ok=True)
                    books_dir = default_path
                except OSError:
                    books_dir = os.path.join(os.getcwd(), ".prig_books")
        self.books_dir = os.path.abspath(books_dir)
        try:
            os.makedirs(self.books_dir, exist_ok=True)
            for cat in CATEGORIES.keys():
                os.makedirs(os.path.join(self.books_dir, cat), exist_ok=True)
        except OSError:
            pass

        self.metadata_dir = os.path.join(self.books_dir, "metadata")
        self.citas_dir = os.path.join(self.books_dir, "citas")
        self.edits_dir = os.path.join(self.citas_dir, "ediciones")
        try:
            os.makedirs(self.metadata_dir, exist_ok=True)
            os.makedirs(self.citas_dir, exist_ok=True)
            os.makedirs(self.edits_dir, exist_ok=True)
        except OSError:
            pass

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

    def get_saved_projects(self) -> List[Dict[str, Any]]:
        """ Lee los proyectos guardados en la configuración de Prig """
        config_paths = [
            os.path.expanduser('~/.prig_config.json'),
            os.path.join(os.getcwd(), '.prig_config.json')
        ]
        for cp in config_paths:
            if os.path.exists(cp):
                try:
                    with open(cp, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                    return cfg.get("saved_projects") or []
                except Exception:
                    pass
        return []

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
        ocultos = rutas_ocultas(self.books_dir)

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
                if fname == "metadata" or fname.startswith(".") or fpath in seen_paths or (sdir == self.books_dir and fname in INFRAESTRUCTURA):
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
                    if esta_oculto(fpath, ocultos):
                        continue

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

        # 2. Añadir proyectos guardados de la biblioteca si se piden todos o PROJECTS
        if category_filter is None or category_filter.lower() in ("projects", "all"):
            for sp in self.get_saved_projects():
                p_path = sp.get("path") if isinstance(sp, dict) else str(sp)
                if not p_path or p_path in seen_paths or not os.path.isdir(p_path):
                    continue
                if esta_oculto(os.path.abspath(p_path), ocultos):
                    continue
                seen_paths.add(p_path)
                p_name = (sp.get("name") if isinstance(sp, dict) else None) or os.path.basename(p_path) or p_path
                meta = self.get_metadata(p_path) or {"title": p_name, "path": p_path, "is_project": True}
                items.append({
                    "id": os.path.basename(p_path),
                    "uid": p_path,
                    "category": "PROJECTS",
                    "category_id": "projects",
                    "title": p_name,
                    "filename": os.path.basename(p_path),
                    "path": p_path,
                    "ext": "project",
                    "is_project": True,
                    "size_mb": 0.0,
                    "indexable": False,
                    "analyzed": True,
                    "analysis_failed": False,
                    "metadata": meta
                })

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

        # Si no está dentro de books_dir, comprobar si coincide con un proyecto guardado
        for sp in self.get_saved_projects():
            p_path = sp.get("path") if isinstance(sp, dict) else str(sp)
            if p_path and os.path.isdir(p_path):
                if p_path == book_id or os.path.basename(p_path) == book_id:
                    return p_path
        return None

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

            volver_a_mostrar(self.books_dir, os.path.abspath(dest_path))
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

    # =========================================================================
    # LECTOR / EDITOR DE TEXTO PDF Y CITAS (nombre_libro.json)
    # =========================================================================

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

