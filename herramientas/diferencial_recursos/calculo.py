"""Diferencial de backend/recursos: la versión de Python puro (el commit REFERENCIA, antes de pasar a Rust) contra
la de ahora (Rust por prig_nativo). Las mismas entradas al azar tienen que dar el mismo JSON: orden de claves, int y
float, textos y excepciones incluidos (docs/plan-prig-rust.md, F1).

    .venv/bin/python herramientas/diferencial_recursos/calculo.py [semilla] [vueltas]
"""
import json, os, random, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402,F401
from recursos_viejo import calculadora as cv, ficha as fv, gguf as gv, perfiles as pv  # noqa: E402
from recursos import calculadora as cn, ficha as fn, gguf as gn, perfiles as pn  # noqa: E402

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
R = random.Random(semilla)
fallos, cuentas = [], {}

def j(x):
    return json.dumps(x, ensure_ascii=False)

def igual(nombre, f_viejo, f_nuevo, *args, **kw):
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    try:
        a = ("ok", j(f_viejo(*args, **kw)))
    except Exception as e:
        a = ("error", type(e).__name__ if not isinstance(e, gv.FaltanBytes) else "FaltanBytes", str(e))
    try:
        b = ("ok", j(f_nuevo(*args, **kw)))
    except Exception as e:
        b = ("error", type(e).__name__ if not isinstance(e, gn.FaltanBytes) else "FaltanBytes", str(e))
    if a != b and len(fallos) < 12:
        fallos.append({"funcion": nombre, "args": repr(args)[:600], "viejo": str(a)[:700], "nuevo": str(b)[:700]})
    return a == b

GPUS = list(cv.ANCHO_GPU) + ["NVIDIA GeForce RTX 4050 Laptop GPU", "NVIDIA GeForce RTX 4060 Ti", "Apple M2 Pro",
                             "AMD Radeon RX 7900 XTX", "Intel Arc A770", "", "RTX 4060 Laptop GPU"]

def entorno():
    e = {}
    if R.random() < 0.5: e["OLLAMA_KV_CACHE_TYPE"] = R.choice(["f16", "q8_0", "Q8_0", "q4_0", "", None, "F16"])
    if R.random() < 0.5: e["OLLAMA_NUM_PARALLEL"] = R.choice(["1", "2", "4", "x", " 3 ", "0", "-2", "", None, "2.0", "1_0", 3])
    if R.random() < 0.4: e["OLLAMA_FLASH_ATTENTION"] = R.choice(["1", "true", "TRUE", "yes", "0", "", None, True, 1])
    if R.random() < 0.4: e["OLLAMA_MAX_LOADED_MODELS"] = R.choice(["0", "1", "3", "", "x", None])
    return e

def radiografia():
    gpus = []
    if R.random() < 0.8:
        g = {"fabricante": R.choice(["nvidia", "amd", "apple"]), "nombre": R.choice(GPUS),
             "vram_total_mb": R.choice([0, None, 2048, 4096, 6141, 8188, 12282, 16380, 24564, 6141.0, 1e5, R.uniform(1000, 30000)]),
             "memoria_unificada": R.random() < 0.15, "flash_attention": R.random() < 0.7}
        if R.random() < 0.3:
            g["otros_procesos"] = [{"pid": 1, "proceso": "x", "mb": R.choice([100, 512, 2048, 4000, 300.5])} for _ in range(R.randint(1, 3))]
        if R.random() < 0.05:
            g = {}
        gpus.append(g)
    ram = R.choice([4, 8, 16, 32, 62, 64, 128]) * 1e9
    rad = {"huella": "h", "gpus": gpus, "memoria": {"ram_total": ram, "ram_disponible": ram * R.uniform(0.2, 0.95), "swap_usada": 0},
           "cpu": {"nucleos_fisicos": R.choice([4, 8, 16])}, "ancho_banda_ram_gbps": R.choice([None, 0, 5.0, 10.0, 14.3, 30.0, 80.0]),
           "ollama": {"entorno": entorno()}}
    if R.random() < 0.05: rad.pop("memoria")
    if R.random() < 0.05: rad["ollama"] = None
    return rad

def calibracion():
    if R.random() < 0.4: return None
    c = {}
    for k, gen in (("presupuesto_gpu", lambda: R.uniform(0, 20e9)), ("vram_parcial", lambda: R.uniform(-1e9, 20e9)),
                   ("ancho_gpu", lambda: R.uniform(50, 1000)), ("ancho_cpu", lambda: R.uniform(5, 120)),
                   ("overhead_entero", lambda: R.uniform(-0.5e9, 0.5e9)), ("overhead_parcial", lambda: R.uniform(0, 1e9))):
        if R.random() < 0.5: c[k] = gen()
    return c

