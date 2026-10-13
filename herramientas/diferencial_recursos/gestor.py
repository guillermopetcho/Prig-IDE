"""Diferencial de gestor: la versión de Python puro (commit de referencia) contra la de ahora (Rust). Uso: .venv/bin/python gestor.py [semilla] [vueltas]"""
import json, os, random, sys, tempfile
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402  (recursos_viejo: backend/recursos del commit de referencia)
S = _referencia.TMP
os.environ["PRIG_SIN_MOTOR_SUAVE"] = "1"
os.environ["PRIG_RECURSOS_ARCHIVO"] = tempfile.mktemp(dir=S)
from recursos_viejo import gestor as gv, calculadora as cv
from recursos import gestor as gn, calculadora as cn
R = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
N = int(sys.argv[2]) if len(sys.argv) > 2 else 500
fallos = []
def j(x): return json.dumps(x, ensure_ascii=False, sort_keys=False, default=str)
class Gob:
    def __init__(self, limite, reanudar): self.limite, self.reanudar = limite, reanudar
FICHA = {"nombre": "qwen2.5-coder:7b", "arquitectura": "qwen2", "bytes_peso": 4683087561, "parametros": 7615616512, "parametros_activos": 7615616512,
         "fraccion_activa": 1.0, "capas": 28, "kv_bytes_token_f16": 57344, "contexto_max": 32768, "es_moe": False, "piensa": False, "embedding": False}
for i in range(N):
    pruebas = {f"{R.choice(['m1', 'm2', 'm|x'])}|{R.choice(['tutor', 'flujos'])}{k}": {"ok": R.choice([True, False, None]), "calidad": R.choice([None, 0.5, 1.0, 0]),
               "fecha": R.choice(["2026-10-01T10:00:00", "2026-10-02T10:00:00", ""]), "opciones": {"num_ctx": R.choice([2048, 4096])}} for k in range(R.randint(0, 6))}
    rad = {"gpus": R.choice([[], [{}], [{"nombre": "RTX", "vram_total_mb": 6141.0, "vram_usada_mb": 300.0, "temperatura_c": R.choice([None, 40.0, 52.0, 61.0, 70]),
                                       "consumo_w": 7.0, "uso_pct": 0.0, "otros_procesos": R.choice([[], [{"pid": 1, "proceso": "Xorg", "mb": 200.0}, {"pid": 2, "proceso": "firefox", "mb": 512}, {"pid": 3, "proceso": "Xorg", "mb": 4}]])}]]),
           "memoria": R.choice([{}, {"ram_disponible": 50e9, "swap_usada": R.choice([0, 2.5e9])}]), "energia": R.choice([{}, {"con_bateria": True}, {"con_bateria": False, "portatil": True}]),
           "ollama": R.choice([{}, {"responde": True, "version": "0.34", "dueno": "prig", "modelos_cargados": []}])}
    gob = Gob(R.choice([60.0, 65.0]), R.choice([50.0, 48.5]))
    prueba = R.choice([None, {}, {"ok": True, "opciones": {"num_ctx": 2048}}, {"ok": True, "opciones": {"num_ctx": 9000}}, {"ok": False, "opciones": {"num_ctx": 1024}}, {"ok": True}])
    perfil = R.choice(["tutor", "extraccion", "revision"])
    maq_rad = {"gpus": [{"nombre": "RTX 4050", "vram_total_mb": 6141}], "memoria": {"ram_disponible": 50e9}}
    res = []
    for mod, calc in ((gv, cv), (gn, cn)):
        g = mod.Gestor()
        alm = mock.Mock()
        alm.pruebas.return_value = pruebas
        alm.prueba.return_value = prueba
        with mock.patch.object(mod, "almacen", return_value=alm), mock.patch.object(g, "radiografia", return_value=rad), \
                mock.patch.object(mod.termico_mod, "gobernador", return_value=gob), mock.patch.object(g, "ficha", return_value=FICHA), \
                mock.patch.object(g, "maquina", return_value=calc.Maquina(maq_rad)):
            out = []
            for f in (g.medidas, g.estado_vivo, lambda: g.recomendar("qwen2.5-coder:7b", perfil)):
                try: out.append(("ok", j(f())))
                except Exception as e: out.append(("error", type(e).__name__, str(e)))
        res.append(out)
    if res[0] != res[1] and len(fallos) < 10:
        for x, y in zip(*res):
            if x != y: fallos.append((x[:1] + (x[1][:700],), y[:1] + (y[1][:700],))); break
print("fallos:", len(fallos))
for f in fallos[:6]: print(json.dumps(f, ensure_ascii=False)[:1500])
