"""
Servicio de descarga completa y respaldo de modelos desde Hugging Face para Prig IDE.

Permite descargar no solo los pesos (.gguf o .safetensors), sino la totalidad de los
archivos de configuración, tokenizer y metadatos del repositorio:
    - config.json, generation_config.json
    - tokenizer.json, tokenizer_config.json, special_tokens_map.json, vocab.json, merges.txt
    - chat_template.json, preprocessor_config.json
    - README.md, LICENSE, .gitattributes, etc.

Objetivo:
Garantizar la preservación permanente y autónoma del modelo en el equipo local,
evitando pérdidas irreparables en caso de que el creador o Hugging Face eliminen,
privaticen o modifiquen el repositorio en el futuro.
"""

import os
import re
import json
import time
import shutil
import hashlib
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from buscador_modelos import UA, agrupar_gguf, cuantizacion_de

BASE_HF = "https://huggingface.co"
CARPETA_DEFECTO = "modelos_completos"

# Nombres y extensiones reconocidos como configuración y metadatos
NOMBRES_CONFIG = {
    "config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json",
    "special_tokens_map.json", "vocab.json", "merges.txt", "chat_template.json",
    "added_tokens.json", "preprocessor_config.json", "adapter_config.json",
    "README.md", "readme.md", "LICENSE", "license", "LICENSE.txt", "license.txt",
    "LICENSE.md", "license.md", ".gitattributes", "params", "template", "Modelfile",
    "modelfile", "model.safetensors.index.json", "pytorch_model.bin.index.json"
}

EXTS_CONFIG = {".json", ".txt", ".yaml", ".yml", ".py", ".md", ".jinja", ".jinja2"}
EXTS_PESOS = {".gguf", ".safetensors", ".bin", ".pt", ".pth", ".onnx", ".h5"}


def obtener_token_hf() -> Optional[str]:
    """Obtiene el token de Hugging Face desde variables de entorno o caché estándar."""
    for var in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
        token = os.environ.get(var)
        if token and token.strip():
            return token.strip()
    ruta_cache = os.path.expanduser("~/.cache/huggingface/token")
    if os.path.isfile(ruta_cache):
        try:
            with open(ruta_cache, "r", encoding="utf-8") as f:
                t = f.read().strip()
                if t:
                    return t
        except Exception:
            pass
    return None


def cabeceras_hf(token: Optional[str] = None) -> Dict[str, str]:
    """Construye cabeceras HTTP con User-Agent y autenticación opcional para Hugging Face."""
    cab = dict(UA)
    tok = token or obtener_token_hf()
    if tok:
        cab["Authorization"] = f"Bearer {tok}"
    return cab


def limpiar_repo_hf(ref_o_url: str) -> Tuple[str, Optional[str]]:
    """
    Normaliza una referencia o URL hacia (repo_id, variante_opcional).
    Ejemplos:
        'hf.co/unsloth/Qwen3-8B-GGUF:Q4_K_M' -> ('unsloth/Qwen3-8B-GGUF', 'Q4_K_M')
        'https://huggingface.co/Qwen/Qwen2.5-Coder-7B' -> ('Qwen/Qwen2.5-Coder-7B', None)
        'unsloth/Qwen3-8B-GGUF' -> ('unsloth/Qwen3-8B-GGUF', None)
    """
    t = (ref_o_url or "").strip()
    # Eliminar prefijos de protocolo y dominio
    t = re.sub(r"^https?://(?:www\.)?(?:huggingface\.co|hf\.co)/", "", t, flags=re.I)
    t = re.sub(r"^(?:hf\.co|huggingface\.co)/", "", t, flags=re.I)
    t = re.sub(r"^models/", "", t, flags=re.I)
    
    variante = None
    if ":" in t:
        partes = t.split(":", 1)
        t = partes[0]
        variante = partes[1].strip() or None
    
    # Limpiar posibles sufijos de URL como /tree/main o /blob/main
    t = re.sub(r"/(?:tree|blob|resolve)/[\w.\-]+(?:/.*)?$", "", t)
    return t.strip(), variante


