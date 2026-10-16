"""
Notebooks de Kaggle explicados, en PDF: el código original celda a celda con la
explicación del profesor debajo, para leerlo sin Prig o imprimirlo.

El documento se describe como una lista de bloques (portada, sección, celda, código,
Markdown, caja del profesor...) y lo compone Typst en Rust (prig_nativo.documentos,
backend-rust/crates/prig-documentos), con DejaVu Sans del sistema si está y las
fuentes que trae Typst. Antes era ReportLab con Pygments.

  · El código se resalta (lo hace Typst) y va en una caja que se parte entre páginas.
  · El Markdown (celdas de texto y explicaciones) es CommonMark con tablas; el HTML que
    traen muchos notebooks se reduce a su texto. Nada del texto se interpreta como Typst.
  · Los emojis se quitan: ninguna fuente disponible los tiene y saldrían como cuadrados.
  · De cada celda se usa la explicación guardada más reciente que corresponda al código
    actual (si el autor cambió la celda, la explicación vieja no se imprime).

Un PDF puede llevar un notebook o todos los de una colección. Lo usan también la
exportación de repositorios de GitHub (github_lector) y la de carpetas (pdf_exporter).
"""

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import kaggle_lector as kl

CARPETA_PDF = "kaggle_pdf"

Bloque = Dict[str, Any]


def _rs():
    from nativo_rust import rust
    return rust().documentos


def md(texto: str) -> str:
    """ Texto que va dentro de Markdown (líneas de portada, notas) sin que se interprete """
    return _rs().escapar_md(texto or "")


def enlace(url: str) -> str:
    return f"[{md(url)}](<{(url or '').replace('<', '%3C').replace('>', '%3E')}>)"


# ===========================================================================
# Bloques
# ===========================================================================

def _registrar_fuentes():
    """ Ya no hace nada: las fuentes las carga Typst (se conserva para quien la llamaba) """


def _estilos() -> Dict[str, Any]:
    """ Ya no hay estilos que preparar: van en el preámbulo de Typst (se conserva para quien la llamaba) """
    return {}


def markdown(texto: str, est=None, profesor: bool = False) -> List[Bloque]:
    return [{"tipo": "markdown", "texto": texto or "", "profesor": profesor}]


def _caja_codigo(codigo: str, est=None, lenguaje: Optional[str] = "python", salida: bool = False,
                 max_lineas: Optional[int] = None) -> List[Bloque]:
    return [{"tipo": "codigo", "texto": codigo or "", "lenguaje": lenguaje, "salida": salida,
             "max_lineas": max_lineas}]


def _caja_profesor(texto: str, est, etiqueta: str) -> Bloque:
    return {"tipo": "profesor", "etiqueta": etiqueta, "texto": texto or ""}


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

def _portada(titulo: str, est, subtitulo: str, lineas: List[str]) -> List[Bloque]:
    """ `lineas`: Markdown (con lo que viene de fuera pasado por md()) """
    return [{"tipo": "portada", "etiqueta": subtitulo, "titulo": titulo, "lineas": lineas,
             "fecha": f"Generado con Prig el {datetime.now().strftime('%d/%m/%Y')}"}]


