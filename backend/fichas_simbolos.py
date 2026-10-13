"""
Fichas por símbolo (etapa 3 de docs/arquitectura-unificada.md): lo que el modelo entendió de cada
función, método y clase al leer su unidad, verificado sin modelo contra el código y el grafo.

Se escriben sobre la lectura restaurada de la unidad (lectura_unidades.py): el código ya está leído,
así que solo cuesta escribir. En inglés terso, que es el idioma en que el modelo es más preciso y el
que menos tokens gasta. Cada ficha:

  does       qué hace (1-2 frases)
  contract   entradas, salida y precondiciones
  effects    archivos, red, configuración, estado global que toca
  risks      casos borde o fallos posibles
  change     «para cambiar X, tocar aquí»

Verificación sin modelo (una ficha con problemas queda marcada, no se borra):
  · el símbolo existe en esa ruta
  · todo nombre citado entre comillas invertidas existe en el código del proyecto
  · las líneas citadas caen dentro del símbolo (con un margen)
"""

import json
import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set

TANDA = 12          # con 20, dos tandas de 5 salieron sin JSON válido (respuesta demasiado larga)
MARGEN_LINEAS = 3

PEDIDO_FICHAS = (
    "Write a record for EACH of these symbols of this unit, from your reading. Reply ONLY with a JSON array, "
    "one object per symbol, in this order:\n{simbolos}\n"
    'Each object: {{"name": exact name as listed, "does": "1-2 terse sentences", '
    '"contract": "inputs, output, preconditions", "effects": "files, network, config keys, env vars, global '
    'state it touches, or none", "risks": "edge cases or failure modes, or none", "change": "to change X, edit '
    'here (what to touch)"}}. Terse technical English, exact identifiers in `backticks`, line numbers as '
    '"l.123". Do not call tools.'
)


def _crear_tabla(c):
    c.execute("""CREATE TABLE IF NOT EXISTS fichas (
        ruta TEXT, nombre TEXT, unidad INTEGER, datos TEXT, sha TEXT, problemas TEXT, creado TEXT,
        PRIMARY KEY (ruta, nombre))""")


def _json_lista(texto: str) -> List[Dict[str, Any]]:
    texto = (texto or "").strip()
    m = re.search(r"```(?:json)?\s*(\[.*\])\s*```", texto, re.S)
    if m:
        texto = m.group(1)
    else:
        ini, fin = texto.find("["), texto.rfind("]")
        if ini >= 0 and fin > ini:
            texto = texto[ini:fin + 1]
    datos = json.loads(texto)
    return [d for d in datos if isinstance(d, dict)] if isinstance(datos, list) else []


