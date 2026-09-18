"""
Ejecutar páginas y comprobar desafíos.

Las páginas se escriben como archivos en una carpeta temporal y se ejecutan con el
mismo Python que el resto del IDE: `import pila` en una página carga pila.py, igual que
en un proyecto. Nada queda en el workspace del usuario.

La comprobación corre en un proceso aparte con un arnés que devuelve, además de
aprobado/suspendido, cuántas pruebas pasan y cuál falla con su mensaje: saber QUÉ caso
falla es lo que permite aprender del error, no solo que «no está bien».

Tres formas de comprobar, según de dónde venga el desafío:
    unittest  los tests de Exercism
    doctest   los ejemplos del docstring (TheAlgorithms)
    asserts   fragmentos independientes que genera el modelo; cada uno cuenta como una prueba
"""

import json
import os
import re
import shutil
import tempfile
import uuid
from typing import Any, Dict, List, Optional

MARCA = "__PRIG_RESULTADO__"
NOMBRE_PAGINA = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}\.py$")
RESERVADOS = {"pytest.py", "unittest.py", "doctest.py", "json.py", "sys.py", "os.py", "io.py",
              "traceback.py", "importlib.py", "contextlib.py"}
MAX_PAGINAS = 8
MAX_BYTES_PAGINA = 200_000


class ErrorDesafio(Exception):
    pass


def validar_paginas(paginas: List[Dict[str, Any]], permitir_vacio: bool = False) -> List[Dict[str, Any]]:
    """ Nombres de módulo válidos, sin repetir, sin pisar módulos del arnés """
    if not isinstance(paginas, list) or (not paginas and not permitir_vacio):
        raise ErrorDesafio("El desafío necesita al menos una página de código.")
    if len(paginas) > MAX_PAGINAS:
        raise ErrorDesafio(f"Como mucho {MAX_PAGINAS} páginas.")
    vistas, salida = set(), []
    for p in paginas:
        nombre = str((p or {}).get("nombre", "")).strip()
        if not NOMBRE_PAGINA.match(nombre):
            raise ErrorDesafio(f"«{nombre}» no es un nombre de página válido: usa letras, números y _, "
                               "sin espacios ni guiones, terminado en .py (por ejemplo pila.py).")
        if nombre.startswith("_prig") or nombre in RESERVADOS:
            raise ErrorDesafio(f"«{nombre}» está reservado; elige otro nombre.")
        if nombre.lower() in vistas:
            raise ErrorDesafio(f"Hay dos páginas llamadas «{nombre}».")
        vistas.add(nombre.lower())
        contenido = str(p.get("contenido") or "")
        if len(contenido.encode("utf-8")) > MAX_BYTES_PAGINA:
            raise ErrorDesafio(f"La página «{nombre}» es demasiado grande.")
        salida.append({**p, "nombre": nombre, "contenido": contenido})
    return salida


# ---------------------------------------------------------------------------
# Arnés: se escribe junto a las páginas y se ejecuta en un proceso aparte
# ---------------------------------------------------------------------------

PYTEST_MINIMO = '''"""Sustituto mínimo de pytest para los tests de Exercism que solo lo usan para marcar tareas."""
import contextlib as _c


class _Marca:
    def __getattr__(self, nombre):
        def decorador(*args, **kwargs):
            if len(args) == 1 and callable(args[0]) and not kwargs:
                return args[0]
            return lambda f: f
        return decorador


mark = _Marca()


@_c.contextmanager
def raises(tipo, match=None):
    import re as _re

    class _Info:
        value = None
    info = _Info()
    try:
        yield info
    except tipo as e:
        info.value = e
        if match is not None and not _re.search(match, str(e)):
            raise AssertionError(f"El mensaje {str(e)!r} no coincide con {match!r}")
    else:
        raise AssertionError(f"Se esperaba {tipo.__name__} y no se lanzó")
'''

