"""
Gestor de Perfiles de Configuración del Entorno Prig IDE (Backend).
Almacena y sincroniza los perfiles de personalización, apariencia, rendimiento de movimiento,
modelos y preferencias del usuario de forma persistente en disco (.prig_dataset/config_profiles.json).
La lectura y la escritura están en Rust (backend-rust/crates/prig-plataforma, perfiles.rs): los archivos salen byte
a byte igual que cuando los escribía Python.
"""

import os
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

RUTA_PERFILES = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".prig_dataset", "config_profiles.json")

def _rs():
    from nativo_rust import rust
    return rust().perfiles_config


# Los perfiles de fábrica están en Rust (perfiles_predeterminados.json, dentro del módulo)
PERFILES_PREDETERMINADOS = _rs().predeterminados()

DATASET_DIR = os.path.dirname(RUTA_PERFILES)
RUTA_APARIENCIA = os.path.join(DATASET_DIR, "apariencia.json")
RUTA_SINTAXIS = os.path.join(DATASET_DIR, "sintaxis_personalizada.json")
RUTA_MOTOR_MOVIMIENTO = os.path.join(DATASET_DIR, "motor_movimiento.json")
RUTA_ACCESIBILIDAD = os.path.join(DATASET_DIR, "accesibilidad.json")
RUTA_AUDIO_REACTIVO = os.path.join(DATASET_DIR, "audio_reactivo.json")


def _cargar_json(ruta: str, por_defecto: Any) -> Any:
    return _rs().cargar_json(DATASET_DIR, ruta, por_defecto)


def _guardar_json(ruta: str, datos: Any) -> bool:
    return _rs().guardar_json(DATASET_DIR, ruta, datos)


def cargar_perfiles() -> Dict[str, Any]:
    """ Si no hay archivo se crea con los de fábrica; si está roto se devuelven los de fábrica """
    return _rs().cargar_perfiles(DATASET_DIR, RUTA_PERFILES)


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