BASE = [
    {"nombre": "qwen2.5-coder:7b", "arquitectura": "qwen2", "bytes_peso": 4683087561, "parametros": 7615616512, "parametros_activos": 7615616512, "fraccion_activa": 1.0, "capas": 28, "cabezas_kv": 4, "dim_cabeza": 128, "kv_bytes_token_f16": 57344, "contexto_max": 32768, "es_moe": False, "piensa": False, "embedding": False},
    {"nombre": "qwen3:14b-q4_k_m", "arquitectura": "qwen3", "bytes_peso": 9276198565, "parametros": 14768307200, "parametros_activos": 14768307200, "fraccion_activa": 1.0, "capas": 40, "cabezas_kv": 8, "dim_cabeza": 128, "kv_bytes_token_f16": 163840, "contexto_max": 40960, "es_moe": False, "piensa": True, "embedding": False},
    {"nombre": "qwen3:30b-a3b-q4_k_m", "arquitectura": "qwen3moe", "bytes_peso": 18622563179, "parametros": 30532122624, "parametros_activos": 3353032704, "fraccion_activa": 0.1098, "capas": 48, "cabezas_kv": 4, "dim_cabeza": 128, "kv_bytes_token_f16": 98304, "contexto_max": 40960, "es_moe": True, "piensa": True, "embedding": False},
    {"nombre": "nomic-embed-text", "arquitectura": "nomic-bert", "bytes_peso": 274302450, "parametros": 136727040, "parametros_activos": 136727040, "fraccion_activa": 1.0, "capas": 12, "kv_bytes_token_f16": 0, "contexto_max": 2048, "es_moe": False, "piensa": False, "embedding": True},
]

def ficha():
    f = dict(R.choice(BASE))
    f["nombre"] = f["nombre"] + R.choice(["", ":x", "-b"])
    if R.random() < 0.6:
        escala = R.choice([0.1, 0.3, 0.5, 1, 1.5, 2, 4, 8])
        f["bytes_peso"] = int(f["bytes_peso"] * escala)
        f["parametros"] = int(f["parametros"] * escala)
        f["parametros_activos"] = int(f["parametros_activos"] * escala)
    if R.random() < 0.2: f["capas"] = R.choice([0, None, 1, 80, 28.0])
    if R.random() < 0.2: f["contexto_max"] = R.choice([0, None, 2048, 3000, 4096, 131072, 8192.0])
    if R.random() < 0.2: f["kv_bytes_token_f16"] = R.choice([0, 1024, 57344, 400000, 98304.0])
    if R.random() < 0.15: f["fraccion_activa"] = R.choice([0.05, 0.5, 1, 1.0])
    if R.random() < 0.1: f.pop("fraccion_activa", None)
    if R.random() < 0.1: f["estimada"] = R.choice([True, False, None])
    if R.random() < 0.1: f["piensa"] = not f.get("piensa")
    if R.random() < 0.1: f["embedding"] = R.choice([True, False, 0, None])
    if R.random() < 0.1: f["arquitectura"] = R.choice(["gemma3", "llama4", "Qwen3", "", None, "llama"])
    if R.random() < 0.1: f["es_moe"] = not f.get("es_moe")
    return f

PERF = list(pv.PERFILES)
TIR = ["equilibrado", "calidad", "velocidad", "otro"]

