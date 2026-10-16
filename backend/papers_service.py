"""
Servicio de Papers y Algoritmos Seminales de Machine Learning en Prig IDE.
Permite explorar, buscar localmente y desde GitHub, leer, descargar al workspace
y consultar interactivamente con modelos de IA sobre las 21 monografías algorítmicas.
"""

import os
import json
import shutil
import re
from typing import List, Dict, Any, Optional, Generator

GITHUB_REPO_DEFAULT = "guillermopetcho/Prig-IDE"
GITHUB_BRANCH_DEFAULT = "main"

# El catálogo vive en catalogos/papers_catalogo.json: lo leen este módulo y el servidor de Rust (una sola fuente)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalogos", "papers_catalogo.json"), encoding="utf-8") as _f:
    CATALOGO_21_ALGORITMOS: List[Dict[str, Any]] = json.load(_f)


class PapersService:
    """Gestiona el catálogo, búsqueda, lectura y consulta de papers seminales de ML."""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.base_dir = os.path.abspath(base_dir)
        else:
            # Buscar el directorio raíz de Prig
            current = os.path.dirname(os.path.abspath(__file__))
            self.base_dir = os.path.abspath(os.path.join(current, ".."))

        self.docs_dir = os.path.join(self.base_dir, "docs")
        self.algoritmos_dir = os.path.join(self.docs_dir, "algoritmos_ml")
        self.analisis_dir = os.path.join(self.docs_dir, "analisis_papers")
        self.compendio_path = os.path.join(self.docs_dir, "papers_machine_learning_referencias.md")
        self.catalogo = CATALOGO_21_ALGORITMOS

    def list_papers(self, q: Optional[str] = None, categoria: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lista las monografías con metadatos, estado de archivos locales y filtrado."""
        results = []
        q_clean = (q or "").strip().lower()
        cat_clean = (categoria or "").strip().lower()

        for item in self.catalogo:
            # Comprobar existencia y tamaños en disco
            ficha_path = os.path.join(self.algoritmos_dir, f"{item['id']}.md")
            analisis_path = os.path.join(self.analisis_dir, f"{item['id']}.md")

            ficha_existe = os.path.isfile(ficha_path)
            analisis_existe = os.path.isfile(analisis_path)

            ficha_bytes = os.path.getsize(ficha_path) if ficha_existe else 0
            analisis_bytes = os.path.getsize(analisis_path) if analisis_existe else 0

            entry = {
                **item,
                "ficha_existe": ficha_existe,
                "analisis_existe": analisis_existe,
                "ficha_bytes": ficha_bytes,
                "analisis_bytes": analisis_bytes,
                "github_url_ficha": f"https://github.com/{GITHUB_REPO_DEFAULT}/blob/{GITHUB_BRANCH_DEFAULT}/docs/algoritmos_ml/{item['id']}.md",
                "github_url_analisis": f"https://github.com/{GITHUB_REPO_DEFAULT}/blob/{GITHUB_BRANCH_DEFAULT}/docs/analisis_papers/{item['id']}.md",
                "github_raw_analisis": f"https://raw.githubusercontent.com/{GITHUB_REPO_DEFAULT}/{GITHUB_BRANCH_DEFAULT}/docs/analisis_papers/{item['id']}.md"
            }

            # Filtro por categoría
            if cat_clean and cat_clean != "todas":
                if cat_clean not in entry["categoria"].lower():
                    continue

            # Filtro por consulta textual
            if q_clean:
                texto_busqueda = (
                    f"{entry['titulo']} {entry['categoria']} {entry['papers_clave']} "
                    f"{' '.join(entry['autores'])} {' '.join(entry['conceptos'])} {entry['resumen']}"
                ).lower()
                
                # Búsqueda por términos
                terminos = [t for t in q_clean.split() if t]
                if not all(t in texto_busqueda for t in terminos):
                    # Si no coincide en metadatos, buscar en contenido si existe
                    coincide_en_archivo = False
                    if analisis_existe:
                        try:
                            with open(analisis_path, "r", encoding="utf-8") as f:
                                contenido_doc = f.read(50000).lower()
                                if all(t in contenido_doc for t in terminos):
                                    coincide_en_archivo = True
                        except Exception:
                            pass
                    if not coincide_en_archivo:
                        continue

            results.append(entry)

        return results

    def get_paper(self, paper_id: str, tipo: str = "analisis") -> Dict[str, Any]:
        """Obtiene el contenido completo en Markdown y metadatos de un paper/algoritmo."""
        # Sanitizar identificador
        clean_id = os.path.basename(paper_id).replace(".md", "")
        
        # Buscar en catálogo
        meta = next((item for item in self.catalogo if item["id"] == clean_id), None)
        if not meta:
            # Fallback por número o búsqueda aproximada
            if clean_id.isdigit():
                num = int(clean_id)
                meta = next((item for item in self.catalogo if item["num"] == num), None)

        target_dir = self.analisis_dir if tipo == "analisis" else self.algoritmos_dir
        filename = f"{clean_id}.md" if not clean_id.endswith(".md") else clean_id
        file_path = os.path.join(target_dir, filename)

        if not os.path.isfile(file_path):
            return {"error": f"No se encontró el documento para '{paper_id}' (tipo: {tipo})"}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                contenido = f.read()

            rel_path = os.path.relpath(file_path, self.base_dir)
            github_url = f"https://github.com/{GITHUB_REPO_DEFAULT}/blob/{GITHUB_BRANCH_DEFAULT}/{rel_path}"

            return {
                "success": True,
                "id": clean_id,
                "tipo": tipo,
                "titulo": (meta["titulo"] if meta else clean_id),
                "categoria": (meta["categoria"] if meta else "Algoritmo ML"),
                "meta": meta,
                "contenido": contenido,
                "tamano_bytes": len(contenido.encode("utf-8")),
                "lineas": len(contenido.splitlines()),
                "archivo_relativo": rel_path,
                "github_url": github_url,
                "github_repo": GITHUB_REPO_DEFAULT
            }
        except Exception as e:
            return {"error": f"Error leyendo archivo de paper: {str(e)}"}

    def download_paper(self, paper_id: str, workspace_path: str, tipo: str = "analisis") -> Dict[str, Any]:
        """Descarga o copia el archivo Markdown directamente a la carpeta del proyecto del usuario."""
        paper = self.get_paper(paper_id, tipo=tipo)
        if "error" in paper:
            return paper

        dest_folder = os.path.join(workspace_path, "papers_ml")
        os.makedirs(dest_folder, exist_ok=True)

        target_filename = f"{paper['id']}_{tipo}.md"
        dest_path = os.path.join(dest_folder, target_filename)

        try:
            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(paper["contenido"])

            rel_dest = os.path.relpath(dest_path, workspace_path)
            return {
                "success": True,
                "ok": True,
                "saved_to": dest_path,
                "rel_path": rel_dest,
                "filename": target_filename,
                "bytes": len(paper["contenido"].encode("utf-8")),
                "mensaje": f"Monografía guardada exitosamente en {rel_dest}"
            }
        except Exception as e:
            return {"error": f"Error al guardar monografía en el proyecto: {str(e)}"}

    def ask_paper_stream(
        self,
        paper_id: str,
        pregunta: str,
        ai_engine,
        modelo: str = "qwen2.5-coder:7b",
        tipo: str = "analisis",
        historial: Optional[List[Dict[str, str]]] = None
    ) -> Generator[str, None, None]:
        """Inyecta el contenido del paper y responde preguntas con el modelo de IA seleccionado."""
        doc = self.get_paper(paper_id, tipo=tipo)
        contenido = doc.get("contenido", "")
        titulo = doc.get("titulo", paper_id)

        # Contexto estructurado enfocado (primeras 20,000 letras para no desbordar el contexto)
        contexto_paper = contenido[:22000] if len(contenido) > 22000 else contenido

        sys_prompt = (
            "Eres un Catedrático y Tutor Senior de Inteligencia Artificial y Machine Learning en Prig IDE. "
            f"Estás analizando la monografía del paper seminal '{titulo}'. "
            "Responde a las preguntas del desarrollador o estudiante con máximo rigor matemático, claridad didáctica, "
            "fórmulas en LaTeX (usando $ o $$) y ejemplos de código en Python/NumPy cuando sea oportuno. "
            "Basa tus explicaciones y deducciones estrictamente en el contenido y derivaciones de la monografía proporcionada."
        )

        historial_str = ""
        if historial:
            mensajes_recientes = historial[-6:]
            for m in mensajes_recientes:
                rol = "Alumno" if m.get("rol") in ("user", "usuario") else "Profesor"
                historial_str += f"\n{rol}: {m.get('texto', '')}"

        user_prompt = (
            f"=== DOCUMENTO SEMINAL: {titulo} ===\n\n"
            f"{contexto_paper}\n\n"
            f"=== FIN DEL DOCUMENTO ===\n"
            f"{historial_str}\n\n"
            f"Pregunta del Alumno: {pregunta}\n\n"
            "Profesor:"
        )

        try:
            for chunk in ai_engine.generate_response(user_prompt, model=modelo, system_prompt=sys_prompt, uso="tutor_papers"):
                yield chunk
        except Exception as e:
            yield f"\n[Error consultando al modelo {modelo}: {str(e)}]"

