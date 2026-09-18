"""
Notebooks de Kaggle explicados, en PDF: el código original celda a celda con la
explicación del profesor debajo, para leerlo sin Prig o imprimirlo.

Con ReportLab (ya lo usa el exportador de carpetas) y las fuentes DejaVu del sistema,
que tienen tildes, «», flechas y griegas; si no están se usa Helvetica y se sustituye
lo que no sabe dibujar. Los emojis se quitan: ninguna de las dos los tiene y saldrían
como cuadrados.

  · El código se resalta con Pygments y va en una caja que se parte entre páginas.
  · El markdown (celdas de texto y explicaciones) se convierte con un lector pequeño:
    títulos, listas, citas, tablas, bloques de código, negrita, cursiva, código en
    línea y enlaces. El HTML que traen muchos notebooks se reduce a su texto.
  · De cada celda se usa la explicación guardada más reciente que corresponda al código
    actual (si el autor cambió la celda, la explicación vieja no se imprime).

Un PDF puede llevar un notebook o todos los de una colección.
"""

import os
import re
from datetime import datetime
from html import escape
from typing import Any, Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle, XPreformatted)

import kaggle_lector as kl

CARPETA_PDF = "kaggle_pdf"
AZUL = colors.HexColor("#0a7bb0")
MORADO = colors.HexColor("#7c3aed")
GRIS = colors.HexColor("#6b7280")
FONDO_CODIGO = colors.HexColor("#f5f6f8")
FONDO_PROFESOR = colors.HexColor("#f6f2ff")
FONDO_SALIDA = colors.HexColor("#fbfbfb")
LINEAS_POR_TROZO = 40          # una fila de tabla no puede pasar de una página: el código va en trozos

# ===========================================================================
# Fuentes
# ===========================================================================

_FUENTES = {"normal": "Helvetica", "negrita": "Helvetica-Bold", "cursiva": "Helvetica-Oblique",
            "mono": "Courier", "unicode": False}


def _registrar_fuentes():
    if _FUENTES.get("hecho"):
        return
    _FUENTES["hecho"] = True
    carpetas = [os.environ.get("PRIG_FUENTES_PDF") or "", "/usr/share/fonts/truetype/dejavu",
                "/usr/share/fonts/dejavu", "/usr/local/share/fonts", os.path.expanduser("~/.local/share/fonts")]
    nombres = {"normal": "DejaVuSans.ttf", "negrita": "DejaVuSans-Bold.ttf", "cursiva": "DejaVuSans-Oblique.ttf",
               "negrita_cursiva": "DejaVuSans-BoldOblique.ttf", "mono": "DejaVuSansMono.ttf", "mono_negrita": "DejaVuSansMono-Bold.ttf"}
    for carpeta in carpetas:
        if carpeta and all(os.path.exists(os.path.join(carpeta, n)) for n in nombres.values()):
            try:
                for clave, archivo in nombres.items():
                    pdfmetrics.registerFont(TTFont(f"Prig-{clave}", os.path.join(carpeta, archivo)))
                pdfmetrics.registerFontFamily("Prig-normal", normal="Prig-normal", bold="Prig-negrita",
                                              italic="Prig-cursiva", boldItalic="Prig-negrita_cursiva")
                pdfmetrics.registerFontFamily("Prig-mono", normal="Prig-mono", bold="Prig-mono_negrita",
                                              italic="Prig-mono", boldItalic="Prig-mono_negrita")
                _FUENTES.update(normal="Prig-normal", negrita="Prig-negrita", cursiva="Prig-cursiva",
                                mono="Prig-mono", unicode=True)
            except Exception:
                pass
            return


EMOJI = re.compile("[\U00010000-\U0010FFFF☀-➿️‍]")


def _texto_seguro(t: str) -> str:
    """ Quita lo que ninguna fuente disponible dibuja """
    t = EMOJI.sub("", t or "")
    if not _FUENTES["unicode"]:
        t = t.translate({0x2192: "->", 0x2190: "<-", 0x2264: "<=", 0x2265: ">=", 0x2260: "!=", 0x2026: "...",
                         0x201C: '"', 0x201D: '"', 0x2018: "'", 0x2019: "'", 0x2014: "-", 0x2013: "-", 0x2022: "*"})
        t = t.encode("latin-1", "replace").decode("latin-1")
    return t


# ===========================================================================
# Estilos
# ===========================================================================

