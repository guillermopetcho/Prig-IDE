"""
Gestor de Perfiles de Configuración del Entorno Prig IDE (Backend).
Almacena y sincroniza los perfiles de personalización, apariencia, rendimiento de movimiento,
modelos y preferencias del usuario de forma persistente en disco (.prig_dataset/config_profiles.json).
"""

import json
import os
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

RUTA_PERFILES = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".prig_dataset", "config_profiles.json")

PERFILES_PREDETERMINADOS = [
    {
        "id": "catppuccin_equilibrado",
        "nombre": "Catppuccin Mocha Equilibrado",
        "icono": "fa-cat",
        "desc": "Tema pastel suave con constelación neuronal a 60 FPS. Máximo confort visual diario.",
        "esPreset": True,
        "apariencia": {
            "temaActivo": "catppuccin_mocha",
            "opacidad": 0.92,
            "desenfoque": 10,
            "acento": "#89b4fa",
            "densidad": "normal",
            "colores": {
                "bg_dark": "#1e1e2e",
                "bg_panel": "#181825",
                "bg_editor": "#11111b",
                "bg_hover": "#313244",
                "border_color": "#313244",
                "text_main": "#cdd6f4",
                "text_muted": "#a6adc8",
                "accent_blue": "#89b4fa",
                "accent_purple": "#cba6f7",
                "accent_green": "#a6e3a1",
                "accent_red": "#f38ba8",
                "accent_yellow": "#f9e2af"
            },
            "fondoGlobal": {
                "tipo": "movimiento",
                "color": "#181825",
                "efectoMovimiento": "particulas",
                "overlayAlfa": 0.35
            },
            "secciones": {}
        },
        "motorMovimiento": {
            "efecto": "particulas",
            "fpsLimite": 60,
            "escalaRender": 0.75,
            "densidad": "media",
            "velocidad": 1.0,
            "interaccionMouse": True,
            "pausarEnSegundoPlano": True
        },
        "sintaxis": {
            "presetActivo": "personalizado",
            "tokens": {
                "keyword": { "color": "#cba6f7", "fontStyle": "bold", "efectoRaro": "resplandor_neon" },
                "type": { "color": "#89b4fa", "fontStyle": "bold", "efectoRaro": "ninguno" },
                "function": { "color": "#89dceb", "fontStyle": "", "efectoRaro": "ninguno" },
                "string": { "color": "#a6e3a1", "fontStyle": "", "efectoRaro": "ninguno" },
                "number": { "color": "#fab387", "fontStyle": "", "efectoRaro": "ninguno" },
                "comment": { "color": "#6c7086", "fontStyle": "italic", "efectoRaro": "ninguno" },
                "operator": { "color": "#89dceb", "fontStyle": "", "efectoRaro": "ninguno" },
                "variable": { "color": "#cdd6f4", "fontStyle": "", "efectoRaro": "ninguno" }
            },
            "efectosGlobales": {
                "lineasEscaneo": False,
                "resplandorCursor": False,
                "codigoCss": ""
            }
        }
    },
    {
        "id": "cyberpunk_neon",
        "nombre": "Cyberpunk Neón Extremo",
        "icono": "fa-bolt",
        "desc": "Estilo futurista de alto contraste con lluvia digital Matrix y resplandor cian/magenta.",
        "esPreset": True,
        "apariencia": {
            "temaActivo": "cyberpunk",
            "opacidad": 0.88,
            "desenfoque": 12,
            "acento": "#00f0ff",
            "densidad": "normal",
            "colores": {
                "bg_dark": "#0f051d",
                "bg_panel": "#1a0933",
                "bg_editor": "#0b0217",
                "bg_hover": "#2a1152",
                "border_color": "#ff007f55",
                "text_main": "#00ffff",
                "text_muted": "#a277ff",
                "accent_blue": "#00f0ff",
                "accent_purple": "#ff007f",
                "accent_green": "#00ff66",
                "accent_red": "#ff0055",
                "accent_yellow": "#ffe600"
            },
            "fondoGlobal": {
                "tipo": "movimiento",
                "color": "#0f051d",
                "efectoMovimiento": "matrix",
                "overlayAlfa": 0.25
            },
            "secciones": {}
        },
        "motorMovimiento": {
            "efecto": "matrix",
            "fpsLimite": 60,
            "escalaRender": 0.75,
            "densidad": "alta",
            "velocidad": 1.2,
            "interaccionMouse": True,
            "pausarEnSegundoPlano": True
        },
        "sintaxis": {
            "presetActivo": "cyberpunk_glitch",
            "tokens": {
                "keyword": { "color": "#ff007f", "fontStyle": "bold", "efectoRaro": "glitch_rgb" },
                "type": { "color": "#00ffff", "fontStyle": "bold", "efectoRaro": "resplandor_neon" },
                "function": { "color": "#00ff66", "fontStyle": "bold", "efectoRaro": "resplandor_neon" },
                "string": { "color": "#ffe600", "fontStyle": "", "efectoRaro": "ninguno" },
                "number": { "color": "#ff0055", "fontStyle": "bold", "efectoRaro": "ninguno" },
                "comment": { "color": "#a277ff", "fontStyle": "italic", "efectoRaro": "ninguno" },
                "operator": { "color": "#00f0ff", "fontStyle": "", "efectoRaro": "ninguno" },
                "variable": { "color": "#00ffff", "fontStyle": "", "efectoRaro": "ninguno" }
            },
            "efectosGlobales": {
                "lineasEscaneo": False,
                "resplandorCursor": True,
                "codigoCss": ""
            }
        }
    },
    {
        "id": "midnight_ahorro",
        "nombre": "Midnight Oscuro (Modo Batería)",
        "icono": "fa-moon",
        "desc": "Fondo estático oscuro profundo (#0d1117) con motor en pausa. 0% consumo de GPU.",
        "esPreset": True,
        "apariencia": {
            "temaActivo": "midnight_dark",
            "opacidad": 1.0,
            "desenfoque": 0,
            "acento": "#58a6ff",
            "densidad": "compacta",
            "colores": {
                "bg_dark": "#0d1117",
                "bg_panel": "#161b22",
                "bg_editor": "#0d1117",
                "bg_hover": "#21262d",
                "border_color": "#30363d",
                "text_main": "#c9d1d9",
                "text_muted": "#8b949e",
                "accent_blue": "#58a6ff",
                "accent_purple": "#bc8cff",
                "accent_green": "#3fb950",
                "accent_red": "#ff7b72",
                "accent_yellow": "#d29922"
            },
            "fondoGlobal": {
                "tipo": "color",
                "color": "#0d1117"
            },
            "secciones": {}
        },
        "motorMovimiento": {
            "efecto": "particulas",
            "fpsLimite": 30,
            "escalaRender": 0.5,
            "densidad": "baja",
            "velocidad": 0.8,
            "interaccionMouse": False,
            "pausarEnSegundoPlano": True
        },
        "sintaxis": {
            "presetActivo": "monokai_bizarro",
            "tokens": {
                "keyword": { "color": "#ff007f", "fontStyle": "bold", "efectoRaro": "resplandor_neon" },
                "type": { "color": "#66d9ef", "fontStyle": "bold italic", "efectoRaro": "ninguno" },
                "function": { "color": "#a6e22e", "fontStyle": "bold", "efectoRaro": "resplandor_neon" },
                "string": { "color": "#e6db74", "fontStyle": "", "efectoRaro": "ninguno" },
                "number": { "color": "#ae81ff", "fontStyle": "bold", "efectoRaro": "ninguno" },
                "comment": { "color": "#88846f", "fontStyle": "italic", "efectoRaro": "ninguno" },
                "operator": { "color": "#f92672", "fontStyle": "", "efectoRaro": "ninguno" },
                "variable": { "color": "#fd971f", "fontStyle": "", "efectoRaro": "ninguno" }
            },
            "efectosGlobales": {
                "lineasEscaneo": False,
                "resplandorCursor": True,
                "codigoCss": ""
            }
        }
    },
    {
        "id": "nord_frost",
        "nombre": "Nord Frost Minimalista",
        "icono": "fa-snowflake",
        "desc": "Gama ártica fría y elegante con aurora boreal fluida suave de fondo.",
        "esPreset": True,
        "apariencia": {
            "temaActivo": "nord",
            "opacidad": 0.94,
            "desenfoque": 8,
            "acento": "#88c0d0",
            "densidad": "normal",
            "colores": {
                "bg_dark": "#2e3440",
                "bg_panel": "#3b4252",
                "bg_editor": "#242933",
                "bg_hover": "#434c5e",
                "border_color": "#4c566a",
                "text_main": "#eceff4",
                "text_muted": "#d8dee9",
                "accent_blue": "#88c0d0",
                "accent_purple": "#b48ead",
                "accent_green": "#a3be8c",
                "accent_red": "#bf616a",
                "accent_yellow": "#ebcb8b"
            },
            "fondoGlobal": {
                "tipo": "movimiento",
                "color": "#2e3440",
                "efectoMovimiento": "aurora",
                "overlayAlfa": 0.35
            },
            "secciones": {}
        },
        "motorMovimiento": {
            "efecto": "aurora",
            "fpsLimite": 45,
            "escalaRender": 0.75,
            "densidad": "media",
            "velocidad": 0.7,
            "interaccionMouse": True,
            "pausarEnSegundoPlano": True
        },
        "sintaxis": {
            "presetActivo": "nord_aurora_mistica",
            "tokens": {
                "keyword": { "color": "#88c0d0", "fontStyle": "bold", "efectoRaro": "resplandor_neon" },
                "type": { "color": "#81a1c1", "fontStyle": "bold", "efectoRaro": "ninguno" },
                "function": { "color": "#8fbcbb", "fontStyle": "bold", "efectoRaro": "subrayado_onda" },
                "string": { "color": "#a3be8c", "fontStyle": "", "efectoRaro": "ninguno" },
                "number": { "color": "#b48ead", "fontStyle": "bold", "efectoRaro": "ninguno" },
                "comment": { "color": "#616e88", "fontStyle": "italic", "efectoRaro": "ninguno" },
                "operator": { "color": "#81a1c1", "fontStyle": "", "efectoRaro": "ninguno" },
                "variable": { "color": "#eceff4", "fontStyle": "", "efectoRaro": "ninguno" }
            },
            "efectosGlobales": {
                "lineasEscaneo": False,
                "resplandorCursor": True,
                "codigoCss": ""
            }
        }
    },
    {
        "id": "synthwave_retro",
        "nombre": "Synthwave 3D Retro",
        "icono": "fa-border-all",
        "desc": "Cuadrícula retro 3D en perspectiva con horizonte ondulante y tonos magenta/oro.",
        "esPreset": True,
        "apariencia": {
            "temaActivo": "obsidian_gold",
            "opacidad": 0.90,
            "desenfoque": 10,
            "acento": "#ffd54f",
            "densidad": "normal",
            "colores": {
                "bg_dark": "#141414",
                "bg_panel": "#1c1c1c",
                "bg_editor": "#0d0d0d",
                "bg_hover": "#292929",
                "border_color": "#3d382d",
                "text_main": "#e6e6e6",
                "text_muted": "#999487",
                "accent_blue": "#64b5f6",
                "accent_purple": "#ba68c8",
                "accent_green": "#81c784",
                "accent_red": "#e57373",
                "accent_yellow": "#ffd54f"
            },
            "fondoGlobal": {
                "tipo": "movimiento",
                "color": "#141414",
                "efectoMovimiento": "malla_cyberpunk",
                "overlayAlfa": 0.30
            },
            "secciones": {}
        },
        "motorMovimiento": {
            "efecto": "malla_cyberpunk",
            "fpsLimite": 60,
            "escalaRender": 0.75,
            "densidad": "media",
            "velocidad": 1.0,
            "interaccionMouse": True,
            "pausarEnSegundoPlano": True
        },
        "sintaxis": {
            "presetActivo": "lava_arcade_8bit",
            "tokens": {
                "keyword": { "color": "#ff3d00", "fontStyle": "bold", "efectoRaro": "fuego_retro" },
                "type": { "color": "#ff9100", "fontStyle": "bold", "efectoRaro": "resplandor_neon" },
                "function": { "color": "#ffea00", "fontStyle": "bold", "efectoRaro": "ninguno" },
                "string": { "color": "#00e676", "fontStyle": "", "efectoRaro": "ninguno" },
                "number": { "color": "#d500f9", "fontStyle": "bold", "efectoRaro": "ninguno" },
                "comment": { "color": "#a1887f", "fontStyle": "italic", "efectoRaro": "ninguno" },
                "operator": { "color": "#ff3d00", "fontStyle": "", "efectoRaro": "ninguno" },
                "variable": { "color": "#ffffff", "fontStyle": "", "efectoRaro": "ninguno" }
            },
            "efectosGlobales": {
                "lineasEscaneo": False,
                "resplandorCursor": True,
                "codigoCss": ""
            }
        }
    }
]