def es_archivo_config(nombre: str, tam_bytes: int) -> bool:
    """Determina si un archivo de Hugging Face corresponde a configuración, tokenizer o metadatos."""
    base = os.path.basename(nombre).lower()
    if base in {x.lower() for x in NOMBRES_CONFIG}:
        return True
    if base.startswith("imatrix") and base.endswith(".dat"):
        return True
    ext = os.path.splitext(base)[1].lower()
    if ext in EXTS_CONFIG and ext not in EXTS_PESOS:
        # Menor a 50 MB para evitar falsos positivos
        if tam_bytes < 50 * 1024 * 1024:
            return True
    return False


def inspeccionar_modelo_hf(repo_o_ref: str, variante: Optional[str] = None,
                           token: Optional[str] = None) -> Dict[str, Any]:
    """
    Consulta la API de Hugging Face y clasifica todos los archivos del repositorio:
    - Archivos de configuración (config.json, tokenizer, README, etc.)
    - Archivos de pesos por variante (.gguf, .safetensors, .bin)
    """
    repo_id, var_ref = limpiar_repo_hf(repo_o_ref)
    variante_elegida = variante or var_ref
    
    if not re.match(r"^[\w.\-]+/[\w.\-]+$", repo_id):
        raise ValueError(f"Identificador de repositorio Hugging Face no válido: {repo_id!r}")
        
    url_api = f"{BASE_HF}/api/models/{repo_id}"
    r = requests.get(url_api, params={"blobs": "true"}, headers=cabeceras_hf(token), timeout=25)
    if r.status_code == 404:
        raise ValueError(f"El modelo '{repo_id}' no existe en Hugging Face (404).")
    if r.status_code in (401, 403):
        raise PermissionError(f"El modelo '{repo_id}' requiere autenticación o aceptar su licencia (gated).")
    if r.status_code != 200:
        raise RuntimeError(f"Hugging Face respondió {r.status_code}: {r.text[:200]}")
        
    datos = r.json()
    siblings = datos.get("siblings") or []
    
    archivos_config: List[Dict[str, Any]] = []
    archivos_pesos_todos: List[Dict[str, Any]] = []
    archivos_gguf: List[Tuple[str, int]] = []
    
    for s in siblings:
        rfilename = s.get("rfilename", "")
        tam = s.get("size") or 0
        url_descarga = f"{BASE_HF}/{repo_id}/resolve/main/{rfilename}"
        
        item_info = {"nombre": rfilename, "bytes": tam, "url": url_descarga}
        
        if es_archivo_config(rfilename, tam):
            archivos_config.append(item_info)
        else:
            archivos_pesos_todos.append(item_info)
            if rfilename.lower().endswith(".gguf") and "mmproj" not in rfilename.lower():
                archivos_gguf.append((rfilename, tam))
                
    # Variantes GGUF agrupadas si existen
    variantes_gguf = agrupar_gguf(archivos_gguf, prefijo=f"hf.co/{repo_id}")
    
    # Determinar archivos de pesos seleccionados según la variante
    pesos_seleccionados: List[Dict[str, Any]] = []
    if variante_elegida and variante_elegida.lower() in ("solo_configs", "__solo_configs__", "configs"):
        pesos_seleccionados = []
    elif variante_elegida and variante_elegida.lower() != "todo":
        # Buscar en variantes agrupadas
        v_match = next((v for v in variantes_gguf if v["etiqueta"].lower() == variante_elegida.lower()), None)
        if v_match:
            nombres_buscados = set(v_match["archivos"])
            pesos_seleccionados = [p for p in archivos_pesos_todos if p["nombre"] in nombres_buscados]
        else:
            # Búsqueda por substring en nombres
            q_lower = variante_elegida.lower()
            pesos_seleccionados = [p for p in archivos_pesos_todos if q_lower in p["nombre"].lower()]
            
        # Si incluye proyector mmproj, añadirlo automáticamente
        mmprojs = [p for p in archivos_pesos_todos if "mmproj" in p["nombre"].lower()]
        pesos_seleccionados.extend(mmprojs)
    else:
        # Todo el repositorio o safetensors
        pesos_seleccionados = archivos_pesos_todos

    bytes_configs = sum(c["bytes"] for c in archivos_config)
    bytes_pesos = sum(p["bytes"] for p in pesos_seleccionados)
    
    autor = repo_id.split("/")[0]
    nombre_repo = repo_id.split("/")[-1]
    carpeta_sugerida = os.path.join(CARPETA_DEFECTO, f"{autor}__{nombre_repo}")
    
    return {
        "ok": True,
        "repo_id": repo_id,
        "url_hf": f"{BASE_HF}/{repo_id}",
        "autor": autor,
        "nombre": nombre_repo,
        "variante_elegida": variante_elegida,
        "carpeta_sugerida": carpeta_sugerida,
        "requiere_licencia": bool(datos.get("gated")),
        "arquitectura": (datos.get("gguf") or {}).get("architecture"),
        "context_length": (datos.get("gguf") or {}).get("context_length"),
        "chat_template": (datos.get("gguf") or {}).get("chat_template"),
        "total_archivos_repo": len(siblings),
        "archivos_config": archivos_config,
        "bytes_configs": bytes_configs,
        "archivos_pesos_seleccionados": pesos_seleccionados,
        "bytes_pesos_seleccionados": bytes_pesos,
        "total_bytes_respaldo": bytes_configs + bytes_pesos,
        "variantes_gguf": variantes_gguf,
        "es_gguf": len(archivos_gguf) > 0,
    }