def _estilos() -> Dict[str, ParagraphStyle]:
    n, b, i, m = _FUENTES["normal"], _FUENTES["negrita"], _FUENTES["cursiva"], _FUENTES["mono"]
    base = ParagraphStyle("base", fontName=n, fontSize=9.6, leading=13.6, spaceAfter=4)
    return {
        "base": base,
        "portada_tipo": ParagraphStyle("pt", parent=base, fontSize=10, textColor=AZUL, alignment=TA_CENTER, spaceAfter=10),
        "portada_titulo": ParagraphStyle("ptt", parent=base, fontName=b, fontSize=24, leading=29, alignment=TA_CENTER, spaceAfter=10),
        "portada_sub": ParagraphStyle("ps", parent=base, fontSize=11, textColor=GRIS, alignment=TA_CENTER, spaceAfter=4),
        "seccion": ParagraphStyle("sec", parent=base, fontName=b, fontSize=15, leading=19, textColor=AZUL, spaceBefore=6, spaceAfter=8),
        "celda": ParagraphStyle("cel", parent=base, fontName=b, fontSize=8, textColor=GRIS, spaceBefore=10, spaceAfter=3),
        "h1": ParagraphStyle("h1", parent=base, fontName=b, fontSize=14, leading=18, spaceBefore=6, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=base, fontName=b, fontSize=12, leading=16, spaceBefore=5, spaceAfter=3),
        "h3": ParagraphStyle("h3", parent=base, fontName=b, fontSize=10.5, leading=14, spaceBefore=4, spaceAfter=2),
        "h3_profesor": ParagraphStyle("h3p", parent=base, fontName=b, fontSize=10, leading=14, textColor=MORADO, spaceBefore=4, spaceAfter=2),
        "lista": ParagraphStyle("li", parent=base, leftIndent=14, bulletIndent=4, spaceAfter=2),
        "cita": ParagraphStyle("ci", parent=base, fontName=i, leftIndent=12, textColor=GRIS),
        "codigo": ParagraphStyle("co", fontName=m, fontSize=7.8, leading=10.2),
        "salida": ParagraphStyle("sa", fontName=m, fontSize=7.4, leading=9.6, textColor=colors.HexColor("#374151")),
        "etiqueta_profesor": ParagraphStyle("ep", parent=base, fontName=b, fontSize=8, textColor=MORADO, spaceAfter=2),
        "tabla": ParagraphStyle("ta", parent=base, fontSize=8, leading=10.5, spaceAfter=0),
        "nota": ParagraphStyle("no", parent=base, fontSize=8, textColor=GRIS),
        "chat_alumno": ParagraphStyle("ca", parent=base, fontName=b, textColor=AZUL, spaceBefore=6),
    }


# ===========================================================================
# Código resaltado
# ===========================================================================

def _colores_pygments():
    try:
        from pygments.styles import get_style_by_name
        return get_style_by_name("friendly")
    except Exception:
        return None


_ESTILO_PYG = _colores_pygments()


def _resaltar(codigo: str, lenguaje: str = "python") -> str:
    """ Marcado de ReportLab (<font color>) para XPreformatted, que respeta espacios """
    codigo = _texto_seguro(codigo.expandtabs(4))
    try:
        from pygments import lex
        from pygments.lexers import get_lexer_by_name
        lexer = get_lexer_by_name(lenguaje or "python")
    except Exception:
        return escape(codigo)
    salida = []
    for tok, valor in lex(codigo, lexer):
        texto = escape(valor)
        estilo = _ESTILO_PYG.style_for_token(tok) if _ESTILO_PYG else {}
        if estilo.get("color") and texto.strip():
            texto = f'<font color="#{estilo["color"]}">{texto}</font>'
        if estilo.get("bold") and texto.strip():
            texto = f"<b>{texto}</b>"
        salida.append(texto)
    return "".join(salida).rstrip("\n")