DATASET_DIR = os.path.dirname(RUTA_PERFILES)
RUTA_APARIENCIA = os.path.join(DATASET_DIR, "apariencia.json")
RUTA_SINTAXIS = os.path.join(DATASET_DIR, "sintaxis_personalizada.json")
RUTA_MOTOR_MOVIMIENTO = os.path.join(DATASET_DIR, "motor_movimiento.json")
RUTA_ACCESIBILIDAD = os.path.join(DATASET_DIR, "accesibilidad.json")
RUTA_AUDIO_REACTIVO = os.path.join(DATASET_DIR, "audio_reactivo.json")


def _asegurar_directorio():
    directorio = DATASET_DIR
    if not os.path.exists(directorio):
        try:
            os.makedirs(directorio, exist_ok=True)
        except Exception:
            pass


def _cargar_json(ruta: str, por_defecto: Any) -> Any:
    _asegurar_directorio()
    if not os.path.isfile(ruta):
        return por_defecto
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error cargando JSON de {ruta}: {e}")
        return por_defecto


def _guardar_json(ruta: str, datos: Any) -> bool:
    _asegurar_directorio()
    try:
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Error guardando JSON en {ruta}: {e}")
        return False


def cargar_perfiles() -> Dict[str, Any]:
    _asegurar_directorio()
    if not os.path.isfile(RUTA_PERFILES):
        datos_iniciales = {
            "perfil_activo": "catppuccin_equilibrado",
            "perfiles": PERFILES_PREDETERMINADOS
        }
        guardar_perfiles(datos_iniciales)
        return datos_iniciales

    try:
        with open(RUTA_PERFILES, "r", encoding="utf-8") as f:
            datos = json.load(f)
            if not isinstance(datos, dict) or "perfiles" not in datos:
                raise ValueError("Estructura inválida")
            return datos
    except Exception:
        return {
            "perfil_activo": "catppuccin_equilibrado",
            "perfiles": PERFILES_PREDETERMINADOS
        }