for i in range(N):
    rad, cal = radiografia(), calibracion()
    mv, mn = cv.Maquina(rad, cal), cn.Maquina(rad, cal)
    attrs = lambda m: {k: getattr(m, k) for k in ("hay_gpu", "gpu_nombre", "unificada", "flash_attention", "origen_presupuesto",
                                                  "origen_ancho_gpu", "origen_ancho_cpu", "servidor", "calibrada", "nucleos")}
    nums = lambda m: [float(getattr(m, k)) for k in ("vram_total", "vram_libre", "ram_disponible", "ram_total", "presupuesto_gpu",
                                                      "vram_parcial", "ancho_gpu", "ancho_cpu", "overhead_entero", "overhead_parcial")]
    igual("Maquina.attrs", lambda: attrs(mv), lambda: attrs(mn))
    igual("Maquina.nums", lambda: nums(mv), lambda: nums(mn))
    igual("Maquina.resumen", mv.resumen, mn.resumen)
    f = ficha()
    for _ in range(3):
        ctx, par, kv = R.choice([512, 2048, 3072, 4096, 6144, 8192, 16384, 32768]), R.choice([1, 2, 3]), R.choice(["f16", "q8_0", "q4_0", "x"])
        igual("estimar", lambda *a: cv.estimar(f, mv, *a), lambda *a: cn.estimar(f, mn, *a), ctx, par, kv)
    for perfil in PERF + (["nada"] if R.random() < 0.02 else []):
        t = R.choice(TIR)
        igual("recomendar", lambda: cv.recomendar(f, mv, perfil, t), lambda: cn.recomendar(f, mn, perfil, t))
    fichas = [ficha() for _ in range(R.randint(1, 5))]
    medidas = {x["nombre"]: {"calidad": R.choice([None, 0.0, 0.5, 1.0])} for x in fichas if R.random() < 0.4} or None
    p, t = R.choice(PERF), R.choice(TIR)
    igual("elegir_modelo", lambda: cv.elegir_modelo(fichas, mv, p, t, medidas), lambda: cn.elegir_modelo(fichas, mn, p, t, medidas))
    igual("calidad_esperada", cv.calidad_esperada, cn.calidad_esperada, f)
    e = cv.estimar(f, mv, 4096, R.choice([1, 2, 4]))
    igual("rendimiento", cv.rendimiento, cn.rendimiento, e)
    igual("servidor_efectivo", cv.servidor_efectivo, cn.servidor_efectivo, entorno())
    igual("penalizacion_contexto", cv.penalizacion_contexto, cn.penalizacion_contexto, R.choice([1, 2048, 3000, 4096, 100000, 2048.5]))

# ---------------------------------------------------------------- ficha
def meta_al_azar():
    arch = R.choice(["qwen3", "qwen3moe", "llama", "gemma3", "", None, "bert"])
    m = {"general.architecture": arch}
    a = arch or ""
    def pon(k, v):
        if R.random() < 0.85: m[f"{a}.{k}"] = v
    pon("block_count", R.choice([28, 48, 0, "36", [10, 20], None, 32.7, True]))
    pon("attention.head_count", R.choice([28, 32, 0, [32, 16], "x"]))
    pon("attention.head_count_kv", R.choice([4, 8, 0, [8, 4, 8], [], ["a"], [2, 3.5]]))
    pon("embedding_length", R.choice([3584, 2048, 4096, 0]))
    pon("attention.key_length", R.choice([128, 0, None]))
    pon("attention.value_length", R.choice([128, 0]))
    pon("context_length", R.choice([32768, 40960, 2048, 0]))
    if R.random() < 0.4:
        pon("expert_count", R.choice([128, 8, 1, 0]))
        pon("expert_used_count", R.choice([8, 2, 0]))
        pon("expert_feed_forward_length", R.choice([768, 1536, 0]))
    if R.random() < 0.3: pon("pooling_type", R.choice([0, 1, None]))
    if R.random() < 0.3: pon("attention.causal", R.choice([False, True, 0]))
    if R.random() < 0.2: pon("vision.block_count", R.choice([24, None]))
    if R.random() < 0.6: m["general.parameter_count"] = R.choice([7615616512, 0, None, 30532122624, "123"])
    if R.random() < 0.4: m["tokenizer.chat_template"] = R.choice(["{% if enable_thinking %}", "<think>", "plain", "", None])
    if R.random() < 0.4: m["general.file_type"] = R.choice([15, 7, 0, "Q4_K_M"])
    return m