def descargar_archivo_individual(url: str, destino_final: str, cabeceras: dict,
                                 cancelar: threading.Event,
                                 notificar_chunk: Optional[Callable[[int], None]] = None) -> int:
    """
    Descarga un archivo por streaming con soporte de reanudación (HTTP Range).
    Guarda en un archivo '.part' temporal y al terminar renombra atómicamente.
    """
    os.makedirs(os.path.dirname(os.path.abspath(destino_final)), exist_ok=True)
    destino_part = destino_final + ".part"
    
    bytes_existentes = 0
    if os.path.isfile(destino_part):
        bytes_existentes = os.path.getsize(destino_part)
        
    cab = dict(cabeceras)
    if bytes_existentes > 0:
        cab["Range"] = f"bytes={bytes_existentes}-"
        
    r = requests.get(url, headers=cab, stream=True, timeout=(15, 300), allow_redirects=True)
    
    modo = "ab" if r.status_code == 206 and bytes_existentes > 0 else "wb"
    if modo == "wb":
        bytes_existentes = 0
        
    if r.status_code not in (200, 206):
        r.close()
        raise RuntimeError(f"Error descargando {os.path.basename(destino_final)}: HTTP {r.status_code}")
        
    bytes_descargados_sesion = 0
    try:
        with open(destino_part, modo) as f:
            for trozo in r.iter_content(chunk_size=512 * 1024):
                if cancelar.is_set():
                    raise RuntimeError("Descarga cancelada por el usuario.")
                if trozo:
                    f.write(trozo)
                    bytes_descargados_sesion += len(trozo)
                    if notificar_chunk:
                        notificar_chunk(len(trozo))
    finally:
        r.close()
        
    # Renombrar a destino final
    if os.path.exists(destino_final):
        os.remove(destino_final)
    os.rename(destino_part, destino_final)
    return bytes_existentes + bytes_descargados_sesion