def _caja_codigo(codigo: str, est, fondo=FONDO_CODIGO, borde=colors.HexColor("#e5e7eb"), lenguaje="python",
                 estilo_texto="codigo", resaltar=True, max_lineas: Optional[int] = None) -> List[Any]:
    lineas = codigo.rstrip("\n").split("\n")
    recortado = False
    if max_lineas and len(lineas) > max_lineas:
        lineas, recortado = lineas[:max_lineas], True
    filas = []
    for i in range(0, max(1, len(lineas)), LINEAS_POR_TROZO):
        trozo = "\n".join(lineas[i:i + LINEAS_POR_TROZO])
        marcado = _resaltar(trozo, lenguaje) if resaltar else escape(_texto_seguro(trozo))
        filas.append([XPreformatted(marcado or " ", est[estilo_texto])])
    if recortado:
        filas.append([Paragraph("… (salida recortada)", est["nota"])])
    t = Table(filas, colWidths=["100%"], splitByRow=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fondo), ("BOX", (0, 0), (-1, -1), 0.5, borde),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, 0), 5), ("BOTTOMPADDING", (0, -1), (-1, -1), 5),
    ]))
    return [t]


# ===========================================================================
# Markdown → flowables
# ===========================================================================

def _quitar_html(t: str) -> str:
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", t)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</(p|div|h\d|li|tr|center)>", "\n", t)
    t = re.sub(r"(?i)<img[^>]*alt=[\"']([^\"']*)[\"'][^>]*>", r"[imagen: \1]", t)
    t = re.sub(r"(?i)<img[^>]*>", "[imagen]", t)
    # Solo etiquetas de verdad: «a < b & c > d» es texto, no HTML
    t = re.sub(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]{0,400})?/?>", "", t)
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)
    from html import unescape
    return unescape(t)


def _en_linea(t: str) -> str:
    """ Negrita, cursiva, código y enlaces en el marcado de ReportLab """
    t = _texto_seguro(t)
    t = re.sub(r"!\[([^\]]*)\]\([^)]*\)", lambda m: f"[imagen{': ' + m.group(1) if m.group(1) else ''}]", t)
    partes, codigos = [], []

    def guardar_codigo(m):
        codigos.append(m.group(1))
        return f"\x00{len(codigos) - 1}\x00"
    t = re.sub(r"`([^`]+)`", guardar_codigo, t)
    t = escape(t, quote=False)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", lambda m: f'<link href="{escape(m.group(2))}" color="#0a7bb0"><u>{m.group(1)}</u></link>', t)
    t = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"<b>{m.group(1) or m.group(2)}</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)|(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w])",
               lambda m: f"<i>{m.group(1) or m.group(2)}</i>", t)
    mono = _FUENTES["mono"]
    t = re.sub(r"\x00(\d+)\x00", lambda m: f'<font face="{mono}" color="#b4235a" size="8.4">{escape(_texto_seguro(codigos[int(m.group(1))]))}</font>', t)
    partes.append(t)
    return "".join(partes)