def _historia_notebook(nb: Dict[str, Any], est, opciones: Dict[str, Any], con_portada: bool = True) -> Tuple[List[Bloque], int]:
    por_celda, guia = elegir_explicaciones(nb, opciones.get("nivel"))
    solo = bool(opciones.get("solo_explicadas"))
    fl: List[Bloque] = []
    modelos = sorted({e["modelo"].replace("gemini:", "Gemini ") for e in por_celda.values()})
    fuentes = ", ".join(nb.get("competiciones", []) + nb.get("datasets", []))
    if con_portada:
        lineas = [f"de **{md(nb.get('autor') or '')}** · {len(nb['celdas'])} celdas · {len(por_celda)} explicadas por el profesor",
                  enlace(nb["url"])]
        if fuentes:
            lineas.append("Datos: " + md(fuentes))
        if modelos:
            lineas.append("Profesor: " + md(", ".join(modelos)))
        fl += _portada(nb["titulo"], est, "NOTEBOOK DE KAGGLE EXPLICADO", lineas)
        fl.append({"tipo": "espacio", "alto": 28})
        fl.append({"tipo": "nota", "texto": md((nb.get("licencia") or "") + " Autoría del notebook original: "
                                               + (nb.get("autor") or "") + ". Las explicaciones las generó un modelo de IA: pueden contener errores.")})
        fl.append({"tipo": "salto"})
    else:
        fl.append({"tipo": "seccion", "texto": nb["titulo"]})
        fl.append({"tipo": "nota", "texto": f"de {md(nb.get('autor') or '')} · {len(por_celda)} de {len(nb['celdas'])} celdas explicadas · "
                                            + enlace(nb["url"])})
    if guia and opciones.get("guia", True):
        fl.append({"tipo": "seccion", "texto": "Guía de lectura"})
        fl.append(_caja_profesor(guia["texto"], est, "PROFESOR · ANTES DE EMPEZAR"))
        fl.append({"tipo": "espacio", "alto": 10})
    fl.append({"tipo": "seccion", "texto": "El notebook, celda a celda"})
    for c in nb["celdas"]:
        exp = por_celda.get(c["indice"])
        if solo and not exp:
            continue
        if not c["fuente"].strip():
            continue
        # La cabecera nunca se queda sola al pie de la página (Typst la pega a lo que sigue)
        fl.append({"tipo": "celda", "texto": f"CELDA {c['indice']} · {'TEXTO' if c['tipo'] == 'markdown' else 'CÓDIGO'}"})
        if c["tipo"] == "markdown":
            fl += markdown(c["fuente"], est)
        else:
            fl += _caja_codigo(c["fuente"], est)
            if c.get("salida") and opciones.get("salidas", True):
                fl.append({"tipo": "nota", "texto": "Salida guardada"})
                fl += _caja_codigo(c["salida"], est, lenguaje=None, salida=True, max_lineas=30)
        if exp:
            nivel = exp.get("nivel") or ""
            fl.append(_caja_profesor(exp["texto"], est, f"PROFESOR{' · NIVEL ' + nivel.upper() if nivel else ''}"))
        fl.append({"tipo": "espacio", "alto": 6})
    chat = [m for m in (opciones.get("chat") or []) if (m.get("texto") or "").strip()]
    if chat:
        fl.append({"tipo": "salto"})
        fl.append({"tipo": "seccion", "texto": "Preguntas al profesor"})
        for m in chat[:80]:
            if m.get("rol") == "usuario":
                fl.append({"tipo": "alumno", "texto": "Tú: " + m["texto"][:3000]})
            else:
                fl.append(_caja_profesor(m["texto"][:8000], est, "PROFESOR"))
    return fl, len(por_celda)


def _construir(ruta: str, historia: List[Bloque], titulo: str, asunto: str = "Notebook de Kaggle explicado") -> int:
    """ Compone el PDF (Typst, en Rust), lo escribe de golpe y devuelve sus páginas """
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    documento = {"titulo": titulo, "asunto": asunto, "estilo": "notebook", "pie": True, "bloques": historia}
    datos, paginas = _rs().pdf(json.dumps(documento, ensure_ascii=False))
    with open(ruta + ".tmp", "wb") as f:
        f.write(datos)
    os.replace(ruta + ".tmp", ruta)
    return paginas


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
                        [md(coleccion.get("descripcion") or ""), f"{len(cargados)} notebooks"])
    historia.append({"tipo": "salto"})
    historia.append({"tipo": "seccion", "texto": "Contenido"})
    historia.append({"tipo": "markdown", "texto": "\n".join(
        f"{n}\\. **{md(nb['titulo'])}** — {md(nb.get('autor') or '')}  " for n, nb in enumerate(cargados, 1))})
    if fallidos:
        historia.append({"tipo": "nota", "texto": "No incluidos: " + md("; ".join(fallidos))})
    total_explicadas = 0
    for nb in cargados:
        historia.append({"tipo": "salto"})
        fl, explicadas = _historia_notebook(nb, est, {**opciones, "chat": None}, con_portada=False)
        historia += fl
        total_explicadas += explicadas
    ruta = os.path.join(workspace, CARPETA_PDF, "coleccion-" + _nombre_archivo(coleccion["nombre"]) + ".pdf")
    paginas = _construir(ruta, historia, coleccion["nombre"])
    return {"ruta": ruta, "relativa": os.path.relpath(ruta, workspace), "paginas": paginas,
            "notebooks": len(cargados), "explicadas": total_explicadas, "no_incluidos": fallidos,
            "bytes": os.path.getsize(ruta)}
