""" Muestra respuestas de un informe de la sonda: ver.py INFORME.json ID [ID...] """
import json, sys
d = json.load(open(sys.argv[1]))
for r in d["resultados"]:
    if r["id"] not in sys.argv[2:]: continue
    print("#", r["id"], "| PEDIDO", r.get("modo_pedido"), "| USADO", r["modo"], "| UNIDAD", r.get("unidad"), "| MOTIVO", r.get("motivo"))
    print("HECHOS", r.get("hechos_caracteres"), "| AL FINAL", r.get("hechos_al_final", False), "| SEG", r["segundos"], "| TOKENS", r["tokens"], "| AGOTADA", r["agotada"], "| MEM", r.get("memoria_del_modelo"))
    for c in r["consultas"]:
        print("  -", c["nombre"], c["argumentos"][:250], "→", c.get("resultado_caracteres"))
    print("-" * 60); print(r["respuesta"]); print("=" * 80)