def _tabla_md(filas: List[str], est) -> Any:
    celdas = [[c.strip() for c in f.strip().strip("|").split("|")] for f in filas]
    celdas = [f for f in celdas if not all(re.fullmatch(r":?-{2,}:?", c) for c in f if c)]
    if not celdas:
        return Spacer(1, 1)
    n = max(len(f) for f in celdas)
    datos = [[Paragraph(_en_linea(c), est["tabla"]) for c in f + [""] * (n - len(f))] for f in celdas[:60]]
    t = Table(datos, repeatRows=1, splitByRow=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    return t


def markdown(texto: str, est, profesor: bool = False) -> List[Any]:
    """ Markdown sencillo a flowables de ReportLab """
    salida: List[Any] = []
    lineas = _quitar_html(texto or "").replace("\r\n", "\n").split("\n")
    parrafo: List[str] = []

    def cerrar_parrafo():
        if parrafo:
            salida.append(Paragraph(_en_linea(" ".join(l.strip() for l in parrafo)), est["base"]))
            parrafo.clear()

    i = 0
    while i < len(lineas):
        linea = lineas[i]
        s = linea.strip()
        if s.startswith("```"):
            cerrar_parrafo()
            lenguaje = s[3:].strip() or "python"
            bloque = []
            i += 1
            while i < len(lineas) and not lineas[i].strip().startswith("```"):
                bloque.append(lineas[i])
                i += 1
            salida.extend(_caja_codigo("\n".join(bloque), est, lenguaje=lenguaje if lenguaje.isalnum() else "python"))
            salida.append(Spacer(1, 4))
        elif not s:
            cerrar_parrafo()
        elif re.match(r"^#{1,6}\s", s):
            cerrar_parrafo()
            nivel = len(s) - len(s.lstrip("#"))
            estilo = "h3_profesor" if profesor else ("h1" if nivel == 1 else "h2" if nivel == 2 else "h3")
            salida.append(Paragraph(_en_linea(s.lstrip("#").strip()), est[estilo]))
        elif re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            cerrar_parrafo()
            salida.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#d1d5db"), spaceBefore=3, spaceAfter=3))
        elif s.startswith("|") and i + 1 < len(lineas) and re.match(r"^\|?\s*:?-{2,}", lineas[i + 1].strip()):
            cerrar_parrafo()
            filas = []
            while i < len(lineas) and lineas[i].strip().startswith("|"):
                filas.append(lineas[i])
                i += 1
            salida.append(_tabla_md(filas, est))
            salida.append(Spacer(1, 4))
            continue
        elif re.match(r"^([-*+]|\d+[.)])\s+", s):
            cerrar_parrafo()
            sangria = (len(linea) - len(linea.lstrip())) // 2
            marca = re.match(r"^([-*+]|\d+[.)])\s+", s).group(1)
            contenido = s[len(re.match(r"^([-*+]|\d+[.)])\s+", s).group(0)):]
            # Las líneas siguientes sin marca y con sangría son parte del mismo punto
            while i + 1 < len(lineas) and lineas[i + 1].startswith("  ") and lineas[i + 1].strip() \
                    and not re.match(r"^\s*([-*+]|\d+[.)])\s+", lineas[i + 1]):
                i += 1
                contenido += " " + lineas[i].strip()
            estilo = ParagraphStyle(f"li{sangria}", parent=est["lista"], leftIndent=14 + 12 * sangria, bulletIndent=4 + 12 * sangria)
            salida.append(Paragraph(_en_linea(contenido), estilo, bulletText="•" if not marca[0].isdigit() else marca))
        elif s.startswith(">"):
            cerrar_parrafo()
            salida.append(Paragraph(_en_linea(s.lstrip("> ")), est["cita"]))
        else:
            parrafo.append(linea)
        i += 1
    cerrar_parrafo()
    return salida


def _caja_profesor(texto: str, est, etiqueta: str) -> Table:
    filas = [[Paragraph(etiqueta, est["etiqueta_profesor"])]] + [[f] for f in markdown(texto, est, profesor=True)]
    t = Table(filas, colWidths=["100%"], splitByRow=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), FONDO_PROFESOR),
        ("LINEBEFORE", (0, 0), (0, -1), 2.2, MORADO),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
    ]))
    return t


# ===========================================================================
# Qué explicación se imprime
# ===========================================================================

def elegir_explicaciones(nb: Dict[str, Any], nivel: Optional[str] = None) -> Tuple[Dict[int, Dict[str, Any]], Optional[Dict[str, Any]]]:
    """ Por celda, la explicación guardada más reciente cuyo código coincide con el actual
    (con preferencia por el nivel pedido); y la guía de lectura más reciente """
    guardadas = kl.explicaciones(nb["ref"])
    por_celda: Dict[int, Dict[str, Any]] = {}
    guia = None
    for clave, e in guardadas.items():
        if clave.startswith("guia:"):
            if guia is None or (e.get("fecha") or "") > (guia.get("fecha") or ""):
                guia = {**e, "modelo": clave.split(":", 1)[1]}
            continue
        partes = clave.split(":")
        if len(partes) < 4:
            continue
        indice, nivel_e, huella = int(partes[0]), partes[1], partes[-1]
        modelo = ":".join(partes[2:-1])
        if not 0 <= indice < len(nb["celdas"]) or kl._clave_explicacion(nb, indice, nivel_e, modelo) != clave:
            continue                                  # el código de la celda cambió desde entonces
        candidata = {**e, "nivel": nivel_e, "modelo": modelo}
        actual = por_celda.get(indice)
        mejor = actual is None or (
            (nivel_e == nivel) > (actual["nivel"] == nivel)
            or ((nivel_e == nivel) == (actual["nivel"] == nivel) and (e.get("fecha") or "") > (actual.get("fecha") or "")))
        if mejor:
            por_celda[indice] = candidata
    return por_celda, guia


# ===========================================================================
# Documento
# ===========================================================================

