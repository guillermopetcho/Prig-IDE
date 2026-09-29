"""
Lectura por unidades con captura múltiple (etapa 2 de docs/arquitectura-unificada.md).

Cada unidad de la partición (particion_proyecto.py) se lee UNA vez con el motor MoE y de esa lectura
quedan:

  1. el estado exacto del motor al terminarla (caché de atención + SSM): volver a esa unidad cuesta
     ~0,1 s en lugar de releerla (medido: 0,07-0,10 s, releyendo ~40 tokens);
  2. los expertos que usó, que vuelven a la GPU al restaurarla (medido: aciertos en GPU del 35,9 al
     46,2 %, +12 % de velocidad);
  3. un resumen corto (estilo ReadAgent).

Todo pasa por el mismo camino que el chat (AIEngine.chat_eventos → motor MoE), con una lista FIJA
de herramientas: el motor guarda la lectura como «proyecto» (clave = el prefijo renderizado, que
incluye las herramientas) y cualquier pregunta posterior con el mismo prefijo la restaura sola, con
sus expertos. Si la lista de herramientas cambiara, el prefijo no coincidiría y habría que releer.

(La «sorpresa» por token no se puede medir sin parchar el servidor: no devuelve la probabilidad de
los tokens leídos.)

El prefijo de cada lectura va por capas, lo más estable primero:
  sistema del lector · tarjeta global vN · contexto de la unidad (vecinas e interfaces) · código
El estado se guarda justo al final del código; lo que se pregunte después va en otro mensaje.
"""

import hashlib
import json
import os
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

def _sistema_lector() -> str:
    import memoria_consulta
    return (
        "You are reading one unit of a large software project, as part of a complete study of the project. "
        "The unit is given in repository format. Remember exact names, signatures, constants, file paths and "
        "line numbers: later questions will be answered from this reading. Be precise and never invent "
        "identifiers.\n"
        "Answer from this reading when it contains the answer. For anything outside this unit, use the "
        "tool `consola`: Python over the WHOLE project as the object P (only the methods listed below "
        "exist; no other imports). If the answer is in this reading, answer directly WITHOUT tools.\n"
        "One call is enough for most questions:\n"
        "  who calls X → P.llamadores(\"X\") · call chain from A to B → P.camino(\"A\", \"B\")\n"
        "  what breaks if X changes → P.impacto(\"X\") · everything about X → P.ficha(\"X\")\n"
        "  who reads config/env key K → P.hechos(r=\"lee_config\", o=\"K\") (or lee_entorno)\n"
        "  endpoint E → P.api(\"E\") · value of a constant elsewhere → P.grep(r\"^NAME\\s*=\")\n"
        "Conclude after at most 3 tool calls.\n\n" + memoria_consulta.AYUDA
    )


# El sistema es parte del prefijo guardado: incluye la ayuda de la consola (sin ella, el modelo
# inventaba métodos de P e intentaba importar módulos: medido en el piloto de la etapa 2)
SISTEMA_LECTOR = _sistema_lector()
PEDIDO_RESUMEN = (
    "Write the gist of this unit for later lookup: 5-8 terse bullet lines covering purpose, main entry "
    "points (exact names), key state and data, external effects (files, network, config keys, env vars) "
    "and notable risks. Exact identifiers only."
)
# Siempre las mismas y en este orden: van en el prefijo guardado
HERRAMIENTAS_UNIDAD = ("consola", "ver_simbolo", "anotar")
TOPE_TARJETA = 6000
TOPE_CONTEXTO = 3000


