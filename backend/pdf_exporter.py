import os
import json
import io
import re
from html import escape as html_escape
from typing import List, Dict, Any, Optional
import pygments
from pygments.lexers import get_lexer_by_name, guess_lexer, PythonLexer, TextLexer
from pygments.formatters import HtmlFormatter

# ReportLab imports for direct PDF generation
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

class PDFExporter:
    CODE_EXTENSIONS = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'jsx',
        '.tsx': 'tsx',
        '.html': 'html',
        '.css': 'css',
        '.json': 'json',
        '.md': 'markdown',
        '.sh': 'bash',
        '.bash': 'bash',
        '.c': 'c',
        '.cpp': 'cpp',
        '.h': 'c',
        '.hpp': 'cpp',
        '.java': 'java',
        '.sql': 'sql',
        '.yml': 'yaml',
        '.yaml': 'yaml',
        '.r': 'r',
        '.php': 'php',
        '.rb': 'ruby'
    }

    IGNORED_DIRS = {
        '__pycache__', 'node_modules', 'venv', '.venv', 'env', '.env',
        '.git', '.github', '.ipynb_checkpoints', 'dist', 'build',
        '.cache', 'site-packages', '.idea', '.vscode', '.gemini', '.antigravity'
    }

    def list_folder_code_files(self, folder_path: str) -> Dict[str, Any]:
        """ Escanea la carpeta y retorna archivos .ipynb y de código con sus metadatos """
        abs_folder = os.path.abspath(folder_path)
        if not os.path.exists(abs_folder) or not os.path.isdir(abs_folder):
            return {"error": f"La carpeta no existe: {folder_path}", "files": []}

        result_files = []

        for root, dirs, files in os.walk(abs_folder):
            # Excluir directorios ignorados
            dirs[:] = [d for d in dirs if d not in self.IGNORED_DIRS and not d.startswith('.')]

            for f in sorted(files):
                if f.startswith('.'):
                    continue
                ext = os.path.splitext(f)[1].lower()
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, abs_folder)

                is_notebook = (ext == '.ipynb')
                is_code = (ext in self.CODE_EXTENSIONS)

                if is_notebook or is_code:
                    size = os.path.getsize(full_path)
                    item_info = {
                        "name": f,
                        "path": full_path,
                        "rel_path": rel_path,
                        "extension": ext,
                        "is_notebook": is_notebook,
                        "size": size,
                        "lines_count": 0,
                        "cells_count": 0
                    }

                    if is_notebook:
                        try:
                            with open(full_path, 'r', encoding='utf-8', errors='ignore') as nf:
                                data = json.load(nf)
                                item_info["cells_count"] = len(data.get("cells", []))
                        except Exception:
                            item_info["cells_count"] = 0
                    else:
                        try:
                            with open(full_path, 'r', encoding='utf-8', errors='ignore') as cf:
                                item_info["lines_count"] = sum(1 for _ in cf)
                        except Exception:
                            item_info["lines_count"] = 0

                    result_files.append(item_info)

        return {
            "folder_name": os.path.basename(abs_folder) or abs_folder,
            "folder_path": abs_folder,
            "total_files": len(result_files),
            "files": result_files
        }

    def _get_lexer_for_filename(self, filename: str, content: str):
        ext = os.path.splitext(filename)[1].lower()
        lang_alias = self.CODE_EXTENSIONS.get(ext)
        if lang_alias:
            try:
                return get_lexer_by_name(lang_alias)
            except Exception:
                pass
        try:
            return guess_lexer(content)
        except Exception:
            return TextLexer()

    def _format_markdown_simple(self, text: str) -> str:
        """ Convierte markdown simple a HTML estilizado """
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        text = re.sub(r'^# (.*$)', r'<h1 class="pdf-h1">\1</h1>', text, flags=re.M)
        text = re.sub(r'^## (.*$)', r'<h2 class="pdf-h2">\1</h2>', text, flags=re.M)
        text = re.sub(r'^### (.*$)', r'<h3 class="pdf-h3">\1</h3>', text, flags=re.M)
        text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
        text = re.sub(r'`([^`]+)`', r'<code class="pdf-inline-code">\1</code>', text)
        text = text.replace('\n', '<br>')
        return text

    def generate_styled_html(
        self,
        folder_path: str,
        file_paths: List[str],
        theme: str = "light",
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        """ Genera un documento HTML completo estilizado para los archivos seleccionados """
        if options is None:
            options = {}

        include_outputs = options.get("include_outputs", True)
        show_line_numbers = options.get("show_line_numbers", True)
        include_cover = options.get("include_cover", True)
        font_size = options.get("font_size", "13px")
        page_size = options.get("page_size", "a4")

        abs_folder = os.path.abspath(folder_path)
        folder_name = os.path.basename(abs_folder) or abs_folder
        safe_folder_name = html_escape(folder_name)
        safe_abs_folder = html_escape(abs_folder)

        pygments_style = "default" if theme == "light" else ("dracula" if theme == "dark" else "friendly")

        pyg_formatter = HtmlFormatter(style=pygments_style, noclasses=True, linenos=False)

        sections_html = []

        for fpath in file_paths:
            if not os.path.isfile(fpath):
                continue

            fname = os.path.basename(fpath)
            rel_path = os.path.relpath(fpath, abs_folder)
            ext = os.path.splitext(fname)[1].lower()

            if ext == '.ipynb':
                # Procesar Notebook
                sec_html = self._render_notebook_html(fpath, rel_path, pyg_formatter, include_outputs, show_line_numbers)
                sections_html.append(sec_html)
            else:
                # Procesar código
                sec_html = self._render_code_file_html(fpath, rel_path, pyg_formatter, show_line_numbers)
                sections_html.append(sec_html)

        cover_html = ""
        if include_cover:
            cover_html = f"""
            <div class="pdf-cover-page">
                <div class="pdf-cover-badge"><i class="fa-solid fa-file-pdf"></i> DOCUMENTO EXPORTADO</div>
                <h1 class="pdf-cover-title">{safe_folder_name}</h1>
                <p class="pdf-cover-subtitle">Cuadernos Jupyter y Código Fuente Estilizado</p>
                <div class="pdf-cover-meta">
                    <div class="meta-item"><strong>Ruta:</strong> <code>{safe_abs_folder}</code></div>
                    <div class="meta-item"><strong>Archivos exportados:</strong> {len(file_paths)}</div>
                    <div class="meta-item"><strong>Generado con:</strong> Prig IDE - Editor & Tutor IA</div>
                </div>
            </div>
            <div class="pdf-page-break"></div>
            """

        css_theme = self._get_theme_css(theme, font_size, page_size)

        full_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Exportación PDF - {safe_folder_name}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Inter:wght@300;400;500;600;700&display=swap">
    <style>
        {css_theme}
    </style>
</head>
<body class="theme-{theme}">
    <div class="pdf-container">
        {cover_html}
        {'<div class="pdf-page-break"></div>'.join(sections_html)}
    </div>
</body>
</html>"""
        return full_html

    def _render_notebook_html(
        self,
        fpath: str,
        rel_path: str,
        pyg_formatter: HtmlFormatter,
        include_outputs: bool,
        show_line_numbers: bool
    ) -> str:
        from file_manager import FileManager
        fm = FileManager()
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                raw_json = f.read()
            nb_data = fm.read_notebook_structured(raw_json, fpath)
            cells = nb_data.get("cells", [])
        except Exception as e:
            return f'<div class="pdf-section-card"><div class="pdf-error">Error al leer notebook {rel_path}: {e}</div></div>'

        fname = os.path.basename(fpath)
        cells_html = []

        for idx, cell in enumerate(cells, 1):
            c_type = cell.get("type", "code")
            c_src = cell.get("source", "")
            c_exec = cell.get("execution_count", None)
            c_outputs = cell.get("outputs", [])

            if c_type == "markdown":
                md_formatted = self._format_markdown_simple(c_src)
                cell_box = f"""
                <div class="pdf-nb-cell pdf-cell-markdown">
                    <div class="pdf-cell-header">
                        <span class="pdf-tag pdf-tag-md"><i class="fa-solid fa-align-left"></i> Markdown</span>
                    </div>
                    <div class="pdf-cell-body pdf-md-body">
                        {md_formatted}
                    </div>
                </div>
                """
                cells_html.append(cell_box)
            else:
                lexer = self._get_lexer_for_filename(fname, c_src) if not fname.endswith('.ipynb') else PythonLexer()
                highlighted_code = pygments.highlight(c_src, lexer, pyg_formatter)

                code_lines = c_src.splitlines()
                lines_markup = []
                if show_line_numbers:
                    lineno_col = "\n".join([f'<span class="lineno">{i}</span>' for i in range(1, len(code_lines) + 1)])
                    lines_markup = f"""<div class="pdf-code-container">
                        <div class="pdf-lineno-col">{lineno_col}</div>
                        <div class="pdf-code-content">{highlighted_code}</div>
                    </div>"""
                else:
                    lines_markup = f'<div class="pdf-code-content">{highlighted_code}</div>'

                exec_label = f"In [{c_exec if c_exec is not None else idx}]:"

                outputs_markup = ""
                if include_outputs and c_outputs:
                    out_items = []
                    for out in c_outputs:
                        o_type = out.get("type", "")
                        if o_type == "error":
                            err_text = out.get("text", "").replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            out_items.append(f'<div class="pdf-out-line pdf-out-err"><i class="fa-solid fa-triangle-exclamation"></i> <pre>{err_text}</pre></div>')
                        elif o_type == "html":
                            out_items.append(f'<div class="pdf-out-line pdf-out-html">{out.get("text", "")}</div>')
                        elif o_type == "image":
                            clean_b64 = out.get("data", "").replace("\n", "").replace("\r", "").strip()
                            mime = out.get("mime", "image/png")
                            out_items.append(f'<div class="pdf-out-line pdf-out-img"><img src="data:{mime};base64,{clean_b64}" alt="Notebook Plot" /></div>')
                        else:
                            txt = out.get("text", "").replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            out_items.append(f'<div class="pdf-out-line pdf-out-stdout"><pre>{txt}</pre></div>')

                    outputs_markup = f"""
                    <div class="pdf-nb-outputs">
                        <div class="pdf-nb-out-tag">Out [{c_exec if c_exec is not None else idx}]:</div>
                        {''.join(out_items)}
                    </div>
                    """

                cell_box = f"""
                <div class="pdf-nb-cell pdf-cell-code">
                    <div class="pdf-cell-header">
                        <span class="pdf-tag pdf-tag-code"><i class="fa-brands fa-python"></i> {exec_label}</span>
                    </div>
                    <div class="pdf-cell-body">
                        {lines_markup}
                    </div>
                    {outputs_markup}
                </div>
                """
                cells_html.append(cell_box)

        return f"""
        <div class="pdf-file-document">
            <div class="pdf-file-banner pdf-banner-notebook">
                <div class="pdf-banner-title"><i class="fa-solid fa-book-bookmark"></i> {html_escape(fname)}</div>
                <div class="pdf-banner-path"><i class="fa-solid fa-folder"></i> {html_escape(rel_path)}</div>
                <div class="pdf-banner-badge">{len(cells)} CELDAS</div>
            </div>
            <div class="pdf-file-body">
                {''.join(cells_html)}
            </div>
        </div>
        """

    def _render_code_file_html(
        self,
        fpath: str,
        rel_path: str,
        pyg_formatter: HtmlFormatter,
        show_line_numbers: bool
    ) -> str:
        fname = os.path.basename(fpath)
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                code_content = f.read()
        except Exception as e:
            return f'<div class="pdf-section-card"><div class="pdf-error">Error al leer código {rel_path}: {e}</div></div>'

        lexer = self._get_lexer_for_filename(fname, code_content)
        highlighted_code = pygments.highlight(code_content, lexer, pyg_formatter)
        lines = code_content.splitlines()

        if show_line_numbers:
            lineno_col = "\n".join([f'<span class="lineno">{i}</span>' for i in range(1, len(lines) + 1)])
            code_markup = f"""<div class="pdf-code-container">
                <div class="pdf-lineno-col">{lineno_col}</div>
                <div class="pdf-code-content">{highlighted_code}</div>
            </div>"""
        else:
            code_markup = f'<div class="pdf-code-content">{highlighted_code}</div>'

        ext_badge = os.path.splitext(fname)[1].upper().replace('.', '') or 'FILE'

        return f"""
        <div class="pdf-file-document">
            <div class="pdf-file-banner pdf-banner-code">
                <div class="pdf-banner-title"><i class="fa-solid fa-code"></i> {fname}</div>
                <div class="pdf-banner-path"><i class="fa-solid fa-folder"></i> {rel_path}</div>
                <div class="pdf-banner-badge">{len(lines)} LÍNEAS | {ext_badge}</div>
            </div>
            <div class="pdf-file-body">
                <div class="pdf-code-block">
                    {code_markup}
                </div>
            </div>
        </div>
        """

    def _get_theme_css(self, theme: str, font_size: str, page_size: str) -> str:
        base_size = font_size or "13px"
        is_dark = (theme == "dark")
        is_exec = (theme == "executive")

        if is_dark:
            bg_main = "#141417"
            bg_card = "#1e1e24"
            bg_code = "#18181c"
            text_main = "#e0e0e6"
            text_muted = "#8a8a99"
            border_col = "#2d2d38"
            accent_blue = "#61afef"
            accent_purple = "#c678dd"
            accent_tag = "#98c379"
            banner_bg = "linear-gradient(135deg, #1f2335 0%, #282c34 100%)"
        elif is_exec:
            bg_main = "#f9f8f6"
            bg_card = "#ffffff"
            bg_code = "#f4f3ef"
            text_main = "#2c2c2c"
            text_muted = "#666666"
            border_col = "#d8d6d0"
            accent_blue = "#2b5797"
            accent_purple = "#68217a"
            accent_tag = "#008a00"
            banner_bg = "linear-gradient(135deg, #2b5797 0%, #1e395b 100%)"
        else:
            # Light printable
            bg_main = "#ffffff"
            bg_card = "#ffffff"
            bg_code = "#f8f9fa"
            text_main = "#1a1a1a"
            text_muted = "#555555"
            border_col = "#e1e4e8"
            accent_blue = "#0969da"
            accent_purple = "#8250df"
            accent_tag = "#1a7f37"
            banner_bg = "linear-gradient(135deg, #0969da 0%, #0349b4 100%)"

        return f"""
        @page {{
            size: {page_size};
            margin: 15mm;
        }}
        @media print {{
            body {{
                background: #ffffff !important;
                color: #000000 !important;
            }}
            .pdf-container {{
                padding: 0 !important;
                margin: 0 !important;
            }}
            .pdf-page-break {{
                page-break-after: always;
                break-after: page;
            }}
            .pdf-nb-cell, .pdf-file-document {{
                break-inside: avoid;
            }}
        }}

        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background-color: {bg_main};
            color: {text_main};
            font-family: {'Georgia, serif' if is_exec else "'Inter', system-ui, -apple-system, sans-serif"};
            font-size: {base_size};
            line-height: 1.5;
            padding: 20px;
        }}

        .pdf-container {{
            max-width: 900px;
            margin: 0 auto;
        }}

        .pdf-page-break {{
            height: 20px;
            margin: 20px 0;
            border-bottom: 2px dashed {border_col};
        }}

        /* Portada */
        .pdf-cover-page {{
            text-align: center;
            padding: 60px 20px;
            background: {bg_card};
            border: 1px solid {border_col};
            border-radius: 12px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.05);
            margin-bottom: 30px;
        }}
        .pdf-cover-badge {{
            display: inline-block;
            background: rgba(9, 105, 218, 0.1);
            color: {accent_blue};
            font-weight: 700;
            font-size: 11px;
            padding: 4px 12px;
            border-radius: 20px;
            margin-bottom: 16px;
            letter-spacing: 1px;
        }}
        .pdf-cover-title {{
            font-size: 32px;
            font-weight: 800;
            margin-bottom: 10px;
            color: {'#ffffff' if (is_dark or is_exec) else '#0969da'};
        }}
        .pdf-cover-subtitle {{
            font-size: 16px;
            color: {text_muted};
            margin-bottom: 30px;
        }}
        .pdf-cover-meta {{
            text-align: left;
            display: inline-block;
            background: {bg_code};
            padding: 16px 24px;
            border-radius: 8px;
            border: 1px solid {border_col};
            font-size: 13px;
        }}
        .pdf-cover-meta .meta-item {{
            margin-bottom: 6px;
        }}

        /* Document File Banner */
        .pdf-file-document {{
            margin-bottom: 30px;
            border: 1px solid {border_col};
            border-radius: 10px;
            background: {bg_card};
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.03);
        }}
        .pdf-file-banner {{
            padding: 14px 18px;
            background: {banner_bg};
            color: #ffffff;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .pdf-banner-title {{
            font-size: 16px;
            font-weight: 700;
        }}
        .pdf-banner-path {{
            font-size: 12px;
            opacity: 0.85;
        }}
        .pdf-banner-badge {{
            margin-left: auto;
            background: rgba(255,255,255,0.2);
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }}

        .pdf-file-body {{
            padding: 16px;
        }}

        /* Notebook Cells */
        .pdf-nb-cell {{
            margin-bottom: 16px;
            border: 1px solid {border_col};
            border-radius: 8px;
            background: {bg_card};
            overflow: hidden;
        }}
        .pdf-cell-code {{
            border-left: 4px solid {accent_blue};
        }}
        .pdf-cell-markdown {{
            border-left: 4px solid {accent_purple};
        }}
        .pdf-cell-header {{
            background: {bg_code};
            padding: 6px 12px;
            border-bottom: 1px solid {border_col};
            display: flex;
            align-items: center;
        }}
        .pdf-tag {{
            font-size: 11px;
            font-weight: 700;
            padding: 2px 8px;
            border-radius: 4px;
            font-family: 'Fira Code', monospace;
        }}
        .pdf-tag-code {{
            background: rgba(9, 105, 218, 0.15);
            color: {accent_blue};
        }}
        .pdf-tag-md {{
            background: rgba(130, 80, 223, 0.15);
            color: {accent_purple};
        }}

        .pdf-cell-body {{
            padding: 12px;
        }}
        .pdf-md-body {{
            line-height: 1.6;
        }}
        .pdf-h1 {{ font-size: 20px; font-weight: 700; margin: 12px 0 6px 0; border-bottom: 1px solid {border_col}; padding-bottom: 4px; }}
        .pdf-h2 {{ font-size: 17px; font-weight: 700; margin: 10px 0 4px 0; }}
        .pdf-h3 {{ font-size: 15px; font-weight: 600; margin: 8px 0 4px 0; }}
        .pdf-inline-code {{
            background: {bg_code};
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Fira Code', monospace;
            font-size: 0.9em;
            border: 1px solid {border_col};
        }}

        /* Code & Line numbers */
        .pdf-code-container {{
            display: flex;
            font-family: 'Fira Code', 'Consolas', monospace;
            font-size: 12px;
            background: {bg_code};
            border-radius: 6px;
            overflow-x: auto;
        }}
        .pdf-lineno-col {{
            padding: 10px 10px;
            background: rgba(0,0,0,0.03);
            border-right: 1px solid {border_col};
            color: {text_muted};
            text-align: right;
            user-select: none;
            display: flex;
            flex-direction: column;
            line-height: 1.45;
        }}
        .pdf-code-content {{
            padding: 10px;
            flex: 1;
            overflow-x: auto;
            line-height: 1.45;
        }}
        .pdf-code-content pre {{
            margin: 0;
            font-family: 'Fira Code', 'Consolas', monospace;
        }}

        /* Outputs */
        .pdf-nb-outputs {{
            background: {bg_code};
            border-top: 1px dashed {border_col};
            padding: 10px 12px;
        }}
        .pdf-nb-out-tag {{
            font-size: 10px;
            font-weight: 700;
            color: {text_muted};
            margin-bottom: 6px;
            font-family: 'Fira Code', monospace;
        }}
        .pdf-out-line {{
            margin-bottom: 6px;
            font-size: 12px;
        }}
        .pdf-out-stdout pre {{
            font-family: 'Fira Code', monospace;
            white-space: pre-wrap;
            color: {text_main};
        }}
        .pdf-out-err {{
            background: rgba(244, 135, 113, 0.1);
            color: #d73a49;
            padding: 8px;
            border-radius: 6px;
            border-left: 3px solid #d73a49;
        }}
        .pdf-out-img img {{
            max-width: 100%;
            height: auto;
            border-radius: 6px;
            border: 1px solid {border_col};
            display: block;
            margin: 8px auto;
        }}
        """

    def generate_pdf_bytes(
        self,
        folder_path: str,
        file_paths: List[str],
        theme: str = "light",
        options: Optional[Dict[str, Any]] = None
    ) -> bytes:
        """ Genera un archivo binario PDF nativo utilizando ReportLab """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=0.5*inch, rightMargin=0.5*inch,
            topMargin=0.5*inch, bottomMargin=0.5*inch
        )

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'CoverTitle',
            parent=styles['Heading1'],
            fontName='Helvetica-Bold',
            fontSize=24,
            leading=28,
            textColor=colors.HexColor('#0969da'),
            alignment=1, # Center
            spaceAfter=12
        )

        subtitle_style = ParagraphStyle(
            'CoverSubtitle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=13,
            leading=16,
            textColor=colors.HexColor('#555555'),
            alignment=1,
            spaceAfter=24
        )

        banner_style = ParagraphStyle(
            'FileBanner',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=14,
            leading=18,
            textColor=colors.HexColor('#ffffff'),
            backColor=colors.HexColor('#0969da'),
            borderPadding=8,
            spaceBefore=12,
            spaceAfter=8
        )

        code_style = ParagraphStyle(
            'CodeText',
            parent=styles['Code'],
            fontName='Courier',
            fontSize=9,
            leading=11,
            textColor=colors.HexColor('#1a1a1a')
        )

        story = []

        abs_folder = os.path.abspath(folder_path)
        folder_name = os.path.basename(abs_folder) or abs_folder

        story.append(Spacer(1, 20))
        story.append(Paragraph(f"Exportación de Código: {folder_name}", title_style))
        story.append(Paragraph(f"Generado con Prig IDE | Total archivos: {len(file_paths)}", subtitle_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e1e4e8'), spaceAfter=20))

        from file_manager import FileManager
        fm = FileManager()

        for fpath in file_paths:
            if not os.path.isfile(fpath):
                continue

            fname = os.path.basename(fpath)
            rel_path = os.path.relpath(fpath, abs_folder)
            ext = os.path.splitext(fname)[1].lower()

            story.append(Paragraph(f"📄 {fname}  ({rel_path})", banner_style))

            if ext == '.ipynb':
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                        raw_json = f.read()
                    nb_data = fm.read_notebook_structured(raw_json, fpath)
                    cells = nb_data.get("cells", [])

                    for idx, cell in enumerate(cells, 1):
                        c_type = cell.get("type", "code")
                        c_src = cell.get("source", "")
                        c_exec = cell.get("execution_count", None)

                        cell_tag = f"<b>Markdown</b>" if c_type == "markdown" else f"<b>In [{c_exec or idx}]:</b>"
                        story.append(Paragraph(cell_tag, styles['Normal']))

                        src_lines = c_src.splitlines()
                        formatted_src = "\n".join(src_lines[:100]) # Prevenir overflows excesivos
                        story.append(Preformatted(formatted_src, code_style))
                        story.append(Spacer(1, 6))

                except Exception as e:
                    story.append(Paragraph(f"Error procesando notebook: {e}", styles['Normal']))
            else:
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                        code_content = f.read()
                    lines = code_content.splitlines()
                    formatted_code = "\n".join(lines[:300]) # Cap en 300 líneas para el PDF rápido
                    story.append(Preformatted(formatted_code, code_style))
                except Exception as e:
                    story.append(Paragraph(f"Error procesando archivo: {e}", styles['Normal']))

            story.append(Spacer(1, 15))

        doc.build(story)
        return buffer.getvalue()
