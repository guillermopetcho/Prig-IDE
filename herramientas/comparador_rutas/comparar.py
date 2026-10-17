"""
Comparador de rutas: la misma petición al backend de Python y al servidor de Rust (que la atiende él o la pasa a
Python por el proxy) tiene que dar la misma respuesta. Es la red de seguridad para mover rutas de Python a Rust.

Todo corre aislado: un HOME temporal (la configuración, los desafíos y la biblioteca del usuario no se tocan), un
proyecto de prueba, puertos libres y el proxy de red apuntando a ninguna parte. El backend de prueba no cierra los
llama-server del Prig que esté abierto (PRIG_SIN_LIMPIAR_HUERFANOS=1) ni usa pkexec. Solo se hacen peticiones que
leen o que escriben dentro del HOME temporal: nada que genere con un modelo, descargue o arranque servidores.

    .venv/bin/python herramientas/comparador_rutas/comparar.py [--casos casos.json] [--solo /api/tree,...]
                                                              [--desafios carpeta_con_json]

Sale con 0 si todo coincide; con 1 y las diferencias si no.
"""
import argparse
import json
import re
import os
import shutil
import signal
import socket
import threading
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(AQUI))
SERVIDOR = os.path.join(RAIZ, "backend-rust", "target", "release", "prig-server")
PYTHON = os.path.join(RAIZ, ".venv", "bin", "python")

# Claves que cambian de una llamada a otra (horas, duraciones, medidas en vivo): se comparan solo por tipo
VOLATILES = {"avg_seconds_to_green", "ts", "elapsed", "guardado", "rendido", "empezado", "creado", "resuelto", "cuando", "segundos_hasta_resolver", "timestamp", "ts", "elapsed_ms", "duracion_ms", "ms", "segundos", "uptime", "cpu_percent", "fecha",
             "actualizado", "momento", "hora", "ahora", "generado", "libre_mb"}


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def esperar(url: str, proc, segundos: float = 60) -> bool:
    limite = time.time() + segundos
    while time.time() < limite:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(0.2)
    return False


def pedir(base: str, caso: dict):
    datos = None
    cab = {"Content-Type": "application/json"}
    if "json" in caso:
        datos = json.dumps(caso["json"]).encode()
    elif "crudo" in caso:
        datos = caso["crudo"].encode()
    req = urllib.request.Request(base + caso["ruta"], data=datos, headers=cab, method=caso.get("metodo", "GET"))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            estado, cuerpo, tipo = r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        estado, cuerpo, tipo = e.code, e.read(), e.headers.get("Content-Type", "")
    if "ndjson" in tipo:
        # una línea JSON por evento: se comparan como JSON (así valen los volátiles)
        try:
            return estado, ("json", [normalizar(json.loads(l)) for l in cuerpo.decode().splitlines() if l.strip()])
        except ValueError:
            pass
    if "json" in tipo:
        try:
            return estado, ("json", normalizar(json.loads(cuerpo)))
        except ValueError:
            pass
    return estado, ("bytes", cuerpo)


# Volátiles del caso en curso: claves extra y contenedores cuyos VALORES cambian (p. ej. `completion_dates`, con la
# hora en que se marcó cada bloque bajo el id del bloque)
VOLATILES_CASO = set()
CONTENEDORES_CASO = set()
# La vista previa de exportación: Python resalta con pygments y Rust con syntect; se compara todo menos ese bloque
SIN_RESALTADO = [False]
RESALTADO = re.compile(r'<div class="highlight" style="[^"]*"><pre style="line-height: 125%;"><span></span>.*?</pre></div>\n', re.S)


def normalizar(v):
    if isinstance(v, dict):
        return {k: (type(x).__name__ if k in VOLATILES or k in VOLATILES_CASO
                    else {kk: type(xx).__name__ for kk, xx in x.items()} if k in CONTENEDORES_CASO and isinstance(x, dict)
                    else normalizar(x)) for k, x in v.items()}
    if isinstance(v, list):
        return [normalizar(x) for x in v]
    if isinstance(v, str) and SIN_RESALTADO[0]:
        return RESALTADO.sub("<resaltado>", v)
    return v