def _sha(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8", "replace")).hexdigest()


def _crear_tabla(c):
    c.execute("""CREATE TABLE IF NOT EXISTS lecturas (
        orden INTEGER PRIMARY KEY, archivo TEXT, sha TEXT, llave TEXT, tokens INTEGER, segundos REAL,
        bytes INTEGER, expertos TEXT, resumen TEXT, aceptacion REAL, tok_s REAL, creado TEXT)""")


class LectorUnidades:
    def __init__(self, banco, ai_engine, modelo: Optional[str] = None,
                 generar_sub: Optional[Callable[[str, str, int], str]] = None):
        from ai_engine import motor_moe
        self.banco = banco
        self.ai = ai_engine
        self.modelo = modelo or motor_moe.NOMBRE
        self.generar_sub = generar_sub            # para P.llm dentro de la consola
        self._unidades = {u["orden"]: u for u in banco.unidades()}
        self._tarjeta: Optional[str] = None
        with banco.conectar() as c:
            _crear_tabla(c)
    # ------------------------------------------------------------------ el prefijo
    def tarjeta_global(self) -> str:
        """ Visión global del proyecto (versión 0: el mapa del banco con los resúmenes de carpetas y
        proyecto). Es la misma para todas las unidades: si cambia, cambian todas las lecturas. """
        if self._tarjeta is None:
            self._tarjeta = "PROJECT CARD\n" + self.banco.mapa(TOPE_TARJETA)
        return self._tarjeta

    def contexto_unidad(self, u: Dict[str, Any]) -> str:
        """ Su lugar en el proyecto y las interfaces que cruzan su frontera: qué usa de las vecinas y
        quién la usa, con firma y ubicación """
        total = len(self._unidades)
        lineas = [f"UNIT {u['orden'] + 1} of {total}: {u['nombre']}",
                  "Files: " + ", ".join(f"{p['ruta']} (lines {p['ini']}-{p['fin']})" for p in u["piezas"])]
        propias = {(p["ruta"], p["ini"], p["fin"]) for p in u["piezas"]}

        def dentro(ruta: str, linea: int) -> bool:
            return any(r == ruta and a <= linea <= b for r, a, b in propias)
        usa, la_usan = {}, {}
        with self.banco.conectar() as c:
            inicio = {(f["ruta"], f["nombre"]): (f["ini"], f["firma"]) for f in c.execute("SELECT ruta, nombre, ini, firma FROM simbolos")}
            for f in c.execute("SELECT ruta, desde, a_ruta, a_nombre, linea FROM llamadas"):
                destino = inicio.get((f["a_ruta"], f["a_nombre"]))
                if not destino:
                    continue
                desde_dentro, hacia_dentro = dentro(f["ruta"], f["linea"]), dentro(f["a_ruta"], destino[0])
                if desde_dentro and not hacia_dentro:
                    usa[(f["a_ruta"], f["a_nombre"])] = destino
                elif hacia_dentro and not desde_dentro:
                    la_usan.setdefault((f["a_ruta"], f["a_nombre"]), set()).add(f"{f['desde']} ({f['ruta']})")
        if usa:
            lineas.append("Uses from other units:")
            for (ruta, nombre), (ini, firma) in sorted(usa.items())[:60]:
                lineas.append(f"  {ruta}:{ini} {firma or nombre}")
        if la_usan:
            lineas.append("Used by other units:")
            for (ruta, nombre), quienes in sorted(la_usan.items())[:40]:
                lineas.append(f"  {nombre} ← " + ", ".join(sorted(quienes)[:4]))
        texto = "\n".join(lineas)
        import banco_proyecto as bp
        while bp.estimar_tokens(texto) > TOPE_CONTEXTO and len(lineas) > 3:
            lineas.pop()
            texto = "\n".join(lineas)
        return texto

    def codigo_unidad(self, u: Dict[str, Any]) -> str:
        """ El código en el formato de repositorio del preentrenamiento (<|repo_name|>, <|file_sep|>) """
        partes = [f"<|repo_name|>{os.path.basename(self.banco.raiz)}"]
        with self.banco.conectar() as c:
            import zlib
            for p in u["piezas"]:
                f = c.execute("SELECT contenido FROM archivos WHERE ruta = ?", (p["ruta"],)).fetchone()
                if not f:
                    continue
                lineas = zlib.decompress(f["contenido"]).decode("utf-8", "replace").splitlines()
                encabezado = p["ruta"] if (p["ini"] == 1 and p["fin"] >= len(lineas)) else f"{p['ruta']} (lines {p['ini']}-{p['fin']})"
                partes.append(f"<|file_sep|>{encabezado}\n" + "\n".join(lineas[p["ini"] - 1:p["fin"]]))
        return "\n".join(partes)

    def mensajes(self, u: Dict[str, Any]) -> List[Dict[str, str]]:
        return [{"role": "system", "content": SISTEMA_LECTOR},
                {"role": "user", "content": f"{self.tarjeta_global()}\n\n{self.contexto_unidad(u)}\n\n{self.codigo_unidad(u)}"}]

    def llave(self, u: Dict[str, Any]) -> Dict[str, Any]:
        """ Todo lo que, si cambia, invalida la lectura guardada """
        version = ""
        try:
            from ai_engine import motor_moe
            with open(os.path.join(motor_moe.LIB, "VERSION")) as f:
                version = f.read().strip()
        except OSError:
            pass
        return {"motor": _sha(version)[:12], "tarjeta": _sha(self.tarjeta_global())[:12],
                "herramientas": ",".join(HERRAMIENTAS_UNIDAD), "unidad": _sha(json.dumps(self.mensajes(u)))[:12]}

    # ------------------------------------------------------------------ conversar sobre una unidad
    def _conversar(self, orden: int, texto: str, max_rondas: int = 10) -> Dict[str, Any]:
        """ Una pregunta sobre la unidad por el camino del chat: la primera vez el motor lee la unidad
        y guarda su estado; después lo restaura (con sus expertos) y solo lee la pregunta """
        import memoria_consulta
        from herramientas_chat import Herramientas
        from ai_engine import motor_moe
        u = self._unidades[orden]
        consola = memoria_consulta.Consola(self.banco, generar=self.generar_sub)
        herramientas = Herramientas(banco=self.banco, consola=consola, solo=list(HERRAMIENTAS_UNIDAD))
        salida, usadas, stats, avisos = "", [], {}, []
        t0 = time.time()
        try:
            for ev in self.ai.chat_eventos(self.mensajes(u) + [{"role": "user", "content": texto}], self.modelo, "tutor",
                                           think=False, herramientas=herramientas, max_rondas=max_rondas,
                                           extra={motor_moe.PERFIL: "preciso"}):
                if ev.get("t") == "texto":
                    salida += ev.get("v") or ""
                elif ev.get("t") == "herramienta":
                    usadas.append(ev.get("nombre"))
                elif ev.get("t") == "stats":
                    stats = ev.get("v") or {}
                elif ev.get("t") in ("aviso", "error"):
                    avisos.append(str(ev.get("v")))
        finally:
            consola.cerrar()
        # Lo que hizo el motor con el prefijo (leerlo o restaurarlo): en respuestas con varias rondas de
        # herramientas no llega en las estadísticas finales, así que se toma del motor
        motor = self.ai.motor_moe()
        proyecto = dict(getattr(motor, "ultimo_proyecto", None) or stats.get("proyecto") or {})
        if getattr(motor, "ultimo_proyecto", None):
            motor.ultimo_proyecto = {}          # la próxima conversación informa lo suyo
        return {"texto": salida, "segundos": round(time.time() - t0, 2), "herramientas": usadas, "avisos": avisos,
                "lectura": proyecto.get("origen") or "en memoria", "lectura_s": proyecto.get("segundos"),
                "tokens_unidad": proyecto.get("tokens"), "clave": proyecto.get("clave"),
                "tok_s": stats.get("generacion_tok_s"), "rondas": stats.get("rondas")}

    # ------------------------------------------------------------------ leer
    def leer(self, orden: int) -> Dict[str, Any]:
        """ Lee la unidad (el motor guarda su estado y sus expertos) y deja su resumen """
        from ai_engine import motor_moe
        u = self._unidades[orden]
        llave = self.llave(u)
        r = self._conversar(orden, PEDIDO_RESUMEN + " Do not call tools.", max_rondas=2)
        clave = r["clave"] or ""
        archivo = f"{clave}.bin" if clave else ""
        ruta = os.path.join(motor_moe.CARPETA_PROYECTOS, archivo) if archivo else ""
        expertos = []
        try:
            with open(os.path.join(motor_moe.CARPETA_PROYECTOS, clave + ".calientes.json")) as f:
                expertos = json.load(f)
        except (OSError, ValueError):
            pass
        salida = {"orden": orden, "archivo": archivo, "llave": llave, "tokens": int(r["tokens_unidad"] or 0),
                  "segundos": r["lectura_s"], "origen": r["lectura"],
                  "bytes": os.path.getsize(ruta) if ruta and os.path.exists(ruta) else 0,
                  "expertos": expertos, "resumen": r["texto"].strip(), "aceptacion": None, "tok_s": r["tok_s"]}
        with self.banco.conectar() as c:
            _crear_tabla(c)
            c.execute("INSERT OR REPLACE INTO lecturas VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (orden, archivo, llave["unidad"], json.dumps(llave), salida["tokens"], salida["segundos"], salida["bytes"],
                       json.dumps(expertos), salida["resumen"], None, salida["tok_s"],
                       datetime.now().isoformat(timespec="seconds")))
        return salida

    def pasada(self, ordenes: Optional[List[int]] = None, progreso: Optional[Callable[[Dict[str, Any]], None]] = None,
               cancelar=None) -> List[Dict[str, Any]]:
        salida = []
        for orden in (ordenes if ordenes is not None else sorted(self._unidades)):
            if cancelar is not None and cancelar.is_set():
                break
            if self.vigente(orden):
                continue
            r = self.leer(orden)
            salida.append(r)
            if progreso:
                progreso(r)
        return salida

    # ------------------------------------------------------------------ usar lo leído
    def lectura(self, orden: int) -> Optional[Dict[str, Any]]:
        with self.banco.conectar() as c:
            _crear_tabla(c)
            f = c.execute("SELECT * FROM lecturas WHERE orden = ?", (orden,)).fetchone()
        if not f:
            return None
        d = dict(f)
        d["llave"], d["expertos"] = json.loads(d["llave"]), json.loads(d["expertos"])
        return d

    def vigente(self, orden: int) -> bool:
        """ Leída, con la misma llave y con su estado todavía en disco (el motor poda los viejos) """
        from ai_engine import motor_moe
        l = self.lectura(orden)
        return bool(l) and l["llave"] == self.llave(self._unidades[orden]) and bool(l["archivo"]) \
            and os.path.exists(os.path.join(motor_moe.CARPETA_PROYECTOS, l["archivo"]))

    def preguntar(self, orden: int, pregunta: str, max_rondas: int = 10) -> Dict[str, Any]:
        """ Pregunta sobre una unidad: el motor restaura su lectura (y sus expertos) y el modelo puede
        consultar el resto del proyecto con la consola """
        return self._conversar(orden, pregunta, max_rondas=max_rondas)

    # ------------------------------------------------------------------ enrutador
    def unidad_de(self, ruta: str, linea: int) -> Optional[int]:
        for orden, u in self._unidades.items():
            for p in u["piezas"]:
                if p["ruta"] == ruta and p["ini"] <= linea <= p["fin"]:
                    return orden
        return None

    def elegir_unidad(self, pregunta: str, minimo: float = 0.35) -> Dict[str, Any]:
        """ Qué unidad restaurar para esta pregunta. Suma tres señales: los símbolos y rutas que la
        pregunta nombra (las más fuertes), los fragmentos que encuentra la búsqueda del banco y los
        hechos del grafo (claves, endpoints). Devuelve la ganadora solo si se despega de la segunda:
        si la pregunta reparte su peso entre varias, mejor el modo general (paquete + consola). """
        import banco_proyecto as bp
        puntos: Dict[int, float] = {}

        def sumar(orden: Optional[int], p: float):
            if orden is not None:
                puntos[orden] = puntos.get(orden, 0.0) + p
        with self.banco.conectar() as c:
            for nombre in bp.identificadores_nombrados(pregunta):
                for f in c.execute("SELECT ruta, ini FROM simbolos WHERE nombre = ? OR corto = ?", (nombre, nombre.split(".")[-1])):
                    sumar(self.unidad_de(f["ruta"], f["ini"]), 3.0)
                for f in c.execute("SELECT ruta, linea FROM hechos WHERE o = ? OR o LIKE ?", (nombre, f"% {nombre}")):
                    sumar(self.unidad_de(f["ruta"], f["linea"]), 1.5)
            for ruta in self.banco._rutas_mencionadas(c, pregunta):
                for orden, u in self._unidades.items():
                    if ruta in u["rutas"]:
                        sumar(orden, 2.0 / max(1, sum(1 for p in u["piezas"] if p["ruta"] == ruta)))
        for rango, f in enumerate(self.banco.buscar(pregunta, k=12)):
            sumar(self.unidad_de(f["ruta"], f["ini"]), 1.0 / (1 + rango * 0.5))
        if not puntos:
            return {"orden": None, "motivo": "ninguna unidad coincide"}
        orden_puntos = sorted(puntos.items(), key=lambda x: -x[1])
        total = sum(puntos.values())
        mejor, p1 = orden_puntos[0]
        p2 = orden_puntos[1][1] if len(orden_puntos) > 1 else 0.0
        cuota = p1 / total
        alternativas = [{"orden": o, "nombre": self._unidades[o]["nombre"], "puntos": round(p, 2)} for o, p in orden_puntos[:4]]
        if cuota < minimo or p1 < 1.5 * p2:
            return {"orden": None, "motivo": f"repartida entre unidades (la mejor tiene {cuota:.0%})", "alternativas": alternativas}
        return {"orden": mejor, "nombre": self._unidades[mejor]["nombre"], "cuota": round(cuota, 2),
                "vigente": self.vigente(mejor), "alternativas": alternativas}


