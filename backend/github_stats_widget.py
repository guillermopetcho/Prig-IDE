"""
GitHub Stats Widget para Prig IDE.

Permite al usuario recopilar sus estadísticas de aprendizaje (rachas, desafíos resueltos,
cursos de YouTube, lecturas de Kaggle y conceptos dominados), generar una tarjeta visual
vectorial en SVG nativo con temas personalizables (Catppuccin, Mocha, Cyber, Minimal)
e inyectar el widget directamente en su repositorio de perfil de GitHub (username/username)
mediante un commit seguro vía la API de GitHub.
"""

import base64
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

import requests

import sys
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

import github_lector as gl
import inicio
import kaggle_colecciones

ARCHIVO_CONFIG = os.path.expanduser("~/.prig_github_widget.json")

TEMAS = {
    "catppuccin": {
        "nombre": "Catppuccin Macchiato",
        "fondo": "#1e1e2e",
        "borde": "#313244",
        "texto": "#cdd6f4",
        "subtexto": "#a6adc8",
        "acento1": "#fab387",  # Racha / Peach
        "acento2": "#cba6f7",  # Desafíos / Mauve
        "acento3": "#f38ba8",  # YouTube / Red
        "acento4": "#89b4fa",  # Kaggle / Blue
        "acento5": "#a6e3a1",  # Conceptos / Green
        "gradiente_inicio": "#89b4fa",
        "gradiente_fin": "#cba6f7"
    },
    "mocha": {
        "nombre": "Mocha Dark",
        "fondo": "#11111b",
        "borde": "#27293a",
        "texto": "#ffffff",
        "subtexto": "#9399b2",
        "acento1": "#f9e2af",
        "acento2": "#b4befe",
        "acento3": "#eba0ac",
        "acento4": "#74c7ec",
        "acento5": "#94e2d5",
        "gradiente_inicio": "#a6e3a1",
        "gradiente_fin": "#94e2d5"
    },
    "cyber": {
        "nombre": "Cyber Neon",
        "fondo": "#0b0f19",
        "borde": "#1e293b",
        "texto": "#f8fafc",
        "subtexto": "#94a3b8",
        "acento1": "#00f2fe",
        "acento2": "#4facfe",
        "acento3": "#f72585",
        "acento4": "#7209b7",
        "acento5": "#10b981",
        "gradiente_inicio": "#00f2fe",
        "gradiente_fin": "#7209b7"
    },
    "minimal": {
        "nombre": "Minimal Monocromo",
        "fondo": "#0d1117",
        "borde": "#30363d",
        "texto": "#e6edf3",
        "subtexto": "#7d8590",
        "acento1": "#58a6ff",
        "acento2": "#3fb950",
        "acento3": "#d29922",
        "acento4": "#bc8cff",
        "acento5": "#3fb950",
        "gradiente_inicio": "#58a6ff",
        "gradiente_fin": "#3fb950"
    }
}

CONFIG_PREDETERMINADA = {
    "tema": "catppuccin",
    "mostrar_racha": True,
    "mostrar_desafios": True,
    "mostrar_youtube": True,
    "mostrar_kaggle": True,
    "mostrar_conceptos": True,
    "mostrar_modelos": False,
    "mostrar_nivel": True,
    "ultimo_sync": None
}


def leer_config() -> Dict[str, Any]:
    try:
        if os.path.exists(ARCHIVO_CONFIG):
            with open(ARCHIVO_CONFIG, "r", encoding="utf-8") as f:
                datos = json.load(f)
                return {**CONFIG_PREDETERMINADA, **datos}
    except Exception:
        pass
    return dict(CONFIG_PREDETERMINADA)


def guardar_config(cambios: Dict[str, Any]) -> Dict[str, Any]:
    actual = leer_config()
    actual.update(cambios)
    try:
        os.makedirs(os.path.dirname(ARCHIVO_CONFIG) or ".", exist_ok=True)
        with open(ARCHIVO_CONFIG + ".tmp", "w", encoding="utf-8") as f:
            json.dump(actual, f, ensure_ascii=False, indent=2)
        os.replace(ARCHIVO_CONFIG + ".tmp", ARCHIVO_CONFIG)
    except Exception as e:
        print("Error guardando config del widget:", e)
    return actual