def diferencia(a, b, ruta="") -> str:
    """ La primera diferencia, con su camino dentro del JSON """
    if type(a) is not type(b):
        return f"{ruta or '.'}: {type(a).__name__} {str(a)[:120]!r} ≠ {type(b).__name__} {str(b)[:120]!r}"
    if isinstance(a, dict):
        if list(a) != list(b):
            return f"{ruta or '.'}: claves {list(a)[:15]} ≠ {list(b)[:15]}"
        for k in a:
            d = diferencia(a[k], b[k], f"{ruta}.{k}")
            if d:
                return d
        return ""
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{ruta or '.'}: {len(a)} elementos ≠ {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = diferencia(x, y, f"{ruta}[{i}]")
            if d:
                return d
        return ""
    if a == b:
        return ""
    if isinstance(a, str) and isinstance(b, str) and len(a) > 160:
        # un texto largo: lo que hay alrededor de la primera diferencia
        i = next((n for n, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        return f"{ruta or '.'} (carácter {i}): {a[max(0, i - 60):i + 100]!r} ≠ {b[max(0, i - 60):i + 100]!r}"
    return f"{ruta or '.'}: {str(a)[:160]!r} ≠ {str(b)[:160]!r}"


def copia_de_prig(tmp: str) -> str:
    """ Prig aislado: las rutas que escriben (la configuración de `.prig_dataset/`, que vive dentro de Prig) no tocan
    la de verdad. Se copian `backend` y `.prig_dataset`; lo que solo se lee se enlaza """
    copia = os.path.join(tmp, "prig")
    os.makedirs(copia)
    # PRIG_COMPARADOR_BACKEND: otro backend de Python (p. ej. el del último commit, para recomparar rutas retiradas)
    shutil.copytree(os.environ.get("PRIG_COMPARADOR_BACKEND") or os.path.join(RAIZ, "backend"), os.path.join(copia, "backend"),
                    ignore=shutil.ignore_patterns("__pycache__", ".index"))
    if os.path.isdir(os.path.join(RAIZ, ".prig_dataset")):
        shutil.copytree(os.path.join(RAIZ, ".prig_dataset"), os.path.join(copia, ".prig_dataset"))
    for nombre in os.listdir(RAIZ):
        if nombre not in ("backend", ".prig_dataset", ".git", "__pycache__"):
            os.symlink(os.path.join(RAIZ, nombre), os.path.join(copia, nombre))
    return copia


def preparar(tmp: str) -> dict:
    """ HOME temporal y un proyecto de prueba con un poco de todo """
    home = os.path.join(tmp, "home")
    proyecto = os.path.join(tmp, "proyecto")
    os.makedirs(home)
    archivos = {
        "main.py": "import os\n\n\ndef saludar(nombre):\n    return f'hola {nombre}'\n\n\nclass Pila:\n    pass\n",
        "lib/util.py": "def sumar(a, b):\n    return a + b\n# TODO revisar\n",
        "lib/__init__.py": "",
        "docs/leeme.md": "# Proyecto\n\nTexto con ñ y «comillas».\n",
        "datos/tabla.csv": "a,b\n1,2\n",
        "web/app.js": "function hola() { return 1 }\n",
        "notas.txt": "saludar aquí\n",
        ".oculto/x.txt": "x\n",
    }
    # libros en la carpeta personal, para el explorador
    for ruta in ("Documentos/Libro de cálculo.pdf", "Documentos/apuntes/redes neuronales.epub", "Descargas/paper.pdf",
                 "Descargas/.oculto.pdf", "Descargas/foto.png", "Escritorio/nota.txt"):
        destino = os.path.join(home, ruta)
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        with open(destino, "wb") as f:
            f.write(b"%PDF-1.4 x" * 10)
    for ruta, texto in archivos.items():
        destino = os.path.join(proyecto, ruta)
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        with open(destino, "w", encoding="utf-8") as f:
            f.write(texto)
    env = os.environ.copy()
    env.update({
        "HOME": home, "PRIG_SIN_LIMPIAR_HUERFANOS": "1", "PRIG_ENERGIA_SIN_PKEXEC": "1",
        "PRIG_DESAFIOS_DIR": os.path.join(home, ".prig_desafios"),
        "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost",
        "RUST_LOG": "warn",
        # El motor suave nunca toca el Ollama de Prig de verdad (lib/ es un enlace a la carpeta real)
        "PRIG_SIN_MOTOR_SUAVE": "1", "PRIG_OLLAMA_LIB": os.path.join(home, "ollama_lib"),
        "PRIG_SUAVE_SO": os.path.join(home, "prig_suave.so"), "PRIG_SUAVE_CONTROL": os.path.join(home, "prig_suave"),
    })
    return {"home": home, "proyecto": proyecto, "env": env}


def sembrar_desafios(home: str):
    """ Desafíos de prueba con cada tipo de comprobación """
    d = os.path.join(home, ".prig_desafios", "desafios")
    os.makedirs(d, exist_ok=True)
    base = lambda id_, comp, paginas, **extra: {"id": id_, "titulo": f"prueba {id_}", "conceptos": ["pilas", "listas"],
                                                "paginas": paginas, "privado": {"comprobacion": comp, "referencia": paginas},
                                                "progreso": {"estado": "nuevo", "intentos": 0, "pistas": 1}, **extra}
    py = [{"nombre": "sol.py", "contenido": "def doble(x):\n    return 2 * x\n"}]
    desafios = [
        base("des_aaaaaaaaa1", {"tipo": "unittest", "archivos": {"test_sol.py": "import unittest\nfrom sol import doble\n"
             "class T(unittest.TestCase):\n    def test_uno(self):\n        self.assertEqual(doble(2), 4)\n"
             "    def test_dos(self):\n        self.assertEqual(doble(3), 6)\n"}}, py),
        base("des_aaaaaaaaa2", {"tipo": "doctest", "modulo": "sol", "ejemplos": ">>> from sol import doble\n>>> doble(5)\n10\n>>> doble(0)\n0\n"}, py),
        base("des_aaaaaaaaa3", {"tipo": "asserts", "asserts": ["from sol import doble\nassert doble(1) == 2", "from sol import doble\nassert doble(-1) == -2, 'negativos'"]}, py),
        base("des_aaaaaaaaa4", {"tipo": "ninguna"}, py),
        base("des_aaaaaaaaa5", {"tipo": "cpp_asserts", "asserts": ["doble(2) == 4", "REQUIRE(doble(3) == 6)"]},
             [{"nombre": "sol.h", "contenido": "inline int doble(int x) { return 2 * x; }\n"}]),
        base("des_aaaaaaaaa6", {"tipo": "asserts", "asserts": ["assert True"]}, py,
             origen={"tipo": "prig-hub", "ref": "ana/Prig-ml#pilas", "version": "1.2"}),
    ]
    for x in desafios:
        with open(os.path.join(d, x["id"] + ".json"), "w", encoding="utf-8") as f:
            json.dump(x, f, ensure_ascii=False, indent=1)


def sembrar_buscador(home: str):
    """ Dos modelos seguidos y una revisión de actualizaciones reciente (sin red no se puede llegar a ellos) """
    import time
    datos = {"seguidos": {
        "ollama:qwen3": {"fuente": "ollama", "id": "qwen3", "titulo": "Qwen 3", "desde": "2026-01-02T03:04:05",
                         "instantanea": {"8b": {"bytes": 5000, "digest": "abc"}}, "cambios": {"nuevas": ["14b"], "retiradas": [], "cambiadas": []},
                         "revisado": "2026-01-02T03:04:05"},
        "huggingface:Qwen/Qwen3-8B-GGUF": {"fuente": "huggingface", "id": "Qwen/Qwen3-8B-GGUF", "titulo": "Qwen/Qwen3-8B-GGUF",
                                           "desde": "2026-01-02T03:04:05", "instantanea": {}, "cambios": None, "revisado": "2026-01-02T03:04:05"}},
        "actualizaciones": {"marca": time.time(), "fecha": "2026-01-02T03:04:05", "actualizables": 1,
                            "modelos": [{"modelo": "qwen2.5-coder:7b", "fuente": "ollama", "estado": "actualizable", "bytes": 9, "local": "a", "remoto": "b"},
                                        {"modelo": "mio:1b", "fuente": "ollama", "estado": "local", "detalle": "x"}]}}
    with open(os.path.join(home, ".prig_buscador.json"), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)


def sembrar_exportar(proyecto: str):
    """ Una carpeta para exportar a PDF: código, un cuaderno con salidas, carpetas que se ignoran """
    raiz = os.path.join(proyecto, "exportar")
    def escribir(rel, texto):
        ruta = os.path.join(raiz, rel)
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8", newline="") as f:
            f.write(texto)
    escribir("a.py", "def f(x):\n    return x * 2  # doble <ñ>\n\nprint(f'{f(2)}')")
    escribir("b.js", "const a = 1;\r\nconsole.log(a);\r\n")
    escribir("sub/notas.md", "# Título\n\n**negrita** y `código`\n")
    escribir("sub/vacio.sql", "")
    escribir("node_modules/x.js", "x\n")
    escribir(".oculto/y.py", "y\n")
    escribir(".z.py", "z\n")
    escribir("leeme.txt", "no es código\n")
    nb = {"cells": [
        {"cell_type": "markdown", "metadata": {}, "source": ["# Cuaderno\n", "Con *énfasis* y <html> & más"]},
        {"cell_type": "code", "execution_count": 3, "metadata": {}, "source": ["import math\n", "print(math.pi)"],
         "outputs": [{"output_type": "stream", "name": "stdout", "text": ["3.14 <b>\n"]}]},
        {"cell_type": "code", "execution_count": None, "metadata": {}, "source": ["1/0"],
         "outputs": [{"output_type": "error", "ename": "ZeroDivisionError", "evalue": "division by zero", "traceback": ["ZeroDivisionError <x>"]}]},
        {"cell_type": "code", "execution_count": 0, "metadata": {}, "source": "x", "outputs": [
            {"output_type": "display_data", "data": {"text/html": ["<b>hola</b>"]}, "metadata": {}},
            {"output_type": "display_data", "data": {"image/png": "aGV5\n"}, "metadata": {}}]}],
        "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    escribir("cuaderno.ipynb", json.dumps(nb))
    escribir("roto.ipynb", "{no")


def sembrar_kaggle_datos(proyecto: str, home: str):
    """ Datos de Kaggle «descargados» en el proyecto: tablas con comillas y huecos, una imagen, una carpeta sin registro """
    raiz = os.path.join(proyecto, "kaggle_datos")
    def escribir(rel, datos, modo="w"):
        ruta = os.path.join(raiz, rel)
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, modo, **({} if "b" in modo else {"encoding": "utf-8", "newline": ""})) as f:
            f.write(datos)
    filas = ["PassengerId,Name,Age,Fare,Sex"]
    for i in range(1, 60):
        filas.append(f'{i},"Persona {i}, Sr.",{"" if i % 7 == 0 else 20 + i % 30},{i * 1.5:.2f},{"male" if i % 3 else "female"}')
    escribir("titanic/train.csv", "\r\n".join(filas) + "\r\n")
    escribir("titanic/sub/notas.txt", "Notas del dataset — ñandú\n" * 3)
    escribir("titanic/foto.png", b"\x89PNG\r\n\x1a\nfalso", "wb")
    escribir("titanic/datos.tsv", "a\tb\n1\tNA\n2\t3\n")
    escribir("titanic/raro.csv", "x;y\n1,5;inf\n2;3\n")
    escribir("titanic/punto.csv", "v\n1_000\n2.5\n-3e2\n")
    escribir("suelta/a.bin", b"\x00\x01", "wb")
    os.makedirs(os.path.join(home, ".prig_kaggle"), exist_ok=True)
    with open(os.path.join(home, ".prig_kaggle", "descargas.json"), "w") as f:
        json.dump({os.path.join(raiz, "titanic"): {"tipo": "competicion", "ref": "titanic", "fecha": "2026-10-05T10:00:00"}}, f)


def sembrar_ejercicios(proyecto: str):
    """ Ejercicios guardados en el proyecto de prueba (como los deja exercise_store.py) """
    d = os.path.join(proyecto, ".prig_dataset")
    os.makedirs(d, exist_ok=True)
    ej = lambda i, concepto, fecha: {"exercise_id": f"ex_{i}", "concept": concepto, "title": f"Ejercicio {i}",
                                     "statement": "Escribe doble(x)", "function_name": "doble",
                                     "starter_code": "def doble(x):\n    pass\n",
                                     "reference_solution": "def doble(x):\n    return 2 * x\n",
                                     "tests": "assert doble(2) == 4\nassert doble(-3) == -6\n", "created_at": fecha}
    datos = {"ex_1": ej(1, "funciones", "2026-10-01T10:00:00"), "ex_2": ej(2, "bucles", "2026-10-03T10:00:00"),
             "ex_3": {**ej(3, "funciones", "2026-10-02T10:00:00"), "attempts_used": 2}}
    with open(os.path.join(d, "exercises.json"), "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)


def sembrar_guiado(proyecto: str):
    """ Seguimientos y planes de estudio en el proyecto de prueba """
    seg = os.path.join(proyecto, ".prig_seguimientos")
    os.makedirs(seg, exist_ok=True)
    escribir = lambda ruta, datos: open(ruta, "w", encoding="utf-8").write(datos if isinstance(datos, str) else json.dumps(datos))
    escribir(os.path.join(seg, "seg_aaaa0001.json"), {"id": "seg_aaaa0001", "goal": "Aprender pandas", "created_at": "2026-10-02T10:00:00",
                                                      "source": "profundo", "blocks": [{"title": "a"}, {"title": "b"}, {"title": "c"}],
                                                      "completed_blocks": ["x"]})
    escribir(os.path.join(seg, "seg_aaaa0002.json"), {"id": "seg_aaaa0002", "goal": "Redes", "created_at": "2026-10-05T10:00:00",
                                                      "blocks": [{"title": "a"}, {"title": "b"}], "completed_blocks": ["a"]})
    escribir(os.path.join(seg, "seg_aaaa0003.json"), {"id": "seg_aaaa0003", "goal": "Nulo", "blocks": None})
    escribir(os.path.join(seg, "seg_aaaa0004.json"), "{roto")
    escribir(os.path.join(seg, "seg_aaaa0005.json"), {"id": "seg_aaaa0005", "goal": "Sin fecha", "blocks": [], "completed_blocks": []})
    # v1 (sin marca de esquema): se migra al leerla; bloques con id fijo para que la vista no tenga nada al azar
    escribir(os.path.join(seg, "seg_aaaa0006.json"), {"id": "seg_aaaa0006", "goal": "Álgebra", "created_at": "2026-10-03T10:00:00",
                                                      "blocks": [{"block_id": "b1", "title": "Vectores", "topics": "suma, producto,,"},
                                                                 {"block_id": "b2", "learning_objective": " Matrices ", "topics": []}],
                                                      "completed_blocks": ["b1"], "extra": 1})
    escribir(os.path.join(seg, "seg_aaaa0007.json"), {"schema_version": 9, "id": "seg_aaaa0007", "goal": "Futuro"})
    escribir(os.path.join(seg, "seg_aaaa0008.json"), {"schema_version": "3", "id": "seg_aaaa0008", "goal": "Texto",
                                                      "created_at": "2026-10-01T10:00:00", "completion_dates": {"b": "x"}})
    planes = os.path.join(proyecto, ".prig_plans")
    os.makedirs(os.path.join(planes, "plan_nuevo"), exist_ok=True)
    escribir(os.path.join(planes, "plan_nuevo", "manifest.json"), {"plan_id": "plan_nuevo", "user_goal": "SQL", "current_version": 3,
                                                                  "status": "APPROVED", "updated_at": "2026-10-04T10:00:00"})
    # un plan entero (con currículo y cuadernos), ids y fechas fijos: nada al azar
    os.makedirs(os.path.join(planes, "plan_completo"), exist_ok=True)
    completo = {"schema_version": 2, "plan_id": "plan_completo", "version": 1, "status": "APPROVED",
                "user_goal": "Aprender SQL con pandas",
                "practical_curriculum": {"curriculum_id": "curr_1", "modules": [
                    {"module_id": "m1", "name": "Consultas", "objective": "Consultar", "validation_criteria": ["c1", "c2"]}]},
                "executable_learning_plan": {"plan_id": "exec_1", "modules_notebooks": [
                    {"module_id": "m1", "module_name": "Consultas", "notebooks": [
                        {"notebook_id": "nb1", "title": "Uno", "action": "copy", "executable_path": "a.ipynb"},
                        {"notebook_id": "nb2", "title": "Dos", "action": "nuevo", "executable_path": "b.ipynb"}]}]},
                "completed_notebooks": ["nb1"], "created_at": "2026-10-01T09:00:00", "updated_at": "2026-10-02T09:00:00"}
    escribir(os.path.join(planes, "plan_completo", "current.json"), completo)
    escribir(os.path.join(planes, "plan_completo", "manifest.json"), {"plan_id": "plan_completo", "user_goal": "Aprender SQL con pandas",
                                                                     "current_version": 1, "status": "APPROVED",
                                                                     "updated_at": "2026-10-02T09:00:00"})
    # un borrador con fechas fijas para la cadena de los agentes (cada caso parte de lo que dejó Rust en el anterior)
    os.makedirs(os.path.join(planes, "plan_borrador"), exist_ok=True)
    escribir(os.path.join(planes, "plan_borrador", "current.json"), {"schema_version": 2, "plan_id": "plan_borrador", "version": 1,
                                                                    "status": "DRAFT", "user_goal": "Dominar SQL 'avanzado'",
                                                                    "created_at": "2026-10-05T09:00:00", "updated_at": "2026-10-05T09:00:00"})
    escribir(os.path.join(planes, "plan_borrador", "v1.json"), {"schema_version": 2, "plan_id": "plan_borrador", "version": 1,
                                                               "status": "DRAFT", "user_goal": "Primera versión",
                                                               "created_at": "2026-10-05T09:00:00", "updated_at": "2026-10-05T09:00:00"})
    escribir(os.path.join(planes, "plan_viejo.json"), {"plan_id": "plan_viejo", "user_goal": "Estadística", "version": 2,
                                                       "updated_at": "2026-09-01T10:00:00"})


def pdf_minimo(paginas) -> bytes:
    """ Un PDF de verdad, hecho a mano: una página por texto, en Helvetica """
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", None, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for t in paginas:
        flujo = ("BT /F1 14 Tf 20 150 Td (" + t + ") Tj ET").encode("latin-1")
        objs.append(b"<< /Length " + str(len(flujo)).encode() + b" >>\nstream\n" + flujo + b"\nendstream")
        objs.append(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] /Contents %d 0 R /Resources << /Font << /F1 3 0 R >> >> >>" % len(objs)).encode())
        kids.append("%d 0 R" % len(objs))
    objs[1] = ("<< /Type /Pages /Kids [" + " ".join(kids) + "] /Count %d >>" % len(paginas)).encode()
    salida, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(salida))
        salida += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(salida)
    salida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    salida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return salida


def sembrar_kb(home: str):
    """ Una base de conocimiento con tres libros (paquetes de prueba importados, unificados, con dosieres y compilada).
    Se hace con el backend de Python en un proceso aparte, con el HOME temporal """
    codigo = r'''
import sys, os
sys.path.insert(0, "tests")
from test_pack_importer import hacer_pack
from knowledge_base import KnowledgeBase
from pack_importer import PackImporter
from contexto_modelo import CompiladorContexto
p = os.path.join(os.path.expanduser("~"), "packs_prueba"); os.makedirs(p, exist_ok=True)
hacer_pack(p, "bk_math", "Calculo (Apostol)", "math",
    claims=[("DEFINITION","gradiente","El gradiente es el vector de derivadas parciales de la función.","el vector de las derivadas parciales",10),
            ("FORMULA","gradiente","La fórmula es ∇f = (∂f/∂x, ∂f/∂y) en el plano.","nabla f",11),
            ("DEFINITION","regla de la cadena","La regla de la cadena da la derivada de una composición de funciones.","(f o g)' = f'(g) g'",20),
            ("PITFALL","gradiente","Un error frecuente es confundir el gradiente con la derivada direccional.","no confundir",12)],
    concepts=[("gradiente",["grad","vector gradiente"]),("regla de la cadena",["chain rule"])],
    relations=[("gradiente","regla de la cadena","REQUIRES","se construye con ella")], symbols=[("nabla","gradiente",10)])
hacer_pack(p, "bk_dl", "Deep Learning (Goodfellow)", "deep_learning",
    claims=[("INTUITION","gradiente","En redes, el gradiente dice cuánto cambia la pérdida al mover un peso.","gradiente de la perdida",80),
            ("DEFINITION","regularizacion L2","La regularización L2 penaliza la norma de los pesos del modelo.","norma L2 de los pesos",90)],
    concepts=[("gradiente",["gradientes"]),("regularizacion L2",["weight decay"])])
hacer_pack(p, "bk_ml", "Bishop", "machine_learning",
    claims=[("DEFINITION","regularizacion L2","Se conoce como ridge y reduce el sobreajuste del modelo.","known as ridge regression",5)],
    concepts=[("regularizacion L2",["ridge","ridge regression"])])
kb = KnowledgeBase(); imp = PackImporter(kb)
imp.importar_carpeta(p); imp.unificar(); imp.construir_dosieres(); CompiladorContexto(kb).precompilar()
# una ficha de libro (con SQL, como la guarda la ficha: JSON sin escapar)
import json, sqlite3
ficha = {"source_id": "bk_math", "titulo": "Calculo (Apostol)", "campo": "math", "paginas": 100, "construida": "2026-10-01T10:00:00", "modelos": ["m"],
         "temario": {"capitulos": [{"capitulo": 1, "titulo": "Límites", "paginas": "1-20", "dificultad": 2}, {"capitulo": 2, "titulo": "Derivadas"}, "suelto"]},
         "asume": {"asume": [{"tema": "álgebra", "gravedad": "alta"}, "trigonometría", {"x": 1, "y": True}]},
         "identidad": {"nivel": "intermedio", "que_cubre": "cálculo de una variable"}, "lagunas": ["integrales múltiples"]}
with sqlite3.connect(kb.ruta) as c:
    c.execute("INSERT OR REPLACE INTO book_profiles VALUES (?,?,?,?);", ("bk_math", json.dumps(ficha, ensure_ascii=False), "2026-10-01T10:00:00", '["m"]'))
# en la carpeta de paquetes de Prig: uno ya importado, uno nuevo y uno roto (para verificar e importar)
q = os.path.join(os.path.expanduser("~"), ".prig_books", "packs"); os.makedirs(q, exist_ok=True)
import shutil; shutil.copy(os.path.join(p, "bk_ml.prigpack"), q)
hacer_pack(q, "bk_nuevo", "Optimizacion", "math", claims=[("DEFINITION","convexidad","Una función convexa tiene un único mínimo.","convexa",3)],
           concepts=[("convexidad",["convexa"])])
hacer_pack(q, "bk_roto", "Roto", "nada", claims=[("DEFINITION","x","t","q",1)], concepts=[("x",[])], romper_checksum=True)
open(os.path.join(q, "no_es.prigpack"), "w").write("no zip")
'''
    subprocess.run([os.path.join(RAIZ, ".venv", "bin", "python"), "-c", codigo], cwd=os.path.join(RAIZ, "backend"),
                   env={**os.environ, "HOME": home}, check=True, capture_output=True)


def sembrar_biblioteca(home: str):
    """ Una biblioteca con fichas, un elemento quitado, carpetas y proyectos guardados (dentro y fuera) """
    lib = os.path.join(home, ".prig_books")
    def escribir(rel, texto):
        ruta = os.path.join(lib, rel)
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        open(ruta, "w", encoding="utf-8").write(texto)
    escribir("books/Álgebra_lineal-2ed.pdf", "%PDF falso")
    escribir("books/sin ficha.txt", "texto")
    escribir("books/oculto.pdf", "%PDF quitado")
    escribir("documentation/notas.md", "# notas")
    escribir("papers/x.pdf", "%PDF")
    escribir("code/script.py", "print(1)")
    escribir("datasets/d.csv", "a,b")
    escribir("projects/repo/a.py", "x = 1")
    escribir("suelto_arxiv.pdf", "%PDF")
    escribir("suelto.csv", "1")
    escribir("raro.xyz", "no se muestra")
    escribir(".escondido.md", "no se muestra")
    escribir("metadata/books__Álgebra_lineal-2ed.pdf.json", json.dumps({"title": "Álgebra lineal", "topics": ["vectores"]}))
    escribir("metadata/notas.md.json", json.dumps({"title": "", "analysis_failed": True}))
    escribir("metadata/projects__repo.json", json.dumps({}))
    # el lector de libros: un PDF de verdad, citas, recortes, una ficha y una página corregida
    ruta_pdf = os.path.join(lib, "books", "Redes_neuronales.pdf")
    with open(ruta_pdf, "wb") as f:
        f.write(pdf_minimo(["Hola mundo, primera pagina de redes", "Segunda pagina: gradiente y redes", "Tercera sin nada"]))
    escribir("metadata/books__Redes_neuronales.pdf.json", json.dumps({"title": "Redes neuronales", "topics": ["redes"]}, ensure_ascii=False))
    escribir("citas/Redes_neuronales.json", json.dumps({"libro": "Redes_neuronales.pdf", "titulo": "Redes neuronales", "stem": "Redes_neuronales",
        "archivo_json": "Redes_neuronales.json", "total_citas": 2, "citas": [
            {"id": "c1", "pagina": 2, "texto": "El gradiente descendente", "nota": "clave", "tags": ["optimizacion"]},
            {"id": "c0", "pagina": 1, "texto": "Una neurona", "nota": "", "tags": "basico"}]}, ensure_ascii=False, indent=2))
    escribir("citas/rota.json", "{mal")
    escribir("citas/ediciones/Redes_neuronales_p3.txt", "Página corregida a mano\r\n")
    escribir("snippets.json", json.dumps({"snp_1": {"id": "snp_1", "book_id": "x", "page": 2, "text": "t"}}))
    escribir("projects/repo/sub/b.py", "y = 2")
    escribir("projects/repo/.oculto", "z")
    escribir("documentation/crlf.md", "uno\r\ndos\rtres")
    escribir("notebooks/n.ipynb", json.dumps({"cells": [{"cell_type": "markdown", "source": ["# T\n", "texto"]}, {"cell_type": "code", "source": "print(1)"}]}))
    # librerías: una propia, citas con tipos raros y un archivo roto
    escribir("librerias/lista_librerias.json", json.dumps([{"id": "datasets", "nombre": "Datasets", "repo": "huggingface/datasets"}], indent=2))
    escribir("librerias/pandas.json", json.dumps({"libreria": "pandas", "nombre": "Pandas", "total_citas": 3, "citas": [
        {"id": "p1", "tema": "Agrupar con groupby", "funcion": "DataFrame.groupby", "explicacion": "agrupa filas", "tags": ["agrupar", "Tablas"]},
        {"id": "p2", "tema": "Unir tablas", "funcion": "merge", "explicacion": "join", "tags": "uniones"},
        {"id": "p3", "tema": 5, "funcion": "x"}]}, ensure_ascii=False, indent=2))
    escribir("librerias/rota.json", "{no es json")
    escribir(".index/ocultos.json", json.dumps({"version": 1, "ocultos": [
        {"ruta": os.path.join(lib, "books", "oculto.pdf"), "titulo": "oculto", "categoria": "books", "proyecto": False,
         "quitado_en": "2026-10-01T10:00:00"},
        {"ruta": os.path.join(home, "externo_quitado"), "titulo": "q", "categoria": "projects", "proyecto": True,
         "quitado_en": "2026-10-01T10:00:00"}]}))
    for d in ("externo", "externo_quitado"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    cfg = os.path.join(home, ".prig_config.json")
    datos = json.load(open(cfg)) if os.path.exists(cfg) else {}
    datos["saved_projects"] = [{"path": os.path.join(home, "externo"), "name": "Externo"},
                               os.path.join(home, "externo_quitado"),
                               {"path": os.path.join(home, "no_existe")}]
    json.dump(datos, open(cfg, "w"))


def kaggle_falso() -> str:
    """ Una API de Kaggle falsa (sin red): las rutas que usa Prig, con datos fijos. Acepta solo las credenciales de
    prueba (el token, «ana:clave-buena» y la cuenta sembrada «ana:clave-falsa») """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import base64, io, zipfile
    from urllib.parse import urlparse, parse_qs

    celdas = [
        {"cell_type": "markdown", "source": ["# Titanic\n", "Análisis"]},
        {"cell_type": "code", "source": ["import pandas as pd\n", "df = pd.read_csv('/kaggle/input/titanic/train.csv')\n",
                                         "otro = pd.read_csv('../input/otro-ds/x.csv')\n", "z = open('/kaggle/input/extra-cosa/f.txt')"],
         "outputs": [{"output_type": "stream", "text": ["hola\n"]}, {"output_type": "execute_result", "data": {"text/plain": ["42"]}},
                     {"output_type": "error", "ename": "ValueError", "evalue": "malo"}]},
        {"cell_type": "raw", "source": "nada"},
        {"cell_type": "code", "source": "print(1)\r\nprint(2)", "outputs": []},
    ]
    notebooks = {
        "ana/nb-uno": {"metadata": {"ref": "ana/nb-uno", "title": "Notebook uno", "author": "ana", "totalVotes": 7,
                                    "currentVersionNumber": 3, "language": "python", "kernelType": "notebook",
                                    "lastRunTime": "2026-09-01T10:00:00Z", "enableGpu": True,
                                    "competitionDataSources": ["titanic"], "datasetDataSources": ["ana/otro-ds"]},
                       "blob": {"source": json.dumps({"cells": celdas, "nbformat": 4}), "kernelType": "notebook"}},
        "ana/script-uno": {"metadata": {"ref": "ana/script-uno", "title": "Script", "kernelType": "script"},
                           "blob": {"source": "x = open('/kaggle/input/titanic/test.csv')\n", "kernelType": "script"}},
    }
    kernels = [
        {"ref": "ana/nb-uno", "title": "Notebook uno", "author": "ana", "totalVotes": 7, "lastRunTime": "2026-09-01T10:00:00Z",
         "language": "python", "kernelType": "notebook", "enableGpu": True, "competitionDataSources": ["titanic"]},
        {"ref": "bo/r-nb", "title": "En R", "language": "R"},
        {"ref": "", "title": "sin ref"},
        {"ref": "cy/script", "title": "Script", "language": None, "kernelType": "script", "totalVotes": None,
         "lastRunTime": "2020-01-01T00:00:00Z", "datasetDataSources": ["cy/ds"]},
    ]
    datasets = [{"ref": "ana/otro-ds", "title": "Otro", "subtitle": None, "ownerName": "Ana", "thumbnailImageUrl": "https://img/x.png",
                 "voteCount": 4, "downloadCount": 10, "viewCount": 99, "totalBytes": 1234, "usabilityRating": 0.875,
                 "lastUpdated": "2026-01-01", "licenseName": "CC0", "kernelCount": 2, "tags": [{"name": "csv"}, {"name": ""}],
                 "url": ""},
                {"ref": "bo/ds2", "title": "Dos", "creatorName": "Bo", "usabilityRating": "0.5", "tags": None}]
    competiciones = [{"url": "https://www.kaggle.com/competitions/titanic", "title": "Titanic", "description": "Clásica",
                      "organizationName": "Kaggle", "category": "gettingStarted", "reward": "Knowledge", "teamCount": 15000,
                      "deadline": "2099-01-01T00:00:00Z", "evaluationMetric": "Accuracy", "maxTeamSize": 5,
                      "maxDailySubmissions": 10, "userHasEntered": True, "isKernelsSubmissionsOnly": False,
                      "tags": [{"name": "tabular"}]},
                     {"ref": "vieja", "title": "Vieja", "deadline": "2001-01-01T00:00:00Z"}]

    def zip_de_datos():
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("x.csv", "a,b\n1,2\n")
            z.writestr("sub/y.txt", "hola")
            z.writestr("../fuera.txt", "no")
        return b.getvalue()

    class Kaggle(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def responder(self, estado, datos, tipo="application/json"):
            cuerpo = datos if isinstance(datos, bytes) else json.dumps(datos).encode()
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_GET(self):
            auth = self.headers.get("Authorization") or ""
            buena = auth == "Bearer token_de_prueba_valido_0123456789" or auth in (
                "Basic " + base64.b64encode(b"ana:clave-buena").decode(), "Basic " + base64.b64encode(b"ana:clave-falsa").decode())
            u = urlparse(self.path)
            ruta, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
            if ruta.endswith("/kernels/pull"):
                nb = notebooks.get(f"{q.get('userName')}/{q.get('kernelSlug')}")
                return self.responder(200 if nb else 404, nb or {})
            if not buena and "/datasets/" not in ruta:
                return self.responder(401, {"message": "no"})
            if ruta.endswith("/kernels/list"):
                return self.responder(200, [] if q.get("search") == "titanic" else kernels)
            if ruta.endswith("/datasets/list"):
                return self.responder(200, datasets)
            if "/datasets/view/" in ruta:
                return self.responder(200, {**datasets[0], "description": "Descripción", "currentVersionNumber": 2,
                                            "versions": [{"versionNumber": 2, "creationDate": "2026-01-01", "versionNotes": "v2"}]})
            if "/datasets/list/" in ruta:
                if q.get("pageToken"):
                    return self.responder(200, {"datasetFiles": [{"name": "y.txt", "totalBytes": 4}]})
                return self.responder(200, {"datasetFiles": [{"name": "x.csv", "totalBytes": 9, "description": None,
                                                              "columns": [{"name": "a", "type": "Integer"}, {"name": "b"}]}],
                                            "nextPageToken": "p2"})
            if ruta.endswith("/competitions/list"):
                return self.responder(200, competiciones)
            if "/competitions/data/list/" in ruta:
                return self.responder(200, {"files": [{"name": "train.csv", "totalBytes": 100}, {"name": "test.csv", "totalBytes": None}]})
            if "/datasets/download/" in ruta:
                return self.responder(200, zip_de_datos(), "application/zip")
            if "/competitions/data/download-all/" in ruta:
                return self.responder(403, {"message": "reglas"})
            return self.responder(404, {})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Kaggle)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


def github_falso() -> str:
    """ GitHub falso (sin red): API, «raw» y «codeload» en el mismo servidor """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import io, zipfile
    from urllib.parse import urlparse, parse_qs, unquote

    meta = {"full_name": "ana/Repo", "name": "Repo", "owner": {"login": "ana", "avatar_url": "https://a/ana.png"},
            "description": "Un repo", "stargazers_count": 42, "forks_count": 3, "language": "Python", "topics": ["ml", "cli"],
            "pushed_at": "2026-09-01T00:00:00Z", "license": {"spdx_id": "MIT"}, "default_branch": "main", "size": 120,
            "open_issues_count": 1, "homepage": None, "archived": False, "fork": False, "html_url": "https://github.com/ana/Repo"}
    arbol = {"tree": [{"path": "README.md", "type": "blob", "size": 30, "sha": "aaa111aaa111aaa111"},
                      {"path": "src", "type": "tree"},
                      {"path": "src/main.py", "type": "blob", "size": 40, "sha": "bbb222bbb222bbb222"},
                      {"path": "src/nul.py", "type": "blob", "size": 5, "sha": "ccc333"},
                      {"path": "docs/a b.md", "type": "blob", "size": 4, "sha": None},
                      {"path": "img/logo.png", "type": "blob", "size": 10, "sha": "ddd"},
                      {"path": "datos/grande.csv", "type": "blob", "size": 500000, "sha": "eee"}], "truncated": False}
    crudos = {"README.md": "# Repo\nHola ñandú\n", "src/main.py": "print('hola')\r\nprint(2)\n", "src/nul.py": "a\x00b",
              "docs/a b.md": "doc\n"}

    def zip_repo():
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("Repo-main/", "")
            z.writestr("Repo-main/README.md", "# Repo")
            z.writestr("Repo-main/src/main.py", "print(1)")
            z.writestr("Repo-main/../../fuera.txt", "no")
        return b.getvalue()

    class GitHub(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_PUT(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            return self.responder(201, {})

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            return self.responder(201, {})

        def responder(self, estado, datos, tipo="application/json", cab=None):
            cuerpo = datos if isinstance(datos, bytes) else json.dumps(datos).encode()
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            for k, v in (cab or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def do_GET(self):
            u = urlparse(self.path)
            ruta, q = unquote(u.path), {k: v[0] for k, v in parse_qs(u.query).items()}
            auth = self.headers.get("Authorization") or ""
            if ruta == "/user":
                ok = auth in ("Bearer github_pat_bueno_de_prueba_000", "Bearer github_pat_falso_para_pruebas_000000")
                return self.responder(200 if ok else 401, {"login": "ana", "name": "Ana", "avatar_url": "https://a/ana.png",
                                                           "html_url": "https://github.com/ana"})
            if ruta == "/repos/ana/ana":
                return self.responder(200, {"full_name": "ana/ana"})
            if ruta == "/repos/ana/ana/contents/README.md":
                import base64 as b64
                return self.responder(200, {"sha": "r1", "content": b64.encodebytes("# Hola\n\nYo\n".encode()).decode()})
            if ruta == "/repos/ana/ana/contents/prig-stats.svg":
                return self.responder(404, {})
            if ruta == "/rate_limit":
                return self.responder(200 if auth == "Bearer github_pat_bueno_de_prueba_000" else 401, {})
            if ruta == "/search/repositories":
                if "malo" in q.get("q", ""):
                    return self.responder(422, {})
                if "limite" in q.get("q", ""):
                    return self.responder(403, {}, cab={"X-RateLimit-Remaining": "0", "X-RateLimit-Resource": "search"})
                return self.responder(200, {"total_count": 25, "items": [meta, {**meta, "full_name": "bo/otro", "license": None,
                                                                                "topics": None, "pushed_at": None, "updated_at": "2020"}]})
            if ruta in ("/repos/ana/repo", "/repos/ana/Repo"):
                return self.responder(200, meta)
            if ruta == "/repos/ana/Repo/languages":
                return self.responder(200, {"Python": 900, "Shell": 100, "C": 100})
            if ruta == "/repos/ana/Repo/git/trees/main":
                return self.responder(200, arbol)
            if ruta.startswith("/raw/ana/Repo/main/"):
                c = crudos.get(ruta[len("/raw/ana/Repo/main/"):])
                return self.responder(200 if c is not None else 404, (c or "").encode(), "text/plain")
            if ruta == "/codeload/ana/Repo/zip/refs/heads/main":
                return self.responder(200, zip_repo(), "application/zip")
            return self.responder(404, {})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), GitHub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


def youtube_falso() -> str:
    """ YouTube, sus sugerencias y el traductor, falsos (sin red) """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs

    def txt(t):
        return {"runs": [{"text": t}]}

    def video(vid, titulo, canal, dur, vistas, publicado, desc=None):
        vr = {"videoId": vid, "title": txt(titulo), "ownerText": txt(canal), "lengthText": {"simpleText": dur},
              "viewCountText": {"simpleText": vistas}, "publishedTimeText": {"simpleText": publicado},
              "thumbnail": {"thumbnails": [{"url": "//i.ytimg.com/a.jpg"}, {"url": f"//i.ytimg.com/vi/{vid}/hq.jpg"}]}}
        if desc:
            vr["detailedMetadataSnippets"] = [{"snippetText": txt(desc)}]
        return {"videoRenderer": vr}

    resultados = {"contents": {"sec": [
        video("v1aaaaaaaaa", "Curso completo de Python desde cero", "freeCodeCamp Español", "4:12:30", "1,823,481 vistas", "hace 2 años", "Aprende Python &amp; más"),
        video("v2aaaaaaaaa", "Python in 100 seconds", "Fireship", "2:15", "3.4M views", "1 year ago"),
        video("v3aaaaaaaaa", "Machine learning lecture 1", "Stanford Online", "1:15:00", "12 mil visualizaciones", "hace 3 semanas", "the course for beginners"),
        video("v1aaaaaaaaa", "Duplicado", "x", "10:00", "", ""),
        {"playlistRenderer": {"playlistId": "PLaaa", "title": {"simpleText": "Lista de Python"}, "shortBylineText": txt("MoureDev"),
                              "videoCount": "42", "thumbnails": [{"thumbnails": [{"url": "https://i/x.jpg"}]}],
                              "navigationEndpoint": {"watchEndpoint": {"videoId": "v9aaaaaaaaa"}}}},
        {"lockupViewModel": {"contentId": "PLbbb", "contentType": "LOCKUP_CONTENT_TYPE_PLAYLIST",
                             "metadata": {"lockupMetadataViewModel": {"title": {"content": "Curso C++ &lt;STL&gt;"},
                                          "metadata": {"contentMetadataViewModel": {"metadataRows": [{"metadataParts": [{"text": {"content": "Fazt"}}]}]}}}},
                             "contentImage": {"collectionThumbnailViewModel": {"primaryThumbnail": {"thumbnailViewModel": {
                                 "image": {"sources": [{"url": "https://i.ytimg.com/vi/v8aaaaaaaaa/x.jpg"}]},
                                 "overlays": [{"thumbnailOverlayBadgeViewModel": {"thumbnailBadges": [{"thumbnailBadgeViewModel": {"text": "12 videos"}}]}}]}}}}}},
        {"lockupViewModel": {"contentId": "v7aaaaaaaaa", "contentType": "LOCKUP_CONTENT_TYPE_VIDEO"}},
    ]}}
    pistas = {
        "vidEN": [{"baseUrl": "TT/timedtext?v=vidEN&lang=en", "languageCode": "en", "name": {"simpleText": "English"}},
                  {"baseUrl": "TT/timedtext?v=vidEN&lang=fr", "languageCode": "fr", "name": {"runs": [{"text": "Français"}]}, "isTranslatable": False}],
        "vidES": [{"baseUrl": "TT/timedtext?v=vidES&lang=es", "languageCode": "es-419", "name": {"simpleText": "Spanish (auto)"}}],
    }
    xml_en = ('<transcript><text start="0.5" dur="4">Hello &amp;amp; welcome.</text><text start="3.0" dur="2.5">This is <b>Python</b>.</text>'
              + "".join(f'<text start="{5 + i * 3}" dur="3">line number {i}</text>' for i in range(20))
              + '<text start="99" dur="1.2.3">rota</text><text start="70">sin dur</text></transcript>')
    xml_es = '<transcript><text start="0" dur="13">Hola a todos.</text><text start="13" dur="5">Seguimos con más</text></transcript>'
    xml_fr = '<timedtext><body><p t="1000" d="2500">Bonjour</p><p t="3000">le monde</p></body></timedtext>'

    class YT(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def responder(self, estado, cuerpo, tipo="application/json"):
            b = cuerpo if isinstance(cuerpo, bytes) else (cuerpo if isinstance(cuerpo, str) else json.dumps(cuerpo)).encode()
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_POST(self):
            u = urlparse(self.path)
            datos = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            base = f"http://127.0.0.1:{self.server.server_address[1]}"
            if u.path == "/youtubei/v1/search":
                q = datos.get("query", "")
                if "caido" in q:
                    return self.responder(500, {})
                if "vacio" in q:
                    return self.responder(200, {})
                return self.responder(200, resultados)
            if u.path == "/youtubei/v1/player":
                p = pistas.get(datos.get("videoId"))
                if not p:
                    return self.responder(200, {"captions": None})
                return self.responder(200, {"captions": {"playerCaptionsTracklistRenderer": {"captionTracks": [
                    {**t, "baseUrl": t["baseUrl"].replace("TT", base)} for t in p]}}})
            return self.responder(404, {})

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if u.path == "/results":
                if "caido" in q.get("search_query", ""):
                    return self.responder(500, "")
                html = "<html><script>var ytInitialData = " + json.dumps({"x": [video("s1aaaaaaaaa", "Scraper: curso completo", "MIT OpenCourseWare", "45:00", "1.2K views", "2 days ago")]}) + ";</script></html>"
                return self.responder(200, html, "text/html")
            if u.path == "/complete/search":
                return self.responder(200, 'window.google.ac.h(["%s",[["%s curso",0],["%s tutorial"],[]]])' % ((q.get("q", ""),) * 3), "text/javascript")
            if u.path == "/timedtext":
                return self.responder(200, {"en": xml_en, "es": xml_es, "fr": xml_fr}[q.get("lang")], "text/xml")
            if u.path == "/translate_a/single":
                return self.responder(200, [[[q.get("q", "").upper(), q.get("q", ""), None]]])
            if u.path == "/watch":
                return self.responder(200, "<html></html>", "text/html")
            return self.responder(404, {})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), YT)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


OLLAMA_FALSA = "http://127.0.0.1:9"


def ollama_falso() -> str:
    """ Una Ollama falsa (sin GPU ni modelos de verdad): versión, modelos, borrar y descargar """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Ollama(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *a):
            pass

        def responder(self, estado, datos, tipo="application/json"):
            b = datos if isinstance(datos, bytes) else json.dumps(datos).encode()
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def cuerpo(self):
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")

        def do_GET(self):
            if self.path == "/api/version":
                return self.responder(200, {"version": "0.12.3"})
            if self.path == "/api/tags":
                return self.responder(200, {"models": [
                    {"name": "qwen2.5-coder:7b", "size": 4683087332, "modified_at": "2026-09-01T10:00:00.123Z",
                     "details": {"quantization_level": "Q4_K_M", "family": "qwen2", "parameter_size": "7.6B", "format": "gguf"}},
                    {"name": "nomic-embed-text:latest", "size": 274302450, "modified_at": "2026-08-01T10:00:00Z", "details": {}}]})
            if self.path == "/api/ps":
                return self.responder(200, {"models": []})
            return self.responder(404, {"error": "no"})

        def do_DELETE(self):
            d = self.cuerpo()
            return self.responder(200 if d.get("name") == "qwen2.5-coder:7b" else 404, {})

        def do_POST(self):
            d = self.cuerpo()
            if self.path == "/api/pull":
                n = d.get("name")
                if n == "noexiste":
                    return self.responder(404, b"pull model manifest: file does not exist", "text/plain")
                if n == "viejo":
                    return self.responder(412, b"requires a newer version", "text/plain")
                lineas = [{"status": "pulling manifest"}, {"status": "pulling abc", "completed": 1048576, "total": 3145728},
                          {"status": "pulling abc", "completed": 3145728, "total": 3145728}, {"otra": 1}, "no es json"]
                if n == "roto":
                    lineas.insert(1, {"error": "invalid model name"})
                b = "".join((json.dumps(x) if isinstance(x, dict) else x) + "\n" for x in lineas).encode()
                return self.responder(200, b, "application/x-ndjson")
            if self.path in ("/api/generate", "/api/chat"):
                if d.get("stream") is False:
                    return self.responder(200, {"done": True})
                # en streaming, una respuesta que depende de lo pedido (así se comparan los prompts)
                import hashlib
                firma = hashlib.sha1(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:8]
                chat = self.path == "/api/chat"
                if os.environ.get("PRIG_COMPARADOR_PEDIDOS"):
                    with open(os.path.join(os.environ["PRIG_COMPARADOR_PEDIDOS"], firma + ".json"), "w") as f:
                        json.dump(d, f, ensure_ascii=False, indent=1)
                trozos = ["Explicación ", f"de prueba {firma}."]
                if "OBJETIVOS DE APRENDIZAJE" in (d.get("system") or ""):
                    trozos = ['```json\n{"objetivos": [{"titulo": "Uno ' + firma + '", "inicio_timestamp": "0:30", "fin_timestamp": "0:10", "conceptos": "x"}, ',
                              '{"titulo": "Dos", "inicio_timestamp": "0:05", "fin_timestamp": "9:99"}]}\n```']
                if "GENERADOR DE EJERCICIOS" in (d.get("system") or ""):
                    ej = {"title": "Doble " + firma, "statement": "Devuelve el doble", "function_name": "doble",
                          "starter_code": "def doble(x):\n    pass", "reference_solution": "def doble(x):\n    return 2 * x",
                          "tests": "assert doble(2) == 4\nassert doble(0) == 0\nassert doble(-1) == -2"}
                    if "roto" in (d.get("prompt") or ""):
                        ej["reference_solution"] = "def doble(x):\n    return x"
                    trozos = ["```json\n" + json.dumps(ej), "\n```"]
                elif "AGENTE 1: KNOWLEDGE ARCHITECT" in (d.get("system") or ""):
                    km = {"goal": "Meta " + firma, "domains": [{"domain_id": "dom_1", "name": "Datos", "topics": [
                        {"topic_id": "top_1", "name": "SQL", "concepts": [
                            {"concept_id": "conc_a", "name": "Joins", "evidence": [{"source_id": "libro.pdf", "locator": "cap 2"}]},
                            {"concept_id": "conc_a", "name": "Joins repetido", "type": "ADVANCED"},
                            {"concept_id": "conc_b", "name": "Índices"}]}]}],
                        "prerequisites": [{"name": "Álgebra relacional", "reason": "base"}, {"name": "Python básico"}],
                        "relationships": [{"from": "conc_a", "to": "conc_z"}, {"source_concept_id": ""}]}
                    trozos = ["<think>pienso</think>```json\n" + json.dumps(km, ensure_ascii=False), "\n```"]
                elif "AGENTE 2: PRACTICE & CURRICULUM ARCHITECT" in (d.get("system") or ""):
                    cu = {"curriculum_id": "curr_1", "modules": [
                        {"module_id": "mod_01", "name": "Joins " + firma, "objective": "Unir tablas", "concepts": ["conc_a", "conc_x"],
                         "validation_criteria": ["Une dos tablas", "Cuenta filas"]},
                        {"module_id": "mod_02", "name": "Índices"}], "objectives": ["SQL"]}
                    trozos = [json.dumps(cu, ensure_ascii=False)]
                elif "AGENTE 3: NOTEBOOK & LEARNING MANAGER" in (d.get("system") or ""):
                    ej = {"plan_id": "exec_1", "modules_notebooks": [
                        {"module_id": "mod_01", "module_name": "x", "notebooks": [
                            {"notebook_id": "nb_01", "title": "Joins " + firma, "action": "create", "source_library_notebook": None},
                            {"notebook_id": "nb_02", "title": "Copia", "action": "copy", "source_library_notebook": "no/existe.ipynb"}]},
                        {"module_id": "mod_09", "module_name": "Fantasma", "notebooks": [{"notebook_id": "nb_03", "title": "F"}]}],
                        "total_notebooks_created": 2, "total_notebooks_copied_and_edited": 1}
                    trozos = [json.dumps(ej, ensure_ascii=False)]
                elif "ASISTENTE DISEÑADOR DEL PLAN" in (d.get("system") or ""):
                    import re
                    m = re.search(r"Petición del alumno: '(\w+)\|(.*)'", d.get("prompt") or "")
                    cr = {"target_agent": "KNOWLEDGE_ARCHITECT", "action": m.group(1), "target": m.group(2), "reason": "Por " + firma} \
                        if m else {"firma": firma}
                    trozos = [json.dumps(cr, ensure_ascii=False)]
                elif "ÚNICAMENTE un objeto JSON válido" in (d.get("system") or ""):
                    trozos = ['Aquí está:\n```json\n{"tema": "Prueba ' + firma + '", ', '"tags": ["a"]}\n```']
                lineas = [({"message": {"role": "assistant", "content": t}} if chat else {"response": t}) | {"done": False}
                          for t in trozos]
                lineas.append({"done": True, "done_reason": "stop", "eval_count": 2, **({"message": {"role": "assistant", "content": ""}} if chat else {"response": ""})})
                return self.responder(200, "".join(json.dumps(l) + "\n" for l in lineas).encode(), "application/x-ndjson")
            if self.path == "/api/show":
                if d.get("model") == "qwen2.5-coder:7b":
                    return self.responder(200, {
                        "modelfile": "FROM /m/blobs/sha256-" + "a" * 64, "template": "{{ .Prompt }}",
                        "capabilities": ["completion", "tools", "insert"], "details": {"quantization_level": "Q4_K_M"},
                        "model_info": {"general.architecture": "qwen2", "general.parameter_count": 7615616512,
                                       "qwen2.block_count": 28, "qwen2.attention.head_count": 28,
                                       "qwen2.attention.head_count_kv": 4, "qwen2.embedding_length": 3584,
                                       "qwen2.context_length": 32768, "qwen2.feed_forward_length": 18944}})
                if d.get("model") == "nomic-embed-text:latest":
                    return self.responder(200, {"capabilities": ["embedding"], "details": {"quantization_level": "F16"},
                                                "model_info": {"general.architecture": "nomic-bert",
                                                               "general.parameter_count": 136731648,
                                                               "nomic-bert.block_count": 12}})
            return self.responder(404, {"error": "no"})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Ollama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


def sembrar_integraciones(home: str):
    """ Cuentas falsas de GitHub y Kaggle y dos colecciones de Kaggle, en el HOME temporal """
    def escribir(ruta, datos):
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False)
    escribir(os.path.join(home, ".prig_github.json"), {"token": "github_pat_falso_para_pruebas_000000"})
    escribir(os.path.join(home, ".prig_github", "explicaciones", "ana__Repo.json"), {
        "repo:qwen:0000000000": {"texto": "Visión vieja", "ruta": None, "nivel": "", "modelo": "qwen", "fecha": "2026-10-01T10:00:00"},
        "repo:gemini:1111111111": {"texto": "Visión nueva", "ruta": None, "nivel": "", "modelo": "gemini", "fecha": "2026-10-02T10:00:00"},
        "archivo:src/main.py:intermedio:qwen:bbb222bbb2": {"texto": "Explica main", "ruta": "src/main.py", "nivel": "intermedio", "modelo": "qwen", "fecha": "2026-10-02T10:00:00"},
        "archivo:src/main.py:avanzado:qwen:bbb222bbb2": {"texto": "Explica main (avanzado)", "ruta": "src/main.py", "nivel": "avanzado", "modelo": "qwen", "fecha": "2026-10-03T10:00:00"},
        "archivo:README.md:intermedio:qwen:viejo00000": {"texto": "README cambió", "ruta": "README.md", "nivel": "intermedio", "modelo": "qwen", "fecha": "2026-10-03T10:00:00"},
        "archivo:no/existe.py:intermedio:qwen:x": {"texto": "ya no", "ruta": "no/existe.py", "fecha": "2026-10-03T10:00:00"}})
    escribir(os.path.join(home, ".kaggle", "kaggle.json"), {"username": "ana", "key": "clave-falsa"})
    item = lambda tipo, ref, anadido, imagen=None: {"tipo": tipo, "ref": ref, "anadido": anadido, "titulo": ref,
                                                    **({"imagen": imagen} if imagen else {})}
    escribir(os.path.join(home, ".prig_kaggle", "colecciones.json"), {"colecciones": [
        {"id": "col_1", "nombre": "Titanic", "descripcion": "", "color": "#20beff", "creada": "2026-10-01T10:00:00",
         "actualizada": "2026-10-02T10:00:00", "items": [
             item("notebook", "a/titanic", "2026-10-01T11:00:00", "https://img/1.png"),
             item("dataset", "b/titanic-data", "2026-10-01T12:00:00"),
             item("notebook", "c/otro", "2026-10-01T12:00:00", "https://img/2.png")]},
        {"id": "col_2", "nombre": "Visión", "descripcion": "imágenes", "color": "#cba6f7", "creada": "2026-10-03T10:00:00",
         "actualizada": "2026-10-03T10:00:00", "items": [item("competicion", "x/coches", "2026-10-03T10:00:00"),
                                                        item("notebook", "a/titanic", "2026-10-03T11:00:00")]},
        {"id": "col_3", "nombre": "Vacía", "descripcion": "", "color": "#a6e3a1", "creada": "2026-10-02T10:00:00",
         "actualizada": "2026-10-02T10:00:00", "items": []}]})
    import hashlib
    fuente1 = ("import pandas as pd\ndf = pd.read_csv('/kaggle/input/titanic/train.csv')\n"
               "otro = pd.read_csv('../input/otro-ds/x.csv')\nz = open('/kaggle/input/extra-cosa/f.txt')")
    h1 = hashlib.sha1(fuente1.encode()).hexdigest()[:10]
    escribir(os.path.join(home, ".prig_kaggle", "explicaciones", "ana__nb-uno.json"), {
        f"1:basico:qwen:{h1}": {"texto": "Explicación básica", "fecha": "2026-10-01T10:00:00", "indice": 1},
        f"1:avanzado:gemini:flash:{h1}": {"texto": "Explicación avanzada", "fecha": "2026-10-03T10:00:00", "indice": 1},
        "9:basico:m:abcdef0123": {"texto": "fuera", "fecha": "2026-10-03T10:00:00"},
        "0:basico:m:0000000000": {"texto": "código viejo", "fecha": "2026-10-03T10:00:00"},
        "guia:qwen": {"texto": "Guía vieja", "fecha": "2026-10-01T10:00:00"},
        "guia:gemini:flash": {"texto": "Guía nueva", "fecha": "2026-10-02T10:00:00"},
        "estudio:qwen": {"texto": "plan", "fecha": "2026-10-02T10:00:00"}})
    escribir(os.path.join(home, ".prig_kaggle", "lecturas.json"), {
        "a/titanic": {"titulo": "Titanic", "leidas": [0, 2, 5], "total": 12, "ultima": "2026-10-04T10:00:00", "ultima_celda": 5},
        "b/otro": {"titulo": "Otro", "leidas": [], "total": 0, "ultima": "2026-10-05T10:00:00", "ultima_celda": 0},
        "c/sin_fecha": {"titulo": "Sin fecha", "leidas": [1]}})


def casos_por_defecto(proyecto: str, home: str, desafio: str = "des_0000000000", desafio2: str = "des_0000000000") -> list:
    PLAN = {"archivo": "{proyecto}/.prig_plans/plan_borrador/current.json", "restaurar": True, "archivo_json": True, "volatiles": ["timestamp", "created_at", "updated_at", "request_id"]}
    RECURSOS = {"archivo": "{home}/.prig_recursos.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha"]}
    MOE = {"archivo": "{home}/.prig_ai_config.json", "restaurar": True, "archivo_json": True,
           "claves": ["moe_contexto", "moe_hilos", "moe_calientes", "moe_modo", "moe_mtp", "moe_nucleo", "moe_cache_gb",
                      "moe_cache_reserva_gb"]}
    casos = [
        {"ruta": "/api/health", "solo_rust": True},
        {"ruta": "/api/workspace", "solo_rust": True},
        {"ruta": "/api/tree", "solo_rust": True},
        {"ruta": "/api/tree?path=" + urllib.request.quote(os.path.join(proyecto, "lib")), "solo_rust": True},
        {"ruta": "/api/tree?path=/no/existe", "solo_rust": True},
        {"ruta": "/api/ide/archivos", "solo_rust": True},
        {"ruta": "/api/ide/buscar", "metodo": "POST", "json": {"consulta": "saludar"}, "solo_rust": True},
        {"ruta": "/api/ide/buscar", "metodo": "POST", "json": {"consulta": "s[au]+", "regex": True}, "solo_rust": True},
        {"ruta": "/api/ide/buscar", "metodo": "POST", "json": {"consulta": "hola", "palabra": True, "mayusculas": True}, "solo_rust": True},
        {"ruta": "/api/ide/buscar", "metodo": "POST", "json": {"consulta": "(", "regex": True}, "solo_rust": True},
        {"ruta": "/api/desafios", "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}", "solo_rust": True},
        {"ruta": "/api/desafios/des_ffffffffff", "solo_rust": True},
        {"ruta": "/api/desafios/des_0000000000", "solo_rust": True},
        {"ruta": "/api/desafios/no-es-un-id", "solo_rust": True},
        {"ruta": "/api/desafios/fuentes", "solo_rust": True},
        {"ruta": "/api/progreso/analisis", "solo_rust": True},
        {"ruta": "/api/progreso/historial", "solo_rust": True},
        {"ruta": "/api/progreso/historial?limite=3", "solo_rust": True},
        {"ruta": "/api/progreso/historial?estado=resuelto", "solo_rust": True},
        {"ruta": "/api/progreso/historial?estado=", "solo_rust": True},
        {"ruta": "/api/progreso/historial?fuente=prig-hub", "solo_rust": True},
        {"ruta": "/api/progreso/historial?concepto=PILAS", "solo_rust": True},
        {"ruta": "/api/progreso/historial?concepto=%C3%A1rboles%20binarios", "solo_rust": True},
        {"ruta": "/api/progreso/historial?concepto=prueba%20des_aaaaaaaaa3", "solo_rust": True},
        {"ruta": "/api/progreso/historial?limite=600", "solo_rust": True},
        {"ruta": "/api/github/guardados"},
        {"ruta": "/api/github/estado", "solo_rust": True},
        {"ruta": "/api/kaggle/estado", "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones", "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones/col_1"},
        {"ruta": "/api/kaggle/colecciones/col_3"},
        {"ruta": "/api/kaggle/colecciones/no_existe"},
        {"ruta": "/api/kaggle/mis_datos", "solo_rust": True},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/titanic/train.csv", "solo_rust": True},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/titanic/datos.tsv", "solo_rust": True},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/titanic/punto.csv", "solo_rust": True},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/titanic/raro.csv", "solo_rust": True},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/titanic/sub/notas.txt", "solo_rust": True},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/titanic/foto.png", "solo_rust": True},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/suelta/a.bin", "solo_rust": True},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/titanic/../../ejercicio.py", "solo_rust": True},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos", "solo_rust": True},
        {"ruta": "/api/kaggle/previa", "solo_rust": True},
        {"ruta": "/api/kaggle/archivo?ruta={proyecto}/kaggle_datos/titanic/foto.png", "solo_rust": True},
        {"ruta": "/api/kaggle/archivo?ruta={proyecto}/kaggle_datos/titanic/train.csv", "solo_rust": True},
        {"ruta": "/api/kaggle/archivo", "solo_rust": True},
        {"ruta": "/api/kaggle/buscar", "solo_rust": True},
        {"ruta": "/api/kaggle/buscar?q=uno&orden=votos&tipo=script&votos_min=0&gpu=false&padre=kaggle.com/code/ana/nb-uno/edit", "solo_rust": True},
        {"ruta": "/api/kaggle/buscar?votos_min=5&dias=36500&gpu=true", "solo_rust": True},
        {"ruta": "/api/kaggle/buscar?q=titanic", "solo_rust": True},
        {"ruta": "/api/kaggle/buscar?pagina=0", "solo_rust": True},
        {"ruta": "/api/kaggle/buscar?gpu=quizas", "solo_rust": True},
        {"ruta": "/api/kaggle/buscar?padre=../x", "solo_rust": True},
        {"ruta": "/api/kaggle/notebook?ref=https://www.kaggle.com/code/ana/nb-uno", "solo_rust": True},
        {"ruta": "/api/kaggle/notebook?ref=ana/nb-uno&refrescar=true", "volatiles": ["descargado"], "solo_rust": True},
        {"ruta": "/api/kaggle/notebook?ref=ana/script-uno&refrescar=1", "volatiles": ["descargado"], "solo_rust": True},
        {"ruta": "/api/kaggle/notebook?ref=ana/no-existe", "solo_rust": True},
        {"ruta": "/api/kaggle/notebook?ref=no%20vale", "solo_rust": True},
        {"ruta": "/api/kaggle/notebook", "solo_rust": True},
        {"ruta": "/api/kaggle/importar", "metodo": "POST", "json": {"ref": "ana/nb-uno"}, "archivo": "{proyecto}/kaggle_notebooks/nb-uno.ipynb", "restaurar": True, "solo_rust": True},
        {"ruta": "/api/kaggle/importar", "metodo": "POST", "json": {"ref": "ana/script-uno"}, "archivo": "{proyecto}/kaggle_notebooks/script-uno.py", "restaurar": True, "solo_rust": True},
        {"ruta": "/api/kaggle/importar", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/kaggle/datasets", "solo_rust": True},
        {"ruta": "/api/kaggle/datasets?q=x&orden=votos&tipo_archivo=csv&licencia=cc&tamano=mediano&usuario=ana", "solo_rust": True},
        {"ruta": "/api/kaggle/dataset?ref=https://www.kaggle.com/datasets/ana/otro-ds/data", "solo_rust": True},
        {"ruta": "/api/kaggle/dataset?ref=no", "solo_rust": True},
        {"ruta": "/api/kaggle/competiciones?grupo=mias&categoria=playground&orden=premio", "solo_rust": True},
        {"ruta": "/api/kaggle/competicion?ref=titanic", "solo_rust": True},
        {"ruta": "/api/kaggle/competicion?ref=inexistente", "solo_rust": True},
        {"ruta": "/api/kaggle/descargar", "metodo": "POST", "json": {"tipo": "dataset", "ref": "ana/otro-ds"}, "solo_rust": True},
        {"ruta": "/api/kaggle/descargar", "metodo": "POST", "json": {"tipo": "competicion", "ref": "titanic"}, "solo_rust": True},
        {"ruta": "/api/kaggle/descargar", "metodo": "POST", "json": {"tipo": "modelo", "ref": "x"}, "solo_rust": True},
        {"ruta": "/api/kaggle/pdf", "metodo": "POST", "json": {"ref": "ana/nb-uno", "nivel": "basico", "chat": [{"rol": "usuario", "texto": "¿Qué hace?"}, {"rol": "profesor", "texto": "Lee datos."}, {"texto": " "}]}, "solo_rust": True},
        {"ruta": "/api/kaggle/pdf", "metodo": "POST", "json": {"ref": "ana/script-uno", "salidas": False, "guia": False}, "solo_rust": True},
        {"ruta": "/api/kaggle/pdf", "metodo": "POST", "json": {"ref": "ana/nb-uno", "solo_explicadas": True}, "solo_rust": True},
        {"ruta": "/api/kaggle/pdf", "metodo": "POST", "json": {"ref": "ana/nb-uno", "solo_explicadas": True, "nivel": "avanzado"}, "solo_rust": True},
        {"ruta": "/api/kaggle/pdf", "metodo": "POST", "json": {"coleccion": "col_1"}, "solo_rust": True},
        {"ruta": "/api/kaggle/pdf", "metodo": "POST", "json": {"coleccion": "nope"}, "solo_rust": True},
        {"ruta": "/api/kaggle/pdf", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/kaggle/pdf?ruta={proyecto}/kaggle_pdf/nb-uno.pdf", "solo_rust": True},
        {"ruta": "/api/kaggle/pdf?ruta={proyecto}/kaggle_datos/titanic/train.csv", "solo_rust": True},
        {"ruta": "/api/kaggle/pdf/abrir", "metodo": "POST", "json": {"ref": "/etc/passwd"}, "solo_rust": True},
        {"ruta": "/api/github/widget/config", "solo_rust": True},
        {"ruta": "/api/github/widget/config", "metodo": "POST", "json": {"config": {"tema": "cyber", "mostrar_modelos": True}}, "archivo": "{home}/.prig_github_widget.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/github/widget/config", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/github/widget/preview", "metodo": "POST", "json": {"config": {"tema": "minimal", "mostrar_modelos": True, "mostrar_youtube": False}, "extras": {"yt_cursos_completados": 3, "yt_fotogramas": 2.5, "modelo_local": "<Qwen & Cía> muy largo de verdad"}}, "solo_rust": True},
        {"ruta": "/api/github/widget/preview", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/github/widget/preview", "metodo": "POST", "json": {"config": "x"}, "solo_rust": True},
        {"ruta": "/api/github/widget/publicar", "metodo": "POST", "json": {"config": {"tema": "mocha"}}, "archivo": "{home}/.prig_github_widget.json", "restaurar": True, "archivo_json": True, "volatiles": ["ultimo_sync"], "solo_rust": True},
        {"ruta": "/api/github/buscar?q=cli&lenguaje=Python&estrellas_min=10&tema=ml&orden=actualizados&pagina=2", "solo_rust": True},
        {"ruta": "/api/github/buscar?q=cli&orden=relevancia", "solo_rust": True},
        {"ruta": "/api/github/buscar", "solo_rust": True},
        {"ruta": "/api/github/buscar?q=malo", "solo_rust": True},
        {"ruta": "/api/github/buscar?q=limite", "solo_rust": True},
        {"ruta": "/api/github/buscar?pagina=51&q=x", "solo_rust": True},
        {"ruta": "/api/github/repo?ref=https://github.com/ana/repo.git", "solo_rust": True},
        {"ruta": "/api/github/repo?ref=ana/Repo&refrescar=true", "volatiles": ["descargado"], "solo_rust": True},
        {"ruta": "/api/github/repo?ref=nadie/x", "solo_rust": True},
        {"ruta": "/api/github/repo?ref=no", "solo_rust": True},
        {"ruta": "/api/github/archivo?ref=ana/Repo&ruta=src/main.py", "archivo": "{home}/.prig_github/archivos/ana__Repo/bbb222bbb222bbb222.txt", "restaurar": True, "solo_rust": True},
        {"ruta": "/api/github/archivo?ref=ana/Repo&ruta=README.md", "solo_rust": True},
        {"ruta": "/api/github/archivo?ref=ana/Repo&ruta=src/nul.py", "solo_rust": True},
        {"ruta": "/api/github/archivo?ref=ana/Repo&ruta=docs/a%20b.md", "solo_rust": True},
        {"ruta": "/api/github/archivo?ref=ana/Repo&ruta=img/logo.png", "solo_rust": True},
        {"ruta": "/api/github/archivo?ref=ana/Repo&ruta=datos/grande.csv", "solo_rust": True},
        {"ruta": "/api/github/archivo?ref=ana/Repo&ruta=no.py", "solo_rust": True},
        {"ruta": "/api/github/archivo?ref=ana/Repo", "solo_rust": True},
        {"ruta": "/api/github/guardados", "metodo": "POST", "json": {"ref": "ana/repo", "nota": "  ver luego "}, "archivo": "{home}/.prig_github/guardados.json", "restaurar": True, "archivo_json": True, "volatiles": ["guardado"]},
        {"ruta": "/api/github/guardados?ref=ANA/REPO", "metodo": "DELETE", "archivo": "{home}/.prig_github/guardados.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/github/guardados", "metodo": "DELETE"},
        {"ruta": "/api/github/token", "metodo": "POST", "json": {"texto": " github_pat_bueno_de_prueba_000 "}, "archivo": "{home}/.prig_github.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/github/token", "metodo": "POST", "json": {"texto": "github_pat_malo_de_prueba_0000"}, "archivo": "{home}/.prig_github.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/github/token", "metodo": "POST", "json": {"texto": "corto"}, "archivo": "{home}/.prig_github.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/github/token", "metodo": "DELETE", "archivo": "{home}/.prig_github.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/github/exportar", "metodo": "POST", "json": {"ref": "ana/Repo", "nota": "md"}, "solo_rust": True},
        {"ruta": "/api/github/exportar", "metodo": "POST", "json": {"ref": "ana/Repo"}, "solo_rust": True},
        {"ruta": "/api/github/exportado?ruta={proyecto}/github_explicaciones/ana__Repo.md", "solo_rust": True},
        {"ruta": "/api/github/exportado?ruta={proyecto}/github_explicaciones/ana__Repo.pdf&descargar=true", "solo_rust": True},
        {"ruta": "/api/github/exportado?ruta=/etc/passwd", "solo_rust": True},
        {"ruta": "/api/github/descargar", "metodo": "POST", "json": {"ref": "ana/Repo"}, "solo_rust": True},
        {"ruta": "/api/github/descargar", "metodo": "POST", "json": {"ref": "nadie/x"}, "solo_rust": True},
        {"ruta": "/api/progreso/resumen", "volatiles": ["id", "bloque_id", "generado"], "solo_rust": True},
        {"ruta": "/api/progreso/resumen?dias=7", "volatiles": ["id", "bloque_id", "generado"], "solo_rust": True},
        {"ruta": "/api/progreso/resumen?dias=400", "solo_rust": True},
        {"ruta": "/api/youtube/palabras_registradas", "solo_rust": True},
        {"ruta": "/api/youtube/sugerencias?q=python%20curso&limite=1", "solo_rust": True},
        {"ruta": "/api/youtube/sugerencias?q=python", "solo_rust": True},
        {"ruta": "/api/youtube/sugerencias?q=%20%20", "solo_rust": True},
        {"ruta": "/api/youtube/sugerencias", "solo_rust": True},
        {"ruta": "/api/youtube/buscar?q=python&forzar=true", "solo_rust": True},
        {"ruta": "/api/youtube/buscar?q=Python&idioma=es&orden=vistas&forzar=true", "solo_rust": True},
        {"ruta": "/api/youtube/buscar?q=machine%20learning&idioma=en&orden=recientes&forzar=true", "solo_rust": True},
        {"ruta": "/api/youtube/buscar?q=curso&tipo=playlist&orden=duracion&forzar=true", "solo_rust": True},
        {"ruta": "/api/youtube/buscar?q=curso&duracion_filtro=cursos&forzar=true", "solo_rust": True},
        {"ruta": "/api/youtube/buscar?q=curso&duracion_filtro=cortos&max_resultados=2&forzar=true", "solo_rust": True},
        {"ruta": "/api/youtube/buscar?q=vacio&forzar=true", "solo_rust": True},
        {"ruta": "/api/youtube/buscar?q=caido&forzar=true", "solo_rust": True},
        {"ruta": "/api/youtube/buscar?q=deep_learning&forzar=true&filtro_educativo=false", "solo_rust": True},
        {"ruta": "/api/youtube/buscar?q=%20", "solo_rust": True},
        {"ruta": "/api/youtube/buscar?q=x&max_resultados=abc", "solo_rust": True},
        {"ruta": "/api/youtube/abrir_externo", "metodo": "POST", "json": {"url": "https://malicioso.com/x"}, "solo_rust": True},
        {"ruta": "/api/youtube/abrir_externo", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/youtube/abrir_externo", "metodo": "POST", "crudo": "{roto", "solo_rust": True},
        {"ruta": "/api/youtube/transcripcion?video_id=vidEN&forzar=true", "solo_rust": True},
        {"ruta": "/api/youtube/transcripcion?video_id=vidES", "solo_rust": True},
        {"ruta": "/api/youtube/transcripcion?video_id=vidEN&idioma=fr&forzar=1", "solo_rust": True},
        {"ruta": "/api/youtube/transcripcion?video_id=sinsubs", "solo_rust": True},
        {"ruta": "/api/youtube/transcripcion?video_id=", "solo_rust": True},
        {"ruta": "/api/youtube/transcripcion", "solo_rust": True},
        {"ruta": "/api/ai/status", "solo_rust": True},
        {"ruta": "/api/ai/reload", "solo_rust": True},
        {"ruta": "/api/ai/models", "solo_rust": True},
        {"ruta": "/api/ai/models/detailed", "solo_rust": True},
        {"ruta": "/api/ai/models/delete", "metodo": "POST", "json": {"model": "qwen2.5-coder:7b"}, "solo_rust": True},
        {"ruta": "/api/ai/models/delete", "metodo": "POST", "json": {"model": "otro"}, "solo_rust": True},
        {"ruta": "/api/ai/models/delete", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/ai/pull", "metodo": "POST", "json": {"model": "Qwen3-30B-A3B (rápido)"}, "solo_rust": True},
        {"ruta": "/api/ai/pull", "metodo": "POST", "json": {"model": "roto"}, "solo_rust": True},
        {"ruta": "/api/ai/pull", "metodo": "POST", "json": {"model": "noexiste"}, "solo_rust": True},
        {"ruta": "/api/ai/pull", "metodo": "POST", "json": {"model": "viejo"}, "solo_rust": True},
        {"ruta": "/api/ai/config", "solo_rust": True},
        {"ruta": "/api/ai/config", "metodo": "POST", "json": {"temperature": "0.5", "num_ctx": 8192.0, "low_vram": "yes", "keep_alive": "10m", "otra": 1}, "archivo": "{home}/.prig_ai_config.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/ai/config", "metodo": "POST", "json": {"agent1_model": None, "top_k": 7}, "archivo": "{home}/.prig_ai_config.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/ai/config", "metodo": "POST", "json": {"num_ctx": 1.5}, "archivo": "{home}/.prig_ai_config.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/ai/config", "metodo": "POST", "json": {"keep_alive": 5}, "archivo": "{home}/.prig_ai_config.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/kaggle/lecturas", "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones", "metodo": "POST", "json": {"nombre": "  Mis   notebooks ", "descripcion": " d ", "color": "#f38ba8"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones", "metodo": "POST", "json": {"nombre": "titanic"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones", "metodo": "POST", "json": {"nombre": "   "}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones", "metodo": "POST", "json": {"nombre": "Otra", "color": "rojo"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones", "metodo": "POST", "json": {"nombre": 5}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones/col_1", "metodo": "PATCH", "json": {"nombre": "Titanic 2", "descripcion": "x", "color": "#89b4fa"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_1", "metodo": "PATCH", "json": {"nombre": "Visión"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_1", "metodo": "PATCH", "json": {}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/nope", "metodo": "PATCH", "json": {"nombre": "x"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_2", "metodo": "DELETE", "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/nope", "metodo": "DELETE", "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_3/items", "metodo": "POST", "json": {"tipo": "notebook", "ref": "ana/nb-uno", "datos": {"titulo": "Uno", "votos": 3, "otro": 1}}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones/col_1/items", "metodo": "POST", "json": {"tipo": "notebook", "ref": "a/titanic", "datos": {"autor": "Ana", "titulo": None}}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones/col_3/items", "metodo": "POST", "json": {"tipo": "competicion", "ref": "https://www.kaggle.com/competitions/titanic/data"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones/col_3/items", "metodo": "POST", "json": {"tipo": "competicion", "ref": "no vale"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones/col_3/items", "metodo": "POST", "json": {"tipo": "modelo", "ref": "a/b"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones/col_3/items", "metodo": "POST", "json": {"tipo": "dataset", "ref": "a/../b"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones/col_3/items", "metodo": "POST", "json": {"tipo": "dataset", "ref": "a/b", "datos": "x"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones/col_3/items", "metodo": "POST", "json": {"ref": "a/b"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones/col_1/items", "metodo": "PATCH", "json": {"tipo": "notebook", "ref": "a/titanic", "nota": "  repasar  "}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones/col_1/items", "metodo": "PATCH", "json": {"tipo": "notebook", "ref": "z/nada", "nota": "x"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones/col_1/items?tipo=notebook&ref=a/titanic", "metodo": "DELETE", "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones/col_1/items?tipo=notebook", "metodo": "DELETE", "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/colecciones/nope/items?tipo=notebook&ref=a", "metodo": "DELETE", "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"], "solo_rust": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {"texto": "token_de_prueba_valido_0123456789"}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {"texto": "  '{\"username\": \"ana\", \"key\": \"clave-buena\"}'  "}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {"texto": "token_de_prueba_que_kaggle_rechaza"}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {"texto": "corto"}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {"texto": "{roto"}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {"texto": "{\"username\": \"ana\"}"}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {"texto": ""}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "DELETE", "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/books/read?id=Redes_neuronales.pdf", "solo_rust": True},
        {"ruta": "/api/books/read?id=books/sin%20ficha.txt", "solo_rust": True},
        {"ruta": "/api/books/read?id=crlf.md", "solo_rust": True},
        {"ruta": "/api/books/read?id=repo", "solo_rust": True},
        {"ruta": "/api/books/read?id=../../etc/passwd", "solo_rust": True},
        {"ruta": "/api/books/read", "solo_rust": True},
        {"ruta": "/api/books/metadata?id=Redes_neuronales.pdf", "solo_rust": True},
        {"ruta": "/api/books/metadata?id=nada.pdf", "solo_rust": True},
        {"ruta": "/api/books/metadata/notas.md.json", "solo_rust": True},
        {"ruta": "/api/books/metadata/%C3%81lgebra_lineal-2ed.pdf", "solo_rust": True},
        {"ruta": "/api/books/snippets", "solo_rust": True},
        {"ruta": "/api/books/snippet/snp_1", "solo_rust": True},
        {"ruta": "/api/books/snippet/nada", "solo_rust": True},
        {"ruta": "/api/books/snippet", "metodo": "POST", "json": {"book_id": "Redes_neuronales.pdf", "page": "3", "text": "cita", "box": {"x": 1}}, "archivo": "{home}/.prig_books/snippets.json", "restaurar": True, "archivo_json": True, "claves": ["snp_1"], "volatiles": ["id", "cite_tag"], "solo_rust": True},
        {"ruta": "/api/books/snippet", "metodo": "POST", "json": {"page": "x"}, "solo_rust": True},
        {"ruta": "/api/books/pdf-pages?id=Redes_neuronales.pdf", "solo_rust": True},
        {"ruta": "/api/books/pdf-pages?id=Redes_neuronales.pdf&page=2&search=REDES", "solo_rust": True},
        {"ruta": "/api/books/pdf-pages?id=Redes_neuronales.pdf&page=99&search=%20%20", "solo_rust": True},
        {"ruta": "/api/books/pdf-pages?id=Redes_neuronales.pdf&page=-4", "solo_rust": True},
        {"ruta": "/api/books/pdf-pages?id=crlf.md&page=7&search=dos", "solo_rust": True},
        {"ruta": "/api/books/pdf-pages?id=nada.pdf", "solo_rust": True},
        {"ruta": "/api/books/pdf-pages?id=x&page=uno", "solo_rust": True},
        {"ruta": "/api/books/pdf-page-save", "metodo": "POST", "json": {"book_id": "Redes_neuronales.pdf", "page": 2, "text": "corregida"}, "archivo": "{home}/.prig_books/citas/ediciones/Redes_neuronales_p2.txt", "restaurar": True, "solo_rust": True},
        {"ruta": "/api/books/pdf-page-save", "metodo": "POST", "json": {"book_id": "no existe.pdf", "page": 1, "text": "x"}, "archivo": "{home}/.prig_books/citas/ediciones/no existe_p1.txt", "restaurar": True, "solo_rust": True},
        {"ruta": "/api/books/pdf-page-save", "metodo": "POST", "json": {"book_id": "x"}, "solo_rust": True},
        {"ruta": "/api/books/citations?id=Redes_neuronales.pdf", "solo_rust": True},
        {"ruta": "/api/books/citations?id=sin%20ficha.txt", "archivo": "{home}/.prig_books/citas/sin ficha.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion", "created_at", "id"], "solo_rust": True},
        {"ruta": "/api/books/citations?id=otro_libro-nuevo.pdf", "archivo": "{home}/.prig_books/citas/otro_libro_nuevo.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion", "created_at", "id"], "solo_rust": True},
        {"ruta": "/api/books/citations?id=rota", "archivo": "{home}/.prig_books/citas/rota.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion", "created_at", "id"], "solo_rust": True},
        {"ruta": "/api/books/citations/save", "metodo": "POST", "json": {"book_id": "Redes_neuronales.pdf", "citation": {"id": "c2", "pagina": "1", "capitulo": " Cap 1 ", "texto": "x", "tags": "a, b"}}, "archivo": "{home}/.prig_books/citas/Redes_neuronales.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion", "created_at", "id"], "solo_rust": True},
        {"ruta": "/api/books/citations/save", "metodo": "POST", "json": {"book_id": "Redes_neuronales.pdf", "citation": {"id": "c1", "pagina": 2.9}}, "archivo": "{home}/.prig_books/citas/Redes_neuronales.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion", "created_at", "id"], "solo_rust": True},
        {"ruta": "/api/books/citations/save", "metodo": "POST", "json": {"book_id": "Redes_neuronales.pdf", "citation": {"id": "c9", "pagina": "x"}}, "solo_rust": True},
        {"ruta": "/api/books/citations/save", "metodo": "POST", "json": {"book_id": "Redes_neuronales.pdf", "citation": {"id": "c9", "texto": 4}}, "solo_rust": True},
        {"ruta": "/api/books/citations/delete", "metodo": "POST", "json": {"book_id": "Redes_neuronales.pdf", "citation_id": "c0"}, "archivo": "{home}/.prig_books/citas/Redes_neuronales.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion", "created_at", "id"], "solo_rust": True},
        {"ruta": "/api/books/citations/delete", "metodo": "POST", "json": {"book_id": "Redes_neuronales.pdf", "citation_id": "zz"}, "solo_rust": True},
        {"ruta": "/api/books/citations/export", "metodo": "POST", "json": {"book_id": "Redes_neuronales.pdf", "workspace_path": "{proyecto}/citas_libros"}, "archivo": "{proyecto}/citas_libros/Redes_neuronales.json", "restaurar": True, "solo_rust": True},
        {"ruta": "/api/books/citations/export", "metodo": "POST", "json": {"book_id": "Redes_neuronales.pdf", "workspace_path": "/proc/x"}, "solo_rust": True},
        {"ruta": "/api/books/all-citations", "solo_rust": True},
        {"ruta": "/api/books/all-citations?query=gradiente%20basico%20de", "solo_rust": True},
        {"ruta": "/api/books/analyze", "metodo": "POST", "json": {"book_id": "Redes_neuronales.pdf"}, "archivo": "{home}/.prig_books/metadata/books__Redes_neuronales.pdf.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion", "created_at", "id"], "solo_rust": True},
        {"ruta": "/api/books/analyze", "metodo": "POST", "json": {"book_id": "x", "path": "n.ipynb", "model": "qwen3:8b"}, "archivo": "{home}/.prig_books/metadata/notebooks__n.ipynb.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion", "created_at", "id"], "solo_rust": True},
        {"ruta": "/api/books/analyze", "metodo": "POST", "json": {"book_id": "nada"}, "solo_rust": True},
        {"ruta": "/api/knowledge/status", "solo_rust": True},
        {"ruta": "/api/knowledge/search", "metodo": "POST", "json": {"query": "gradiente descendente"}, "solo_rust": True},
        {"ruta": "/api/knowledge/search", "metodo": "POST", "json": {"query": "tensor", "top_k": 3, "expand": False, "max_context_tokens": 100}, "solo_rust": True},
        {"ruta": "/api/knowledge/search", "metodo": "POST", "json": {"query": "x", "top_k": "muchos"}, "solo_rust": True},
        {"ruta": "/api/knowledge/search", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/knowledge/index", "metodo": "POST", "json": {"force": "quizas"}, "solo_rust": True},
        {"ruta": "/api/kb/status", "solo_rust": True},
        {"ruta": "/api/kb/search", "metodo": "POST", "json": {"query": "gradiente de la pérdida", "top_k": 3}, "solo_rust": True},
        {"ruta": "/api/kb/search", "metodo": "POST", "json": {"query": "cómo se cocina una paella"}, "solo_rust": True},
        {"ruta": "/api/kb/bridges", "solo_rust": True},
        {"ruta": "/api/kb/bridges?limite=201", "solo_rust": True},
        {"ruta": "/api/kb/concept?nombre=gradientes", "solo_rust": True},
        {"ruta": "/api/kb/concept?nombre=ridge", "solo_rust": True},
        {"ruta": "/api/kb/concept?nombre=nada", "solo_rust": True},
        {"ruta": "/api/kb/concept", "solo_rust": True},
        {"ruta": "/api/kb/contexto?pregunta=%C2%BFqu%C3%A9%20es%20el%20gradiente%3F", "solo_rust": True},
        {"ruta": "/api/kb/contexto?pregunta=weight%20decay&presupuesto=200&compilado=false", "solo_rust": True},
        {"ruta": "/api/kb/contexto?pregunta=x&compilado=quizas", "solo_rust": True},
        {"ruta": "/api/kb/context", "metodo": "POST", "json": {"pregunta": "regla de la cadena", "dominio": "math", "nivel": "principiante"}, "solo_rust": True},
        {"ruta": "/api/kb/context", "metodo": "POST", "json": {"pregunta": "paella", "presupuesto_tokens": 500}, "solo_rust": True},
        {"ruta": "/api/kb/context", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/kb/compilar", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/kb/indice", "volatiles": ["descargado"], "solo_rust": True},
        {"ruta": "/api/kb/indexar", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/knowledge/ask", "metodo": "POST", "json": {"query": "¿qué es el gradiente?"}, "solo_rust": True},
        {"ruta": "/api/knowledge/ask", "metodo": "POST", "json": {"query": "paella valenciana", "expand": False, "top_k": 2}, "solo_rust": True},
        {"ruta": "/api/knowledge/ask", "metodo": "POST", "json": {"model": 3}, "solo_rust": True},
        {"ruta": "/api/kb/books", "solo_rust": True},
        {"ruta": "/api/kb/verify", "metodo": "POST", "json": {"ruta": "bk_nuevo.prigpack"}, "solo_rust": True},
        {"ruta": "/api/kb/verify", "metodo": "POST", "json": {"ruta": "../../bk_roto.prigpack"}, "solo_rust": True},
        {"ruta": "/api/kb/verify", "metodo": "POST", "json": {"ruta": "no_es.prigpack"}, "solo_rust": True},
        {"ruta": "/api/kb/verify", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/kb/verify", "metodo": "POST", "json": {"forzar": "x"}, "solo_rust": True},
        {"ruta": "/api/kb/import", "metodo": "POST", "json": {"ruta": "nada.prigpack"}, "solo_rust": True},
        {"ruta": "/api/kb/import", "metodo": "POST", "json": {"ruta": "bk_roto.prigpack"}, "solo_rust": True},
        {"ruta": "/api/kb/import", "metodo": "POST", "json": {}, "solo_rust": True, "volatiles": ["imported_at", "importado", "unificado_en", "segundos"]},
        {"ruta": "/api/job/list", "solo_rust": True},
        {"ruta": "/api/job/books", "solo_rust": True},
        {"ruta": "/api/job/prepare", "metodo": "POST", "json": {"libros": [{"path": "{home}/.prig_books/books/Redes_neuronales.pdf"}, {"ruta": "{home}/.prig_books/documentation/crlf.md", "domain": "math", "ajustes": {"max_chunk_tokens": 40}}, {"path": "{home}/.prig_books/no.pdf"}, {"path": "{home}/.prig_books/books/foto.png"}, {"path": "{home}/.prig_books/books"}, {"path": "/etc/hosts.txt"}, {"domain": "x"}]}, "volatiles": ["job_id", "created_at", "output_dir"], "solo_rust": True},
        {"ruta": "/api/job/prepare", "metodo": "POST", "json": {"libros": [{"path": "{home}/.prig_books/no.pdf"}, {"path": "/etc/passwd"}]}, "solo_rust": True},
        {"ruta": "/api/job/prepare", "metodo": "POST", "json": {"libros": []}, "solo_rust": True},
        {"ruta": "/api/job/prepare", "metodo": "POST", "json": {"max_chunk_tokens": "x"}, "solo_rust": True},
        {"ruta": "/api/sondeo/preparar", "metodo": "POST", "json": {"libros": [{"path": "{home}/.prig_books/documentation/notas.md"}]}, "volatiles": ["job_id", "created_at", "output_dir"], "solo_rust": True},
        {"ruta": "/api/job/prepare-stream", "metodo": "POST", "json": {"libros": [{"path": "{home}/.prig_books/no.pdf"}]}, "solo_rust": True},
        {"ruta": "/api/sondeo", "metodo": "POST", "json": {"rutas": ["{home}/.prig_books/books/Redes_neuronales.pdf", "{home}/.prig_books/documentation/crlf.md", "{home}/.prig_books/books/Redes_neuronales.pdf", "/etc/hostname"], "con_modelo": False}, "volatiles": ["medido_en"], "solo_rust": True},
        {"ruta": "/api/sondeo", "metodo": "POST", "json": {"rutas": ["{home}/.prig_books/documentation/notas.md"], "modelo": "qwen3:8b"}, "volatiles": ["medido_en"], "solo_rust": True},
        {"ruta": "/api/sondeo", "metodo": "POST", "json": {"carpeta": "{home}/.prig_books/documentation", "tope": 2, "con_modelo": False}, "volatiles": ["medido_en"], "solo_rust": True},
        {"ruta": "/api/sondeo", "metodo": "POST", "json": {"carpeta": "/etc"}, "solo_rust": True},
        {"ruta": "/api/sondeo", "metodo": "POST", "json": {"carpeta": "{home}/.prig_books/nada"}, "solo_rust": True},
        {"ruta": "/api/sondeo", "metodo": "POST", "json": {"rutas": []}, "solo_rust": True},
        {"ruta": "/api/sondeo", "metodo": "POST", "json": {"tope": "x"}, "solo_rust": True},
        {"ruta": "/api/libros/analizables", "solo_rust": True},
        {"ruta": "/api/libros/ficha/bk_math", "solo_rust": True},
        {"ruta": "/api/libros/ficha/bk_dl", "solo_rust": True},
        {"ruta": "/api/libros/resumen/bk_math", "solo_rust": True},
        {"ruta": "/api/libros/resumen/nada", "solo_rust": True},
        {"ruta": "/api/libros/material?concepto=gradientes", "solo_rust": True},
        {"ruta": "/api/libros/material?concepto=ridge", "solo_rust": True},
        {"ruta": "/api/libros/material?concepto=paella", "solo_rust": True},
        {"ruta": "/api/libros/material", "solo_rust": True},
        {"ruta": "/api/libros/contexto-plan", "solo_rust": True},
        {"ruta": "/api/libros/contexto-plan?objetivo=x", "solo_rust": True},
        {"ruta": "/api/sql/databases", "volatiles": ["execution_time_ms", "message", "tamano_bytes", "tamano_formato"], "solo_rust": True},
        {"ruta": "/api/sql/databases/create", "metodo": "POST", "json": {"nombre": "comp_sql"}, "volatiles": ["created", "message"], "solo_rust": True},
        {"ruta": "/api/sql/databases/create", "metodo": "POST", "json": {"nombre": "comp_sql"}, "solo_rust": True},
        {"ruta": "/api/sql/databases/create", "metodo": "POST", "json": {"nombre": "!!"}, "solo_rust": True},
        {"ruta": "/api/sql/databases/create", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/sql/seed", "metodo": "POST", "json": {"db": "comp_sql"}, "solo_rust": True},
        {"ruta": "/api/sql/tables?db=comp_sql", "solo_rust": True},
        {"ruta": "/api/sql/tables?db=nada", "solo_rust": True},
        {"ruta": "/api/sql/schema?db=comp_sql&table=usuarios", "solo_rust": True},
        {"ruta": "/api/sql/schema?db=comp_sql", "solo_rust": True},
        {"ruta": "/api/sql/query", "metodo": "POST", "json": {"db": "comp_sql", "sql": "SELECT id, username, activo FROM usuarios ORDER BY id;"}, "volatiles": ["execution_time_ms", "message", "tamano_bytes", "tamano_formato"], "solo_rust": True},
        {"ruta": "/api/sql/query", "metodo": "POST", "json": {"db": "comp_sql", "sql": "show tables;"}, "volatiles": ["execution_time_ms", "message", "tamano_bytes", "tamano_formato"], "solo_rust": True},
        {"ruta": "/api/sql/query", "metodo": "POST", "json": {"db": "comp_sql", "sql": "DESCRIBE `productos`"}, "volatiles": ["execution_time_ms", "message", "tamano_bytes", "tamano_formato"], "solo_rust": True},
        {"ruta": "/api/sql/query", "metodo": "POST", "json": {"db": "comp_sql", "sql": "CREATE TABLE t (id INT AUTO_INCREMENT PRIMARY KEY, n VARCHAR(5)) ENGINE=InnoDB; INSERT INTO t (n) VALUES ('a');"}, "volatiles": ["execution_time_ms", "message", "tamano_bytes", "tamano_formato"], "solo_rust": True},
        {"ruta": "/api/sql/query", "metodo": "POST", "json": {"db": "comp_sql", "sql": "SELECT * FROM t"}, "volatiles": ["execution_time_ms", "message", "tamano_bytes", "tamano_formato"], "solo_rust": True},
        {"ruta": "/api/sql/query", "metodo": "POST", "json": {"db": "comp_sql", "sql": "SELEC x"}, "volatiles": ["execution_time_ms", "message", "tamano_bytes", "tamano_formato"], "solo_rust": True},
        {"ruta": "/api/sql/query", "metodo": "POST", "json": {"sql": "   "}, "solo_rust": True},
        {"ruta": "/api/sql/query", "metodo": "POST", "json": {"db": "comp_sql", "sql": "SELECT 1.5, NULL, 'ñ'"}, "volatiles": ["execution_time_ms", "message", "tamano_bytes", "tamano_formato"], "solo_rust": True},
        {"ruta": "/api/exercise/generate", "metodo": "POST", "json": {"concept": "funciones"}, "volatiles": ["exercise_id"], "restaurar_otro": "{proyecto}/.prig_dataset/exercises.json", "solo_rust": True},
        {"ruta": "/api/exercise/generate", "metodo": "POST", "json": {"concept": "concepto roto", "attempts": 9}, "solo_rust": True},
        {"ruta": "/api/exercise/generate", "metodo": "POST", "json": {"attempts": "x"}, "solo_rust": True},
        {"ruta": "/api/exercise/ex_1/hint", "metodo": "POST", "json": {"level": 7}, "solo_rust": True},
        {"ruta": "/api/exercise/ex_1/hint", "metodo": "POST", "json": {"level": 1, "model": "qwen3:8b"}, "solo_rust": True},
        {"ruta": "/api/exercise/nada/hint", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/librerias/list", "solo_rust": True},
        {"ruta": "/api/librerias/citations?id=numpy", "solo_rust": True},
        {"ruta": "/api/librerias/citations?id=%20Pandas%20", "solo_rust": True},
        {"ruta": "/api/librerias/citations?id=Nueva", "archivo": "{home}/.prig_books/librerias/nueva.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion"], "solo_rust": True},
        {"ruta": "/api/librerias/citations?id=rota", "archivo": "{home}/.prig_books/librerias/rota.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion"], "solo_rust": True},
        {"ruta": "/api/librerias/citations?id=datasets", "archivo": "{home}/.prig_books/librerias/datasets.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion"], "solo_rust": True},
        {"ruta": "/api/librerias/citations", "solo_rust": True},
        {"ruta": "/api/librerias/citations/save", "metodo": "POST", "json": {"lib_id": "pandas", "citation": {"id": "p2", "tema": "  Unir  ", "funcion_o_clase": "pd.merge", "codigo_ejemplo": "pd.merge(a, b)", "parametros_clave": "on, how ,", "tags": ["join"]}}, "archivo": "{home}/.prig_books/librerias/pandas.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion"], "solo_rust": True},
        {"ruta": "/api/librerias/citations/save", "metodo": "POST", "json": {"lib_id": "numpy", "citation": {"id": 7, "tema": "", "modulo": None, "parametros_clave": None, "tags": {"a": 1}}}, "archivo": "{home}/.prig_books/librerias/numpy.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion"], "solo_rust": True},
        {"ruta": "/api/librerias/citations/save", "metodo": "POST", "json": {"lib_id": "numpy", "citation": {"id": "z", "tema": 3}}, "archivo": "{home}/.prig_books/librerias/numpy.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion"], "solo_rust": True},
        {"ruta": "/api/librerias/citations/save", "metodo": "POST", "json": {"lib_id": "numpy", "citation": []}, "solo_rust": True},
        {"ruta": "/api/librerias/citations/delete", "metodo": "POST", "json": {"lib_id": "pandas", "citation_id": "p1"}, "archivo": "{home}/.prig_books/librerias/pandas.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha", "fecha_actualizacion"], "solo_rust": True},
        {"ruta": "/api/librerias/citations/delete", "metodo": "POST", "json": {"lib_id": "pandas", "citation_id": "nada"}, "solo_rust": True},
        {"ruta": "/api/librerias/citations/export", "metodo": "POST", "json": {"lib_id": "pandas", "workspace_path": "{proyecto}/citas"}, "archivo": "{proyecto}/citas/pandas.json", "restaurar": True, "solo_rust": True},
        {"ruta": "/api/librerias/citations/export", "metodo": "POST", "json": {"lib_id": "matplotlib"}, "archivo": "{proyecto}/matplotlib.json", "restaurar": True, "volatiles": ["fecha", "fecha_actualizacion"], "solo_rust": True},
        {"ruta": "/api/librerias/citations/export", "metodo": "POST", "json": {"lib_id": "pandas", "workspace_path": "/proc/no"}, "solo_rust": True},
        {"ruta": "/api/librerias/add", "metodo": "POST", "json": {"repo": "https://github.com/scikit-learn/scikit-learn/"}, "archivo": "{home}/.prig_books/librerias/lista_librerias.json", "restaurar": True, "archivo_json": True, "volatiles": [], "solo_rust": True},
        {"ruta": "/api/librerias/add", "metodo": "POST", "json": {"repo": " huggingface/datasets ", "name": "HF", "desc": "datos"}, "archivo": "{home}/.prig_books/librerias/lista_librerias.json", "restaurar": True, "archivo_json": True, "volatiles": [], "solo_rust": True},
        {"ruta": "/api/librerias/add", "metodo": "POST", "json": {"repo": "sinbarra"}, "solo_rust": True},
        {"ruta": "/api/librerias/add", "metodo": "POST", "json": {"name": "x"}, "solo_rust": True},
        {"ruta": "/api/librerias/all-citations", "solo_rust": True},
        {"ruta": "/api/librerias/all-citations?query=agrupar%20tablas%20de", "solo_rust": True},
        {"ruta": "/api/librerias/all-citations?query=svd", "solo_rust": True},
        {"ruta": "/api/librerias/analyze", "metodo": "POST", "json": {"lib_id": "NumPy", "topic": "np.einsum"}, "solo_rust": True},
        {"ruta": "/api/librerias/analyze", "metodo": "POST", "json": {"lib_id": "otra", "topic": "f", "model": "qwen3:8b"}, "solo_rust": True},
        {"ruta": "/api/librerias/analyze", "metodo": "POST", "json": {"lib_id": "otra"}, "solo_rust": True},
        {"ruta": "/api/papers/list", "solo_rust": True},
        {"ruta": "/api/papers/list?q=regresion", "solo_rust": True},
        {"ruta": "/api/papers/list?q=Gradiente%20%20descenso", "solo_rust": True},
        {"ruta": "/api/papers/list?q=xgboost&categoria=todas", "solo_rust": True},
        {"ruta": "/api/papers/list?categoria=supervisado", "solo_rust": True},
        {"ruta": "/api/papers/list?q=%C3%A1rbol", "solo_rust": True},
        {"ruta": "/api/papers/list?q=no-aparece-en-ninguno", "solo_rust": True},
        # escrituras de desafíos (cada lado parte del mismo archivo)
        {"ruta": "/api/desafios/{desafio}/paginas", "metodo": "PUT", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/{desafio}.json",
         "json": {"paginas": [{"nombre": "mi_pila.py", "contenido": "x = 1\n", "otra": 2}, {"nombre": "util.h", "contenido": None}]}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/paginas", "metodo": "PUT", "json": {"paginas": [{"nombre": "mal nombre.py"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/paginas", "metodo": "PUT", "json": {"paginas": [{"nombre": "os.py"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/paginas", "metodo": "PUT", "json": {"paginas": [{"nombre": "a.py"}, {"nombre": "A.py"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/paginas", "metodo": "PUT", "json": {"paginas": []}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/paginas", "metodo": "PUT", "json": {"paginas": [{"nombre": "x.py", "contenido": "ñ" * 120000}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_0000000000/paginas", "metodo": "PUT", "json": {"paginas": [{"nombre": "x.py"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/malo/paginas", "metodo": "PUT", "json": {"paginas": [{"nombre": "x.py"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/razonamiento/visto", "metodo": "POST", "json": {"pasos_vistos": 4}, "restaurar": True,
         "archivo_json": True, "archivo": "{home}/.prig_desafios/desafios/{desafio}.json", "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/razonamiento/visto", "metodo": "POST", "json": {"pasos_vistos": "99"}, "restaurar": True,
         "archivo_json": True, "archivo": "{home}/.prig_desafios/desafios/{desafio}.json", "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/razonamiento/visto", "metodo": "POST", "json": {"pasos_vistos": 2.5}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/razonamiento/visto", "metodo": "POST", "json": {"pasos_vistos": "tres"}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/razonamiento/visto", "metodo": "POST", "json": {"pasos_vistos": True}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/razonamiento/visto", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/rendirse", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/{desafio}.json", "solo_rust": True},
        {"ruta": "/api/desafios/{desafio2}/rendirse", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/{desafio2}.json", "solo_rust": True},
        {"ruta": "/api/desafios/des_0000000000/rendirse", "metodo": "POST", "solo_rust": True},
        {"ruta": "/api/desafios/{desafio2}", "metodo": "DELETE", "restaurar": True, "archivo": "{home}/.prig_desafios/desafios/{desafio2}.json", "solo_rust": True},
        {"ruta": "/api/desafios/des_ffffffffff", "metodo": "DELETE", "solo_rust": True},
        # ejecutar una página de un desafío (Python como herramienta; nada de modelos)
        {"ruta": "/api/desafios/{desafio}/ejecutar", "metodo": "POST",
         "json": {"pagina": "main.py", "paginas": [{"nombre": "main.py", "contenido": "import util\nprint('hola', util.f(2))\nimport sys\nprint('err', file=sys.stderr)\n"},
                                                   {"nombre": "util.py", "contenido": "def f(x):\n    return x * 21\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/ejecutar", "metodo": "POST",
         "json": {"pagina": "main.py", "paginas": [{"nombre": "main.py", "contenido": "raise ValueError('mal')\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/ejecutar", "metodo": "POST",
         "json": {"pagina": "t.py", "paginas": [{"nombre": "t.py", "contenido": "import pytest\nprint(pytest.mark.slow(lambda: 3)())\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/ejecutar", "metodo": "POST", "json": {"pagina": "no.py", "paginas": [{"nombre": "a.py"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/ejecutar", "metodo": "POST", "json": {"paginas": [{"nombre": "a.py"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_0000000000/ejecutar", "metodo": "POST", "json": {"pagina": "a.py", "paginas": [{"nombre": "a.py"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/{desafio}/detener", "metodo": "POST", "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa1/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa1.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return 2 * x\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa1/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa1.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return x + 2\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa1/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa1.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x)\\n    return\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa2/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa2.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return 2 * x\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa2/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa2.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return x + 2\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa2/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa2.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x)\\n    return\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa3/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa3.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return 2 * x\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa3/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa3.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return x + 2\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa3/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa3.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x)\\n    return\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa4/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa4.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return 2 * x\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa4/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa4.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return x + 2\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa4/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa4.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x)\\n    return\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa6/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa6.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return 2 * x\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa6/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa6.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return x + 2\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa6/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa6.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x)\\n    return\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa5/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa5.json", "json": {"paginas": [{"nombre": "sol.h", "contenido": "inline int doble(int x) { return 2 * x; }\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa5/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa5.json", "json": {"paginas": [{"nombre": "sol.h", "contenido": "inline int doble(int x) { return x + 2; }\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa5/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa5.json", "json": {"paginas": [{"nombre": "sol.h", "contenido": "inline int doble(int x) { return 2 * x }\\n"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa1/comprobar", "metodo": "POST", "json": {"paginas": [{"nombre": "test_sol.py"}]}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa1/comprobar", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/desafios/des_aaaaaaaaa6/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_hub/progreso.jsonl", "solo_archivo": True, "json": {"paginas": [{"nombre": "sol.py", "contenido": "x = 1\n"}]}, "solo_rust": True},
        {"ruta": "/api/learning/metrics", "solo_rust": True},
        {"ruta": "/api/learning/metrics?days=1", "solo_rust": True},
        {"ruta": "/api/learning/metrics?days=0", "solo_rust": True},
        {"ruta": "/api/learning/metrics?days=400", "solo_rust": True},
        {"ruta": "/api/learning/metrics?days=dos", "solo_rust": True},
        {"ruta": "/api/exercise/recent", "solo_rust": True},
        {"ruta": "/api/exercise/recent?limit=2", "solo_rust": True},
        {"ruta": "/api/exercise/recent?concept=funciones&limit=100", "solo_rust": True},
        {"ruta": "/api/exercise/recent?limit=0", "solo_rust": True},
        {"ruta": "/api/exercise/ex_3", "solo_rust": True},
        {"ruta": "/api/exercise/no_existe", "solo_rust": True},
        {"ruta": "/api/exercise/ex_1/solution", "solo_rust": True},
        {"ruta": "/api/exercise/no_existe/solution", "solo_rust": True},
        {"ruta": "/api/exercise/submit", "metodo": "POST", "restaurar_otro": "{proyecto}/.prig_dataset/learning.db", "json": {"exercise_id": "ex_1", "code": "def doble(x):\n    return x * 2\n", "hints_used": 1}, "solo_rust": True},
        {"ruta": "/api/exercise/submit", "metodo": "POST", "restaurar_otro": "{proyecto}/.prig_dataset/learning.db", "json": {"exercise_id": "ex_1", "code": "def doble(x):\n    return x + 2\n"}, "solo_rust": True},
        {"ruta": "/api/exercise/submit", "metodo": "POST", "restaurar_otro": "{proyecto}/.prig_dataset/learning.db", "json": {"exercise_id": "ex_1", "code": "def doble(x)\n"}, "solo_rust": True},
        {"ruta": "/api/exercise/submit", "metodo": "POST", "restaurar_otro": "{proyecto}/.prig_dataset/learning.db", "json": {"exercise_id": "ex_1", "code": "   "}, "solo_rust": True},
        {"ruta": "/api/exercise/submit", "metodo": "POST", "restaurar_otro": "{proyecto}/.prig_dataset/learning.db", "json": {"exercise_id": "ex_1", "code": "raise KeyError('x')"}, "solo_rust": True},
        {"ruta": "/api/exercise/submit", "metodo": "POST", "json": {"exercise_id": "nada", "code": "x"}, "solo_rust": True},
        {"ruta": "/api/exercise/submit", "metodo": "POST", "json": {"code": "x"}, "solo_rust": True},
        {"ruta": "/api/learning/metrics", "solo_rust": True},
        {"ruta": "/api/guided/list", "solo_rust": True},
        {"ruta": "/api/seguimiento/list", "solo_rust": True},
        {"solo_rust": True, "ruta": "/api/study-plan/list"},
        {"ruta": "/api/guided/seg_aaaa0002", "metodo": "DELETE", "restaurar": True, "archivo": "{proyecto}/.prig_seguimientos/seg_aaaa0002.json", "solo_rust": True},
        {"ruta": "/api/seguimiento/seg_aaaa0001", "metodo": "DELETE", "restaurar": True, "archivo": "{proyecto}/.prig_seguimientos/seg_aaaa0001.json", "solo_rust": True},
        {"ruta": "/api/guided/no_existe", "metodo": "DELETE", "solo_rust": True},
        {"ruta": "/api/dataset/summary", "volatiles": ["created_at", "updated_at", "last_activity", "block_id"], "solo_rust": True},
        {"ruta": "/api/dataset/export", "volatiles": ["created_at", "updated_at", "last_activity", "block_id"], "solo_rust": True},
        {"ruta": "/api/guided/seg_aaaa0006/progress", "metodo": "POST", "json": {"completed_blocks": ["b1", "b2", "b2"], "solo_rust": True},
         "archivo": "{proyecto}/.prig_seguimientos/seg_aaaa0006.json", "restaurar": True, "archivo_json": True,
         "contenedores": ["completion_dates"], "solo_rust": True},
        {"ruta": "/api/seguimiento/seg_aaaa0006/progress", "metodo": "POST", "json": {"completed_blocks": []},
         "archivo": "{proyecto}/.prig_seguimientos/seg_aaaa0006.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/guided/no_existe/progress", "metodo": "POST", "json": {"completed_blocks": []}, "solo_rust": True},
        {"ruta": "/api/seguimiento/no_existe/progress", "metodo": "POST", "json": {"completed_blocks": []}, "solo_rust": True},
        {"ruta": "/api/guided/seg_aaaa0006/progress", "metodo": "POST", "json": {"completed_blocks": "b1"}, "solo_rust": True},
        {"ruta": "/api/guided/seg_aaaa0006/progress", "metodo": "POST", "json": {"completed_blocks": [1, "b"]}, "solo_rust": True},
        {"ruta": "/api/guided/seg_aaaa0006/progress", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/guided/seg_aaaa0003/progress", "metodo": "POST", "json": {"completed_blocks": []}, "solo_rust": True},
        {"solo_rust": True, "ruta": "/api/study-plan/progress/toggle-criterion", "metodo": "POST",
         "json": {"plan_id": "plan_completo", "module_id": "m1", "criterion_text": "c1"},
         "archivo": "{proyecto}/.prig_plans/plan_completo/current.json", "restaurar": True, "archivo_json": True,
         "volatiles": ["updated_at"]},
        {"solo_rust": True, "ruta": "/api/study-plan/progress/toggle-notebook", "metodo": "POST", "json": {"plan_id": "plan_completo", "notebook_id": "nb1"},
         "archivo": "{proyecto}/.prig_plans/plan_completo/current.json", "restaurar": True, "archivo_json": True,
         "volatiles": ["updated_at"]},
        {"solo_rust": True, "ruta": "/api/study-plan/progress/toggle-notebook", "metodo": "POST", "json": {"plan_id": "plan_completo", "notebook_id": "nb9"},
         "archivo": "{proyecto}/.prig_plans/plan_completo/current.json", "restaurar": True, "archivo_json": True,
         "volatiles": ["updated_at"]},
        {"solo_rust": True, "ruta": "/api/study-plan/progress/toggle-notebook", "metodo": "POST", "json": {"plan_id": "no_existe", "notebook_id": "x"}},
        {"solo_rust": True, "ruta": "/api/study-plan/progress/toggle-criterion", "metodo": "POST", "json": {"plan_id": "plan_completo"}},
        {"ruta": "/api/guided/seg_aaaa0006", "solo_rust": True},
        {"ruta": "/api/seguimiento/seg_aaaa0006", "solo_rust": True},
        {"ruta": "/api/guided/seg_aaaa0008", "solo_rust": True},
        {"ruta": "/api/guided/seg_aaaa0003", "solo_rust": True},
        {"ruta": "/api/guided/seg_aaaa0004", "solo_rust": True},
        {"ruta": "/api/seguimiento/seg_aaaa0007", "solo_rust": True},
        {"ruta": "/api/guided/no_existe", "solo_rust": True},
        {"ruta": "/api/seguimiento/no_existe", "solo_rust": True},
        {"ruta": "/api/seguimiento/no_existe", "metodo": "DELETE", "solo_rust": True},
        {"ruta": "/api/study-plan/plan_viejo", "metodo": "DELETE", "restaurar": True, "archivo": "{proyecto}/.prig_plans/plan_viejo.json", "solo_rust": True},
        {"ruta": "/api/study-plan/no_existe", "metodo": "DELETE", "solo_rust": True},
        {"ruta": "/api/study-plan/%2E%2E", "metodo": "DELETE", "solo_rust": True},
        {"solo_rust": True, "ruta": "/api/study-plan/list"},
        {"solo_rust": True, "ruta": "/api/study-plan/state/plan_borrador"},
        {"solo_rust": True, "ruta": "/api/study-plan/state/plan_borrador?version=1"},
        {"solo_rust": True, "ruta": "/api/study-plan/state/plan_borrador?version=0"},
        {"solo_rust": True, "ruta": "/api/study-plan/state/plan_borrador?version=7"},
        {"solo_rust": True, "ruta": "/api/study-plan/state/plan_borrador?version=uno"},
        {"solo_rust": True, "ruta": "/api/study-plan/state/plan_viejo?version=3", "volatiles": ["created_at", "updated_at"]},
        {"solo_rust": True, "ruta": "/api/study-plan/state/no_existe"},
        {"solo_rust": True, "ruta": "/api/study-plan/init", "metodo": "POST", "json": {"user_goal": "Grafos"}, "volatiles": ["plan_id", "created_at", "updated_at"]},
        {"solo_rust": True, "ruta": "/api/study-plan/init", "metodo": "POST", "json": {}},
        {"solo_rust": True, "ruta": "/api/study-plan/approve", "metodo": "POST", "json": {"plan_id": "plan_borrador", "step": "knowledge"}},
        {"solo_rust": True, "ruta": "/api/study-plan/approve", "metodo": "POST", "json": {"plan_id": "plan_borrador", "step": "otro"}},
        {"solo_rust": True, "ruta": "/api/study-plan/approve", "metodo": "POST", "json": {"plan_id": "no_existe", "step": "learning"}},
        {"solo_rust": True, "ruta": "/api/study-plan/agent2", "metodo": "POST", "json": {"plan_id": "plan_borrador"}},
        {"solo_rust": True, "ruta": "/api/study-plan/agent3", "metodo": "POST", "json": {"plan_id": "plan_borrador"}},
        {"solo_rust": True, "ruta": "/api/study-plan/agent1", "metodo": "POST", "json": {"plan_id": "no_existe"}},
        {"solo_rust": True, "ruta": "/api/study-plan/agent1", "metodo": "POST", "json": {"model": "otro"}},
        {"solo_rust": True, "ruta": "/api/study-plan/change-request", "metodo": "POST", "json": {"plan_id": "no_existe", "user_prompt": "x"}},
        {"solo_rust": True, "ruta": "/api/study-plan/change-request", "metodo": "POST", "json": {"plan_id": "plan_borrador", "user_prompt": "MODIFY_OBJECTIVE|sin mapa"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/agent1", "metodo": "POST", "json": {"plan_id": "plan_borrador"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/agent1", "metodo": "POST", "json": {"plan_id": "plan_borrador", "model": "qwen3:8b"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/approve", "metodo": "POST", "json": {"plan_id": "plan_borrador", "step": "practical"}},
        {"solo_rust": True, "ruta": "/api/study-plan/change-request", "metodo": "POST", "json": {"plan_id": "plan_borrador", "user_prompt": "ADD_PREREQUISITE|Cálculo"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/change-request", "metodo": "POST", "json": {"plan_id": "plan_borrador", "user_prompt": "REMOVE_PREREQUISITE|ÁLGEBRA"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/change-request", "metodo": "POST", "json": {"plan_id": "plan_borrador", "user_prompt": "ADD_CONCEPT|Vistas"}, **PLAN, "volatiles": PLAN["volatiles"] + ["concept_id"]},
        {"solo_rust": True, "ruta": "/api/study-plan/change-request", "metodo": "POST", "json": {"plan_id": "plan_borrador", "user_prompt": "REMOVE_CONCEPT|joins"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/change-request", "metodo": "POST", "json": {"plan_id": "plan_borrador", "user_prompt": "REMOVE_CONCEPT|conc_b"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/change-request", "metodo": "POST", "json": {"plan_id": "plan_borrador", "user_prompt": "ADD_TOPIC|Grafos"}, **PLAN, "volatiles": PLAN["volatiles"] + ["concept_id", "topic_id"]},
        {"solo_rust": True, "ruta": "/api/study-plan/change-request", "metodo": "POST", "json": {"plan_id": "plan_borrador", "user_prompt": "MODIFY_OBJECTIVE|Nuevo objetivo"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/change-request", "metodo": "POST", "json": {"plan_id": "plan_borrador", "user_prompt": "texto libre"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/change-request", "metodo": "POST", "json": {"plan_id": "plan_borrador", "user_prompt": "ADD_PRACTICAL_MODULE|sin currículo"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/state/plan_borrador?version=3", "volatiles": PLAN["volatiles"]},
        {"solo_rust": True, "ruta": "/api/study-plan/approve", "metodo": "POST", "json": {"plan_id": "plan_borrador", "step": "knowledge"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/approve", "metodo": "POST", "json": {"plan_id": "plan_borrador", "step": "knowledge"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/agent2", "metodo": "POST", "json": {"plan_id": "plan_borrador"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/change-request", "metodo": "POST", "json": {"plan_id": "plan_borrador", "user_prompt": "ADD_PRACTICAL_MODULE|Vistas"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/approve", "metodo": "POST", "json": {"plan_id": "plan_borrador", "step": "learning"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/approve", "metodo": "POST", "json": {"plan_id": "plan_borrador", "step": "practical"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/agent3", "metodo": "POST", "json": {"plan_id": "plan_borrador"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/approve", "metodo": "POST", "json": {"plan_id": "plan_borrador", "step": "learning"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/approve", "metodo": "POST", "json": {"plan_id": "plan_borrador", "step": "learning"}, **PLAN},
        {"solo_rust": True, "ruta": "/api/study-plan/agent3", "metodo": "POST", "json": {"plan_id": "plan_completo"},
         "archivo": "{proyecto}/.prig_plans/plan_completo/current.json", "restaurar": True, "archivo_json": True,
         "volatiles": ["timestamp", "updated_at"]},
        {"solo_rust": True, "ruta": "/api/study-plan/progress/toggle-criterion", "metodo": "POST",
         "json": {"plan_id": "plan_borrador", "module_id": "mod_01", "criterion_text": "Une dos tablas"}, **PLAN},
        # el cuaderno explicado que se escribe en notebooks_plan/, byte a byte (con los criterios del módulo del currículo)
        {"solo_rust": True, "ruta": "/api/study-plan/agent3", "metodo": "POST", "json": {"plan_id": "plan_borrador"},
         "archivo": "{proyecto}/notebooks_plan/mod_01_nb_01.ipynb", "restaurar": True, "solo_archivo": True},
        {"solo_rust": True, "ruta": "/api/study-plan/agent3", "metodo": "POST", "json": {"plan_id": "plan_borrador"},
         "archivo": "{proyecto}/notebooks_plan/mod_09_nb_03.ipynb", "restaurar": True, "solo_archivo": True},
        # escrituras de la configuración: misma respuesta y mismo archivo, byte a byte
        {"ruta": "/api/config/apariencia", "metodo": "POST", "json": {"tema": "oscuro", "ñ": [1, 2.5, None, True], "x": {"y": "z"}},
         "archivo": "{copia}/.prig_dataset/apariencia.json", "solo_rust": True},
        {"ruta": "/api/config/sintaxis", "metodo": "POST", "json": {}, "archivo": "{copia}/.prig_dataset/sintaxis_personalizada.json", "solo_rust": True},
        {"ruta": "/api/config/motor_movimiento", "metodo": "POST", "json": {"fps": 30, "efecto": "lluvia"},
         "archivo": "{copia}/.prig_dataset/motor_movimiento.json", "solo_rust": True},
        {"ruta": "/api/config/audio_reactivo", "metodo": "POST", "json": [1, 2], "solo_rust": True},
        {"ruta": "/api/config/accesibilidad", "metodo": "POST", "json": "texto", "solo_rust": True},
        {"ruta": "/api/config/accesibilidad", "metodo": "POST", "crudo": "{roto", "solo_rust": True},
        {"ruta": "/api/config/accesibilidad", "metodo": "POST", "crudo": "", "solo_rust": True},
        {"ruta": "/api/config/profiles", "metodo": "POST", "json": {"perfil_activo": "mio", "perfiles": [{"id": "mio", "n": 1}], "extra": 1},
         "archivo": "{copia}/.prig_dataset/config_profiles.json", "solo_rust": True},
        {"ruta": "/api/config/profiles", "metodo": "POST", "json": {"perfiles": [{"id": "a"}]}, "solo_rust": True},
        {"ruta": "/api/config/profiles", "metodo": "POST", "json": {"perfil_activo": None, "perfiles": []}, "solo_rust": True},
        {"ruta": "/api/config/profiles", "metodo": "POST", "json": {"perfil_activo": 3, "perfiles": [1, {"a": 1}]}, "solo_rust": True},
        {"ruta": "/api/config/profiles", "metodo": "POST", "json": {"perfil_activo": "x"}, "solo_rust": True},
        {"ruta": "/api/config/profiles", "metodo": "POST", "json": {"perfiles": "no"}, "solo_rust": True},
        {"ruta": "/api/config/profiles", "metodo": "POST", "json": [1], "solo_rust": True},
        {"ruta": "/api/config/profiles/reset", "metodo": "POST", "archivo": "{copia}/.prig_dataset/config_profiles.json", "solo_rust": True},
        {"ruta": "/api/config/estado_completo", "metodo": "POST",
         "json": {"apariencia": {"a": 1}, "sintaxis": "no", "perfiles": {"perfil_activo": "z", "perfiles": []}, "otro": {}},
         "archivo": "{copia}/.prig_dataset/config_profiles.json", "solo_rust": True},
        {"ruta": "/api/config/estado_completo", "solo_rust": True},
        {"ruta": "/api/flags", "metodo": "POST", "json": {"name": "learning_telemetry", "enabled": False}, "archivo": "{home}/.prig_flags.json", "solo_rust": True},
        {"ruta": "/api/flags", "metodo": "POST", "json": {"name": "learning_telemetry", "enabled": "yes"}, "archivo": "{home}/.prig_flags.json", "solo_rust": True},
        {"ruta": "/api/flags", "metodo": "POST", "json": {"name": "learning_telemetry"}, "archivo": "{home}/.prig_flags.json", "solo_rust": True},
        {"ruta": "/api/flags", "metodo": "POST", "json": {"name": "learning_telemetry", "enabled": "quizá"}, "solo_rust": True},
        {"ruta": "/api/flags", "metodo": "POST", "json": {"name": 5, "enabled": [1]}, "solo_rust": True},
        {"ruta": "/api/flags", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/flags", "metodo": "POST", "json": {"name": "no_existe", "enabled": True}, "solo_rust": True},
        {"ruta": "/api/flags", "solo_rust": True},
        # métodos que la ruta propia de Rust no atiende: tienen que llegar a Python por el proxy, con «/api»
        {"ruta": "/api/flags", "metodo": "POST", "json": {"nombre": "no_existe", "valor": True}, "solo_rust": True},
        {"ruta": "/api/desafios/des_0000000000", "metodo": "DELETE", "solo_rust": True},
        {"ruta": "/api/workspace/segunda", "metodo": "POST", "json": {"path": None}, "solo_rust": True},
        {"ruta": "/api/config/profiles", "solo_rust": True},
        {"ruta": "/api/config/apariencia", "solo_rust": True},
        {"ruta": "/api/config/sintaxis", "solo_rust": True},
        {"ruta": "/api/config/motor_movimiento", "solo_rust": True},
        {"ruta": "/api/config/audio_reactivo", "solo_rust": True},
        {"ruta": "/api/config/accesibilidad", "solo_rust": True},
        {"ruta": "/api/config/estado_completo", "solo_rust": True},
        {"ruta": "/api/explorador/atajos", "solo_rust": True},
        {"ruta": "/api/explorador/listar", "solo_rust": True},
        {"ruta": "/api/explorador/listar?ruta={home}/Documentos", "solo_rust": True},
        {"ruta": "/api/explorador/listar?ruta={home}&recursivo=true", "solo_rust": True},
        {"ruta": "/api/explorador/listar?ruta={home}&recursivo=xx", "solo_rust": True},
        {"ruta": "/api/explorador/listar?ruta=/etc", "solo_rust": True},
        {"ruta": "/api/explorador/listar?ruta={home}/no_existe", "solo_rust": True},
        {"ruta": "/api/explorador/listar?ruta={home}/Escritorio/nota.txt", "solo_rust": True},
        {"ruta": "/api/explorador/listar?ruta={proyecto}", "solo_rust": True},
        {"ruta": "/api/explorador/buscar?q=libro", "solo_rust": True},
        {"ruta": "/api/explorador/buscar?q=redes%20neuronales", "solo_rust": True},
        {"ruta": "/api/explorador/buscar?q=pdf&desde={home}/Descargas", "solo_rust": True},
        {"ruta": "/api/explorador/buscar", "solo_rust": True},
        {"ruta": "/api/ide/recientes", "solo_rust": True},
        {"ruta": "/api/workspace/directories", "solo_rust": True},
        {"ruta": "/api/workspace/directories?ruta={proyecto}/lib", "solo_rust": True},
        {"ruta": "/api/workspace/directories?ruta=/no/existe", "solo_rust": True},
        {"ruta": "/api/workspace/projects", "solo_rust": True},
        {"ruta": "/api/workspace/segunda", "solo_rust": True},
        {"ruta": "/api/flags", "solo_rust": True},
        # el panel del motor MoE: comparado 13 de 13 con Python antes de retirar su ruta (F10, tanda 9)
        {"ruta": "/api/papers/detail?id=02_regresion_logistica", "solo_rust": True},
        {"ruta": "/api/papers/detail?id=3&tipo=ficha", "solo_rust": True},
        {"ruta": "/api/papers/detail?id=../../02_regresion_logistica.md&tipo=", "solo_rust": True},
        {"ruta": "/api/papers/detail?id=nada", "solo_rust": True},
        {"ruta": "/api/papers/detail", "solo_rust": True},
        {"ruta": "/api/papers/download", "metodo": "POST", "json": {"paper_id": "02_regresion_logistica"}, "archivo": "{proyecto}/papers_ml/02_regresion_logistica_analisis.md", "restaurar": True, "solo_rust": True},
        {"ruta": "/api/papers/download", "metodo": "POST", "json": {"paper_id": "1", "tipo": "ficha", "workspace_path": "{proyecto}/otra"}, "archivo": "{proyecto}/otra/papers_ml/1_ficha.md", "restaurar": True, "solo_rust": True},
        {"ruta": "/api/papers/download", "metodo": "POST", "json": {"paper_id": "nada"}, "solo_rust": True},
        {"ruta": "/api/papers/download", "metodo": "POST", "json": {"tipo": 3}, "solo_rust": True},
        {"ruta": "/api/papers/ask", "metodo": "POST", "json": {"paper_id": "02_regresion_logistica", "pregunta": "¿qué es la regresión logística?", "historial": [{"rol": "user", "texto": "hola"}, {"rol": "ia", "texto": None}, {"texto": 3}, 5]}, "solo_rust": True},
        {"ruta": "/api/papers/ask", "metodo": "POST", "json": {"paper_id": "nada_raro", "pregunta": "x", "modelo": "qwen3:8b", "tipo": "ficha"}, "solo_rust": True},
        {"ruta": "/api/papers/ask", "metodo": "POST", "json": {"paper_id": "x"}, "solo_rust": True},
        {"ruta": "/api/note/explain", "metodo": "POST", "json": {"topic": "recursión en Python"}, "solo_rust": True},
        {"ruta": "/api/note/explain", "metodo": "POST", "json": {"topic": "redes neuronales", "model": "qwen3:8b"}, "solo_rust": True},
        {"ruta": "/api/note/explain", "metodo": "POST", "json": {"model": 3}, "solo_rust": True},
        {"ruta": "/api/audio/aplicaciones", "solo_rust": True},
        {"ruta": "/api/audio/datos_actuales", "solo_rust": True},
        {"ruta": "/api/audio/seleccionar_fuente", "metodo": "POST", "json": {"fuente_id": 42}, "solo_rust": True},
        {"ruta": "/api/audio/seleccionar_fuente", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/audio/seleccionar_fuente", "metodo": "POST", "json": [1], "solo_rust": True},
        {"ruta": "/api/audio/seleccionar_fuente", "metodo": "POST", "json": {"fuente_id": None}, "solo_rust": True},
        {"ruta": "/api/audio/datos_actuales", "solo_rust": True},
        {"ruta": "/api/ide/pantalla-completa", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/folder/code-files?path={proyecto}/exportar", "solo_rust": True},
        {"ruta": "/api/folder/code-files?path={proyecto}/exportar/sub", "solo_rust": True},
        {"ruta": "/api/folder/code-files?path={proyecto}/exportar/a.py", "solo_rust": True},
        {"ruta": "/api/folder/code-files?path=/no/existe", "solo_rust": True},
        {"ruta": "/api/folder/code-files", "solo_rust": True},
        {"ruta": "/api/export/pdf-preview", "metodo": "POST", "json": {"folder_path": "{proyecto}/exportar", "file_paths": ["{proyecto}/exportar/a.py", "{proyecto}/exportar/b.js", "{proyecto}/exportar/sub/notas.md", "{proyecto}/exportar/sub/vacio.sql", "{proyecto}/exportar/cuaderno.ipynb", "{proyecto}/exportar/roto.ipynb", "{proyecto}/exportar/no.py", "{proyecto}/exportar/sub"]}, "sin_resaltado": True, "solo_rust": True},
        {"ruta": "/api/export/pdf-preview", "metodo": "POST", "json": {"folder_path": "{proyecto}/exportar/", "file_paths": ["{proyecto}/exportar/a.py", "{proyecto}/exportar/b.js", "{proyecto}/exportar/sub/notas.md", "{proyecto}/exportar/sub/vacio.sql", "{proyecto}/exportar/cuaderno.ipynb", "{proyecto}/exportar/roto.ipynb", "{proyecto}/exportar/no.py", "{proyecto}/exportar/sub"], "theme": "dark", "options": {"include_outputs": False, "show_line_numbers": False, "include_cover": False, "font_size": "", "page_size": None}}, "sin_resaltado": True, "solo_rust": True},
        {"ruta": "/api/export/pdf-preview", "metodo": "POST", "json": {"folder_path": "{proyecto}/exportar", "file_paths": ["{proyecto}/exportar/a.py"], "theme": "executive", "options": {"font_size": 15, "page_size": "letter"}}, "sin_resaltado": True, "solo_rust": True},
        {"ruta": "/api/export/pdf-preview", "metodo": "POST", "json": {"folder_path": "{proyecto}/exportar", "file_paths": "x"}, "solo_rust": True},
        {"ruta": "/api/export/pdf-preview", "metodo": "POST", "json": {"file_paths": []}, "solo_rust": True},
        {"ruta": "/api/export/pdf-download", "metodo": "POST", "json": {"folder_path": "{proyecto}/exportar", "file_paths": ["{proyecto}/exportar/a.py", "{proyecto}/exportar/b.js", "{proyecto}/exportar/sub/notas.md", "{proyecto}/exportar/sub/vacio.sql", "{proyecto}/exportar/cuaderno.ipynb", "{proyecto}/exportar/roto.ipynb", "{proyecto}/exportar/no.py", "{proyecto}/exportar/sub"]}, "solo_rust": True},
        {"ruta": "/api/export/pdf-download", "metodo": "POST", "json": {"folder_path": "/", "file_paths": []}, "solo_rust": True},
        {"ruta": "/api/export/pdf-download", "metodo": "POST", "json": {"folder_path": "{proyecto}/exportar", "file_paths": [], "options": 3}, "solo_rust": True},
        {"ruta": "/api/buscador/fuentes", "solo_rust": True},
        {"ruta": "/api/buscador/buscar?q=qwen", "solo_rust": True},
        {"ruta": "/api/buscador/buscar?q=qwen&fuentes=ollama,nada&orden=recientes&pagina_ollama=2", "solo_rust": True},
        {"ruta": "/api/buscador/buscar?fuentes=huggingface&pagina_huggingface=abc&orden=tendencia", "solo_rust": True},
        {"ruta": "/api/buscador/buscar?pagina_ollama=x", "solo_rust": True},
        {"ruta": "/api/buscador/localizar", "solo_rust": True},
        {"ruta": "/api/buscador/localizar?texto=qwen3:8b", "solo_rust": True},
        {"ruta": "/api/buscador/localizar?texto=https://huggingface.co/Qwen/Qwen3-8B-GGUF", "solo_rust": True},
        {"ruta": "/api/buscador/localizar?texto=Qwen/Qwen3-8B", "solo_rust": True},
        {"ruta": "/api/buscador/localizar?texto=", "solo_rust": True},
        {"ruta": "/api/buscador/variantes", "solo_rust": True},
        {"ruta": "/api/buscador/variantes?fuente=nada&id=x", "solo_rust": True},
        {"ruta": "/api/buscador/variantes?fuente=ollama&id=qwen3", "solo_rust": True},
        {"ruta": "/api/buscador/comprobar?ref=qwen3:8b", "solo_rust": True},
        {"ruta": "/api/buscador/comprobar?ref=", "solo_rust": True},
        {"ruta": "/api/buscador/comprobar?ref=a%20b", "solo_rust": True},
        {"ruta": "/api/buscador/analizar?ref=", "solo_rust": True},
        {"ruta": "/api/buscador/analizar?ref=qwen3:8b", "solo_rust": True},
        {"ruta": "/api/buscador/analizar", "solo_rust": True},
        {"ruta": "/api/buscador/novedades", "solo_rust": True},
        {"ruta": "/api/buscador/actualizaciones?max_edad=x", "solo_rust": True},
        {"ruta": "/api/buscador/actualizaciones?forzar=quizas", "solo_rust": True},
        {"ruta": "/api/buscador/actualizaciones?forzar=true", **{"archivo": "{home}/.prig_buscador.json", "restaurar": True, "archivo_json": True}, "volatiles": ["marca", "fecha"], "solo_rust": True},
        {"ruta": "/api/buscador/seguidos", "solo_rust": True},
        {"ruta": "/api/buscador/actualizaciones", "solo_rust": True},
        {"ruta": "/api/buscador/seguidos?revisar=1", **{"archivo": "{home}/.prig_buscador.json", "restaurar": True, "archivo_json": True}, "volatiles": ["revisado"], "solo_rust": True},
        {"ruta": "/api/buscador/seguidos?revisar=x", "solo_rust": True},
        {"ruta": "/api/buscador/seguidos", "metodo": "POST", "json": {"fuente": "ollama", "id": "qwen3"}, **{"archivo": "{home}/.prig_buscador.json", "restaurar": True, "archivo_json": True}, "solo_rust": True},
        {"ruta": "/api/buscador/seguidos", "metodo": "POST", "json": {"fuente": "nada", "id": "qwen3"}, "solo_rust": True},
        {"ruta": "/api/buscador/seguidos", "metodo": "POST", "json": {"fuente": "ollama"}, "solo_rust": True},
        {"ruta": "/api/buscador/seguidos/dejar", "metodo": "POST", "json": {"fuente": "ollama", "id": "qwen3"}, **{"archivo": "{home}/.prig_buscador.json", "restaurar": True, "archivo_json": True}, "solo_rust": True},
        {"ruta": "/api/buscador/seguidos/dejar", "metodo": "POST", "json": {"id": 3}, "solo_rust": True},
        {"ruta": "/api/buscador/seguidos/visto", "metodo": "POST", "json": {"fuente": "ollama", "id": "qwen3"}, "solo_rust": True},
        {"ruta": "/api/modelos", "solo_rust": True},
        {"ruta": "/api/modelos/catalogo", "solo_rust": True},
        {"ruta": "/api/modelos/ficha?modelo=qwen2.5-coder:7b", "solo_rust": True},
        {"ruta": "/api/modelos/ficha?modelo=nada:1b", "solo_rust": True},
        {"ruta": "/api/modelos/ficha", "solo_rust": True},
        {"ruta": "/api/modelos/config", "solo_rust": True},
        {"ruta": "/api/modelos/config?modelo=qwen2.5-coder:7b&uso=tutor", "solo_rust": True},
        {"ruta": "/api/modelos/config?uso=malo", "solo_rust": True},
        {"ruta": "/api/modelos/config", "metodo": "POST", "json": {"capa": "modelo", "modelo": "m", "valores": {"temperature": 0.5, "num_ctx": 8192}}, **{"archivo": "{home}/.prig_modelos.json", "restaurar": True, "archivo_json": True}, "solo_rust": True},
        {"ruta": "/api/modelos/config", "metodo": "POST", "json": {"capa": "global", "valores": {"typical_p": 1, "top_k": "x"}}, **{"archivo": "{home}/.prig_modelos.json", "restaurar": True, "archivo_json": True}, "solo_rust": True},
        {"ruta": "/api/modelos/config", "metodo": "POST", "json": {"capa": "x"}, **{"archivo": "{home}/.prig_modelos.json", "restaurar": True, "archivo_json": True}, "solo_rust": True},
        {"ruta": "/api/modelos/config", "metodo": "POST", "json": {"valores": []}, "solo_rust": True},
        {"ruta": "/api/modelos/plantilla", "metodo": "POST", "json": {"capa": "uso", "uso": "tutor", "plantilla": "codigo"}, **{"archivo": "{home}/.prig_modelos.json", "restaurar": True, "archivo_json": True}, "solo_rust": True},
        {"ruta": "/api/modelos/plantilla", "metodo": "POST", "json": {"capa": "global", "plantilla": "nada"}, "solo_rust": True},
        {"ruta": "/api/modelos/probar", "metodo": "POST", "json": {"modelo": "qwen2.5-coder:7b", "prompt": "hola", "system": "s", "opciones": {"temperature": 0.1, "think": False}, "logprobs": 9, "raw": True, "template": "{{ .Prompt }}"}, "solo_rust": True},
        {"ruta": "/api/modelos/probar", "metodo": "POST", "json": {"modelo": "qwen2.5-coder:7b", "format": "{roto"}, "solo_rust": True},
        {"ruta": "/api/modelos/probar", "metodo": "POST", "json": {"modelo": "qwen2.5-coder:7b", "format": {"type": "object"}, "suffix": "fin"}, "solo_rust": True},
        {"ruta": "/api/modelos/probar", "metodo": "POST", "json": {"modelo": "nomic-embed-text:latest", "suffix": "fin"}, "solo_rust": True},
        {"ruta": "/api/modelos/probar", "metodo": "POST", "json": {"modelo": "m", "opciones": {"typical_p": 1}}, "solo_rust": True},
        {"ruta": "/api/modelos/crear", "metodo": "POST", "json": {"nombre": "x", "desde": "qwen2.5-coder:7b", "parametros": {"num_gpu": 1, "mirostat": 2}}, "solo_rust": True},
        {"ruta": "/api/modelos/crear", "metodo": "POST", "json": {"nombre": "no válido!", "desde": "qwen2.5-coder:7b"}, "solo_rust": True},
        {"ruta": "/api/modelos/copiar", "metodo": "POST", "json": {"origen": "qwen2.5-coder:7b", "destino": "copia:1"}, "solo_rust": True},
        {"ruta": "/api/modelos/borrar", "metodo": "POST", "json": {"modelo": "qwen2.5-coder:7b"}, "solo_rust": True},
        {"ruta": "/api/modelos/borrar", "metodo": "POST", "json": {"modelo": "  "}, "solo_rust": True},
        {"ruta": "/api/modelos/importar", "metodo": "POST", "json": {"ruta": "/etc/x.gguf", "nombre": "x"}, "solo_rust": True},
        {"ruta": "/api/modelos/importar", "metodo": "POST", "json": {"ruta": "~/x.txt", "nombre": "x"}, "solo_rust": True},
        {"ruta": "/api/modelos/cargados", "solo_rust": True},
        {"ruta": "/api/modelos/precargar", "metodo": "POST", "json": {"modelo": "qwen2.5-coder:7b", "uso": "tutor"}, "solo_rust": True},
        {"ruta": "/api/modelos/descargar", "metodo": "POST", "json": {"modelo": "qwen2.5-coder:7b"}, "solo_rust": True},
        {"ruta": "/api/modelos/parciales", "solo_rust": True},
        {"ruta": "/api/modelos/registro", "solo_rust": True},
        {"ruta": "/api/modelos/registro?lineas=x", "solo_rust": True},
        {"ruta": "/api/kaggle/explicar", "metodo": "POST", "json": {"ref": "ana/nb-uno", "indice": 0, "modelo": "qwen2.5-coder:7b"}, "archivo": "{home}/.prig_kaggle/explicaciones/ana__nb-uno.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha"], "solo_rust": True},
        {"ruta": "/api/kaggle/explicar", "metodo": "POST", "json": {"ref": "ana/nb-uno", "indice": 1, "nivel": "avanzado", "incluir_datos": None}, "archivo": "{home}/.prig_kaggle/explicaciones/ana__nb-uno.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha"], "solo_rust": True},
        {"ruta": "/api/kaggle/explicar", "metodo": "POST", "json": {"ref": "ana/nb-uno", "indice": 99}, "solo_rust": True},
        {"ruta": "/api/kaggle/explicar", "metodo": "POST", "json": {"ref": "ana/nb-uno", "indice": 0, "modelo": "gemini:x"}, "solo_rust": True},
        {"ruta": "/api/kaggle/explicar", "metodo": "POST", "json": {"ref": "ana/nb-uno"}, "solo_rust": True},
        {"ruta": "/api/kaggle/guia", "metodo": "POST", "json": {"ref": "ana/nb-uno"}, "archivo": "{home}/.prig_kaggle/explicaciones/ana__nb-uno.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha"], "solo_rust": True},
        {"ruta": "/api/kaggle/notebook/estudio_optimo", "metodo": "POST", "json": {"ref": "ana/nb-uno", "regenerar": True}, "archivo": "{home}/.prig_kaggle/explicaciones/ana__nb-uno.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha"], "solo_rust": True},
        {"ruta": "/api/kaggle/preguntar", "metodo": "POST", "json": {"ref": "ana/nb-uno", "indice": 1, "mensajes": [{"rol": "usuario", "texto": "¿qué hace?"}]}, "solo_rust": True},
        {"ruta": "/api/kaggle/preguntar", "metodo": "POST", "json": {"ref": "ana/nb-uno", "mensajes": [{"role": "user", "content": "¿cómo funciona un random forest?"}]}, "solo_rust": True},
        {"ruta": "/api/kaggle/preguntar", "metodo": "POST", "json": {"ref": "ana/nb-uno", "mensajes": []}, "solo_rust": True},
        {"ruta": "/api/kaggle/explicar", "metodo": "POST", "json": {"ref": "nada/nada", "indice": 0}, "solo_rust": True},
        {"ruta": "/api/github/explicar", "metodo": "POST", "json": {"ref": "ana/Repo"}, "archivo": "{home}/.prig_github/explicaciones/ana__Repo.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha"], "solo_rust": True},
        {"ruta": "/api/github/explicar", "metodo": "POST", "json": {"ref": "ana/Repo", "ruta": "src/main.py", "nivel": "avanzado"}, "archivo": "{home}/.prig_github/explicaciones/ana__Repo.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha"], "solo_rust": True},
        {"ruta": "/api/github/explicar", "metodo": "POST", "json": {"ref": "ana/Repo", "ruta": "src/nul.py"}, "archivo": "{home}/.prig_github/explicaciones/ana__Repo.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha"], "solo_rust": True},
        {"ruta": "/api/github/explicar", "metodo": "POST", "json": {"ref": "ana/Repo", "ruta": "no/esta.py"}, "solo_rust": True},
        {"ruta": "/api/github/explicar", "metodo": "POST", "json": {"ref": "ana/Repo", "modelo": "gemini:x"}, "solo_rust": True},
        {"ruta": "/api/github/preguntar", "metodo": "POST", "json": {"ref": "ana/Repo", "ruta": "src/main.py", "mensajes": [{"rol": "usuario", "texto": "¿qué imprime?"}]}, "solo_rust": True},
        {"ruta": "/api/github/preguntar", "metodo": "POST", "json": {"ref": "ana/Repo", "mensajes": []}, "solo_rust": True},
        {"ruta": "/api/github/preguntar", "metodo": "POST", "json": {"ref": "ana/Repo"}, "solo_rust": True},
        {"ruta": "/api/kaggle/explicar_datos", "metodo": "POST", "json": {"tipo": "dataset", "ref": "ana/otro-ds"}, "archivo": "{home}/.prig_kaggle/explicaciones/datos__dataset__ana__otro-ds.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha"], "solo_rust": True},
        {"ruta": "/api/kaggle/explicar_datos", "metodo": "POST", "json": {"tipo": "competicion", "ref": "titanic", "modelo": "qwen2.5-coder:7b"}, "archivo": "{home}/.prig_kaggle/explicaciones/datos__competicion__titanic.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha"], "solo_rust": True},
        {"ruta": "/api/kaggle/explicar_datos", "metodo": "POST", "json": {"tipo": "otro", "ref": "x"}, "solo_rust": True},
        {"ruta": "/api/kaggle/explicar_datos", "metodo": "POST", "json": {"tipo": "dataset", "ref": "nada/nada"}, "archivo": "{home}/.prig_kaggle/explicaciones/datos__dataset__ana__otro-ds.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha"], "solo_rust": True},
        {"ruta": "/api/kaggle/explicar_datos", "metodo": "POST", "json": {"ref": "x"}, "solo_rust": True},
        {"ruta": "/api/youtube/analizar", "metodo": "POST", "json": {"video_id": "vidES", "titulo": "Clase de listas", "canal": None, "descripcion": " Temario: listas ", "notas_usuario": "", "categoria": "python"}, "solo_rust": True},
        {"ruta": "/api/youtube/analizar", "metodo": "POST", "json": {"video_id": "sinsubs", "titulo": "Sin subtítulos", "modo": "objetivos", "nivel": None}, "solo_rust": True},
        {"ruta": "/api/youtube/analizar", "metodo": "POST", "json": {"video_id": "vidEN", "titulo": "T", "texto_usuario": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "modo": "resumen"}, "solo_rust": True},
        {"ruta": "/api/youtube/analizar", "metodo": "POST", "json": {"video_id": "vidEN", "titulo": "T", "modo": None}, "solo_rust": True},
        {"ruta": "/api/youtube/analizar", "metodo": "POST", "json": {"video_id": "vidEN", "titulo": "T", "modelo": "gemini:x"}, "solo_rust": True},
        {"ruta": "/api/youtube/analizar", "metodo": "POST", "json": {"titulo": "T"}, "solo_rust": True},
        {"ruta": "/api/youtube/traducir_texto", "metodo": "POST", "json": {"texto": " def f(x): return x "}, "solo_rust": True},
        {"ruta": "/api/youtube/traducir_texto", "metodo": "POST", "json": {"texto": "   "}, "solo_rust": True},
        {"ruta": "/api/youtube/traducir_texto", "metodo": "POST", "json": {"texto": "hola", "modelo": "gemini:x"}, "solo_rust": True},
        {"ruta": "/api/file?path=main.py", "solo_rust": True},
        {"ruta": "/api/file?path=datos/tabla.csv", "solo_rust": True},
        {"ruta": "/api/file?path=nada.py", "solo_rust": True},
        {"ruta": "/api/file?path=/etc/hostname", "solo_rust": True},
        {"ruta": "/api/file", "solo_rust": True},
        {"ruta": "/api/file", "metodo": "POST", "json": {"path": "nuevo.txt", "content": "hola ñandú\n"}, "archivo": "{proyecto}/nuevo.txt", "restaurar": True, "solo_rust": True},
        {"ruta": "/api/file", "metodo": "POST", "json": {"path": "/etc/prig_x", "content": "x"}, "solo_rust": True},
        {"ruta": "/api/file", "metodo": "POST", "json": {"path": "x.txt"}, "solo_rust": True},
        {"ruta": "/api/file?path=docs/leeme.md", "metodo": "DELETE", "archivo": "{proyecto}/docs/leeme.md", "restaurar": True, "solo_rust": True},
        {"ruta": "/api/file?path=no_existe.md", "metodo": "DELETE", "solo_rust": True},
        {"ruta": "/api/create", "metodo": "POST", "json": {"path": "creado.txt"}, "archivo": "{proyecto}/creado.txt", "restaurar": True, "solo_rust": True},
        {"ruta": "/api/create", "metodo": "POST", "json": {"path": "main.py"}, "solo_rust": True},
        {"ruta": "/api/create", "metodo": "POST", "json": {"path": "/etc/nada", "is_dir": True}, "solo_rust": True},
        {"ruta": "/api/raw-file?path=main.py", "solo_rust": True},
        {"ruta": "/api/file/raw?path=datos/tabla.csv", "solo_rust": True},
        {"ruta": "/api/file/raw?path=nada.png", "solo_rust": True},
        {"ruta": "/api/raw-file?path=/etc/hostname", "solo_rust": True},
        {"ruta": "/api/workspace/open", "metodo": "POST", "json": {"path": "/no/existe"}, "solo_rust": True},
        {"ruta": "/api/workspace/open", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/workspace/segunda", "metodo": "POST", "json": {"path": "/no/existe"}, "solo_rust": True},
        {"ruta": "/api/workspace/projects/save", "metodo": "POST", "json": {"path": "/tmp", "name": "Temporal"}, "archivo": "{home}/.prig_config.json", "restaurar": True, "archivo_json": True, "volatiles": ["created_at", "last_opened"], "solo_rust": True},
        {"ruta": "/api/workspace/projects/save", "metodo": "POST", "json": {"path": "/no/existe"}, "archivo": "{home}/.prig_config.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/workspace/projects/remove", "metodo": "POST", "json": {"path": "/tmp"}, "archivo": "{home}/.prig_config.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/ide/reemplazar", "metodo": "POST", "json": {"consulta": "hola", "reemplazo": "adiós", "incluir": "*.py"}, "archivo": "{proyecto}/main.py", "restaurar": True, "solo_rust": True},
        {"ruta": "/api/ide/reemplazar", "metodo": "POST", "json": {"consulta": "hola"}, "solo_rust": True},
        {"ruta": "/api/ide/reemplazar", "metodo": "POST", "json": {"consulta": "(", "reemplazo": "x", "regex": True}, "solo_rust": True},
        {"ruta": "/api/ide/renombrar", "metodo": "POST", "json": {"path": "nada.py", "destino": "otra.py"}, "solo_rust": True},
        {"ruta": "/api/ide/renombrar", "metodo": "POST", "json": {"path": "main.py", "destino": "/etc/main.py"}, "solo_rust": True},
        {"ruta": "/api/ide/duplicar", "metodo": "POST", "json": {"path": "nada.py"}, "solo_rust": True},
        {"ruta": "/api/ide/mostrar-en-sistema", "metodo": "POST", "json": {"path": "/etc"}, "solo_rust": True},
        {"ruta": "/api/ide/problemas", "metodo": "POST", "json": {"lenguaje": "python", "codigo": "def f(:\n  pass\n"}, "solo_rust": True},
        {"ruta": "/api/ide/problemas", "metodo": "POST", "json": {"lenguaje": "python", "codigo": "if x:\n\tif y:\n        pass\n"}, "solo_rust": True},
        {"ruta": "/api/ide/problemas", "metodo": "POST", "json": {"lenguaje": "python", "codigo": "a\u0000b"}, "solo_rust": True},
        {"ruta": "/api/ide/problemas", "metodo": "POST", "json": {"lenguaje": "python", "codigo": "print('ok')\n"}, "solo_rust": True},
        {"ruta": "/api/ide/problemas", "metodo": "POST", "json": {"lenguaje": "javascript", "codigo": "x("}, "solo_rust": True},
        {"ruta": "/api/ide/recientes", "metodo": "DELETE", "archivo": "{home}/.prig_config.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/ide/acerca", "solo_rust": True},
        {"ruta": "/api/system/stats", "volatiles": ["cpu_pct", "ram_pct", "ram_used_gb", "ram_total_gb", "gpu_pct", "vram_used_mb", "vram_free_mb", "temperaturas", "hora", "generado", "fecha", "empezado", "ultima"], "solo_rust": True},
        {"ruta": "/api/system/health", "volatiles": ["cpu_pct", "ram_pct", "ram_used_gb", "ram_total_gb", "gpu_pct", "vram_used_mb", "vram_free_mb", "temperaturas", "hora", "generado", "fecha", "empezado", "ultima"], "solo_rust": True},
        {"ruta": "/api/inicio", "volatiles": ["cpu_pct", "ram_pct", "ram_used_gb", "ram_total_gb", "gpu_pct", "vram_used_mb", "vram_free_mb", "temperaturas", "hora", "generado", "fecha", "empezado", "ultima"], "solo_rust": True},
        {"ruta": "/api/inicio/perfil", "solo_rust": True},
        {"ruta": "/api/inicio/perfil", "metodo": "PATCH", "json": {"nombre": "  Ana   María ", "nivel": "avanzado", "favoritas": ["kaggle", "x"], "objetivo": None}, "archivo": "{home}/.prig_inicio.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/inicio/perfil", "metodo": "PATCH", "json": {"mostrar_al_abrir": "quizas"}, "solo_rust": True},
        {"ruta": "/api/inicio/perfil", "metodo": "PATCH", "json": {"nivel": "experto"}, "archivo": "{home}/.prig_inicio.json", "restaurar": True, "archivo_json": True, "solo_rust": True},
        {"ruta": "/api/ai/catalog", "solo_rust": True},
        {"ruta": "/api/ai/cancel", "metodo": "POST", "solo_rust": True},
        {"ruta": "/api/ai/search", "metodo": "POST", "json": {"query": "pandas groupby ejemplo"}, "solo_rust": True},
        {"ruta": "/api/ai/search", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/ai/inline-complete", "metodo": "POST", "json": {"code_prefix": "def suma(a, b):\n    ", "code_suffix": "\n\nprint(suma(1, 2))"}, "solo_rust": True},
        {"ruta": "/api/ai/inline-complete", "metodo": "POST", "json": {"code_prefix": "x = ", "model": "nomic-embed-text:latest"}, "solo_rust": True},
        {"ruta": "/api/ai/inline-complete", "metodo": "POST", "json": {"code_suffix": "x"}, "solo_rust": True},
        {"ruta": "/api/ai/inline-prompt", "metodo": "POST", "json": {"prompt": "suma dos números", "file_content": "import os\n    # Prig//: suma dos números\nprint(1)\n", "line_number": 2, "file_path": "a.py"}, "solo_rust": True},
        {"ruta": "/api/ai/inline-prompt", "metodo": "POST", "json": {"prompt": "ordena", "prefix_code": "def f(l):\n    x = 1\n", "language": "javascript", "model": "otro (raro)"}, "solo_rust": True},
        {"ruta": "/api/ai/inline-prompt", "metodo": "POST", "json": {"prompt": "   "}, "solo_rust": True},
        {"ruta": "/api/guided/cancel", "metodo": "POST", "solo_rust": True},
        {"ruta": "/api/referencias", "solo_rust": True},
        {"ruta": "/api/referencias?q=transformer%20atenci%C3%B3n", "solo_rust": True},
        {"ruta": "/api/referencias?categoria=arboles&tipo=libro", "solo_rust": True},
        {"ruta": "/api/referencias?q=zzzz", "solo_rust": True},
        {"ruta": "/api/referencias/detalle?id=pattern_recognition_and_machine_learning", "solo_rust": True},
        {"ruta": "/api/referencias/detalle?id=nada", "solo_rust": True},
        {"ruta": "/api/referencias/detalle", "solo_rust": True},
        {"ruta": "/api/referencias/relacionadas?q=%C2%BFc%C3%B3mo%20funciona%20un%20random%20forest%20con%20xgboost%3F&maximo=3", "solo_rust": True},
        {"ruta": "/api/referencias/relacionadas?q=transformers%20y%20atenci%C3%B3n%20multi-cabeza", "solo_rust": True},
        {"ruta": "/api/referencias/relacionadas?q=hola", "solo_rust": True},
        {"ruta": "/api/referencias/relacionadas?q=x&maximo=dos", "solo_rust": True},
        {"ruta": "/api/referencias/pdf?id=the_elements_of_statistical_learning_2nd_ed", "solo_rust": True},
        {"ruta": "/api/referencias/pdf?id=nada", "solo_rust": True},
        {"ruta": "/api/referencias/abrir", "metodo": "POST", "json": {"id": "nada"}, "solo_rust": True},
        {"ruta": "/api/referencias/abrir", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/gemini/estado", "solo_rust": True},
        {"ruta": "/api/gemini/modelos", "solo_rust": True},
        {"ruta": "/api/gemini/clave", "metodo": "POST", "json": {"clave": "AIzaPRUEBA_valida_1234567890abcd"}, **{"archivo": "{home}/.prig_gemini.json", "restaurar": True, "archivo_json": True, "volatiles": ["aviso_aceptado"]}, "solo_rust": True},
        {"ruta": "/api/gemini/clave", "metodo": "POST", "json": {"clave": "  'AQ.Ab8RN6PRUEBA_formato-nuevo.x9Yz12345678' ", "acepto_aviso": True}, **{"archivo": "{home}/.prig_gemini.json", "restaurar": True, "archivo_json": True, "volatiles": ["aviso_aceptado"]}, "solo_rust": True},
        {"ruta": "/api/gemini/clave", "metodo": "POST", "json": {"clave": "AIzaSyPRUEBA_inventada_no_valida_000", "acepto_aviso": True}, **{"archivo": "{home}/.prig_gemini.json", "restaurar": True, "archivo_json": True, "volatiles": ["aviso_aceptado"]}, "solo_rust": True},
        {"ruta": "/api/gemini/clave", "metodo": "POST", "json": {"clave": "corta", "acepto_aviso": True}, "solo_rust": True},
        {"ruta": "/api/gemini/clave", "metodo": "POST", "json": {"acepto_aviso": "x"}, "solo_rust": True},
        {"ruta": "/api/gemini/clave", "metodo": "DELETE", **{"archivo": "{home}/.prig_gemini.json", "restaurar": True, "archivo_json": True, "volatiles": ["aviso_aceptado"]}, "solo_rust": True},
        {"ruta": "/api/recursos/perfiles", "solo_rust": True},
        {"ruta": "/api/recursos/servidor", "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fecha", "ram_disponible", "ram_libre", "swap_usada", "vram_libre_mb", "vram_usada_mb", "libre_gb", "usado_gb", "ancho_banda_ram_gbps", "temp_gpu", "temp_cpu", "ram_disponible_gb", "vram_libre_gb", "avisos", "carga", "uso_cpu", "pid", "modelos_cargados", "procesos", "consumo", "libre"], "solo_rust": True},
        {"ruta": "/api/recursos/estado", "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fecha", "ram_disponible", "ram_libre", "swap_usada", "vram_libre_mb", "vram_usada_mb", "libre_gb", "usado_gb", "ancho_banda_ram_gbps", "temp_gpu", "temp_cpu", "ram_disponible_gb", "vram_libre_gb", "avisos", "carga", "uso_cpu", "pid", "modelos_cargados", "procesos", "consumo", "libre"], "solo_rust": True},
        {"ruta": "/api/recursos/maquina", "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fecha", "ram_disponible", "ram_libre", "swap_usada", "vram_libre_mb", "vram_usada_mb", "libre_gb", "usado_gb", "ancho_banda_ram_gbps", "temp_gpu", "temp_cpu", "ram_disponible_gb", "vram_libre_gb", "avisos", "carga", "uso_cpu", "pid", "modelos_cargados", "procesos", "consumo", "libre"], "solo_rust": True},
        {"ruta": "/api/recursos/maquina?fresca=quizas", "solo_rust": True},
        {"ruta": "/api/recursos/modelos", "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fecha", "ram_disponible", "ram_libre", "swap_usada", "vram_libre_mb", "vram_usada_mb", "libre_gb", "usado_gb", "ancho_banda_ram_gbps", "temp_gpu", "temp_cpu", "ram_disponible_gb", "vram_libre_gb", "avisos", "carga", "uso_cpu", "pid", "modelos_cargados", "procesos", "consumo", "libre"], "solo_rust": True},
        {"ruta": "/api/recursos/modelos?perfil=extraccion&tirador=velocidad", "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fecha", "ram_disponible", "ram_libre", "swap_usada", "vram_libre_mb", "vram_usada_mb", "libre_gb", "usado_gb", "ancho_banda_ram_gbps", "temp_gpu", "temp_cpu", "ram_disponible_gb", "vram_libre_gb", "avisos", "carga", "uso_cpu", "pid", "modelos_cargados", "procesos", "consumo", "libre"], "solo_rust": True},
        {"ruta": "/api/recursos/modelos?perfil=nada", "solo_rust": True},
        {"ruta": "/api/recursos/modelos?tirador=nada", "solo_rust": True},
        {"ruta": "/api/recursos/recomendar", "metodo": "POST", "json": {}, "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fecha", "ram_disponible", "ram_libre", "swap_usada", "vram_libre_mb", "vram_usada_mb", "libre_gb", "usado_gb", "ancho_banda_ram_gbps", "temp_gpu", "temp_cpu", "ram_disponible_gb", "vram_libre_gb", "avisos", "carga", "uso_cpu", "pid", "modelos_cargados", "procesos", "consumo", "libre"], "solo_rust": True},
        {"ruta": "/api/recursos/recomendar", "metodo": "POST", "json": {"modelo": "qwen2.5-coder:7b", "perfil": "extraccion"}, "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fecha", "ram_disponible", "ram_libre", "swap_usada", "vram_libre_mb", "vram_usada_mb", "libre_gb", "usado_gb", "ancho_banda_ram_gbps", "temp_gpu", "temp_cpu", "ram_disponible_gb", "vram_libre_gb", "avisos", "carga", "uso_cpu", "pid", "modelos_cargados", "procesos", "consumo", "libre"], "solo_rust": True},
        {"ruta": "/api/recursos/recomendar", "metodo": "POST", "json": {"modelo": "qwen3:8b", "tirador": "calidad"}, "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fecha", "ram_disponible", "ram_libre", "swap_usada", "vram_libre_mb", "vram_usada_mb", "libre_gb", "usado_gb", "ancho_banda_ram_gbps", "temp_gpu", "temp_cpu", "ram_disponible_gb", "vram_libre_gb", "avisos", "carga", "uso_cpu", "pid", "modelos_cargados", "procesos", "consumo", "libre"], "solo_rust": True},
        {"ruta": "/api/recursos/recomendar", "metodo": "POST", "json": {"modelo": "inexistente:1b"}, "solo_rust": True},
        {"ruta": "/api/recursos/recomendar", "metodo": "POST", "json": {"perfil": "nada"}, "solo_rust": True},
        {"ruta": "/api/recursos/recomendar", "metodo": "POST", "json": {"modelo": 5, "perfil": None}, "solo_rust": True},
        {"ruta": "/api/recursos/aplicar", "metodo": "POST", "json": {"modelo": "qwen2.5-coder:7b"}, "archivo": "{home}/.prig_ai_config.json", "restaurar": True, "archivo_json": True, "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fecha", "ram_disponible", "ram_libre", "swap_usada", "vram_libre_mb", "vram_usada_mb", "libre_gb", "usado_gb", "ancho_banda_ram_gbps", "temp_gpu", "temp_cpu", "ram_disponible_gb", "vram_libre_gb", "avisos", "carga", "uso_cpu", "pid", "modelos_cargados", "procesos", "consumo", "libre"], "solo_rust": True},
        {"ruta": "/api/recursos/aplicar", "metodo": "POST", "json": {"modelo": "qwen2.5-coder:7b", "perfil": "extraccion"}, **RECURSOS, "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fecha", "ram_disponible", "ram_libre", "swap_usada", "vram_libre_mb", "vram_usada_mb", "libre_gb", "usado_gb", "ancho_banda_ram_gbps", "temp_gpu", "temp_cpu", "ram_disponible_gb", "vram_libre_gb", "avisos", "carga", "uso_cpu", "pid", "modelos_cargados", "procesos", "consumo", "libre"], "solo_rust": True},
        {"ruta": "/api/recursos/aplicar", "metodo": "POST", "json": {"modelo": "inexistente:1b"}, "solo_rust": True},
        {"ruta": "/api/recursos/aplicar", "metodo": "POST", "json": {}, "solo_rust": True},
        {"ruta": "/api/recursos/restaurar", "metodo": "POST", "json": {"perfil": "tutor"}, **RECURSOS, "solo_rust": True},
        {"ruta": "/api/recursos/restaurar", "metodo": "POST", "json": {"perfil": "nada"}, "solo_rust": True},
        {"ruta": "/api/recursos/probar", "metodo": "POST", "json": {"modelo": "inexistente:1b"}, "solo_rust": True},
        {"ruta": "/api/recursos/probar", "metodo": "POST", "json": {"modelo": "qwen3:8b"}, "solo_rust": True},
        {"ruta": "/api/recursos/probar", "metodo": "POST", "json": {"modelo": "qwen3:8b", "tirador": "nada"}, "solo_rust": True},
        {"ruta": "/api/recursos/probar", "metodo": "POST", "json": {"forzar": "quizas"}, "solo_rust": True},
        {"ruta": "/api/recursos/cancelar", "metodo": "POST", "solo_rust": True},
        {"ruta": "/api/recursos/olvidar-calibracion", "metodo": "POST", **RECURSOS, "solo_rust": True},
        {"ruta": "/api/recursos/servidor", "metodo": "POST", "json": {"cambios": {"OLLAMA_NUM_PARALLEL": "2", "OLLAMA_KV_CACHE_TYPE": "q8_0"}, "reiniciar": False}, **RECURSOS, "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fecha", "ram_disponible", "ram_libre", "swap_usada", "vram_libre_mb", "vram_usada_mb", "libre_gb", "usado_gb", "ancho_banda_ram_gbps", "temp_gpu", "temp_cpu", "ram_disponible_gb", "vram_libre_gb", "avisos", "carga", "uso_cpu", "pid", "modelos_cargados", "procesos", "consumo", "libre"], "solo_rust": True},
        {"ruta": "/api/recursos/servidor", "metodo": "POST", "json": {"cambios": {"OLLAMA_HOST": "x"}, "reiniciar": False}, **RECURSOS, "solo_rust": True},
        {"ruta": "/api/recursos/servidor", "metodo": "POST", "json": {"cambios": {"OLLAMA_NUM_PARALLEL": 2, "b": None}, "forzar": "x"}, "solo_rust": True},
        {"ruta": "/api/recursos/servidor", "metodo": "POST", "json": {"cambios": [1]}, "solo_rust": True},
        {"ruta": "/api/recursos/servidor", "metodo": "POST", "json": {"reiniciar": False}, "solo_rust": True},
        {"ruta": "/api/recursos/eventos", "solo_rust": True},
        {"ruta": "/api/recursos/eventos?limite=0", "solo_rust": True},
        {"ruta": "/api/recursos/eventos?limite=900", "solo_rust": True},
        {"ruta": "/api/recursos/eventos?limite=mucho", "solo_rust": True},
        {"ruta": "/api/recursos/temperaturas", "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fraccion_ahora", "historial", "componentes", "ventiladores", "fecha"], "solo_rust": True},
        {"ruta": "/api/recursos/temperaturas?historial=true", "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fraccion_ahora", "historial", "componentes", "ventiladores", "fecha"], "solo_rust": True},
        {"ruta": "/api/recursos/temperaturas?historial=quizas", "solo_rust": True},
        {"ruta": "/api/recursos/termico", "metodo": "POST", "json": {"limite_gpu": 70}, **RECURSOS, "solo_rust": True},
        {"ruta": "/api/recursos/termico", "metodo": "POST", "json": {"limite_gpu": "65.5"}, **RECURSOS, "solo_rust": True},
        {"ruta": "/api/recursos/termico", "metodo": "POST", "json": {"limite_gpu": 20}, **RECURSOS, "solo_rust": True},
        {"ruta": "/api/recursos/termico", "metodo": "POST", "json": {"olvidar": True}, **RECURSOS, "solo_rust": True},
        {"ruta": "/api/recursos/termico", "metodo": "POST", "json": {"limite_gpu": "x", "olvidar": "quizas"}, **RECURSOS, "solo_rust": True},
        {"ruta": "/api/recursos/termico", "metodo": "POST", "json": [1], **RECURSOS, "solo_rust": True},
        {"ruta": "/api/recursos/ritmo", "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fraccion_ahora", "historial", "componentes", "ventiladores", "fecha"], "solo_rust": True},
        {"ruta": "/api/recursos/ritmo", "metodo": "POST", "json": {"objetivo_c": 99, "rampa_s": "-3", "ritmo_minimo": 0.5, "tramo_s": None}, **RECURSOS, "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fraccion_ahora", "historial", "componentes", "ventiladores", "fecha"], "solo_rust": True},
        {"ruta": "/api/recursos/ritmo", "metodo": "POST", "json": {"activo": False, "cpu_eficiente": "no"}, **RECURSOS, "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fraccion_ahora", "historial", "componentes", "ventiladores", "fecha"], "solo_rust": True},
        {"ruta": "/api/recursos/ritmo", "metodo": "POST", "json": {"objetivo_c": "caliente"}, **RECURSOS, "solo_rust": True},
        {"ruta": "/api/recursos/frio", "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fraccion_ahora", "historial", "componentes", "ventiladores", "fecha"], "solo_rust": True},
        {"ruta": "/api/recursos/frio", "metodo": "POST", "json": {"activo": False, "objetivo_c": 120}, **RECURSOS, "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fraccion_ahora", "historial", "componentes", "ventiladores", "fecha"], "solo_rust": True},
        {"ruta": "/api/recursos/frio", "metodo": "POST", "json": {"objetivo_c": "10"}, **RECURSOS, "volatiles": ["temp", "tomada", "consumo_w", "uso_pct", "ventilador_pct", "nucleo_max", "rpm", "fraccion_ahora", "historial", "componentes", "ventiladores", "fecha"], "solo_rust": True},
        {"ruta": "/api/recursos/frio", "metodo": "POST", "json": {"activo": "tal vez"}, **RECURSOS, "solo_rust": True},
        {"ruta": "/api/recursos/energia", "metodo": "POST", "json": {}, **RECURSOS, "solo_rust": True},
        {"ruta": "/api/recursos/energia", "metodo": "POST", "json": {"frio": True, "vatios": 2.5}, **RECURSOS, "solo_rust": True},
        {"ruta": "/api/recursos/moe", "solo_rust": True},
        {"ruta": "/api/recursos/moe", "metodo": "POST", "json": {"contexto": "999999", "hilos": 3, "calientes": "40"}, **MOE, "solo_rust": True},
        {"ruta": "/api/recursos/moe", "metodo": "POST", "json": {"contexto": "auto", "calientes": "auto", "modo": "exacto", "mtp": False}, **MOE, "solo_rust": True},
        {"ruta": "/api/recursos/moe", "metodo": "POST", "json": {"nucleo": "q4", "cache_gb": 5, "cache_reserva_gb": 30}, **MOE, "solo_rust": True},
        {"ruta": "/api/recursos/moe", "metodo": "POST", "json": {"contexto": "mucho"}, **MOE, "solo_rust": True},
        {"ruta": "/api/recursos/moe", "metodo": "POST", "json": {"calientes": "muchos"}, **MOE, "solo_rust": True},
        {"ruta": "/api/recursos/moe", "metodo": "POST", "json": {"modo": "turbo"}, **MOE, "solo_rust": True},
        {"ruta": "/api/recursos/moe", "metodo": "POST", "json": {"nucleo": "q2"}, **MOE, "solo_rust": True},
        {"ruta": "/api/recursos/moe", "metodo": "POST", "json": {"cache_gb": -1}, **MOE, "solo_rust": True},
        {"ruta": "/api/recursos/moe", "metodo": "POST", "json": {"cache_reserva_gb": 2000}, **MOE, "solo_rust": True},
        {"ruta": "/api/recursos/moe", "metodo": "POST", "json": {"contexto": 5}, **MOE, "solo_rust": True},
        {"ruta": "/api/recursos/moe", "metodo": "POST", "json": {"mtp": "quizas"}, **MOE, "solo_rust": True},
        {"ruta": "/api/recursos/moe", "metodo": "POST", "json": {}, **MOE, "solo_rust": True},
        {"ruta": "/api/books/list", "solo_rust": True},
        {"ruta": "/api/books/list?category=books", "solo_rust": True},
        {"ruta": "/api/books/list?category=PROJECTS", "solo_rust": True},
        {"ruta": "/api/books/list?category=all", "solo_rust": True},
        {"ruta": "/api/books/list?category=nada", "solo_rust": True},
        {"ruta": "/api/books/inventario?id=books/%C3%81lgebra_lineal-2ed.pdf", "solo_rust": True},
        {"ruta": "/api/books/ocultos", "solo_rust": True},
        {"ruta": "/api/books/delete", "metodo": "POST", "json": {"id": "books"}, "solo_rust": True},
        {"ruta": "/api/books/delete", "metodo": "POST", "json": {"id": "papers/x.pdf", "piezas": ["ficha"]}, "solo_rust": True},
        {"ruta": "/api/banco/simbolos", "solo_rust": True},
        {"ruta": "/api/banco/ficha?nombre=saludar", "solo_rust": True},
        {"ruta": "/api/banco/grafo", "solo_rust": True},
    ]
    def sustituir(v):
        """ {home} y {proyecto} también dentro del cuerpo JSON (sin esto llegaban literales: rutas que no existen) """
        if isinstance(v, str):
            return v.replace("{home}", home).replace("{proyecto}", proyecto)
        if isinstance(v, list):
            return [sustituir(x) for x in v]
        if isinstance(v, dict):
            return {k: sustituir(x) for k, x in v.items()}
        return v
    for c in casos:
        if "json" in c:
            c["json"] = sustituir(c["json"])
        c["ruta"] = (c["ruta"].replace("{home}", urllib.request.quote(home)).replace("{proyecto}", urllib.request.quote(proyecto))
                     .replace("{desafio}", desafio).replace("{desafio2}", desafio2))
        if "archivo" in c:
            c["archivo"] = c["archivo"].replace("{desafio}", desafio).replace("{desafio2}", desafio2)
    return casos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--casos", help="JSON con [{ruta, metodo, json}]; {proyecto} se sustituye")
    ap.add_argument("--solo", help="solo estas rutas (separadas por comas)")
    ap.add_argument("--vacio", action="store_true", help="sin cuentas ni colecciones de prueba en el HOME temporal")
    ap.add_argument("--desafios", help="carpeta con JSON de desafíos de muestra (se copian al HOME temporal)")
    args = ap.parse_args()
    if not os.path.exists(SERVIDOR):
        sys.exit(f"Falta {SERVIDOR}: cargo build --release -p prig-server")
    # Con un binario viejo, las rutas nuevas caen en el proxy y se compara Python consigo mismo
    fuentes_rs = os.path.join(RAIZ, "backend-rust", "crates")
    mas_nuevo = max((os.path.getmtime(os.path.join(d, f)) for d, _, fs in os.walk(fuentes_rs) if "/target" not in d and "/tests" not in d
                     for f in fs if f.endswith((".rs", ".toml", ".css", ".json"))), default=0)
    if mas_nuevo > os.path.getmtime(SERVIDOR):
        sys.exit(f"{SERVIDOR} es más viejo que el código de Rust: cargo build --release -p prig-server")

    tmp = tempfile.mkdtemp(prefix="prig-comparador-")
    procesos = []
    try:
        p = preparar(tmp)
        copia = copia_de_prig(tmp)
        p["env"]["PYTHONPATH"] = os.path.join(copia, "backend")
        global OLLAMA_FALSA
        OLLAMA_FALSA = ollama_falso()
        p["env"]["PRIG_SIN_AUTOARRANQUE_OLLAMA"] = "1"     # nunca arrancar ni parar un Ollama de verdad
        p["env"]["PRIG_OLLAMA_URL"] = OLLAMA_FALSA          # la radiografía y las fichas, también con la falsa
        # también en --vacio: la URL de Ollama tiene que ser la falsa (con la real, «pull» bajaría un modelo)
        with open(os.path.join(p["home"], ".prig_ai_config.json"), "w", encoding="utf-8") as f:
            json.dump({"ollama_url": OLLAMA_FALSA, "moe_contexto": "auto", "moe_hilos": 0, "moe_calientes": "auto",
                       "moe_modo": "equilibrado", "moe_mtp": True, "moe_nucleo": "q8", "moe_cache_gb": 32,
                       "moe_cache_reserva_gb": 20}, f, indent=2)
        if not args.vacio:
            sembrar_integraciones(p["home"])
            sembrar_desafios(p["home"])
            sembrar_ejercicios(p["proyecto"])
            sembrar_guiado(p["proyecto"])
            sembrar_biblioteca(p["home"])
            sembrar_kaggle_datos(p["proyecto"], p["home"])
            sembrar_buscador(p["home"])
            sembrar_exportar(p["proyecto"])
            sembrar_kb(p["home"])
        if args.desafios:
            destino = os.path.join(p["home"], ".prig_desafios", "desafios")
            shutil.copytree(args.desafios, destino, dirs_exist_ok=True)
            with open(os.path.join(destino, "des_ffffffffff.json"), "w") as f:
                f.write("{roto")                                 # un desafío dañado
            nombres = sorted(n[:-5] for n in os.listdir(destino) if n.endswith(".json") and n != "des_ffffffffff.json")
            p["desafio"], p["desafio2"] = nombres[0], nombres[-1]
        # el proyecto de prueba, abierto como lo dejaría Prig (los dos servidores lo leen de la configuración)
        with open(os.path.join(p["home"], ".prig_config.json"), "w", encoding="utf-8") as f:
            json.dump({"last_workspace": p["proyecto"]}, f)
        pp, pr = puerto_libre(), puerto_libre()
        p["env"]["PRIG_PUERTO_RUST"] = str(pr)
        p["env"]["PRIG_KAGGLE_API"] = kaggle_falso()
        sys.path.insert(0, os.path.join(RAIZ, "backend"))
        from tests import gemini_falso                    # el Google falso de las pruebas de Python
        p["env"]["PRIG_GEMINI_URL"] = gemini_falso.arrancar()[0]
        p["env"].pop("GEMINI_API_KEY", None)
        yt = youtube_falso()
        p["env"].update(PRIG_YOUTUBE_URL=yt, PRIG_YOUTUBE_SUGERENCIAS=yt, PRIG_TRADUCTOR=yt,
                        PRIG_CACHE_TRANSCRIPCIONES=os.path.join(tmp, "transcripciones"))
        gh = github_falso()
        p["env"].update(PRIG_GITHUB_API=gh, PRIG_GITHUB_RAW=gh + "/raw", PRIG_GITHUB_CODELOAD=gh + "/codeload")          # el motor MoE es del servidor de Rust
        registro = open(os.path.join(tmp, "servidores.log"), "wb")
        py = subprocess.Popen([PYTHON, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", str(pp),
                               "--log-level", "error"], cwd=copia, env=p["env"], stdout=registro, stderr=registro,
                              start_new_session=True)
        procesos.append(py)
        if not esperar(f"http://127.0.0.1:{pp}/api/health", py, 120):
            sys.exit("El backend de Python no arrancó: " + open(os.path.join(tmp, "servidores.log")).read()[-2000:])
        rs = subprocess.Popen([SERVIDOR, "--port", str(pr), "--fallback-port", str(pp)], cwd=copia, env=p["env"],
                              stdout=registro, stderr=registro, start_new_session=True)
        procesos.append(rs)
        if not esperar(f"http://127.0.0.1:{pr}/api/health", rs, 60):
            sys.exit("El servidor de Rust no arrancó: " + open(os.path.join(tmp, "servidores.log")).read()[-2000:])

        # el proyecto de prueba como espacio de trabajo: lo abre el servidor de Rust (y se guarda en el HOME temporal)
        r = pedir(f"http://127.0.0.1:{pr}", {"ruta": "/api/workspace/open", "metodo": "POST", "json": {"path": p["proyecto"]}})
        if r[0] != 200:
            sys.exit(f"No se pudo abrir el proyecto de prueba: {r}")

        if args.casos:
            texto = open(args.casos, encoding="utf-8").read().replace("{proyecto}", p["proyecto"])
            casos = json.loads(texto)
        else:
            casos = casos_por_defecto(p["proyecto"], p["home"], p.get("desafio", "des_0000000000"),
                                      p.get("desafio2", "des_0000000000"))
        if args.solo:
            solo = set(args.solo.split(","))
            casos = [c for c in casos if c["ruta"].split("?")[0] in solo]

        fallos = 0
        for c in casos:
            VOLATILES_CASO.clear()
            VOLATILES_CASO.update(c.get("volatiles", []))
            SIN_RESALTADO[0] = bool(c.get("sin_resaltado"))
            CONTENEDORES_CASO.clear()
            CONTENEDORES_CASO.update(c.get("contenedores", []))
            if c.get("solo_rust") and not os.environ.get("PRIG_COMPARAR_RETIRADAS"):
                b = pedir(f"http://127.0.0.1:{pr}", c)
                print(f"· {c.get('metodo', 'GET'):4} {c['ruta'][:70]}  solo en Rust ({b[0]}): no hay con qué comparar")
                continue
            archivo = c.get("archivo", "").replace("{copia}", copia).replace("{home}", p["home"]).replace("{proyecto}", p["proyecto"])
            leer = lambda: open(archivo, "rb").read() if archivo and os.path.exists(archivo) else None
            original = leer() if c.get("restaurar") else None
            # otro archivo que cada lado tiene que ver igual (p. ej. la base de telemetría), sin compararlo
            otro = c.get("restaurar_otro", "").replace("{copia}", copia).replace("{home}", p["home"]).replace("{proyecto}", p["proyecto"])
            otro_original = open(otro, "rb").read() if otro and os.path.exists(otro) else None
            a = pedir(f"http://127.0.0.1:{pp}", c)
            escrito_python = leer()
            if c.get("restaurar"):
                if original is None:
                    if os.path.exists(archivo):
                        os.remove(archivo)
                else:
                    open(archivo, "wb").write(original)
            if otro:
                if otro_original is None:
                    if os.path.exists(otro):
                        os.remove(otro)
                else:
                    open(otro, "wb").write(otro_original)
            b = pedir(f"http://127.0.0.1:{pr}", c)
            escrito_rust = leer()
            if c.get("archivo_json") and escrito_python is not None and escrito_rust is not None:
                # un JSON o un JSONL (una línea por evento)
                como_json = lambda b: [normalizar(json.loads(l)) for l in b.decode().splitlines() if l.strip()] \
                    if archivo.endswith(".jsonl") else normalizar(json.loads(b))
                if c.get("claves"):
                    # solo esas claves del JSON escrito (el resto lo escribe cada lado a su manera)
                    filtro = lambda d: {k: d.get(k) for k in c["claves"]}
                    previo = como_json
                    como_json = lambda b: filtro(previo(b))
                escrito_python = json.dumps(como_json(escrito_python), ensure_ascii=False).encode()
                escrito_rust = json.dumps(como_json(escrito_rust), ensure_ascii=False).encode()
            if archivo and escrito_python != escrito_rust:
                fallos += 1
                try:
                    detalle_json = diferencia(json.loads(escrito_python), json.loads(escrito_rust))
                except Exception:
                    detalle_json = f"{escrito_python[:200]!r} ≠ {escrito_rust[:200]!r}"
                print(f"✗ {c.get('metodo', 'GET'):4} {c['ruta'][:70]}  el archivo escrito difiere: {detalle_json}")
                continue
            etiqueta = f"{c.get('metodo', 'GET'):4} {c['ruta'][:70]}"
            if c.get("solo_archivo"):
                # la respuesta depende de lo que cambió el otro lado (no se restaura todo): solo cuenta el archivo
                b = a
            if os.environ.get("PRIG_COMPARADOR_VER") and os.environ["PRIG_COMPARADOR_VER"] in c["ruta"]:
                print("  PYTHON:", str(a[1][1])[:600]); print("  RUST:  ", str(b[1][1])[:600])
            if a[0] != b[0]:
                fallos += 1
                print(f"✗ {etiqueta}  estado {a[0]} (Python) ≠ {b[0]} (Rust)  {str(a[1])[:150]} | {str(b[1])[:150]}")
            elif a[1][0] != b[1][0] or diferencia(a[1][1], b[1][1]):
                fallos += 1
                d = diferencia(a[1][1], b[1][1]) if a[1][0] == b[1][0] else f"{a[1][0]} {str(a[1][1])[:300]} ≠ {b[1][0]} {str(b[1][1])[:300]}  (pedido {json.dumps(c.get('json'), ensure_ascii=False)[:120]})"
                print(f"✗ {etiqueta}  {d}")
            else:
                print(f"✓ {etiqueta}  {a[0]}")
        comparados = sum(1 for c in casos if not c.get("solo_rust") or os.environ.get("PRIG_COMPARAR_RETIRADAS"))
        print(f"\n{comparados - fallos} de {comparados} iguales")
        return 1 if fallos else 0
    finally:
        for proc in procesos:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(10)
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