def ejecutar_descarga_completa_hf(repo_id: str,
                                  variante: Optional[str] = None,
                                  carpeta_destino: Optional[str] = None,
                                  workspace_dir: Optional[str] = None,
                                  item: Optional[Dict[str, Any]] = None,
                                  actualizar_fn: Optional[Callable[..., None]] = None) -> Dict[str, Any]:
    """
    Proceso central de descarga y respaldo completo de un modelo de Hugging Face.
    Descarga todos los archivos de configuración y la variante de pesos indicada,
    generando Modelfile y prig_backup_manifest.json.
    """
    ws = workspace_dir or os.getcwd()
    token = obtener_token_hf()
    cab = cabeceras_hf(token)
    cancelar = item.get("_cancelar") if item else threading.Event()
    
    def fijar(**kwargs):
        if actualizar_fn and item:
            actualizar_fn(item, **kwargs)
            
    fijar(fase="Consultando catálogo e inspeccionando archivos en Hugging Face")
    
    info = inspeccionar_modelo_hf(repo_id, variante=variante, token=token)
    
    # Determinar ruta destino final
    if carpeta_destino:
        dest_abs = os.path.abspath(carpeta_destino)
    else:
        dest_abs = os.path.join(ws, info["carpeta_sugerida"])
    os.makedirs(dest_abs, exist_ok=True)
    
    archivos_a_descargar = info["archivos_config"] + info["archivos_pesos_seleccionados"]
    total_bytes = sum(a["bytes"] for a in archivos_a_descargar)
    
    # Comprobar espacio en disco
    try:
        libre = shutil.disk_usage(dest_abs).free
        if libre < total_bytes * 1.03:
            raise OSError(f"Espacio insuficiente: hacen falta {total_bytes/1e9:.2f} GB y solo quedan {libre/1e9:.2f} GB libres.")
    except Exception as e:
        if "Espacio insuficiente" in str(e):
            raise
            
    fijar(total=total_bytes, completado=0, fase="Iniciando descarga de respaldo")
    
    total_archivos = len(archivos_a_descargar)
    bytes_acumulados = 0
    muestras_vel: List[Tuple[float, int]] = []
    
    for idx, arch in enumerate(archivos_a_descargar):
        if cancelar.is_set():
            raise RuntimeError("Descarga cancelada.")
            
        nombre_f = arch["nombre"]
        url_f = arch["url"]
        ruta_local = os.path.join(dest_abs, nombre_f)
        
        fijar(fase=f"Descargando [{idx+1}/{total_archivos}] {nombre_f}")
        
        # Si ya existe y coincide en tamaño exacto, omitir para ganar tiempo
        if os.path.isfile(ruta_local) and arch["bytes"] > 0 and os.path.getsize(ruta_local) == arch["bytes"]:
            bytes_acumulados += arch["bytes"]
            fijar(completado=bytes_acumulados)
            continue
            
        def cb_chunk(tam_chunk):
            nonlocal bytes_acumulados, muestras_vel
            bytes_acumulados += tam_chunk
            ahora = time.time()
            muestras_vel.append((ahora, bytes_acumulados))
            muestras_vel = [m for m in muestras_vel if ahora - m[0] <= 8]
            
            vel = None
            if len(muestras_vel) >= 2 and muestras_vel[-1][0] > muestras_vel[0][0]:
                vel = (muestras_vel[-1][1] - muestras_vel[0][1]) / (muestras_vel[-1][0] - muestras_vel[0][0])
            restante = (total_bytes - bytes_acumulados) / vel if vel and vel > 0 else None
            
            fijar(completado=bytes_acumulados, velocidad=vel, restante_s=restante)
            
        descargar_archivo_individual(url_f, ruta_local, cab, cancelar, cb_chunk)
        
    # Crear manifiesto formal de respaldo
    fijar(fase="Generando manifiesto de respaldo y Modelfile")
    
    manifiesto = {
        "origen": "huggingface",
        "repo_id": repo_id,
        "url_origen": info["url_hf"],
        "fecha_respaldo": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "variante_seleccionada": info["variante_elegida"] or "completo",
        "total_archivos": total_archivos,
        "total_bytes": total_bytes,
        "archivos_configuracion": [a["nombre"] for a in info["archivos_config"]],
        "archivos_pesos": [a["nombre"] for a in info["archivos_pesos_seleccionados"]],
        "preservado_contra_borrado": True,
        "nota": "Copia completa con todos los archivos de configuración y pesos preservados localmente para uso autónomo por si se borra de Hugging Face."
    }
    
    ruta_manifest = os.path.join(dest_abs, "prig_backup_manifest.json")
    with open(ruta_manifest, "w", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=2)
        
    # Si contiene algún archivo GGUF, generar Modelfile para Ollama
    gguf_files = [a["nombre"] for a in info["archivos_pesos_seleccionados"] if a["nombre"].lower().endswith(".gguf")]
    if gguf_files:
        principal_gguf = gguf_files[0]
        ruta_modelfile = os.path.join(dest_abs, "Modelfile")
        chat_tmpl = info.get("chat_template") or ""
        with open(ruta_modelfile, "w", encoding="utf-8") as f:
            f.write(f"# Modelfile generado por Prig IDE para respaldo de {repo_id}\n")
            f.write(f"FROM ./{principal_gguf}\n\n")
            if chat_tmpl and len(chat_tmpl) < 4000:
                f.write(f'TEMPLATE """{chat_tmpl}"""\n\n')
            f.write(f"# Respaldo local completo preservado offline\n")
            
    fijar(completado=total_bytes, velocidad=None, restante_s=None,
          fase=f"Respaldo completo guardado en {os.path.relpath(dest_abs, ws)}")
          
    return {
        "ok": True,
        "repo_id": repo_id,
        "carpeta": dest_abs,
        "carpeta_relativa": os.path.relpath(dest_abs, ws),
        "total_archivos": total_archivos,
        "total_bytes": total_bytes,
        "manifiesto": ruta_manifest
    }
