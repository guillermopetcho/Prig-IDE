#!/usr/bin/env python3
"""
Trabajador de extracción de Prig. Portable y autónomo.

Corre donde haya GPU: Kaggle, Colab, una máquina alquilada o tu propio equipo.
No importa nada de Prig — solo necesita `extraction_schema.py` a su lado.

    ENTRADA   chunks.jsonl + manifest.json  (los produce Prig en local)
    SALIDA    <libro>.prigpack              (uno por libro, para descargar)

Motores, en orden de preferencia:
    1. vLLM            por lotes, el rápido; es el que justifica usar una GPU externa
    2. transformers    respaldo si vLLM no está disponible
    3. OpenAI/Ollama   respaldo por HTTP, para probar en local sin tocar nada

Funciona sin internet siempre que el modelo esté en disco (subido como dataset).

Uso típico en Kaggle con 2×T4:

    python prig_extract.py \
        --input  /kaggle/input/mis-libros \
        --model  /kaggle/input/qwen25-14b-awq \
        --output /kaggle/working/packs \
        --engine vllm --tensor-parallel 2 --quantization awq --batch 32
"""

import os
import re
import io
import sys
import json
import time
import zipfile
import hashlib
import argparse
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Iterable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extraction_schema import (  # noqa: E402
    SCHEMA_VERSION, SYSTEM_PROMPT, USER_TEMPLATE, CLAIM_TYPES, RELATION_TYPES, DIFFICULTY,
)
from domains import DOMAINS, CODE_LANGUAGES  # noqa: E402

WORKER_VERSION = "1.0.0"


# ===========================================================================
# Utilidades
# ===========================================================================

def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def normalizar(texto: str) -> str:
    """ Para comparar citas: sin acentos raros, espacios colapsados, minúsculas.

    Un modelo cambia comillas tipográficas por rectas o mete dobles espacios; eso no
    es una alucinación y no debe invalidar una cita correcta.
    """
    t = unicodedata.normalize("NFKC", texto or "")
    t = t.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    t = t.replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", t).strip().lower()


def sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def extraer_json(bruto: str) -> Optional[dict]:
    """ Primer objeto JSON completo de la respuesta, tolerando markdown alrededor """
    if not bruto:
        return None
    inicio = bruto.find("{")
    if inicio < 0:
        return None
    profundidad, en_cadena, escape = 0, False, False
    for i in range(inicio, len(bruto)):
        c = bruto[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            en_cadena = not en_cadena
            continue
        if en_cadena:
            continue
        if c == "{":
            profundidad += 1
        elif c == "}":
            profundidad -= 1
            if profundidad == 0:
                try:
                    return json.loads(bruto[inicio:i + 1])
                except Exception:
                    return None
    return None


# ===========================================================================
# Motores de inferencia
# ===========================================================================

class MotorVLLM:
    nombre = "vllm"

    def __init__(self, modelo: str, tp: int = 1, quant: Optional[str] = None,
                 max_len: int = 8192, gpu_util: float = 0.90):
        from vllm import LLM, SamplingParams
        log(f"Cargando {modelo} con vLLM (tp={tp}, quant={quant})…")
        kwargs = dict(model=modelo, tensor_parallel_size=tp,
                      max_model_len=max_len, gpu_memory_utilization=gpu_util,
                      trust_remote_code=True,
                      # El prompt de sistema es ~440 tokens idénticos en cada
                      # fragmento: cachear el prefijo ahorra casi la mitad de la
                      # entrada a lo largo de un trabajo de decenas de miles.
                      enable_prefix_caching=True)
        if quant:
            kwargs["quantization"] = quant
        # La T4 es Turing: no tiene bfloat16, así que se fuerza fp16
        kwargs["dtype"] = "half"
        self.llm = LLM(**kwargs)
        self.SamplingParams = SamplingParams
        self.tokenizer = self.llm.get_tokenizer()

    def generar(self, prompts: List[str], max_tokens: int = 1400) -> List[str]:
        chats = []
        for p in prompts:
            mensajes = [{"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": p}]
            try:
                chats.append(self.tokenizer.apply_chat_template(
                    mensajes, tokenize=False, add_generation_prompt=True))
            except Exception:
                chats.append(f"{SYSTEM_PROMPT}\n\n{p}\n")
        params = self.SamplingParams(temperature=0.1, top_p=0.9, max_tokens=max_tokens)
        salidas = self.llm.generate(chats, params)
        return [s.outputs[0].text for s in salidas]


class MotorTransformers:
    nombre = "transformers"

    def __init__(self, modelo: str, max_len: int = 8192, **_):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        log(f"Cargando {modelo} con transformers…")
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(modelo, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            modelo, torch_dtype=torch.float16, device_map="auto", trust_remote_code=True)
        self.model.eval()
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        self.tokenizer.padding_side = "left"

    def generar(self, prompts: List[str], max_tokens: int = 1400) -> List[str]:
        textos = []
        for p in prompts:
            mensajes = [{"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": p}]
            try:
                textos.append(self.tokenizer.apply_chat_template(
                    mensajes, tokenize=False, add_generation_prompt=True))
            except Exception:
                textos.append(f"{SYSTEM_PROMPT}\n\n{p}\n")
        lote = self.tokenizer(textos, return_tensors="pt", padding=True,
                              truncation=True, max_length=7000).to(self.model.device)
        with self.torch.no_grad():
            salida = self.model.generate(**lote, max_new_tokens=max_tokens,
                                         temperature=0.1, do_sample=False,
                                         pad_token_id=self.tokenizer.pad_token_id)
        largo = lote["input_ids"].shape[1]
        return [self.tokenizer.decode(s[largo:], skip_special_tokens=True) for s in salida]


class MotorOllama:
    """ Ollama por su API nativa. Es el motor para correr en tu propia máquina.

    Tres diferencias con el respaldo genérico por HTTP, y las tres se notan:

      · `format: "json"` obliga a la salida a ser JSON válido. Medido sobre un
        fragmento real de libro con qwen2.5-coder:7b, la tasa de citas verificadas
        pasó de 50 % a 80 % y las afirmaciones útiles de 2 a 4. Sin cambiar de
        modelo: el cuello de botella era la disciplina de formato, no el
        conocimiento.
      · `keep_alive` mantiene el modelo cargado entre lotes. Sin esto Ollama lo
        descarga tras unos minutos y cada lote paga de nuevo la carga desde disco.
      · Peticiones en paralelo. Ollama atiende varias a la vez si la VRAM da; con
        un 7B en Q4 (4,7 GB) y contexto de 4096 caben dos rangos de caché KV en
        6 GB, y el rendimiento sube sin coste de memoria apreciable.
    """
    nombre = "ollama"

    def __init__(self, modelo: str, base_url: str = "http://localhost:11434",
                 paralelo: int = 2, num_ctx: int = 4096,
                 keep_alive: str = "30m", **_):
        import requests
        self.requests = requests
        self.modelo = modelo
        self.base = base_url.rstrip("/").removesuffix("/v1")
        self.paralelo = max(1, paralelo)
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive

        try:
            r = self.requests.get(f"{self.base}/api/tags", timeout=10)
            disponibles = [m["name"] for m in r.json().get("models", [])]
        except Exception as err:
            raise RuntimeError(
                f"Ollama no responde en {self.base}. Arráncalo con 'ollama serve'. ({err})")
        if modelo not in disponibles:
            raise RuntimeError(f"El modelo '{modelo}' no está en Ollama. "
                               f"Disponibles: {', '.join(disponibles) or 'ninguno'}. "
                               f"Descárgalo con: ollama pull {modelo}")
        log(f"Ollama en {self.base} · {modelo} · {self.paralelo} en paralelo "
            f"· contexto {num_ctx}")

    def _una(self, prompt: str, max_tokens: int) -> str:
        cuerpo = {
            "model": self.modelo, "stream": False, "keep_alive": self.keep_alive,
            "format": "json",
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": prompt}],
            "options": {"temperature": 0.1, "top_p": 0.9,
                        "num_ctx": self.num_ctx, "num_predict": max_tokens},
        }
        for intento in (1, 2):
            try:
                r = self.requests.post(f"{self.base}/api/chat", json=cuerpo, timeout=900)
                r.raise_for_status()
                return r.json()["message"]["content"]
            except Exception as err:
                if intento == 2:
                    log(f"  ⚠️ fallo de Ollama: {err}")
                    return ""
                time.sleep(3)
        return ""

    def generar(self, prompts: List[str], max_tokens: int = 1400) -> List[str]:
        if self.paralelo == 1:
            return [self._una(p, max_tokens) for p in prompts]
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=self.paralelo) as pool:
            return list(pool.map(lambda p: self._una(p, max_tokens), prompts))