def guardar_perfiles(datos: Dict[str, Any]) -> bool:
    return _guardar_json(RUTA_PERFILES, datos)


# ==========================================
# APARIENCIA Y TEMAS
# ==========================================

def cargar_apariencia() -> Dict[str, Any]:
    return _cargar_json(RUTA_APARIENCIA, {})


def guardar_apariencia(datos: Dict[str, Any]) -> bool:
    return _guardar_json(RUTA_APARIENCIA, datos)


# ==========================================
# SINTAXIS Y TOKENS PERSONALIZADOS
# ==========================================

def cargar_sintaxis() -> Dict[str, Any]:
    return _cargar_json(RUTA_SINTAXIS, {})


def guardar_sintaxis(datos: Dict[str, Any]) -> bool:
    return _guardar_json(RUTA_SINTAXIS, datos)


# ==========================================
# MOTOR DE MOVIMIENTO Y RENDIMIENTO
# ==========================================

def cargar_motor_movimiento() -> Dict[str, Any]:
    return _cargar_json(RUTA_MOTOR_MOVIMIENTO, {})


def guardar_motor_movimiento(datos: Dict[str, Any]) -> bool:
    return _guardar_json(RUTA_MOTOR_MOVIMIENTO, datos)


# ==========================================
# ACCESIBILIDAD Y ATAJOS
# ==========================================

