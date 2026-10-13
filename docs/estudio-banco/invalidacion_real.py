"""Invalidación REAL: una copia del banco se sincroniza con el disco actual (cambios reales de una sesión
de trabajo) y se comparan las llaves de lectura de las unidades antes y después. No toca el banco real.
Uso: .venv/bin/python docs/estudio-banco/invalidacion_real.py"""
import os, shutil, sys, tempfile, json, collections
tmp = tempfile.mkdtemp(prefix="prig_banco_copia_")
shutil.copytree(os.path.expanduser("~/.prig_bancos/Prig-ac5380d79d"), os.path.join(tmp, "Prig-ac5380d79d"))
os.environ["PRIG_BANCOS"] = tmp
sys.path.insert(0, "/home/ama-gi/Prig/backend")
import banco_proyecto as bp, particion_proyecto as pp, lectura_unidades as lu
banco = bp.BancoProyecto("/home/ama-gi/Prig")
assert banco.ruta_db.startswith(tmp), banco.ruta_db
import re as _re
if "--sin-lineas" in sys.argv:
    # simula la corrección propuesta: encabezados de pieza sin números de línea
    original = lu.LectorUnidades.codigo_unidad
    lu.LectorUnidades.codigo_unidad = lambda self, u: _re.sub(r" \(lines \d+-\d+\)", "", original(self, u))
antes = lu.LectorUnidades(banco, None)
llaves_antes = {o: json.dumps(antes.llave(u), sort_keys=True) for o, u in antes._unidades.items()}
rutas_antes = {o: {p["ruta"] for p in u["piezas"]} for o, u in antes._unidades.items()}
sinc = banco.sincronizar()
pp.particionar(banco)
despues = lu.LectorUnidades(banco, None)
llaves_despues = {json.dumps(despues.llave(u), sort_keys=True) for u in despues._unidades.values()}
invalidas = [o for o, k in llaves_antes.items() if k not in llaves_despues]
cambiados = set(sinc.get("rutas_modificadas") or []) if isinstance(sinc, dict) else set()
with banco.conectar() as c:
    cambiados = {r for (r,) in c.execute("SELECT ruta FROM cambios WHERE version > (SELECT MIN(version) FROM cambios WHERE version >= 9) OR version > 9")}
# ¿cuántas inválidas contienen código que cambió? (el resto se invalida de rebote: encabezados, reparto)
con_cambio = [o for o in invalidas if rutas_antes[o] & cambiados]
tokens = sum(u["tokens"] for o, u in antes._unidades.items() if o in invalidas)
firma = lambda u: frozenset((p["ruta"], p["tokens"] > 0) for p in u["piezas"]) | frozenset(u["simbolos"] if isinstance(u["simbolos"][0] if u["simbolos"] else "", str) else [])
nuevas = [frozenset(u["simbolos"]) for u in despues._unidades.values()]
misma_composicion = [o for o in invalidas if frozenset(antes._unidades[o]["simbolos"]) in nuevas]
archivos_nuevas = [frozenset(p["ruta"] for p in u["piezas"]) for u in despues._unidades.values()]
mismos_archivos = [o for o in invalidas if frozenset(rutas_antes[o]) in archivos_nuevas]
print("invalidadas con los MISMOS archivos:", len(mismos_archivos), "· con otros archivos (reagrupadas):", len(invalidas) - len(mismos_archivos))
print("invalidadas con la MISMA composición (cambió su código):", len(misma_composicion),
      "· con composición distinta (reparto):", len(invalidas) - len(misma_composicion))
print(json.dumps({"sincronizacion": {k: v for k, v in sinc.items() if not isinstance(v, (list, dict))} if isinstance(sinc, dict) else str(sinc),
                  "archivos_cambiados": sorted(cambiados), "unidades_antes": len(llaves_antes), "unidades_despues": len(llaves_despues),
                  "invalidadas": len(invalidas), "con_codigo_cambiado": len(con_cambio), "de_rebote": len(invalidas) - len(con_cambio),
                  "tokens_a_releer": tokens}, ensure_ascii=False, indent=1))
shutil.rmtree(tmp)