for i in range(N):
    m = meta_al_azar()
    caps = R.choice([None, [], ["thinking"], ["embedding"], ["tools", "vision"], ["completion"]])
    args = (m, "modelo:" + str(i), R.choice([0, None, 4683087561, 18622563179, 1e9, 274302450.7]))
    kw = dict(capacidades=caps, plantilla=R.choice(["", "<think>x", "reasoning_content", "hola"]),
              origen=R.choice(["ollama", "registro", "catalogo"]), cuantizacion=R.choice(["", "Q4_K_M", "q8_0", "F16", "BF16", "Q5_K_M", "raro"]))
    igual("desde_metadatos", fv.desde_metadatos, fn.desde_metadatos, *args, **kw)
    f = ficha()
    igual("kv_bytes", fv.kv_bytes, fn.kv_bytes, f, R.choice([512, 4096, 8192, 32768]), R.choice([0, 1, 2, 4, -1]), R.choice(["f16", "q8_0", "q4_0", "xx"]))
    info = {}
    if R.random() < 0.9: info["vram_gb"] = R.choice([4.7, 0, None, "5.2", 19, "x", "1_0.5"])
    if R.random() < 0.5: info["familia"] = R.choice(["qwen3", None, "llama"])
    if R.random() < 0.5: info["embedding"] = R.choice([True, False, 1, None])
    if R.random() < 0.5: info["piensa"] = R.choice(["conmutable", "siempre", "nunca", None, True])
    igual("desde_catalogo", fv.desde_catalogo, fn.desde_catalogo, "cat:" + str(i), info)
    nombre = R.choice(["qwen3:8b", "qwen3", "usuario/modelo:tag", "hf.co/org/repo:Q4_K_M", "hf.co/org/repo", "hf.co",
                       "modelscope.cn/org/repo:q4_k_m", "huggingface.co/a/b:c", "a/b/c:d:e", ":x", "", "hf.co/"])
    igual("registro_de", lambda n: list(fv.registro_de(n)), lambda n: list(fn.registro_de(n)), nombre)

igual("PERFILES", lambda: pv.PERFILES, lambda: pn.PERFILES)
igual("TIRADORES", lambda: pv.TIRADORES, lambda: pn.TIRADORES)
for nombre in PERF + ["x"]:
    igual("perfil", pv.perfil, pn.perfil, nombre)

# ---------------------------------------------------------------- gguf
def cadena(t):
    b = t.encode("utf-8", "surrogatepass") if isinstance(t, str) else t
    return struct.pack("<Q", len(b)) + b

FMT = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<B", 10: "<Q", 11: "<q", 12: "<d"}
def valor(tipo, prof=0):
    if tipo in FMT:
        f = FMT[tipo]
        if f == "<f": return struct.pack(f, R.choice([1.5, 1e6, -0.1, 3.4e38, float("inf")]))
        if f == "<d": return struct.pack(f, R.choice([1.5, 1e300, -0.1, 0.0]))
        lim = {"<B": (0, 255), "<b": (-128, 127), "<H": (0, 65535), "<h": (-32768, 32767), "<I": (0, 2**32 - 1),
               "<i": (-2**31, 2**31 - 1), "<Q": (0, 2**64 - 1), "<q": (-2**63, 2**63 - 1)}[f]
        return struct.pack(f, R.randint(*lim))
    if tipo == 8:
        return cadena(R.choice(["qwen3", "", "ñandú", b"\xff\xfe bad", b"a\x80b"]))
    sub = R.choice([4, 8, 6, 9] if prof < 2 else [4, 8])
    n = R.randint(0, 4)
    return struct.pack("<I", sub) + struct.pack("<Q", n) + b"".join(valor(sub, prof + 1) for _ in range(n))

def gguf_al_azar():
    pares = []
    for _ in range(R.randint(0, 8)):
        k = R.choice(["general.architecture", "qwen3.block_count", "tokenizer.ggml.tokens", "tokenizer.ggml.merges.x",
                      "tokenizer.ggml.scores", "a.b", "dup", "dup"])
        t = R.choice([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] + ([13] if R.random() < 0.05 else []))
        pares.append(cadena(k) + struct.pack("<I", t) + (valor(t) if t != 13 else b""))
    version = R.choice([3, 3, 3, 2, 1])
    magia = R.choice([b"GGUF"] * 9 + [b"PK\x03\x04"])
    return magia + struct.pack("<I", version) + struct.pack("<Q", R.randint(0, 9)) + struct.pack("<Q", len(pares)) + b"".join(pares)

for i in range(N):
    d = gguf_al_azar()
    if R.random() < 0.3:
        d = d[:R.randint(0, len(d))]
    igual("leer_metadatos", gv.leer_metadatos, gn.leer_metadatos, d)
    ini, maxi = R.choice([1, 4, 16, 64, 1024]), R.choice([8, 64, 4096, 1 << 20])
    def pedir_de(datos, corto):
        def pedir(desde, hasta):
            trozo = datos[desde:hasta + 1]
            return trozo[:max(0, len(trozo) - 3)] if corto else trozo
        return pedir
    corto = R.random() < 0.2
    igual("leer_con_rangos", lambda: gv.leer_con_rangos(pedir_de(d, corto), ini, maxi), lambda: gn.leer_con_rangos(pedir_de(d, corto), ini, maxi))

print(json.dumps({"semilla": semilla, "casos": cuentas, "fallos": fallos}, ensure_ascii=False, indent=1))