ARNES = r'''
import contextlib, doctest, importlib, io, json, sys, traceback, unittest

MARCA = "__PRIG_RESULTADO__"
with open("_prig_config.json", encoding="utf-8") as f:
    cfg = json.load(f)
res = {"total": 0, "pasados": 0, "fallos": [], "error": None}
salida = io.StringIO()


def corto(texto, n=700):
    texto = (texto or "").strip()
    return texto if len(texto) <= n else texto[:n] + " …"


def ultimo_error():
    lineas = traceback.format_exc().strip().splitlines()
    utiles = [l for l in lineas if "_prig_comprobar.py" not in l]
    return corto("\n".join(utiles[-6:]))


try:
    with contextlib.redirect_stdout(salida):
        tipo = cfg["tipo"]
        if tipo == "unittest":
            cargador = unittest.TestLoader()
            suite = unittest.TestSuite()
            for modulo in cfg["modulos"]:
                try:
                    suite.addTests(cargador.loadTestsFromName(modulo))
                except Exception:
                    res["error"] = "No se pudieron cargar las pruebas (¿falta algo que importan?):\n" + ultimo_error()
            if res["error"] is None:
                resultado = unittest.TestResult()
                suite.run(resultado)
                res["total"] = resultado.testsRun
                malos = [(t, e, "fallo") for t, e in resultado.failures] + [(t, e, "error") for t, e in resultado.errors]
                for prueba, texto, clase in malos:
                    nombre = getattr(prueba, "_testMethodName", str(prueba))
                    lineas = [l for l in texto.strip().splitlines() if l.strip()]
                    mensaje = "\n".join(lineas[-3:])
                    if clase == "error" and nombre.startswith("_"):
                        res["error"] = corto(texto)
                    res["fallos"].append({"nombre": nombre.replace("test_", "", 1).replace("_", " "),
                                          "mensaje": corto(mensaje), "tipo": clase})
                res["pasados"] = res["total"] - len(malos)
        elif tipo == "doctest":
            try:
                modulo = importlib.import_module(cfg["modulo"])
            except Exception:
                res["error"] = "Tu página no se puede importar:\n" + ultimo_error()
            else:
                globales = dict(vars(modulo))
                prueba = doctest.DocTestParser().get_doctest(cfg["ejemplos"], globales, "ejemplos", cfg["modulo"], 0)
                fallos = []

                class Corredor(doctest.DocTestRunner):
                    def report_failure(self, out, test, example, got):
                        fallos.append({"nombre": example.source.strip(), "mensaje": f"Se esperaba: {example.want.strip()}\nSe obtuvo: {got.strip()}", "tipo": "fallo"})

                    def report_unexpected_exception(self, out, test, example, exc_info):
                        err = traceback.format_exception_only(exc_info[0], exc_info[1])[-1].strip()
                        fallos.append({"nombre": example.source.strip(), "mensaje": f"Lanzó {err}", "tipo": "error"})

                corredor = Corredor(optionflags=doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE)
                corredor.run(prueba, out=lambda s: None)
                # Las líneas «>>> from x import y» no cuentan como prueba
                total = sum(1 for e in prueba.examples if e.want.strip() or "import" not in e.source)
                res["total"] = total
                res["fallos"] = [{**f, "mensaje": corto(f["mensaje"]), "nombre": corto(f["nombre"], 200)} for f in fallos]
                res["pasados"] = max(0, total - len(fallos))
        elif tipo == "asserts":
            for i, fragmento in enumerate(cfg["asserts"], 1):
                res["total"] += 1
                try:
                    exec(compile(fragmento, f"<prueba {i}>", "exec"), {"__name__": f"prueba_{i}"})
                    res["pasados"] += 1
                except AssertionError as e:
                    res["fallos"].append({"nombre": f"prueba {i}", "codigo": corto(fragmento, 400),
                                          "mensaje": corto(str(e)) or "La comprobación no se cumple.", "tipo": "fallo"})
                except Exception as e:
                    detalle = traceback.format_exception_only(type(e), e)[-1].strip()
                    res["fallos"].append({"nombre": f"prueba {i}", "codigo": corto(fragmento, 400),
                                          "mensaje": corto(detalle), "tipo": "error"})
        else:
            res["error"] = "Este desafío no tiene comprobación automática."
except BaseException:
    res["error"] = ultimo_error()

res["stdout"] = corto(salida.getvalue(), 3000)
sys.stdout.write("\n" + MARCA + json.dumps(res, ensure_ascii=False) + "\n")
'''