def cargar_accesibilidad() -> Dict[str, Any]:
    return _cargar_json(RUTA_ACCESIBILIDAD, {})


def guardar_accesibilidad(datos: Dict[str, Any]) -> bool:
    return _guardar_json(RUTA_ACCESIBILIDAD, datos)


# ==========================================
# AUDIO REACTIVO Y LUCES
# ==========================================

def cargar_audio_reactivo() -> Dict[str, Any]:
    return _cargar_json(RUTA_AUDIO_REACTIVO, {})


def guardar_audio_reactivo(datos: Dict[str, Any]) -> bool:
    return _guardar_json(RUTA_AUDIO_REACTIVO, datos)


# ==========================================
# ESTADO COMPLETO UNIFICADO
# ==========================================

def cargar_estado_completo() -> Dict[str, Any]:
    return {
        "apariencia": cargar_apariencia(),
        "sintaxis": cargar_sintaxis(),
        "motor_movimiento": cargar_motor_movimiento(),
        "audio_reactivo": cargar_audio_reactivo(),
        "accesibilidad": cargar_accesibilidad(),
        "perfiles": cargar_perfiles()
    }


def guardar_estado_completo(datos: Dict[str, Any]) -> Dict[str, bool]:
    res = {}
    if "apariencia" in datos and isinstance(datos["apariencia"], dict):
        res["apariencia"] = guardar_apariencia(datos["apariencia"])
    if "sintaxis" in datos and isinstance(datos["sintaxis"], dict):
        res["sintaxis"] = guardar_sintaxis(datos["sintaxis"])
    if "motor_movimiento" in datos and isinstance(datos["motor_movimiento"], dict):
        res["motor_movimiento"] = guardar_motor_movimiento(datos["motor_movimiento"])
    if "audio_reactivo" in datos and isinstance(datos["audio_reactivo"], dict):
        res["audio_reactivo"] = guardar_audio_reactivo(datos["audio_reactivo"])
    if "accesibilidad" in datos and isinstance(datos["accesibilidad"], dict):
        res["accesibilidad"] = guardar_accesibilidad(datos["accesibilidad"])
    if "perfiles" in datos and isinstance(datos["perfiles"], dict):
        res["perfiles"] = guardar_perfiles(datos["perfiles"])
    return res


class PerfilGuardarRequest(BaseModel):
    perfil_activo: Optional[str] = "catppuccin_equilibrado"
    perfiles: List[Dict[str, Any]]