def _esc_xml(t: Any) -> str:
    s = str(t or "")
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def recolectar_estadisticas(progreso_mgr=None, almacen_desafios=None, extras_cliente: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """ Recopila todas las métricas del alumno desde las diversas áreas de Prig """
    perf = inicio.perfil()
    nombre_alumno = perf.get("nombre") or "Estudiante de Prig"
    nivel_alumno = perf.get("nivel") or "intermedio"
    objetivo_alumno = perf.get("objetivo") or "Machine Learning & Programación"

    # Métricas de Progreso y Desafíos
    racha_actual = 0
    racha_mejor = 0
    dias_activos = 0
    desafios_resueltos = 0
    desafios_python = 0
    desafios_cpp = 0
    conceptos_dominados = 0

    if progreso_mgr and almacen_desafios:
        try:
            r = progreso_mgr.resumen(almacen_desafios)
            rc = r.get("racha") or {}
            racha_actual = rc.get("actual", 0)
            racha_mejor = rc.get("mejor", 0)
            dias_activos = rc.get("dias_activos", 0)
            des = r.get("desafios") or {}
            desafios_resueltos = (des.get("por_estado") or {}).get("resuelto", 0)
            desafios_python = (des.get("por_lenguaje") or {}).get("python", 0)
            desafios_cpp = (des.get("por_lenguaje") or {}).get("cpp", 0)
            conceptos_dominados = len(r.get("fuertes") or [])
        except Exception:
            pass

    # Métricas de Kaggle
    kaggle_celdas = 0
    kaggle_colecciones_count = 0
    kaggle_notas_count = 0
    try:
        cols = kaggle_colecciones.listar()
        kaggle_colecciones_count = len(cols)
        rec = kaggle_colecciones.recientes(100)
        kaggle_notas_count = sum(1 for it in rec if it.get("nota"))
        if progreso_mgr and hasattr(progreso_mgr, "kaggle_lector"):
            lecturas = progreso_mgr.kaggle_lector.resumen_lecturas()
            kaggle_celdas = sum(l.get("leidas", 0) for l in lecturas)
    except Exception:
        pass

    # Métricas de YouTube Hub (recibidas del cliente o defaults)
    extras = extras_cliente or {}
    yt_cursos_completados = extras.get("yt_cursos_completados", 0)
    yt_horas = extras.get("yt_horas", 0)
    yt_fotogramas = extras.get("yt_fotogramas", 0)
    yt_notas = extras.get("yt_notas", 0)

    # Porcentaje de Dominio Calculado
    pct_desafios = min(100, desafios_resueltos * 5)
    pct_racha = min(100, racha_actual * 10)
    porcentaje_general = max(10, min(100, round((pct_desafios * 0.5) + (pct_racha * 0.3) + (conceptos_dominados * 4))))

    return {
        "nombre": nombre_alumno,
        "nivel": nivel_alumno,
        "objetivo": objetivo_alumno,
        "racha_actual": racha_actual,
        "racha_mejor": racha_mejor,
        "dias_activos": dias_activos,
        "desafios_resueltos": desafios_resueltos,
        "desafios_python": desafios_python,
        "desafios_cpp": desafios_cpp,
        "conceptos_dominados": conceptos_dominados,
        "kaggle_celdas": kaggle_celdas,
        "kaggle_colecciones": kaggle_colecciones_count,
        "kaggle_notas": kaggle_notas_count,
        "youtube_cursos": yt_cursos_completados,
        "youtube_horas": yt_horas,
        "youtube_fotogramas": yt_fotogramas,
        "youtube_notas": yt_notas,
        "porcentaje_general": porcentaje_general,
        "modelo_local": extras.get("modelo_local") or "Qwen 2.5 Coder / DeepSeek",
        "fecha": datetime.now().strftime("%Y-%m-%d")
    }


def generar_svg(stats: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> str:
    """ Genera el archivo SVG vectorial con alta fidelidad y estética de Prig IDE """
    cfg = config or leer_config()
    clave_tema = cfg.get("tema") or "catppuccin"
    t = TEMAS.get(clave_tema) or TEMAS["catppuccin"]

    nombre = _esc_xml(stats.get("nombre") or "Estudiante de Prig")
    nivel = _esc_xml((stats.get("nivel") or "intermedio").capitalize())
    pct = max(5, min(100, int(stats.get("porcentaje_general") or 25)))
    barra_ancho = round(435 * (pct / 100))

    # Tarjetas de estadísticas activadas según configuración
    tarjetas = []

    if cfg.get("mostrar_racha", True):
        racha = stats.get("racha_actual", 0)
        mejor = stats.get("racha_mejor", 0)
        tarjetas.append({
            "icono": "🔥",
            "titulo": "Racha Activa",
            "valor": f"{racha} días",
            "sub": f"Mejor: {mejor}d · {stats.get('dias_activos', 0)} activos",
            "color": t["acento1"]
        })

    if cfg.get("mostrar_desafios", True):
        res = stats.get("desafios_resueltos", 0)
        py = stats.get("desafios_python", 0)
        cpp = stats.get("desafios_cpp", 0)
        tarjetas.append({
            "icono": "♟️",
            "titulo": "Desafíos",
            "valor": f"{res} resueltos",
            "sub": f"{py} Python · {cpp} C++",
            "color": t["acento2"]
        })

    if cfg.get("mostrar_youtube", True):
        yt_cur = stats.get("youtube_cursos", 0)
        yt_fot = stats.get("youtube_fotogramas", 0)
        tarjetas.append({
            "icono": "📺",
            "titulo": "YouTube Study",
            "valor": f"{yt_cur} clases/cursos",
            "sub": f"{yt_fot} notas y fotogramas",
            "color": t["acento3"]
        })

    if cfg.get("mostrar_kaggle", True):
        celdas = stats.get("kaggle_celdas", 0)
        cols = stats.get("kaggle_colecciones", 0)
        tarjetas.append({
            "icono": "📖",
            "titulo": "Kaggle Learning",
            "valor": f"{celdas} celdas leídas",
            "sub": f"{cols} colecciones guardadas",
            "color": t["acento4"]
        })

    if cfg.get("mostrar_conceptos", True):
        conc = stats.get("conceptos_dominados", 0)
        tarjetas.append({
            "icono": "🎯",
            "titulo": "Conceptos",
            "valor": f"{conc} dominados",
            "sub": "ML, Redes & Algoritmos",
            "color": t["acento5"]
        })

    if cfg.get("mostrar_modelos", False):
        mod = stats.get("modelo_local", "Qwen 2.5 Coder")
        tarjetas.append({
            "icono": "🧠",
            "titulo": "Modelo Local",
            "valor": str(mod)[:16],
            "sub": "Inferencia privada local",
            "color": t["acento2"]
        })

    # Renderizar tarjetas en grid de 2 columnas (máximo 4 a 6 visibles)
    items_svg = []
    col_w = 210
    col_h = 56
    start_x = 24
    start_y = 80
    gap_x = 15
    gap_y = 10

    for i, item in enumerate(tarjetas[:6]):
        col = i % 2
        fila = i // 2
        x = start_x + col * (col_w + gap_x)
        y = start_y + fila * (col_h + gap_y)

        items_svg.append(f"""
        <g transform="translate({x}, {y})">
          <rect width="{col_w}" height="{col_h}" rx="8" fill="rgba(255,255,255,0.03)" stroke="rgba(255,255,255,0.07)" stroke-width="1"/>
          <text x="12" y="24" font-size="16">{_esc_xml(item['icono'])}</text>
          <text x="36" y="20" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="600" fill="{t['subtexto']}">{_esc_xml(item['titulo'])}</text>
          <text x="36" y="36" font-family="system-ui, -apple-system, sans-serif" font-size="12.5" font-weight="700" fill="{item['color']}">{_esc_xml(item['valor'])}</text>
          <text x="36" y="48" font-family="system-ui, -apple-system, sans-serif" font-size="9" fill="{t['subtexto']}">{_esc_xml(item['sub'])}</text>
        </g>
        """)

    elementos_tarjetas = "".join(items_svg)

    svg = f"""<svg width="495" height="240" viewBox="0 0 495 240" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="gradienteBarra" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="{t['gradiente_inicio']}"/>
      <stop offset="100%" stop-color="{t['gradiente_fin']}"/>
    </linearGradient>
    <linearGradient id="gradienteLogo" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#89b4fa"/>
      <stop offset="100%" stop-color="#cba6f7"/>
    </linearGradient>
  </defs>

  <!-- Fondo de la tarjeta -->
  <rect width="495" height="240" rx="14" fill="{t['fondo']}" stroke="{t['borde']}" stroke-width="1.2"/>

  <!-- Cabecera: Logo de Prig IDE, Nombre y Nivel -->
  <g transform="translate(24, 20)">
    <!-- Insignia P de Prig -->
    <rect width="32" height="32" rx="8" fill="url(#gradienteLogo)"/>
    <text x="16" y="22" font-family="'Fira Code', system-ui, monospace" font-size="18" font-weight="800" fill="#11111b" text-anchor="middle">P</text>

    <!-- Título y subtítulo -->
    <text x="42" y="16" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700" fill="{t['texto']}">{nombre}</text>
    <text x="42" y="29" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="500" fill="{t['subtexto']}">Aprendizaje en <tspan font-weight="700" fill="{t['gradiente_fin']}">Prig IDE</tspan> · Nivel {nivel}</text>

    <!-- Badge de Estado Activo -->
    <rect x="365" y="4" width="70" height="20" rx="10" fill="rgba(166,227,161,0.14)" stroke="rgba(166,227,161,0.3)" stroke-width="1"/>
    <circle cx="377" cy="14" r="3.5" fill="#a6e3a1"/>
    <text x="385" y="17.5" font-family="system-ui, -apple-system, sans-serif" font-size="9.5" font-weight="700" fill="#a6e3a1">ACTIVO</text>
  </g>

  <!-- Cuadrícula de Métricas -->
  {elementos_tarjetas}

  <!-- Barra de Avance y Dominio -->
  <g transform="translate(24, 208)">
    <rect width="435" height="7" rx="3.5" fill="rgba(255,255,255,0.08)"/>
    <rect width="{barra_ancho}" height="7" rx="3.5" fill="url(#gradienteBarra)"/>
    <text x="0" y="-4" font-family="system-ui, -apple-system, sans-serif" font-size="9" font-weight="600" fill="{t['subtexto']}">Nivel de Dominio General: <tspan font-weight="700" fill="{t['texto']}">{pct}%</tspan></text>
    <text x="435" y="-4" font-family="system-ui, -apple-system, sans-serif" font-size="8.5" fill="{t['subtexto']}" text-anchor="end">{stats.get('fecha', '')}</text>
  </g>
</svg>"""
    return svg.strip()


def inyectar_en_readme(contenido_actual: str, login: str) -> str:
    """ Inyecta o actualiza la sección de Prig en el README.md sin tocar el contenido del usuario """
    bloque = f"""<!-- PRIG-STATS:START -->
<div align="center">
  <a href="https://github.com/guillermopetcho/Prig-IDE">
    <img src="https://raw.githubusercontent.com/{login}/{login}/main/prig-stats.svg" alt="Estadísticas de Estudio en Prig IDE" width="495"/>
  </a>
  <br/>
  <a href="https://github.com/guillermopetcho/Prig-IDE">
    <img src="https://img.shields.io/badge/Estudiando_con-Prig_IDE-cba6f7?style=flat-square&logo=visualstudiocode&logoColor=white" alt="Prig IDE Badge"/>
  </a>
</div>
<!-- PRIG-STATS:END -->"""

    patron = re.compile(r"<!-- PRIG-STATS:START -->.*?<!-- PRIG-STATS:END -->", re.DOTALL)
    if patron.search(contenido_actual):
        return patron.sub(bloque, contenido_actual)
    else:
        # Añadir de forma limpia al final
        separador = "\n\n" if contenido_actual.strip() else ""
        return contenido_actual.rstrip() + separador + bloque + "\n"


def sincronizar_con_github(token: str, stats: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """ Publica el widget prig-stats.svg y actualiza README.md en el repo especial login/login """
    if not token:
        raise ValueError("No hay token de GitHub configurado. Ve a la sección GitHub para agregarlo.")

    cabeceras = {
        "User-Agent": "Prig-IDE (github-stats-widget)",
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }

    # 1. Obtener usuario autenticado
    try:
        r_user = requests.get(f"{gl.API}/user", headers=cabeceras, timeout=20)
    except requests.RequestException:
        raise ValueError("Sin conexión con GitHub.")

    if r_user.status_code != 200:
        raise ValueError(f"No se pudo acceder a tu cuenta de GitHub ({r_user.status_code}). Verifica el token.")
    login = r_user.json()["login"]

    # 2. Verificar o crear el repositorio especial login/login
    r_repo = requests.get(f"{gl.API}/repos/{login}/{login}", headers=cabeceras, timeout=20)
    if r_repo.status_code == 404:
        r_crear = requests.post(
            f"{gl.API}/user/repos",
            headers=cabeceras,
            json={
                "name": login,
                "description": f"Mi perfil de GitHub y progreso en Prig IDE",
                "private": False,
                "auto_init": True
            },
            timeout=25
        )
        if r_crear.status_code not in (200, 201):
            raise ValueError(f"GitHub no permitió crear el repositorio de perfil «{login}/{login}» ({r_crear.status_code}). Comprueba que el token tenga permiso «Administration: write».")

    # 3. Generar SVG y subir como prig-stats.svg
    svg_str = generar_svg(stats, config)
    svg_b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")

    sha_svg = None
    r_meta_svg = requests.get(f"{gl.API}/repos/{login}/{login}/contents/prig-stats.svg", headers=cabeceras, timeout=20)
    if r_meta_svg.status_code == 200:
        sha_svg = r_meta_svg.json().get("sha")

    payload_svg = {
        "message": "chore(prig): update learning stats widget [skip ci]",
        "content": svg_b64
    }
    if sha_svg:
        payload_svg["sha"] = sha_svg

    r_put_svg = requests.put(
        f"{gl.API}/repos/{login}/{login}/contents/prig-stats.svg",
        headers=cabeceras,
        json=payload_svg,
        timeout=25
    )
    if r_put_svg.status_code not in (200, 201):
        raise ValueError(f"Error subiendo prig-stats.svg a GitHub ({r_put_svg.status_code}). Comprueba que el token tenga permiso «Contents: write».")

    # 4. Actualizar README.md
    readme_actual = f"# {login}\n"
    sha_readme = None
    r_readme = requests.get(f"{gl.API}/repos/{login}/{login}/contents/README.md", headers=cabeceras, timeout=20)
    if r_readme.status_code == 200:
        sha_readme = r_readme.json().get("sha")
        content_b64 = r_readme.json().get("content", "")
        try:
            readme_actual = base64.b64decode(content_b64).decode("utf-8")
        except Exception:
            readme_actual = f"# {login}\n"

    readme_nuevo = inyectar_en_readme(readme_actual, login)
    readme_b64 = base64.b64encode(readme_nuevo.encode("utf-8")).decode("ascii")

    payload_readme = {
        "message": "chore(prig): sync profile learning widgets [skip ci]",
        "content": readme_b64
    }
    if sha_readme:
        payload_readme["sha"] = sha_readme

    r_put_readme = requests.put(
        f"{gl.API}/repos/{login}/{login}/contents/README.md",
        headers=cabeceras,
        json=payload_readme,
        timeout=25
    )
    if r_put_readme.status_code not in (200, 201):
        raise ValueError(f"Error actualizando README.md en GitHub ({r_put_readme.status_code}).")

    # 5. Guardar último sync en config
    guardar_config({
        "ultimo_sync": datetime.now().isoformat(),
        "ultimo_login": login
    })

    return {
        "ok": True,
        "login": login,
        "repo_url": f"https://github.com/{login}/{login}",
        "profile_url": f"https://github.com/{login}",
        "svg_url": f"https://raw.githubusercontent.com/{login}/{login}/main/prig-stats.svg",
        "mensaje": f"¡Widget y README.md sincronizados exitosamente en {login}/{login}!"
    }