def main():
    """ Pasada completa, reanudable: lee las unidades que no tengan una lectura vigente (un corte de
    luz o un reinicio no pierden lo hecho). Uso: python lectura_unidades.py --pasada [raíz] """
    import argparse
    import atexit
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import banco_proyecto as bp
    import particion_proyecto as pp
    from ai_engine.ai_engine_class import AIEngine
    parser = argparse.ArgumentParser()
    parser.add_argument("--pasada", action="store_true")
    parser.add_argument("raiz", nargs="?", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = parser.parse_args()
    ai = AIEngine()
    ai.config["moe_contexto"] = "auto"            # solo en esta ejecución: no se guarda
    atexit.register(ai.unload_models)
    banco = bp.BancoProyecto(args.raiz)
    banco.sincronizar()
    if not banco.unidades():
        pp.particionar(banco)

    def sub(pregunta: str, contexto: str, max_tokens: int) -> str:
        return "".join(ai.generate_response(f"{contexto}\n\n---\n{pregunta}", model=lector.modelo,
                                            system_prompt="Answer briefly and precisely from the context only.",
                                            think=False, options={"num_predict": int(max_tokens), "temperature": 0.3}))
    lector = LectorUnidades(banco, ai, generar_sub=sub)
    total = len(lector._unidades)
    t0 = time.time()
    print(f"{datetime.now():%H:%M:%S} pasada: {sum(lector.vigente(o) for o in lector._unidades)}/{total} vigentes", flush=True)

    def progreso(r):
        print(f"{datetime.now():%H:%M:%S} [{time.time() - t0:6.0f} s] unidad {r['orden']:3d}/{total}: {r['origen']} "
              f"{r['tokens']} tokens en {r['segundos']} s, estado {r['bytes'] / 1e6:.0f} MB", flush=True)
    hechas = lector.pasada(progreso=progreso)
    print(f"FIN: {len(hechas)} leídas en {time.time() - t0:.0f} s; vigentes {sum(lector.vigente(o) for o in lector._unidades)}/{total}", flush=True)


if __name__ == "__main__":
    main()