class Carpeta:
    """ Carpeta temporal con las páginas; se borra al salir """

    def __init__(self, paginas: List[Dict[str, Any]], extras: Optional[Dict[str, str]] = None):
        self.paginas = paginas
        self.extras = extras or {}
        self.ruta = None

    def __enter__(self) -> str:
        self.ruta = tempfile.mkdtemp(prefix="prig_desafio_")
        for p in self.paginas:
            self._escribir(p["nombre"], p.get("contenido") or "")
        for nombre, contenido in self.extras.items():
            self._escribir(nombre, contenido)
        return self.ruta

    def _escribir(self, nombre: str, contenido: str):
        destino = os.path.join(self.ruta, nombre)
        if os.path.dirname(os.path.abspath(destino)) != os.path.abspath(self.ruta):
            raise ErrorDesafio(f"Nombre de archivo no válido: {nombre}")
        with open(destino, "w", encoding="utf-8") as f:
            f.write(contenido)

    def __exit__(self, *exc):
        shutil.rmtree(self.ruta, ignore_errors=True)
        return False


def ejecutar_pagina(runner, paginas: List[Dict[str, Any]], nombre: str, timeout: int = 20,
                    run_id: Optional[str] = None) -> Dict[str, Any]:
    """ Ejecuta una página como script; las demás están disponibles para importar """
    paginas = validar_paginas(paginas)
    if not any(p["nombre"] == nombre for p in paginas):
        raise ErrorDesafio(f"No hay ninguna página «{nombre}».")
    with Carpeta(paginas, {"pytest.py": PYTEST_MINIMO}) as carpeta:
        r = runner.run_file(os.path.join(carpeta, nombre), cwd=carpeta, timeout=timeout, run_id=run_id)
        stderr = (r.get("stderr") or "").replace(carpeta + os.sep, "")
    return {"ok": bool(r.get("success")), "stdout": r.get("stdout") or "", "stderr": stderr,
            "elapsed": r.get("elapsed", 0), "cancelado": bool(r.get("cancelled"))}