class MotorHTTP:
    """ Respaldo por HTTP contra Ollama o cualquier API compatible con OpenAI.

    No aprovecha el lote, así que sirve para probar el trabajador en local antes de
    gastar cuota de GPU, no para procesar cien libros.
    """
    nombre = "http"

    def __init__(self, modelo: str, base_url: str = "http://localhost:11434/v1", **_):
        import requests
        self.requests = requests
        self.modelo = modelo
        self.base_url = base_url.rstrip("/")

    def generar(self, prompts: List[str], max_tokens: int = 1400) -> List[str]:
        salidas = []
        for p in prompts:
            try:
                r = self.requests.post(
                    f"{self.base_url}/chat/completions",
                    json={"model": self.modelo, "temperature": 0.1,
                          "max_tokens": max_tokens,
                          "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                       {"role": "user", "content": p}]},
                    timeout=300)
                salidas.append(r.json()["choices"][0]["message"]["content"])
            except Exception as err:
                log(f"  ⚠️ fallo HTTP: {err}")
                salidas.append("")
        return salidas


def temperatura_gpu() -> Optional[int]:
    """ Grados de la GPU, o None si no hay forma de saberlo """
    try:
        import subprocess
        r = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu",
                            "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=5)
        return int(r.stdout.strip().splitlines()[0])
    except Exception:
        return None


def respirar(args):
    """ Pausa entre lotes para que la máquina no se ahogue.

    Una corrida local son horas de GPU al 100 %. En un portátil eso acaba en
    throttling térmico, que ralentiza igual que una pausa pero sin avisar y
    castigando el equipo. Mejor decidir tú cuándo parar.
    """
    if args.temp_max:
        for _ in range(60):                      # como mucho 10 minutos esperando
            t = temperatura_gpu()
            if t is None:
                log("  (no se puede leer la temperatura; se ignora --temp-max)")
                break
            if t <= args.temp_max - 5:
                break
            log(f"  GPU a {t}°C, esperando a que baje de {args.temp_max - 5}°C…")
            time.sleep(10)
    if args.pausa:
        time.sleep(args.pausa)


def crear_motor(args) -> Any:
    orden = [args.engine] if args.engine != "auto" else ["vllm", "transformers", "ollama", "http"]
    ultimo = None
    for nombre in orden:
        try:
            if nombre == "vllm":
                return MotorVLLM(args.model, tp=args.tensor_parallel,
                                 quant=args.quantization, max_len=args.max_len,
                                 gpu_util=args.gpu_util)
            if nombre == "transformers":
                return MotorTransformers(args.model, max_len=args.max_len)
            if nombre == "ollama":
                return MotorOllama(args.model, base_url=args.base_url,
                                   paralelo=args.paralelo, num_ctx=args.num_ctx,
                                   keep_alive=args.keep_alive)
            if nombre == "http":
                return MotorHTTP(args.model, base_url=args.base_url)
        except Exception as err:
            ultimo = err
            log(f"  motor '{nombre}' no disponible: {err}")
    raise RuntimeError(f"Ningún motor de inferencia disponible. Último error: {ultimo}")


# ===========================================================================
# Verificación
# ===========================================================================

def verificar_cita(cita: str, texto_fragmento: str, minimo: int = 12) -> bool:
    """ ¿La cita aparece de verdad en el fragmento?

    Es la defensa principal contra alucinaciones y cuesta prácticamente nada.
    Una cita muy corta no prueba nada, así que se exige un mínimo de longitud.
    """
    if not cita or len(cita.strip()) < minimo:
        return False
    return normalizar(cita) in normalizar(texto_fragmento)


def limpiar_extraccion(datos: dict, fragmento: dict) -> Dict[str, Any]:
    """ Descarta lo que no cuadra y devuelve el resultado con sus contadores.

    Lo rechazado se GUARDA, no solo se cuenta. Cuesta lo mismo y sirve para dos
    cosas: que la pasada de reparación ataque exactamente los fragmentos que
    fallaron en lugar de releer el libro entero, y que puedas comparar modelos
    sobre tus propios libros en vez de fiarte de listas de referencia ajenas.
    """
    texto = fragmento["text"]
    fuera = {"claims": 0, "relations": 0, "symbols": 0}
    rechazados: List[Dict[str, Any]] = []

    claims = []
    for c in datos.get("claims", []) or []:
        if not isinstance(c, dict):
            continue
        tipo = str(c.get("type", "")).upper()
        if tipo not in CLAIM_TYPES:
            tipo = "DEFINITION"
        if not verificar_cita(c.get("quote", ""), texto):
            fuera["claims"] += 1
            cita = str(c.get("quote", ""))
            rechazados.append({
                "que": "claim", "type": tipo, "text": str(c.get("text", ""))[:300],
                "quote": cita[:300],
                "motivo": "cita_corta" if len(cita.strip()) < 12 else "cita_no_literal",
            })
            continue
        lang = str(c.get("code_language", "none")).lower().strip()
        puentes = [str(b).lower().strip() for b in (c.get("bridges_to") or [])]
        claims.append({
            "type": tipo,
            "text": str(c.get("text", "")).strip(),
            "quote": c.get("quote", ""),
            "concepts": [str(x) for x in (c.get("concepts") or [])],
            "confidence": float(c.get("confidence", 0.7) or 0.7),
            "code_language": lang if lang in CODE_LANGUAGES else "none",
            "latex": str(c.get("latex", "")).strip(),
            # Solo se aceptan nombres de dominio reales: el modelo inventa etiquetas
            "bridges_to": [b for b in puentes if b in DOMAINS],
        })

    relations = []
    for r in datos.get("relations", []) or []:
        if not isinstance(r, dict) or not r.get("source") or not r.get("target"):
            continue
        if not verificar_cita(r.get("quote", ""), texto):
            fuera["relations"] += 1
            rechazados.append({"que": "relation", "source": str(r.get("source", ""))[:120],
                               "target": str(r.get("target", ""))[:120],
                               "quote": str(r.get("quote", ""))[:300],
                               "motivo": "cita_no_literal"})
            continue
        tipo = str(r.get("type", "")).upper()
        relations.append({
            "source": str(r["source"]).strip(),
            "target": str(r["target"]).strip(),
            "type": tipo if tipo in RELATION_TYPES else "REQUIRES",
            "quote": r["quote"],
        })

    symbols = []
    for s in datos.get("symbols", []) or []:
        if not isinstance(s, dict) or not s.get("symbol"):
            continue
        if not verificar_cita(s.get("quote", ""), texto, minimo=8):
            fuera["symbols"] += 1
            rechazados.append({"que": "symbol", "symbol": str(s.get("symbol", ""))[:40],
                               "quote": str(s.get("quote", ""))[:300],
                               "motivo": "cita_no_literal"})
            continue
        symbols.append({"symbol": str(s["symbol"]).strip(),
                        "meaning": str(s.get("meaning", "")).strip(),
                        "quote": s["quote"]})

    conceptos = []
    for c in datos.get("concepts", []) or []:
        if isinstance(c, str):
            c = {"name": c}
        if not isinstance(c, dict) or not c.get("name"):
            continue
        otros = [str(d).lower().strip() for d in (c.get("also_known_in") or [])]
        conceptos.append({
            "name": str(c["name"]).strip(),
            "aliases": [str(a).strip() for a in (c.get("aliases") or []) if str(a).strip()],
            "is_defined_here": bool(c.get("is_defined_here", False)),
            "also_known_in": [d for d in otros if d in DOMAINS],
        })

    dif = str(datos.get("difficulty", "INTERMEDIO")).upper()
    return {
        "summary": str(datos.get("summary", "")).strip(),
        "difficulty": dif if dif in DIFFICULTY else "INTERMEDIO",
        "keywords": [str(k).strip() for k in (datos.get("keywords") or []) if str(k).strip()],
        "concepts": conceptos,
        "claims": claims,
        "relations": relations,
        "symbols": symbols,
        "figures": [f for f in (datos.get("figures") or []) if isinstance(f, dict) and f.get("label")],
        "questions": [str(q).strip() for q in (datos.get("questions") or []) if str(q).strip()],
        "_descartados": fuera,
        "_rechazados": rechazados,
    }


# ===========================================================================
# Proceso principal
# ===========================================================================

def leer_fragmentos(carpeta: str) -> List[dict]:
    ruta = os.path.join(carpeta, "chunks.jsonl")
    if not os.path.isfile(ruta):
        # En un cuaderno, el fallo casi siempre es que el dataset quedó un nivel
        # más abajo. Decirlo ahorra buscar a ciegas entre carpetas de /kaggle/input.
        pista = ""
        if os.path.isdir(carpeta):
            for raiz, _, ficheros in os.walk(carpeta):
                if "chunks.jsonl" in ficheros:
                    pista = f"\n  Lo he encontrado aquí: --input {raiz}"
                    break
            else:
                pista = f"\n  Contenido de {carpeta}: {sorted(os.listdir(carpeta))[:8]}"
        else:
            pista = "\n  Esa carpeta no existe. Revisa el nombre del dataset."
        raise SystemExit(f"No se encontró chunks.jsonl en {carpeta}{pista}")
    with open(ruta, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def por_lotes(items: List[Any], n: int) -> Iterable[List[Any]]:
    for i in range(0, len(items), n):
        yield items[i:i + n]


def fijar_gpu(args):
    """ Asigna una GPU concreta a este proceso.

    Con dos T4 sueltas se lanzan dos procesos, uno por GPU, y cada uno se lleva la
    mitad de los fragmentos. Sin esto ambos intentan ocupar la GPU 0 y el segundo
    muere sin memoria. Tiene que ejecutarse ANTES de importar torch o vLLM, porque
    la lista de dispositivos se lee una sola vez al cargarlos.
    """
    if args.gpu is None:
        return
    os.environ["CUDA_VISIBLE_DEVICES"] = str(args.gpu)
    log(f"Este proceso usa únicamente la GPU {args.gpu}")


def ejecutar_lotes(args, motor, pendientes: List[dict], ruta_parcial: str):
    """ Procesa una lista de fragmentos y va dejando el resultado en el parcial """
    log(f"Motor: {motor.nombre} · lote de {args.batch}")
    t0 = time.time()
    procesados = 0
    extra = ("\nOmite los campos \"questions\" y \"figures\": devuélvelos vacíos."
             if args.profile == "core" else "")

    with open(ruta_parcial, "a", encoding="utf-8") as parcial:
        for numero, lote in enumerate(por_lotes(pendientes, args.batch)):
            if numero:
                respirar(args)
            prompts = [USER_TEMPLATE.format(
                book_title=c.get("book_title", ""),
                domain=DOMAINS.get(c.get("domain", ""), {}).get("name", "General"),
                page=c.get("page", "?"),
                section_hint=(f"Sección: {c['section_id']}" if c.get("section_id") else ""),
                text=c["text"][:args.max_chars],
            ) + extra for c in lote]

            try:
                respuestas = motor.generar(prompts, max_tokens=args.max_new_tokens)
            except Exception as err:
                log(f"  ⚠️ el lote falló ({err}); se salta")
                respuestas = [""] * len(lote)

            verificadas = rechazadas = 0
            for frag, bruto in zip(lote, respuestas):
                datos = extraer_json(bruto)
                if datos is None:
                    registro = {"chunk_id": frag["chunk_id"], "source_id": frag["source_id"],
                                "page": frag.get("page"), "ok": False, "error": "json_invalido"}
                else:
                    limpio = limpiar_extraccion(datos, frag)
                    registro = {"chunk_id": frag["chunk_id"], "source_id": frag["source_id"],
                                "page": frag.get("page"), "ok": True, **limpio}
                    verificadas += len(limpio["claims"])
                    rechazadas += limpio["_descartados"]["claims"]
                parcial.write(json.dumps(registro, ensure_ascii=False) + "\n")

            parcial.flush()
            procesados += len(lote)
            transcurrido = max(0.001, time.time() - t0)
            ritmo = procesados / transcurrido
            restantes = (len(pendientes) - procesados) / max(0.001, ritmo)
            tasa = verificadas / max(1, verificadas + rechazadas) * 100
            grados = temperatura_gpu() if args.temp_max else None
            log(f"  {procesados}/{len(pendientes)} · {ritmo * 60:.1f} frag/min "
                f"· citas {tasa:.0f}% · quedan ~{restantes / 60:.0f} min"
                + (f" · {grados}°C" if grados else ""))


def fragmentos_a_reparar(ruta_parcial: str, umbral: float) -> Dict[str, str]:
    """ Qué fragmentos merecen una segunda lectura, y por qué.

    No se relee el libro entero: se releen los fragmentos donde la primera lectura
    falló de forma comprobable. Sobre lo medido, eso ronda el 20 %, así que una
    reparación cuesta una quinta parte de una pasada completa.
    """
    motivos: Dict[str, str] = {}
    if not os.path.isfile(ruta_parcial):
        return motivos
    with open(ruta_parcial, encoding="utf-8") as f:
        for linea in f:
            try:
                r = json.loads(linea)
            except Exception:
                continue
            cid = r.get("chunk_id")
            if not cid:
                continue
            if not r.get("ok"):
                motivos[cid] = "el modelo no devolvió JSON válido"
                continue
            buenas = len(r.get("claims") or [])
            malas = (r.get("_descartados") or {}).get("claims", 0)
            if buenas == 0 and malas == 0:
                motivos[cid] = "no extrajo nada"
            elif buenas == 0:
                motivos[cid] = ("su única afirmación citaba mal" if malas == 1
                                else f"sus {malas} afirmaciones citaban mal")
            elif malas and buenas / (buenas + malas) < umbral:
                motivos[cid] = (f"solo {buenas / (buenas + malas) * 100:.0f}% de citas "
                                f"verificadas")
            else:
                motivos.pop(cid, None)      # una lectura posterior ya lo arregló
    return motivos


def procesar(args):
    manifest_in = {}
    ruta_manifest = os.path.join(args.input, "manifest.json")
    if os.path.isfile(ruta_manifest):
        with open(ruta_manifest, encoding="utf-8") as f:
            manifest_in = json.load(f)

    fragmentos = leer_fragmentos(args.input)
    # Se guarda la lista completa: al empaquetar hay que saber cuántos fragmentos
    # tenía cada libro de verdad, no cuántos tocaron a este proceso.
    todos_los_fragmentos = list(fragmentos)

    if args.pack_only:
        log("Solo empaquetar: se unen los parciales sin ejecutar el modelo.")
        empaquetar(args, manifest_in, todos_los_fragmentos)
        return

    fijar_gpu(args)

    if args.shard:
        try:
            i, n = (int(x) for x in args.shard.split("/"))
        except Exception:
            raise SystemExit("--shard debe tener la forma i/N, por ejemplo 0/2")
        # Reparto por posición: determinista y sin solapes entre procesos
        fragmentos = [c for k, c in enumerate(fragmentos) if k % n == i]
        log(f"Reparto {i}/{n}: {len(fragmentos)} fragmentos para este proceso")

    if args.limit:
        fragmentos = fragmentos[:args.limit]

    libros = sorted({c["source_id"] for c in fragmentos})
    log(f"{len(fragmentos)} fragmentos · {len(libros)} libro(s)")

    os.makedirs(args.output, exist_ok=True)
    sufijo = f"_{args.shard.replace('/', '-')}" if args.shard else ""
    ruta_parcial = os.path.join(args.output, f"_parcial{sufijo}.jsonl")

    # Reanudable: si la sesión murió, no se repite lo ya hecho
    hechos = set()
    if os.path.isfile(ruta_parcial) and not args.restart:
        with open(ruta_parcial, encoding="utf-8") as f:
            for l in f:
                try:
                    hechos.add(json.loads(l)["chunk_id"])
                except Exception:
                    pass
        log(f"Reanudando: {len(hechos)} fragmentos ya procesados")

    if args.reparar:
        motivos = fragmentos_a_reparar(ruta_parcial, args.umbral_citas)
        pendientes = [c for c in fragmentos if c["chunk_id"] in motivos]
        if not pendientes:
            log("Nada que reparar: todos los fragmentos pasaron la verificación.")
            empaquetar(args, manifest_in, todos_los_fragmentos)
            return
        log(f"Reparación: {len(pendientes)} de {len(fragmentos)} fragmentos "
            f"({len(pendientes) / max(1, len(fragmentos)) * 100:.0f}%)")
        for cid, motivo in list(motivos.items())[:5]:
            log(f"    {cid[:26]}  {motivo}")
        if len(motivos) > 5:
            log(f"    … y {len(motivos) - 5} más")
        motor = crear_motor(args)
        ejecutar_lotes(args, motor, pendientes, ruta_parcial)
        empaquetar(args, manifest_in, todos_los_fragmentos)
        return

    pendientes = [c for c in fragmentos if c["chunk_id"] not in hechos]
    if not pendientes:
        log("No queda nada pendiente.")
    elif args.por_libro:
        # Un libro completo antes de empezar el siguiente. En una corrida local de
        # varias noches esto importa: puedes parar después de cualquier libro y
        # tener su .prigpack ya terminado, en vez de un avance repartido entre
        # todos que no sirve para nada hasta el final.
        motor = crear_motor(args)
        orden = []
        for c in pendientes:
            if c["source_id"] not in orden:
                orden.append(c["source_id"])
        titulos = {c["source_id"]: c.get("book_title", c["source_id"]) for c in fragmentos}
        for n, sid in enumerate(orden, 1):
            del_libro = [c for c in pendientes if c["source_id"] == sid]
            log("")
            log(f"═══ LIBRO {n}/{len(orden)} · {titulos.get(sid, sid)[:52]} "
                f"· {len(del_libro)} fragmentos ═══")
            ejecutar_lotes(args, motor, del_libro, ruta_parcial)
            if not args.shard:
                empaquetar(args, manifest_in, todos_los_fragmentos, solo=sid)
    else:
        motor = crear_motor(args)
        ejecutar_lotes(args, motor, pendientes, ruta_parcial)

    if args.shard and not args.pack:
        log("")
        log("Reparto terminado. NO se empaqueta todavía: este proceso solo tiene su")
        log("mitad de los fragmentos y el paquete saldría incompleto sin avisar.")
        log("Cuando hayan acabado todos los repartos, ejecuta:")
        log(f"  python prig_extract.py --input {args.input} --output {args.output} "
            f"--model {args.model} --pack-only")
        return

    empaquetar(args, manifest_in, todos_los_fragmentos)


def _puntuar(registro: dict) -> tuple:
    """ Cómo de buena es una lectura de un fragmento. Más verificado, mejor. """
    if not registro.get("ok"):
        return (0, 0, 0)
    return (len(registro.get("claims") or []),
            len(registro.get("relations") or []),
            len(registro.get("symbols") or []))


def combinar(lecturas: List[dict], unir: bool = False) -> dict:
    """ Varias lecturas del mismo fragmento, en una sola.

    Por defecto se conserva la mejor, que es lo que quieres tras una pasada de
    reparación: la segunda lectura sustituye a la primera solo si mejoró.

    Con `unir` se juntan los hallazgos de todas, quitando duplicados por la cita.
    Esto es lo que hace útil leer un libro con dos modelos distintos: el fallo que
    la verificación NO puede detectar es lo que el modelo se dejó, y dos lecturas
    independientes se dejan cosas distintas. No hace falta que dialoguen.
    """
    if len(lecturas) == 1:
        return lecturas[0]
    ordenadas = sorted(lecturas, key=_puntuar, reverse=True)
    mejor = ordenadas[0]
    if not unir or not mejor.get("ok"):
        return mejor

    salida = dict(mejor)
    for campo, clave in (("claims", "quote"), ("relations", "quote"),
                         ("symbols", "quote"), ("concepts", "name")):
        vistos, juntos = set(), []
        for lectura in ordenadas:
            if not lectura.get("ok"):
                continue
            for item in lectura.get(campo) or []:
                firma = normalizar(str(item.get(clave, "")))[:160]
                if not firma or firma in vistos:
                    continue
                vistos.add(firma)
                juntos.append(item)
        salida[campo] = juntos
    salida["_lecturas"] = len(lecturas)
    return salida


def empaquetar(args, manifest_in: dict, fragmentos: List[dict],
               solo: Optional[str] = None):
    """ Agrupa lo extraído por libro y escribe un .prigpack por cada uno.

    Con `solo` se empaqueta un único libro, que es lo que hace el modo libro a
    libro cada vez que termina uno.
    """
    # Se juntan todos los parciales: si repartiste entre dos GPUs, cada una dejó
    # el suyo y el paquete debe contener el libro entero.
    # Solo valen los fragmentos de ESTE trabajo: en la misma carpeta de salida
    # pueden quedar parciales de una corrida anterior con otros libros, y
    # empaquetarlos mezclaría dos trabajos en un mismo .prigpack.
    del_trabajo = {c["chunk_id"] for c in fragmentos}
    por_id: Dict[str, List[dict]] = {}
    ajenos = 0
    for nombre in sorted(os.listdir(args.output)):
        if not (nombre.startswith("_parcial") and nombre.endswith(".jsonl")):
            continue
        with open(os.path.join(args.output, nombre), encoding="utf-8") as f:
            for l in f:
                try:
                    r = json.loads(l)
                except Exception:
                    continue
                cid = r.get("chunk_id")
                if not cid:
                    continue
                if cid not in del_trabajo:
                    ajenos += 1
                    continue
                por_id.setdefault(cid, []).append(r)

    # Un fragmento puede aparecer varias veces: lo reprocesó la pasada de
    # reparación, o lo leyó un segundo modelo. Quedarse con el primero
    # descartaría justamente la corrección; hay que combinar.
    registros = [combinar(v, unir=args.unir) for v in por_id.values()]
    repetidos = sum(1 for v in por_id.values() if len(v) > 1)
    if repetidos:
        log(f"  {repetidos} fragmentos con más de una lectura: "
            f"{'unidas' if args.unir else 'se conserva la mejor'}")
    if ajenos:
        log(f"  {ajenos} fragmentos de otro trabajo ignorados "
            f"(quedaron en {args.output} de una corrida anterior)")
    if not registros:
        log("")
        log(f"⚠️  No hay nada que empaquetar: ningún _parcial*.jsonl en {args.output}")
        log("   Si repartiste entre varias GPU, comprueba que apuntaban a esta misma")
        log("   carpeta de salida y que los procesos llegaron a escribir algo.")
        return

    titulos = {c["source_id"]: c.get("book_title", c["source_id"]) for c in fragmentos}
    libros_meta = {b["source_id"]: b for b in manifest_in.get("books", [])}

    outline = {}
    ruta_outline = os.path.join(args.input, "outline.json")
    if os.path.isfile(ruta_outline):
        with open(ruta_outline, encoding="utf-8") as f:
            outline = json.load(f)

    por_libro: Dict[str, List[dict]] = {}
    for r in registros:
        if solo and r["source_id"] != solo:
            continue
        por_libro.setdefault(r["source_id"], []).append(r)

    resumen_global = []
    for source_id, regs in sorted(por_libro.items()):
        claims, concepts, relations, symbols, figures, questions = [], {}, [], [], [], []
        descartados = {"claims": 0, "relations": 0, "symbols": 0}
        fallidos = 0

        for r in regs:
            if not r.get("ok"):
                fallidos += 1
                continue
            for k in descartados:
                descartados[k] += (r.get("_descartados") or {}).get(k, 0)

            for c in r.get("claims", []):
                claims.append({**c, "claim_id": f"clm_{sha256_texto(c['quote'])[:12]}",
                               "chunk_id": r["chunk_id"], "page": r.get("page")})
            for c in r.get("concepts", []):
                clave = c["name"].strip().lower()
                entrada = concepts.setdefault(clave, {"name": c["name"], "aliases": set(),
                                                      "pages": set(), "defined_in": [],
                                                      "also_known_in": set()})
                entrada["aliases"].update(a.lower() for a in c.get("aliases", []))
                entrada["also_known_in"].update(c.get("also_known_in", []))
                if r.get("page"):
                    entrada["pages"].add(r["page"])
                if c.get("is_defined_here"):
                    entrada["defined_in"].append(r.get("page"))
            for rel in r.get("relations", []):
                relations.append({**rel, "chunk_id": r["chunk_id"], "page": r.get("page")})
            for s in r.get("symbols", []):
                symbols.append({**s, "page": r.get("page")})
            for fg in r.get("figures", []):
                figures.append({**fg, "page": r.get("page")})
            questions.extend(r.get("questions", []))

        conceptos_lista = [{
            "concept_id": f"conc_{sha256_texto(k)[:12]}",
            "name": v["name"],
            "aliases": sorted(v["aliases"]),
            "pages": sorted(p for p in v["pages"] if p),
            "defined_in_pages": sorted(p for p in v["defined_in"] if p),
            "also_known_in": sorted(v["also_known_in"]),
            "mentions": len(v["pages"]),
        } for k, v in concepts.items()]

        meta = libros_meta.get(source_id, {})
        # Cuántos fragmentos tenía este libro en el trabajo original. Compararlo con
        # los procesados es lo único que delata un paquete a medias: uno que solo
        # trae la mitad del libro declara con toda coherencia las afirmaciones que
        # tiene, así que sin esta cifra nada lo distingue de uno completo.
        esperados = meta.get("chunks") or sum(
            1 for c in fragmentos if c.get("source_id") == source_id)
        completo = len(regs) >= esperados
        if not completo:
            log(f"  ⚠️  {titulos.get(source_id, source_id)[:44]}: solo {len(regs)} de "
                f"{esperados} fragmentos. ¿Falta algún reparto por terminar?")
        pack_manifest = {
            "schema_version": SCHEMA_VERSION,
            "worker_version": WORKER_VERSION,
            "source_id": source_id,
            "title": titulos.get(source_id, source_id),
            "domain": meta.get("domain", "machine_learning"),
            "book_sha256": meta.get("sha256"),
            "pages": meta.get("pages"),
            "input_manifest_sha256": manifest_in.get("chunks_sha256"),
            "job_id": manifest_in.get("job_id"),
            "model_used": args.model,
            "quantization": args.quantization or "none",
            "engine": args.engine,
            "created_at": datetime.now().isoformat(),
            "chunks_processed": len(regs),
            "chunks_expected": esperados,
            "complete": completo,
            "chunks_failed": fallidos,
            "claims_verified": len(claims),
            "claims_rejected": descartados["claims"],
            "relations_verified": len(relations),
            "relations_rejected": descartados["relations"],
            "symbols_verified": len(symbols),
            "concepts": len(conceptos_lista),
            "figures": len(figures),
        }

        nombre = re.sub(r"[^A-Za-z0-9_.-]", "_", titulos.get(source_id, source_id))[:60]
        destino = os.path.join(args.output, f"{nombre}.prigpack")

        contenido = {
            "manifest.json": json.dumps(pack_manifest, ensure_ascii=False, indent=2),
            "claims.jsonl": "\n".join(json.dumps(c, ensure_ascii=False) for c in claims),
            "concepts.jsonl": "\n".join(json.dumps(c, ensure_ascii=False) for c in conceptos_lista),
            "relations.jsonl": "\n".join(json.dumps(r, ensure_ascii=False) for r in relations),
            "symbols.jsonl": "\n".join(json.dumps(s, ensure_ascii=False) for s in symbols),
            "figures.jsonl": "\n".join(json.dumps(f, ensure_ascii=False) for f in figures),
            "questions.json": json.dumps(sorted(set(questions)), ensure_ascii=False, indent=2),
            "outline.json": json.dumps(outline.get(source_id, {}), ensure_ascii=False, indent=2),
        }
        contenido["checksums.json"] = json.dumps(
            {k: sha256_texto(v) for k, v in contenido.items()}, ensure_ascii=False, indent=2)

        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
            for nombre_archivo, datos in contenido.items():
                z.writestr(nombre_archivo, datos)

        tasa = (len(claims) / max(1, len(claims) + descartados["claims"])) * 100
        log(f"  📦 {os.path.basename(destino):48} {len(claims):5} afirmaciones "
            f"· {len(conceptos_lista):4} conceptos · {tasa:.0f}% verificadas")
        resumen_global.append(pack_manifest)

    if not solo:
        with open(os.path.join(args.output, "job_summary.json"), "w", encoding="utf-8") as f:
            json.dump({"job_id": manifest_in.get("job_id"),
                       "created_at": datetime.now().isoformat(),
                       "packs": resumen_global}, f, ensure_ascii=False, indent=2)

    incompletos = [p for p in resumen_global if not p.get("complete", True)]
    if incompletos:
        log("")
        log(f"⚠️  {len(incompletos)} paquete(s) INCOMPLETOS. No los importes todavía:")
        for p in incompletos:
            log(f"     {p['title'][:46]:48} {p['chunks_processed']}/{p['chunks_expected']} fragmentos")

    if solo:
        # Al empaquetar un libro suelto (modo libro a libro) no toca el resumen
        # global: se imprime al final, cuando están todos.
        return

    total_c = sum(p["claims_verified"] for p in resumen_global)
    total_r = sum(p["claims_rejected"] for p in resumen_global)
    log("")
    log(f"LISTO · {len(resumen_global)} paquete(s) · {total_c} afirmaciones verificadas")
    if total_c + total_r:
        tasa = total_c / (total_c + total_r) * 100
        log(f"Tasa de verificación de citas: {tasa:.1f}%")
        if tasa < 60:
            log("  Por debajo del 60%: cambia de modelo, o prueba --reparar con otro")
        elif tasa < 85:
            log("  Aceptable. Con --reparar recuperas parte de lo descartado")


def main():
    p = argparse.ArgumentParser(description="Extractor de conocimiento de Prig")
    p.add_argument("--input", required=True, help="Carpeta con chunks.jsonl y manifest.json")
    p.add_argument("--output", default="./packs", help="Dónde dejar los .prigpack")
    p.add_argument("--model", required=True, help="Ruta local del modelo o id de HuggingFace")
    p.add_argument("--engine", default="auto",
                   choices=["auto", "vllm", "transformers", "ollama", "http"])
    p.add_argument("--base-url", default="http://localhost:11434/v1", help="Solo para el motor http")
    p.add_argument("--tensor-parallel", type=int, default=1, help="2 para las dos T4 de Kaggle")
    p.add_argument("--quantization", default=None, help="awq, gptq… según el modelo")
    p.add_argument("--batch", type=int, default=16, help="Fragmentos por lote")
    # Un fragmento usa ~950 de entrada + ~700 de salida. Con 8192 la caché KV se
    # come la VRAM y vLLM reduce la concurrencia; con 4096 caben el triple de
    # secuencias a la vez, que es de donde sale el rendimiento.
    p.add_argument("--max-len", type=int, default=4096)
    p.add_argument("--max-chars", type=int, default=6000, help="Recorte del fragmento")
    p.add_argument("--max-new-tokens", type=int, default=1400)
    p.add_argument("--gpu-util", type=float, default=0.90)
    p.add_argument("--limit", type=int, default=0, help="Procesar solo N fragmentos (sondeo)")
    p.add_argument("--shard", default=None, metavar="i/N",
                   help="Procesar solo la parte i de N. Con dos T4 sueltas: "
                        "--shard 0/2 en una y --shard 1/2 en la otra (más rápido que tensor-parallel)")
    p.add_argument("--profile", default="full", choices=["full", "core"],
                   help="core omite preguntas y figuras: ~20%% menos tokens de salida")
    p.add_argument("--restart", action="store_true", help="Ignorar lo ya procesado")
    p.add_argument("--gpu", type=int, default=None, metavar="N",
                   help="Usar solo la GPU N. Con dos T4 sueltas: --gpu 0 en un proceso "
                        "y --gpu 1 en el otro, cada uno con su --shard")
    p.add_argument("--pack-only", action="store_true",
                   help="No ejecutar el modelo: solo unir los parciales y empaquetar. "
                        "Es el paso final cuando el trabajo se repartió entre varias GPU")
    p.add_argument("--pack", action="store_true",
                   help="Empaquetar aunque sea un reparto parcial (para depurar)")

    loc = p.add_argument_group("corrida local (motor ollama)")
    loc.add_argument("--paralelo", type=int, default=2, metavar="N",
                     help="Peticiones simultáneas a Ollama. Con 6 GB y un 7B en Q4 "
                          "caben 2; con más VRAM, súbelo")
    loc.add_argument("--num-ctx", type=int, default=4096,
                     help="Ventana de contexto de Ollama. Debe cubrir el prompt "
                          "(~2000 tokens) más la respuesta")
    loc.add_argument("--keep-alive", default="30m",
                     help="Cuánto mantiene Ollama el modelo cargado entre lotes")
    loc.add_argument("--pausa", type=float, default=0, metavar="SEG",
                     help="Espera entre lotes. En un portátil evita el throttling "
                          "térmico, que ralentiza igual pero sin avisar")
    loc.add_argument("--reparar", action="store_true",
                     help="Releer SOLO los fragmentos cuya primera lectura falló. "
                          "Cambia --model para que los relea otro modelo")
    loc.add_argument("--umbral-citas", type=float, default=0.5, metavar="F",
                     help="Por debajo de esta fracción de citas verificadas, el "
                          "fragmento entra en la reparación (0.5 = la mitad)")
    loc.add_argument("--unir", action="store_true",
                     help="Al empaquetar, JUNTAR los hallazgos de todas las lecturas "
                          "de cada fragmento en vez de quedarse con la mejor. Para "
                          "cuando dos modelos han leído el mismo libro entero")
    loc.add_argument("--por-libro", action="store_true",
                     help="Terminar y empaquetar cada libro antes de empezar el "
                          "siguiente. Recomendado en local: puedes parar entre "
                          "libros y lo hecho ya sirve")
    loc.add_argument("--temp-max", type=int, default=0, metavar="GRADOS",
                     help="Si la GPU pasa de esta temperatura, esperar a que baje "
                          "5 grados antes de seguir (necesita nvidia-smi)")
    args = p.parse_args()

    log(f"Prig extractor v{WORKER_VERSION} · esquema v{SCHEMA_VERSION}")
    procesar(args)


if __name__ == "__main__":
    main()