class Fichas:
    def __init__(self, banco, lector):
        self.banco = banco
        self.lector = lector
        self._conocidos: Optional[Set[str]] = None
        with banco.conectar() as c:
            _crear_tabla(c)

    # ------------------------------------------------------------------ qué fichar
    def simbolos_de_unidad(self, orden: int) -> List[Dict[str, Any]]:
        """ Los símbolos cuyo inicio cae dentro de las piezas de la unidad, en orden de lectura """
        u = self.lector._unidades[orden]
        salida = []
        with self.banco.conectar() as c:
            for p in u["piezas"]:
                for f in c.execute("SELECT ruta, nombre, tipo, ini, fin, sha FROM simbolos WHERE ruta = ? AND ini BETWEEN ? AND ? "
                                   "AND tipo IN ('funcion','metodo','clase','anidada') ORDER BY ini", (p["ruta"], p["ini"], p["fin"])):
                    salida.append(dict(f))
        return salida

    def pendientes(self, orden: int) -> List[Dict[str, Any]]:
        """ Los que no tienen ficha o cuya ficha es de otra versión del símbolo """
        with self.banco.conectar() as c:
            hechas = {(f["ruta"], f["nombre"]): f["sha"] for f in c.execute("SELECT ruta, nombre, sha FROM fichas")}
        return [s for s in self.simbolos_de_unidad(orden) if hechas.get((s["ruta"], s["nombre"])) != s["sha"]]

    # ------------------------------------------------------------------ escribir
    def fichar_unidad(self, orden: int, progreso: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        pendientes = self.pendientes(orden)
        hechas, con_problemas, sin_respuesta = 0, 0, 0
        t0 = time.time()
        for i in range(0, len(pendientes), TANDA):
            tanda = pendientes[i:i + TANDA]
            lista = "\n".join(f"- {s['nombre']} ({s['tipo']}, {s['ruta']} l.{s['ini']}-{s['fin']})" for s in tanda)
            r = self.lector.preguntar(orden, PEDIDO_FICHAS.format(simbolos=lista), max_rondas=1)
            try:
                objetos = _json_lista(r["texto"])
            except ValueError:
                objetos = []
            por_nombre = {str(o.get("name") or "").strip("` "): o for o in objetos}
            for s in tanda:
                datos = por_nombre.get(s["nombre"]) or por_nombre.get(s["nombre"].split(".")[-1])
                if not datos:
                    sin_respuesta += 1
                    continue
                problemas = self.verificar(s, datos)
                with self.banco.conectar() as c:
                    c.execute("INSERT OR REPLACE INTO fichas VALUES (?,?,?,?,?,?,?)",
                              (s["ruta"], s["nombre"], orden, json.dumps(datos, ensure_ascii=False), s["sha"],
                               json.dumps(problemas, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))
                hechas += 1
                con_problemas += bool(problemas)
            if progreso:
                progreso({"unidad": orden, "hechas": hechas, "total": len(pendientes)})
        return {"unidad": orden, "fichas": hechas, "con_problemas": con_problemas, "sin_respuesta": sin_respuesta,
                "segundos": round(time.time() - t0, 1)}

    # ------------------------------------------------------------------ verificar
    def _nombres(self) -> Set[str]:
        if self._conocidos is None:
            import examen_proyecto
            self._conocidos = examen_proyecto.nombres_conocidos(self.banco)
        return self._conocidos

    def _lineas(self, ruta: str) -> List[str]:
        if not hasattr(self, "_cache_lineas"):
            self._cache_lineas: Dict[str, List[str]] = {}
        if ruta not in self._cache_lineas:
            import zlib
            with self.banco.conectar() as c:
                f = c.execute("SELECT contenido FROM archivos WHERE ruta = ?", (ruta,)).fetchone()
            self._cache_lineas[ruta] = zlib.decompress(f["contenido"]).decode("utf-8", "replace").splitlines() if f else []
        return self._cache_lineas[ruta]

    def reverificar(self) -> Dict[str, Any]:
        """ Vuelve a verificar todas las fichas guardadas con el verificador actual (sin modelo) """
        with self.banco.conectar() as c:
            filas = [dict(f) for f in c.execute("SELECT f.ruta, f.nombre, f.datos, s.ini, s.fin FROM fichas f "
                                                "JOIN simbolos s ON s.ruta = f.ruta AND s.nombre = f.nombre")]
        for f in filas:
            problemas = self.verificar({"ruta": f["ruta"], "nombre": f["nombre"], "ini": f["ini"], "fin": f["fin"]},
                                       json.loads(f["datos"]))
            with self.banco.conectar() as c:
                c.execute("UPDATE fichas SET problemas = ? WHERE ruta = ? AND nombre = ?",
                          (json.dumps(problemas, ensure_ascii=False), f["ruta"], f["nombre"]))
        return self.resumen()

    def verificar(self, simbolo: Dict[str, Any], datos: Dict[str, Any]) -> List[str]:
        problemas = []
        texto = " ".join(str(v) for k, v in datos.items() if k != "name")
        conocidos = self._nombres()
        for citado in set(re.findall(r"`([A-Za-z_][\w.]*)(?:\(\))?`", texto)):
            partes = [x for x in citado.split(".") if x]
            if any(x not in conocidos for x in partes) and len(citado) > 2:
                problemas.append(f"nombre inexistente: {citado}")
        citados = {x for c in re.findall(r"`([A-Za-z_][\w.]*)(?:\(\))?`", texto) for x in c.split(".") if x}
        lineas = self._lineas(simbolo["ruta"])
        for a, b in re.findall(r"\bl\.\s?(\d+)(?:\s*-\s*(\d+))?", texto):
            for linea in {int(a), int(b or a)}:
                if simbolo["ini"] - MARGEN_LINEAS <= linea <= simbolo["fin"] + MARGEN_LINEAS:
                    continue
                # Fuera del símbolo puede ser legítimo (la constante o el default que usa): vale si esa
                # línea, o la de al lado, contiene algo que la ficha cita
                cerca = " ".join(lineas[max(0, linea - 2):linea + 1])
                if not any(re.search(r"(?<![\w])" + re.escape(x) + r"(?![\w])", cerca) for x in citados):
                    problemas.append(f"línea {linea} no contiene lo citado (fuera de {simbolo['nombre']}, "
                                     f"l.{simbolo['ini']}-{simbolo['fin']})")
        for campo in ("does", "contract", "effects", "change"):
            if not str(datos.get(campo) or "").strip():
                problemas.append(f"falta «{campo}»")
        return problemas

    # ------------------------------------------------------------------ leer
    def ficha(self, ruta: str, nombre: str) -> Optional[Dict[str, Any]]:
        with self.banco.conectar() as c:
            f = c.execute("SELECT * FROM fichas WHERE ruta = ? AND nombre = ?", (ruta, nombre)).fetchone()
        if not f:
            return None
        d = dict(f)
        d["datos"], d["problemas"] = json.loads(d["datos"]), json.loads(d["problemas"])
        return d

    def resumen(self) -> Dict[str, Any]:
        with self.banco.conectar() as c:
            total = c.execute("SELECT COUNT(*) FROM fichas").fetchone()[0]
            con = c.execute("SELECT COUNT(*) FROM fichas WHERE problemas != '[]'").fetchone()[0]
        return {"fichas": total, "con_problemas": con, "verificadas": total - con}