def _portada(nb_o_titulo, est, subtitulo: str, lineas: List[str]) -> List[Any]:
    fl: List[Any] = [Spacer(1, 5 * cm), Paragraph(escape(subtitulo), est["portada_tipo"]),
                     Paragraph(escape(_texto_seguro(nb_o_titulo)), est["portada_titulo"])]
    for l in lineas:
        fl.append(Paragraph(l, est["portada_sub"]))
    fl.append(Spacer(1, 1.5 * cm))
    fl.append(HRFlowable(width="40%", thickness=1, color=AZUL, hAlign="CENTER"))
    fl.append(Spacer(1, 0.4 * cm))
    fl.append(Paragraph(f"Generado con Prig el {datetime.now().strftime('%d/%m/%Y')}", est["portada_sub"]))
    return fl


def _historia_notebook(nb: Dict[str, Any], est, opciones: Dict[str, Any], con_portada: bool = True) -> Tuple[List[Any], int]:
    por_celda, guia = elegir_explicaciones(nb, opciones.get("nivel"))
    solo = bool(opciones.get("solo_explicadas"))
    fl: List[Any] = []
    modelos = sorted({e["modelo"].replace("gemini:", "Gemini ") for e in por_celda.values()})
    fuentes = ", ".join(nb.get("competiciones", []) + nb.get("datasets", []))
    if con_portada:
        lineas = [f"de <b>{escape(nb.get('autor') or '')}</b> · {len(nb['celdas'])} celdas · {len(por_celda)} explicadas por el profesor",
                  f'<link href="{escape(nb["url"])}" color="#0a7bb0">{escape(nb["url"])}</link>']
        if fuentes:
            lineas.append("Datos: " + escape(fuentes))
        if modelos:
            lineas.append("Profesor: " + escape(", ".join(modelos)))
        fl += _portada(nb["titulo"], est, "NOTEBOOK DE KAGGLE EXPLICADO", lineas)
        fl.append(Spacer(1, 1 * cm))
        fl.append(Paragraph(escape(nb.get("licencia") or "") + " Autoría del notebook original: "
                            + escape(nb.get("autor") or "") + ". Las explicaciones las generó un modelo de IA: pueden contener errores.",
                            est["nota"]))
        fl.append(PageBreak())
    else:
        fl.append(Paragraph(escape(_texto_seguro(nb["titulo"])), est["seccion"]))
        fl.append(Paragraph(f"de {escape(nb.get('autor') or '')} · {len(por_celda)} de {len(nb['celdas'])} celdas explicadas · "
                            f'<link href="{escape(nb["url"])}" color="#0a7bb0">{escape(nb["url"])}</link>', est["nota"]))
    if guia and opciones.get("guia", True):
        fl.append(Paragraph("Guía de lectura", est["seccion"]))
        fl.append(_caja_profesor(guia["texto"], est, "PROFESOR · ANTES DE EMPEZAR"))
        fl.append(Spacer(1, 10))
    fl.append(Paragraph("El notebook, celda a celda", est["seccion"]))
    for c in nb["celdas"]:
        exp = por_celda.get(c["indice"])
        if solo and not exp:
            continue
        if not c["fuente"].strip():
            continue
        cabecera = Paragraph(f"CELDA {c['indice']} · {'TEXTO' if c['tipo'] == 'markdown' else 'CÓDIGO'}", est["celda"])
        if c["tipo"] == "markdown":
            cuerpo = markdown(c["fuente"], est)
        else:
            cuerpo = _caja_codigo(c["fuente"], est)
            if c.get("salida") and opciones.get("salidas", True):
                cuerpo += [Spacer(1, 2), Paragraph("Salida guardada", est["nota"])]
                cuerpo += _caja_codigo(c["salida"], est, fondo=FONDO_SALIDA, estilo_texto="salida", resaltar=False, max_lineas=30)
        # La cabecera nunca se queda sola al pie de la página
        fl.append(KeepTogether([cabecera] + cuerpo[:1]))
        fl += cuerpo[1:]
        if exp:
            fl.append(Spacer(1, 4))
            nivel = exp.get("nivel") or ""
            fl.append(_caja_profesor(exp["texto"], est, f"PROFESOR{' · NIVEL ' + nivel.upper() if nivel else ''}"))
        fl.append(Spacer(1, 6))
    chat = [m for m in (opciones.get("chat") or []) if (m.get("texto") or "").strip()]
    if chat:
        fl.append(PageBreak())
        fl.append(Paragraph("Preguntas al profesor", est["seccion"]))
        for m in chat[:80]:
            if m.get("rol") == "usuario":
                fl.append(Paragraph("Tú: " + _en_linea(m["texto"][:3000]), est["chat_alumno"]))
            else:
                fl.append(_caja_profesor(m["texto"][:8000], est, "PROFESOR"))
                fl.append(Spacer(1, 4))
    return fl, len(por_celda)