def comprobar(runner, paginas: List[Dict[str, Any]], privado: Dict[str, Any], timeout: int = 30,
              run_id: Optional[str] = None) -> Dict[str, Any]:
    """ Pasa las pruebas ocultas a las páginas.

    privado["comprobacion"] = {"tipo": "unittest", "archivos": {nombre: contenido}}
                            | {"tipo": "doctest", "modulo": m, "ejemplos": texto}
                            | {"tipo": "asserts", "asserts": [fragmentos]}
                            | {"tipo": "ninguna"}
    """
    paginas = validar_paginas(paginas)
    c = (privado or {}).get("comprobacion") or {"tipo": "ninguna"}
    if c.get("tipo") == "ninguna":
        return {"aprobado": False, "comprobable": False, "total": 0, "pasados": 0, "fallos": [],
                "error": None, "stdout": "", "stderr": "", "elapsed": 0}
    extras = {"pytest.py": PYTEST_MINIMO, "_prig_comprobar.py": ARNES}
    config: Dict[str, Any] = {"tipo": c["tipo"]}
    if c["tipo"] == "unittest":
        archivos = c.get("archivos") or {}
        choque = [n for n in archivos if n in {p["nombre"] for p in paginas}]
        if choque:
            raise ErrorDesafio(f"Una página no puede llamarse como las pruebas: {', '.join(choque)}")
        extras.update(archivos)
        config["modulos"] = [n[:-3] for n in archivos if n.endswith(".py")]
    elif c["tipo"] == "doctest":
        config.update(modulo=c["modulo"], ejemplos=c["ejemplos"])
    elif c["tipo"] == "asserts":
        config["asserts"] = list(c.get("asserts") or [])
    else:
        raise ErrorDesafio(f"Tipo de comprobación desconocido: {c.get('tipo')}")
    extras["_prig_config.json"] = json.dumps(config, ensure_ascii=False)

    with Carpeta(paginas, extras) as carpeta:
        r = runner.run_file(os.path.join(carpeta, "_prig_comprobar.py"), cwd=carpeta, timeout=timeout,
                            run_id=run_id or f"desafio_{uuid.uuid4().hex[:8]}")
        stdout = r.get("stdout") or ""
        stderr = (r.get("stderr") or "").replace(carpeta + os.sep, "")

    datos = None
    if MARCA in stdout:
        try:
            datos = json.loads(stdout.rsplit(MARCA, 1)[1].strip().splitlines()[0])
        except (ValueError, IndexError):
            datos = None
    if datos is not None:
        # La carpeta temporal no le dice nada al alumno
        limpiar = lambda t: t.replace(carpeta + os.sep, "") if isinstance(t, str) else t
        datos["error"] = limpiar(datos.get("error"))
        datos["fallos"] = [{k: limpiar(v) for k, v in f.items()} for f in datos.get("fallos", [])]
    if datos is None:
        motivo = "La comprobación no terminó."
        if "Tiempo límite" in stderr:
            motivo = f"Tardó más de {timeout} s: revisa si hay un bucle que no termina."
        elif r.get("cancelled"):
            motivo = "Comprobación detenida."
        return {"aprobado": False, "comprobable": True, "total": 0, "pasados": 0, "fallos": [],
                "error": motivo, "stdout": stdout[-3000:], "stderr": stderr[-3000:], "elapsed": r.get("elapsed", 0)}

    aprobado = datos["error"] is None and datos["total"] > 0 and datos["pasados"] == datos["total"]
    return {"aprobado": aprobado, "comprobable": True, "total": datos["total"], "pasados": datos["pasados"],
            "fallos": datos["fallos"][:20], "error": datos["error"], "stdout": datos.get("stdout", ""),
            "stderr": stderr[-3000:], "elapsed": r.get("elapsed", 0)}


def validar_desafio(runner, iniciales: List[Dict[str, Any]], referencia: List[Dict[str, Any]],
                    privado: Dict[str, Any], minimo_pruebas: int = 1) -> Dict[str, Any]:
    """ Un desafío vale si la referencia pasa TODO y el código de partida NO.

    La segunda condición descarta pruebas que no comprueban nada (assert True), que
    los modelos pequeños generan a menudo. """
    try:
        iniciales = validar_paginas(iniciales)
        referencia = validar_paginas(referencia)
    except ErrorDesafio as e:
        return {"valido": False, "motivo": str(e)}
    if sorted(p["nombre"] for p in iniciales) != sorted(p["nombre"] for p in referencia):
        return {"valido": False, "motivo": "La solución de referencia no tiene las mismas páginas que el código de partida."}
    ref = comprobar(runner, referencia, privado)
    if not ref["aprobado"]:
        detalle = ref["error"] or (ref["fallos"][0]["mensaje"] if ref["fallos"] else "")
        return {"valido": False, "motivo": f"La solución de referencia no pasa sus pruebas ({ref['pasados']}/{ref['total']}). {detalle}".strip(),
                "referencia": ref}
    if ref["total"] < minimo_pruebas:
        return {"valido": False, "motivo": f"Tiene {ref['total']} pruebas; hacen falta al menos {minimo_pruebas}.", "referencia": ref}
    inicial = comprobar(runner, iniciales, privado)
    if inicial["aprobado"]:
        return {"valido": False, "motivo": "Las pruebas pasan también con el código de partida: no comprueban nada.",
                "referencia": ref, "inicial": inicial}
    return {"valido": True, "motivo": "OK", "pruebas": ref["total"], "referencia": ref, "inicial": inicial}