def _pie(titulo: str):
    def dibujar(canvas, doc):
        canvas.saveState()
        canvas.setFont(_FUENTES["normal"], 7.5)
        canvas.setFillColor(GRIS)
        canvas.drawString(2 * cm, 1.2 * cm, _texto_seguro(titulo)[:95])
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {doc.page}")
        canvas.setStrokeColor(colors.HexColor("#e5e7eb"))
        canvas.line(2 * cm, 1.5 * cm, A4[0] - 2 * cm, 1.5 * cm)
        canvas.restoreState()
    return dibujar


def _construir(ruta: str, historia: List[Any], titulo: str):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    doc = SimpleDocTemplate(ruta + ".tmp", pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.8 * cm, bottomMargin=2 * cm, title=_texto_seguro(titulo),
                            author="Prig", subject="Notebook de Kaggle explicado")
    pie = _pie(titulo)
    doc.build(historia, onFirstPage=lambda c, d: None, onLaterPages=pie)
    os.replace(ruta + ".tmp", ruta)
    return doc.page


def _nombre_archivo(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-.]+", "-", texto).strip("-")[:90] or "notebook"


def pdf_notebook(ref: str, workspace: str, opciones: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """ El PDF de un notebook en <proyecto>/kaggle_pdf/<slug>.pdf """
    _registrar_fuentes()
    opciones = opciones or {}
    nb = kl.abrir(ref)
    est = _estilos()
    historia, explicadas = _historia_notebook(nb, est, opciones)
    if opciones.get("solo_explicadas") and not explicadas:
        raise kl.ErrorKaggle("Este notebook todavía no tiene celdas explicadas: pide alguna explicación o exporta el notebook completo.")
    ruta = os.path.join(workspace, CARPETA_PDF, _nombre_archivo(nb["ref"].split("/")[1]) + ".pdf")
    paginas = _construir(ruta, historia, nb["titulo"])
    return {"ruta": ruta, "relativa": os.path.relpath(ruta, workspace), "paginas": paginas,
            "explicadas": explicadas, "celdas": len(nb["celdas"]), "bytes": os.path.getsize(ruta)}


def pdf_coleccion(coleccion: Dict[str, Any], workspace: str, opciones: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """ Todos los notebooks de una colección en un solo PDF, con índice """
    _registrar_fuentes()
    opciones = opciones or {}
    est = _estilos()
    notebooks = [it for it in coleccion["items"] if it["tipo"] == "notebook"]
    if not notebooks:
        raise kl.ErrorKaggle("Esta colección no tiene notebooks.")
    cargados, fallidos = [], []
    for it in notebooks:
        try:
            cargados.append(kl.abrir(it["ref"]))
        except kl.ErrorKaggle as e:
            fallidos.append(f"{it['ref']}: {e}")
    if not cargados:
        raise kl.ErrorKaggle("No se pudo descargar ninguno de sus notebooks.")
    historia = _portada(coleccion["nombre"], est, "COLECCIÓN DE NOTEBOOKS EXPLICADOS",
                        [escape(coleccion.get("descripcion") or ""), f"{len(cargados)} notebooks"])
    historia.append(PageBreak())
    historia.append(Paragraph("Contenido", est["seccion"]))
    for n, nb in enumerate(cargados, 1):
        historia.append(Paragraph(f"{n}. <b>{escape(_texto_seguro(nb['titulo']))}</b> — {escape(nb.get('autor') or '')}", est["base"]))
    if fallidos:
        historia.append(Paragraph("No incluidos: " + escape("; ".join(fallidos)), est["nota"]))
    total_explicadas = 0
    for nb in cargados:
        historia.append(PageBreak())
        fl, explicadas = _historia_notebook(nb, est, {**opciones, "chat": None}, con_portada=False)
        historia += fl
        total_explicadas += explicadas
    ruta = os.path.join(workspace, CARPETA_PDF, "coleccion-" + _nombre_archivo(coleccion["nombre"]) + ".pdf")
    paginas = _construir(ruta, historia, coleccion["nombre"])
    return {"ruta": ruta, "relativa": os.path.relpath(ruta, workspace), "paginas": paginas,
            "notebooks": len(cargados), "explicadas": total_explicadas, "no_incluidos": fallidos,
            "bytes": os.path.getsize(ruta)}
