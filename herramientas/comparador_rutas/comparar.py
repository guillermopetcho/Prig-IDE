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


def normalizar(v):
    if isinstance(v, dict):
        return {k: (type(x).__name__ if k in VOLATILES or k in VOLATILES_CASO
                    else {kk: type(xx).__name__ for kk, xx in x.items()} if k in CONTENEDORES_CASO and isinstance(x, dict)
                    else normalizar(x)) for k, x in v.items()}
    if isinstance(v, list):
        return [normalizar(x) for x in v]
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
    return "" if a == b else f"{ruta or '.'}: {str(a)[:160]!r} ≠ {str(b)[:160]!r}"


def copia_de_prig(tmp: str) -> str:
    """ Prig aislado: las rutas que escriben (la configuración de `.prig_dataset/`, que vive dentro de Prig) no tocan
    la de verdad. Se copian `backend` y `.prig_dataset`; lo que solo se lee se enlaza """
    copia = os.path.join(tmp, "prig")
    os.makedirs(copia)
    shutil.copytree(os.path.join(RAIZ, "backend"), os.path.join(copia, "backend"),
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
    escribir(os.path.join(planes, "plan_viejo.json"), {"plan_id": "plan_viejo", "user_goal": "Estadística", "version": 2,
                                                       "updated_at": "2026-09-01T10:00:00"})


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
            if self.path == "/api/generate":
                return self.responder(200, {"done": True})
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
    RECURSOS = {"archivo": "{home}/.prig_recursos.json", "restaurar": True, "archivo_json": True, "volatiles": ["fecha"]}
    MOE = {"archivo": "{home}/.prig_ai_config.json", "restaurar": True, "archivo_json": True,
           "claves": ["moe_contexto", "moe_hilos", "moe_calientes", "moe_modo", "moe_mtp", "moe_nucleo", "moe_cache_gb",
                      "moe_cache_reserva_gb"]}
    casos = [
        {"ruta": "/api/health", "solo_rust": True},
        {"ruta": "/api/workspace"},
        {"ruta": "/api/tree"},
        {"ruta": "/api/tree?path=" + urllib.request.quote(os.path.join(proyecto, "lib"))},
        {"ruta": "/api/tree?path=/no/existe"},
        {"ruta": "/api/ide/archivos"},
        {"ruta": "/api/ide/buscar", "metodo": "POST", "json": {"consulta": "saludar"}},
        {"ruta": "/api/ide/buscar", "metodo": "POST", "json": {"consulta": "s[au]+", "regex": True}},
        {"ruta": "/api/ide/buscar", "metodo": "POST", "json": {"consulta": "hola", "palabra": True, "mayusculas": True}},
        {"ruta": "/api/ide/buscar", "metodo": "POST", "json": {"consulta": "(", "regex": True}},
        {"ruta": "/api/desafios"},
        {"ruta": "/api/desafios/{desafio}"},
        {"ruta": "/api/desafios/des_ffffffffff"},
        {"ruta": "/api/desafios/des_0000000000"},
        {"ruta": "/api/desafios/no-es-un-id"},
        {"ruta": "/api/desafios/fuentes"},
        {"ruta": "/api/progreso/analisis"},
        {"ruta": "/api/progreso/historial"},
        {"ruta": "/api/progreso/historial?limite=3"},
        {"ruta": "/api/progreso/historial?estado=resuelto"},
        {"ruta": "/api/progreso/historial?estado="},
        {"ruta": "/api/progreso/historial?fuente=prig-hub"},
        {"ruta": "/api/progreso/historial?concepto=PILAS"},
        {"ruta": "/api/progreso/historial?concepto=%C3%A1rboles%20binarios"},
        {"ruta": "/api/progreso/historial?concepto=prueba%20des_aaaaaaaaa3"},
        {"ruta": "/api/progreso/historial?limite=600"},
        {"ruta": "/api/github/guardados"},
        {"ruta": "/api/github/estado"},
        {"ruta": "/api/kaggle/estado"},
        {"ruta": "/api/kaggle/colecciones"},
        {"ruta": "/api/kaggle/colecciones/col_1"},
        {"ruta": "/api/kaggle/colecciones/col_3"},
        {"ruta": "/api/kaggle/colecciones/no_existe"},
        {"ruta": "/api/kaggle/mis_datos"},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/titanic/train.csv"},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/titanic/datos.tsv"},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/titanic/punto.csv"},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/titanic/raro.csv"},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/titanic/sub/notas.txt"},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/titanic/foto.png"},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/suelta/a.bin"},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos/titanic/../../ejercicio.py"},
        {"ruta": "/api/kaggle/previa?ruta={proyecto}/kaggle_datos"},
        {"ruta": "/api/kaggle/previa"},
        {"ruta": "/api/kaggle/archivo?ruta={proyecto}/kaggle_datos/titanic/foto.png"},
        {"ruta": "/api/kaggle/archivo?ruta={proyecto}/kaggle_datos/titanic/train.csv"},
        {"ruta": "/api/kaggle/archivo"},
        {"ruta": "/api/kaggle/buscar"},
        {"ruta": "/api/kaggle/buscar?q=uno&orden=votos&tipo=script&votos_min=0&gpu=false&padre=kaggle.com/code/ana/nb-uno/edit"},
        {"ruta": "/api/kaggle/buscar?votos_min=5&dias=36500&gpu=true"},
        {"ruta": "/api/kaggle/buscar?q=titanic"},
        {"ruta": "/api/kaggle/buscar?pagina=0"},
        {"ruta": "/api/kaggle/buscar?gpu=quizas"},
        {"ruta": "/api/kaggle/buscar?padre=../x"},
        {"ruta": "/api/kaggle/notebook?ref=https://www.kaggle.com/code/ana/nb-uno"},
        {"ruta": "/api/kaggle/notebook?ref=ana/nb-uno&refrescar=true", "volatiles": ["descargado"]},
        {"ruta": "/api/kaggle/notebook?ref=ana/script-uno&refrescar=1", "volatiles": ["descargado"]},
        {"ruta": "/api/kaggle/notebook?ref=ana/no-existe"},
        {"ruta": "/api/kaggle/notebook?ref=no%20vale"},
        {"ruta": "/api/kaggle/notebook"},
        {"ruta": "/api/kaggle/importar", "metodo": "POST", "json": {"ref": "ana/nb-uno"}, "archivo": "{proyecto}/kaggle_notebooks/nb-uno.ipynb", "restaurar": True},
        {"ruta": "/api/kaggle/importar", "metodo": "POST", "json": {"ref": "ana/script-uno"}, "archivo": "{proyecto}/kaggle_notebooks/script-uno.py", "restaurar": True},
        {"ruta": "/api/kaggle/importar", "metodo": "POST", "json": {}},
        {"ruta": "/api/kaggle/datasets"},
        {"ruta": "/api/kaggle/datasets?q=x&orden=votos&tipo_archivo=csv&licencia=cc&tamano=mediano&usuario=ana"},
        {"ruta": "/api/kaggle/dataset?ref=https://www.kaggle.com/datasets/ana/otro-ds/data"},
        {"ruta": "/api/kaggle/dataset?ref=no"},
        {"ruta": "/api/kaggle/competiciones?grupo=mias&categoria=playground&orden=premio"},
        {"ruta": "/api/kaggle/competicion?ref=titanic"},
        {"ruta": "/api/kaggle/competicion?ref=inexistente"},
        {"ruta": "/api/kaggle/descargar", "metodo": "POST", "json": {"tipo": "dataset", "ref": "ana/otro-ds"}},
        {"ruta": "/api/kaggle/descargar", "metodo": "POST", "json": {"tipo": "competicion", "ref": "titanic"}},
        {"ruta": "/api/kaggle/descargar", "metodo": "POST", "json": {"tipo": "modelo", "ref": "x"}},
        {"ruta": "/api/kaggle/pdf", "metodo": "POST", "json": {"ref": "ana/nb-uno", "nivel": "basico", "chat": [{"rol": "usuario", "texto": "¿Qué hace?"}, {"rol": "profesor", "texto": "Lee datos."}, {"texto": " "}]}},
        {"ruta": "/api/kaggle/pdf", "metodo": "POST", "json": {"ref": "ana/script-uno", "salidas": False, "guia": False}},
        {"ruta": "/api/kaggle/pdf", "metodo": "POST", "json": {"ref": "ana/nb-uno", "solo_explicadas": True}},
        {"ruta": "/api/kaggle/pdf", "metodo": "POST", "json": {"ref": "ana/nb-uno", "solo_explicadas": True, "nivel": "avanzado"}},
        {"ruta": "/api/kaggle/pdf", "metodo": "POST", "json": {"coleccion": "col_1"}},
        {"ruta": "/api/kaggle/pdf", "metodo": "POST", "json": {"coleccion": "nope"}},
        {"ruta": "/api/kaggle/pdf", "metodo": "POST", "json": {}},
        {"ruta": "/api/kaggle/pdf?ruta={proyecto}/kaggle_pdf/nb-uno.pdf"},
        {"ruta": "/api/kaggle/pdf?ruta={proyecto}/kaggle_datos/titanic/train.csv"},
        {"ruta": "/api/kaggle/pdf/abrir", "metodo": "POST", "json": {"ref": "/etc/passwd"}},
        {"ruta": "/api/github/widget/config"},
        {"ruta": "/api/github/widget/config", "metodo": "POST", "json": {"config": {"tema": "cyber", "mostrar_modelos": True}}, "archivo": "{home}/.prig_github_widget.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/github/widget/config", "metodo": "POST", "json": {}},
        {"ruta": "/api/github/widget/preview", "metodo": "POST", "json": {"config": {"tema": "minimal", "mostrar_modelos": True, "mostrar_youtube": False}, "extras": {"yt_cursos_completados": 3, "yt_fotogramas": 2.5, "modelo_local": "<Qwen & Cía> muy largo de verdad"}}},
        {"ruta": "/api/github/widget/preview", "metodo": "POST", "json": {}},
        {"ruta": "/api/github/widget/preview", "metodo": "POST", "json": {"config": "x"}},
        {"ruta": "/api/github/widget/publicar", "metodo": "POST", "json": {"config": {"tema": "mocha"}}, "archivo": "{home}/.prig_github_widget.json", "restaurar": True, "archivo_json": True, "volatiles": ["ultimo_sync"]},
        {"ruta": "/api/github/buscar?q=cli&lenguaje=Python&estrellas_min=10&tema=ml&orden=actualizados&pagina=2"},
        {"ruta": "/api/github/buscar?q=cli&orden=relevancia"},
        {"ruta": "/api/github/buscar"},
        {"ruta": "/api/github/buscar?q=malo"},
        {"ruta": "/api/github/buscar?q=limite"},
        {"ruta": "/api/github/buscar?pagina=51&q=x"},
        {"ruta": "/api/github/repo?ref=https://github.com/ana/repo.git"},
        {"ruta": "/api/github/repo?ref=ana/Repo&refrescar=true", "volatiles": ["descargado"]},
        {"ruta": "/api/github/repo?ref=nadie/x"},
        {"ruta": "/api/github/repo?ref=no"},
        {"ruta": "/api/github/archivo?ref=ana/Repo&ruta=src/main.py"},
        {"ruta": "/api/github/archivo?ref=ana/Repo&ruta=README.md"},
        {"ruta": "/api/github/archivo?ref=ana/Repo&ruta=src/nul.py"},
        {"ruta": "/api/github/archivo?ref=ana/Repo&ruta=docs/a%20b.md"},
        {"ruta": "/api/github/archivo?ref=ana/Repo&ruta=img/logo.png"},
        {"ruta": "/api/github/archivo?ref=ana/Repo&ruta=datos/grande.csv"},
        {"ruta": "/api/github/archivo?ref=ana/Repo&ruta=no.py"},
        {"ruta": "/api/github/archivo?ref=ana/Repo"},
        {"ruta": "/api/github/guardados", "metodo": "POST", "json": {"ref": "ana/repo", "nota": "  ver luego "}, "archivo": "{home}/.prig_github/guardados.json", "restaurar": True, "archivo_json": True, "volatiles": ["guardado"]},
        {"ruta": "/api/github/guardados?ref=ANA/REPO", "metodo": "DELETE", "archivo": "{home}/.prig_github/guardados.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/github/guardados", "metodo": "DELETE"},
        {"ruta": "/api/github/token", "metodo": "POST", "json": {"texto": " github_pat_bueno_de_prueba_000 "}, "archivo": "{home}/.prig_github.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/github/token", "metodo": "POST", "json": {"texto": "github_pat_malo_de_prueba_0000"}, "archivo": "{home}/.prig_github.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/github/token", "metodo": "POST", "json": {"texto": "corto"}, "archivo": "{home}/.prig_github.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/github/token", "metodo": "DELETE", "archivo": "{home}/.prig_github.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/github/exportar", "metodo": "POST", "json": {"ref": "ana/Repo", "nota": "md"}},
        {"ruta": "/api/github/exportar", "metodo": "POST", "json": {"ref": "ana/Repo"}},
        {"ruta": "/api/github/exportado?ruta={proyecto}/github_explicaciones/ana__Repo.md"},
        {"ruta": "/api/github/exportado?ruta={proyecto}/github_explicaciones/ana__Repo.pdf&descargar=true"},
        {"ruta": "/api/github/exportado?ruta=/etc/passwd"},
        {"ruta": "/api/github/descargar", "metodo": "POST", "json": {"ref": "ana/Repo"}},
        {"ruta": "/api/github/descargar", "metodo": "POST", "json": {"ref": "nadie/x"}},
        {"ruta": "/api/progreso/resumen", "volatiles": ["id", "bloque_id", "generado"]},
        {"ruta": "/api/progreso/resumen?dias=7", "volatiles": ["id", "bloque_id", "generado"]},
        {"ruta": "/api/progreso/resumen?dias=400"},
        {"ruta": "/api/youtube/palabras_registradas"},
        {"ruta": "/api/youtube/sugerencias?q=python%20curso&limite=1"},
        {"ruta": "/api/youtube/sugerencias?q=python"},
        {"ruta": "/api/youtube/sugerencias?q=%20%20"},
        {"ruta": "/api/youtube/sugerencias"},
        {"ruta": "/api/youtube/buscar?q=python&forzar=true"},
        {"ruta": "/api/youtube/buscar?q=Python&idioma=es&orden=vistas&forzar=true"},
        {"ruta": "/api/youtube/buscar?q=machine%20learning&idioma=en&orden=recientes&forzar=true"},
        {"ruta": "/api/youtube/buscar?q=curso&tipo=playlist&orden=duracion&forzar=true"},
        {"ruta": "/api/youtube/buscar?q=curso&duracion_filtro=cursos&forzar=true"},
        {"ruta": "/api/youtube/buscar?q=curso&duracion_filtro=cortos&max_resultados=2&forzar=true"},
        {"ruta": "/api/youtube/buscar?q=vacio&forzar=true"},
        {"ruta": "/api/youtube/buscar?q=caido&forzar=true"},
        {"ruta": "/api/youtube/buscar?q=deep_learning&forzar=true&filtro_educativo=false"},
        {"ruta": "/api/youtube/buscar?q=%20"},
        {"ruta": "/api/youtube/buscar?q=x&max_resultados=abc"},
        {"ruta": "/api/youtube/abrir_externo", "metodo": "POST", "json": {"url": "https://malicioso.com/x"}},
        {"ruta": "/api/youtube/abrir_externo", "metodo": "POST", "json": {}},
        {"ruta": "/api/youtube/abrir_externo", "metodo": "POST", "crudo": "{roto"},
        {"ruta": "/api/youtube/transcripcion?video_id=vidEN&forzar=true"},
        {"ruta": "/api/youtube/transcripcion?video_id=vidES"},
        {"ruta": "/api/youtube/transcripcion?video_id=vidEN&idioma=fr&forzar=1"},
        {"ruta": "/api/youtube/transcripcion?video_id=sinsubs"},
        {"ruta": "/api/youtube/transcripcion?video_id="},
        {"ruta": "/api/youtube/transcripcion"},
        {"ruta": "/api/ai/status"},
        {"ruta": "/api/ai/reload"},
        {"ruta": "/api/ai/models"},
        {"ruta": "/api/ai/models/detailed"},
        {"ruta": "/api/ai/models/delete", "metodo": "POST", "json": {"model": "qwen2.5-coder:7b"}},
        {"ruta": "/api/ai/models/delete", "metodo": "POST", "json": {"model": "otro"}},
        {"ruta": "/api/ai/models/delete", "metodo": "POST", "json": {}},
        {"ruta": "/api/ai/pull", "metodo": "POST", "json": {"model": "Qwen3-30B-A3B (rápido)"}},
        {"ruta": "/api/ai/pull", "metodo": "POST", "json": {"model": "roto"}},
        {"ruta": "/api/ai/pull", "metodo": "POST", "json": {"model": "noexiste"}},
        {"ruta": "/api/ai/pull", "metodo": "POST", "json": {"model": "viejo"}},
        {"ruta": "/api/ai/config"},
        {"ruta": "/api/ai/config", "metodo": "POST", "json": {"temperature": "0.5", "num_ctx": 8192.0, "low_vram": "yes", "keep_alive": "10m", "otra": 1}, "archivo": "{home}/.prig_ai_config.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/ai/config", "metodo": "POST", "json": {"agent1_model": None, "top_k": 7}, "archivo": "{home}/.prig_ai_config.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/ai/config", "metodo": "POST", "json": {"num_ctx": 1.5}, "archivo": "{home}/.prig_ai_config.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/ai/config", "metodo": "POST", "json": {"keep_alive": 5}, "archivo": "{home}/.prig_ai_config.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/kaggle/lecturas"},
        {"ruta": "/api/kaggle/colecciones", "metodo": "POST", "json": {"nombre": "  Mis   notebooks ", "descripcion": " d ", "color": "#f38ba8"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones", "metodo": "POST", "json": {"nombre": "titanic"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones", "metodo": "POST", "json": {"nombre": "   "}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones", "metodo": "POST", "json": {"nombre": "Otra", "color": "rojo"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones", "metodo": "POST", "json": {"nombre": 5}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_1", "metodo": "PATCH", "json": {"nombre": "Titanic 2", "descripcion": "x", "color": "#89b4fa"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_1", "metodo": "PATCH", "json": {"nombre": "Visión"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_1", "metodo": "PATCH", "json": {}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/nope", "metodo": "PATCH", "json": {"nombre": "x"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_2", "metodo": "DELETE", "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/nope", "metodo": "DELETE", "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_3/items", "metodo": "POST", "json": {"tipo": "notebook", "ref": "ana/nb-uno", "datos": {"titulo": "Uno", "votos": 3, "otro": 1}}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_1/items", "metodo": "POST", "json": {"tipo": "notebook", "ref": "a/titanic", "datos": {"autor": "Ana", "titulo": None}}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_3/items", "metodo": "POST", "json": {"tipo": "competicion", "ref": "https://www.kaggle.com/competitions/titanic/data"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_3/items", "metodo": "POST", "json": {"tipo": "competicion", "ref": "no vale"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_3/items", "metodo": "POST", "json": {"tipo": "modelo", "ref": "a/b"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_3/items", "metodo": "POST", "json": {"tipo": "dataset", "ref": "a/../b"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_3/items", "metodo": "POST", "json": {"tipo": "dataset", "ref": "a/b", "datos": "x"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_3/items", "metodo": "POST", "json": {"ref": "a/b"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_1/items", "metodo": "PATCH", "json": {"tipo": "notebook", "ref": "a/titanic", "nota": "  repasar  "}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_1/items", "metodo": "PATCH", "json": {"tipo": "notebook", "ref": "z/nada", "nota": "x"}, "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_1/items?tipo=notebook&ref=a/titanic", "metodo": "DELETE", "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/col_1/items?tipo=notebook", "metodo": "DELETE", "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/colecciones/nope/items?tipo=notebook&ref=a", "metodo": "DELETE", "archivo": "{home}/.prig_kaggle/colecciones.json", "restaurar": True, "archivo_json": True, "volatiles": ["id", "creada", "actualizada", "anadido"]},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {"texto": "token_de_prueba_valido_0123456789"}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {"texto": "  '{\"username\": \"ana\", \"key\": \"clave-buena\"}'  "}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {"texto": "token_de_prueba_que_kaggle_rechaza"}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {"texto": "corto"}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {"texto": "{roto"}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {"texto": "{\"username\": \"ana\"}"}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {"texto": ""}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "POST", "json": {}, "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/kaggle/credenciales", "metodo": "DELETE", "archivo": "{home}/.prig_kaggle.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/librerias/list"},
        {"ruta": "/api/papers/list"},
        {"ruta": "/api/papers/list?q=regresion"},
        {"ruta": "/api/papers/list?q=Gradiente%20%20descenso"},
        {"ruta": "/api/papers/list?q=xgboost&categoria=todas"},
        {"ruta": "/api/papers/list?categoria=supervisado"},
        {"ruta": "/api/papers/list?q=%C3%A1rbol"},
        {"ruta": "/api/papers/list?q=no-aparece-en-ninguno"},
        # escrituras de desafíos (cada lado parte del mismo archivo)
        {"ruta": "/api/desafios/{desafio}/paginas", "metodo": "PUT", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/{desafio}.json",
         "json": {"paginas": [{"nombre": "mi_pila.py", "contenido": "x = 1\n", "otra": 2}, {"nombre": "util.h", "contenido": None}]}},
        {"ruta": "/api/desafios/{desafio}/paginas", "metodo": "PUT", "json": {"paginas": [{"nombre": "mal nombre.py"}]}},
        {"ruta": "/api/desafios/{desafio}/paginas", "metodo": "PUT", "json": {"paginas": [{"nombre": "os.py"}]}},
        {"ruta": "/api/desafios/{desafio}/paginas", "metodo": "PUT", "json": {"paginas": [{"nombre": "a.py"}, {"nombre": "A.py"}]}},
        {"ruta": "/api/desafios/{desafio}/paginas", "metodo": "PUT", "json": {"paginas": []}},
        {"ruta": "/api/desafios/{desafio}/paginas", "metodo": "PUT", "json": {"paginas": [{"nombre": "x.py", "contenido": "ñ" * 120000}]}},
        {"ruta": "/api/desafios/des_0000000000/paginas", "metodo": "PUT", "json": {"paginas": [{"nombre": "x.py"}]}},
        {"ruta": "/api/desafios/malo/paginas", "metodo": "PUT", "json": {"paginas": [{"nombre": "x.py"}]}},
        {"ruta": "/api/desafios/{desafio}/razonamiento/visto", "metodo": "POST", "json": {"pasos_vistos": 4}, "restaurar": True,
         "archivo_json": True, "archivo": "{home}/.prig_desafios/desafios/{desafio}.json"},
        {"ruta": "/api/desafios/{desafio}/razonamiento/visto", "metodo": "POST", "json": {"pasos_vistos": "99"}, "restaurar": True,
         "archivo_json": True, "archivo": "{home}/.prig_desafios/desafios/{desafio}.json"},
        {"ruta": "/api/desafios/{desafio}/razonamiento/visto", "metodo": "POST", "json": {"pasos_vistos": 2.5}},
        {"ruta": "/api/desafios/{desafio}/razonamiento/visto", "metodo": "POST", "json": {"pasos_vistos": "tres"}},
        {"ruta": "/api/desafios/{desafio}/razonamiento/visto", "metodo": "POST", "json": {"pasos_vistos": True}},
        {"ruta": "/api/desafios/{desafio}/razonamiento/visto", "metodo": "POST", "json": {}},
        {"ruta": "/api/desafios/{desafio}/rendirse", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/{desafio}.json"},
        {"ruta": "/api/desafios/{desafio2}/rendirse", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/{desafio2}.json"},
        {"ruta": "/api/desafios/des_0000000000/rendirse", "metodo": "POST"},
        {"ruta": "/api/desafios/{desafio2}", "metodo": "DELETE", "restaurar": True, "archivo": "{home}/.prig_desafios/desafios/{desafio2}.json"},
        {"ruta": "/api/desafios/des_ffffffffff", "metodo": "DELETE"},
        # ejecutar una página de un desafío (Python como herramienta; nada de modelos)
        {"ruta": "/api/desafios/{desafio}/ejecutar", "metodo": "POST",
         "json": {"pagina": "main.py", "paginas": [{"nombre": "main.py", "contenido": "import util\nprint('hola', util.f(2))\nimport sys\nprint('err', file=sys.stderr)\n"},
                                                   {"nombre": "util.py", "contenido": "def f(x):\n    return x * 21\n"}]}},
        {"ruta": "/api/desafios/{desafio}/ejecutar", "metodo": "POST",
         "json": {"pagina": "main.py", "paginas": [{"nombre": "main.py", "contenido": "raise ValueError('mal')\n"}]}},
        {"ruta": "/api/desafios/{desafio}/ejecutar", "metodo": "POST",
         "json": {"pagina": "t.py", "paginas": [{"nombre": "t.py", "contenido": "import pytest\nprint(pytest.mark.slow(lambda: 3)())\n"}]}},
        {"ruta": "/api/desafios/{desafio}/ejecutar", "metodo": "POST", "json": {"pagina": "no.py", "paginas": [{"nombre": "a.py"}]}},
        {"ruta": "/api/desafios/{desafio}/ejecutar", "metodo": "POST", "json": {"paginas": [{"nombre": "a.py"}]}},
        {"ruta": "/api/desafios/des_0000000000/ejecutar", "metodo": "POST", "json": {"pagina": "a.py", "paginas": [{"nombre": "a.py"}]}},
        {"ruta": "/api/desafios/{desafio}/detener", "metodo": "POST"},
        {"ruta": "/api/desafios/des_aaaaaaaaa1/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa1.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return 2 * x\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa1/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa1.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return x + 2\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa1/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa1.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x)\\n    return\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa2/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa2.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return 2 * x\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa2/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa2.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return x + 2\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa2/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa2.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x)\\n    return\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa3/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa3.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return 2 * x\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa3/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa3.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return x + 2\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa3/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa3.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x)\\n    return\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa4/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa4.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return 2 * x\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa4/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa4.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return x + 2\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa4/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa4.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x)\\n    return\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa6/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa6.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return 2 * x\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa6/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa6.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x):\\n    return x + 2\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa6/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa6.json", "json": {"paginas": [{"nombre": "sol.py", "contenido": "def doble(x)\\n    return\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa5/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa5.json", "json": {"paginas": [{"nombre": "sol.h", "contenido": "inline int doble(int x) { return 2 * x; }\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa5/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa5.json", "json": {"paginas": [{"nombre": "sol.h", "contenido": "inline int doble(int x) { return x + 2; }\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa5/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_desafios/desafios/des_aaaaaaaaa5.json", "json": {"paginas": [{"nombre": "sol.h", "contenido": "inline int doble(int x) { return 2 * x }\\n"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa1/comprobar", "metodo": "POST", "json": {"paginas": [{"nombre": "test_sol.py"}]}},
        {"ruta": "/api/desafios/des_aaaaaaaaa1/comprobar", "metodo": "POST", "json": {}},
        {"ruta": "/api/desafios/des_aaaaaaaaa6/comprobar", "metodo": "POST", "restaurar": True, "archivo_json": True,
         "archivo": "{home}/.prig_hub/progreso.jsonl", "solo_archivo": True, "json": {"paginas": [{"nombre": "sol.py", "contenido": "x = 1\n"}]}},
        {"ruta": "/api/learning/metrics"},
        {"ruta": "/api/learning/metrics?days=1"},
        {"ruta": "/api/learning/metrics?days=0"},
        {"ruta": "/api/learning/metrics?days=400"},
        {"ruta": "/api/learning/metrics?days=dos"},
        {"ruta": "/api/exercise/recent"},
        {"ruta": "/api/exercise/recent?limit=2"},
        {"ruta": "/api/exercise/recent?concept=funciones&limit=100"},
        {"ruta": "/api/exercise/recent?limit=0"},
        {"ruta": "/api/exercise/ex_3"},
        {"ruta": "/api/exercise/no_existe"},
        {"ruta": "/api/exercise/ex_1/solution"},
        {"ruta": "/api/exercise/no_existe/solution"},
        {"ruta": "/api/exercise/submit", "metodo": "POST", "restaurar_otro": "{proyecto}/.prig_dataset/learning.db", "json": {"exercise_id": "ex_1", "code": "def doble(x):\n    return x * 2\n", "hints_used": 1}},
        {"ruta": "/api/exercise/submit", "metodo": "POST", "restaurar_otro": "{proyecto}/.prig_dataset/learning.db", "json": {"exercise_id": "ex_1", "code": "def doble(x):\n    return x + 2\n"}},
        {"ruta": "/api/exercise/submit", "metodo": "POST", "restaurar_otro": "{proyecto}/.prig_dataset/learning.db", "json": {"exercise_id": "ex_1", "code": "def doble(x)\n"}},
        {"ruta": "/api/exercise/submit", "metodo": "POST", "restaurar_otro": "{proyecto}/.prig_dataset/learning.db", "json": {"exercise_id": "ex_1", "code": "   "}},
        {"ruta": "/api/exercise/submit", "metodo": "POST", "restaurar_otro": "{proyecto}/.prig_dataset/learning.db", "json": {"exercise_id": "ex_1", "code": "raise KeyError('x')"}},
        {"ruta": "/api/exercise/submit", "metodo": "POST", "json": {"exercise_id": "nada", "code": "x"}},
        {"ruta": "/api/exercise/submit", "metodo": "POST", "json": {"code": "x"}},
        {"ruta": "/api/learning/metrics"},
        {"ruta": "/api/guided/list"},
        {"ruta": "/api/seguimiento/list"},
        {"ruta": "/api/study-plan/list"},
        {"ruta": "/api/guided/seg_aaaa0002", "metodo": "DELETE", "restaurar": True, "archivo": "{proyecto}/.prig_seguimientos/seg_aaaa0002.json"},
        {"ruta": "/api/seguimiento/seg_aaaa0001", "metodo": "DELETE", "restaurar": True, "archivo": "{proyecto}/.prig_seguimientos/seg_aaaa0001.json"},
        {"ruta": "/api/guided/no_existe", "metodo": "DELETE"},
        {"ruta": "/api/dataset/summary", "volatiles": ["created_at", "updated_at", "last_activity", "block_id"]},
        {"ruta": "/api/dataset/export", "volatiles": ["created_at", "updated_at", "last_activity", "block_id"]},
        {"ruta": "/api/guided/seg_aaaa0006/progress", "metodo": "POST", "json": {"completed_blocks": ["b1", "b2", "b2"]},
         "archivo": "{proyecto}/.prig_seguimientos/seg_aaaa0006.json", "restaurar": True, "archivo_json": True,
         "contenedores": ["completion_dates"]},
        {"ruta": "/api/seguimiento/seg_aaaa0006/progress", "metodo": "POST", "json": {"completed_blocks": []},
         "archivo": "{proyecto}/.prig_seguimientos/seg_aaaa0006.json", "restaurar": True, "archivo_json": True},
        {"ruta": "/api/guided/no_existe/progress", "metodo": "POST", "json": {"completed_blocks": []}},
        {"ruta": "/api/seguimiento/no_existe/progress", "metodo": "POST", "json": {"completed_blocks": []}},
        {"ruta": "/api/guided/seg_aaaa0006/progress", "metodo": "POST", "json": {"completed_blocks": "b1"}},
        {"ruta": "/api/guided/seg_aaaa0006/progress", "metodo": "POST", "json": {"completed_blocks": [1, "b"]}},
        {"ruta": "/api/guided/seg_aaaa0006/progress", "metodo": "POST", "json": {}},
        {"ruta": "/api/guided/seg_aaaa0003/progress", "metodo": "POST", "json": {"completed_blocks": []}},
        {"ruta": "/api/study-plan/progress/toggle-criterion", "metodo": "POST",
         "json": {"plan_id": "plan_completo", "module_id": "m1", "criterion_text": "c1"},
         "archivo": "{proyecto}/.prig_plans/plan_completo/current.json", "restaurar": True, "archivo_json": True,
         "volatiles": ["updated_at"]},
        {"ruta": "/api/study-plan/progress/toggle-notebook", "metodo": "POST", "json": {"plan_id": "plan_completo", "notebook_id": "nb1"},
         "archivo": "{proyecto}/.prig_plans/plan_completo/current.json", "restaurar": True, "archivo_json": True,
         "volatiles": ["updated_at"]},
        {"ruta": "/api/study-plan/progress/toggle-notebook", "metodo": "POST", "json": {"plan_id": "plan_completo", "notebook_id": "nb9"},
         "archivo": "{proyecto}/.prig_plans/plan_completo/current.json", "restaurar": True, "archivo_json": True,
         "volatiles": ["updated_at"]},
        {"ruta": "/api/study-plan/progress/toggle-notebook", "metodo": "POST", "json": {"plan_id": "no_existe", "notebook_id": "x"}},
        {"ruta": "/api/study-plan/progress/toggle-criterion", "metodo": "POST", "json": {"plan_id": "plan_completo"}},
        {"ruta": "/api/guided/seg_aaaa0006"},
        {"ruta": "/api/seguimiento/seg_aaaa0006"},
        {"ruta": "/api/guided/seg_aaaa0008"},
        {"ruta": "/api/guided/seg_aaaa0003"},
        {"ruta": "/api/guided/seg_aaaa0004"},
        {"ruta": "/api/seguimiento/seg_aaaa0007"},
        {"ruta": "/api/guided/no_existe"},
        {"ruta": "/api/seguimiento/no_existe"},
        {"ruta": "/api/seguimiento/no_existe", "metodo": "DELETE"},
        {"ruta": "/api/study-plan/plan_viejo", "metodo": "DELETE", "restaurar": True, "archivo": "{proyecto}/.prig_plans/plan_viejo.json"},
        {"ruta": "/api/study-plan/no_existe", "metodo": "DELETE"},
        {"ruta": "/api/study-plan/%2E%2E", "metodo": "DELETE"},
        {"ruta": "/api/study-plan/list"},
        # escrituras de la configuración: misma respuesta y mismo archivo, byte a byte
        {"ruta": "/api/config/apariencia", "metodo": "POST", "json": {"tema": "oscuro", "ñ": [1, 2.5, None, True], "x": {"y": "z"}},
         "archivo": "{copia}/.prig_dataset/apariencia.json"},
        {"ruta": "/api/config/sintaxis", "metodo": "POST", "json": {}, "archivo": "{copia}/.prig_dataset/sintaxis_personalizada.json"},
        {"ruta": "/api/config/motor_movimiento", "metodo": "POST", "json": {"fps": 30, "efecto": "lluvia"},
         "archivo": "{copia}/.prig_dataset/motor_movimiento.json"},
        {"ruta": "/api/config/audio_reactivo", "metodo": "POST", "json": [1, 2]},
        {"ruta": "/api/config/accesibilidad", "metodo": "POST", "json": "texto"},
        {"ruta": "/api/config/accesibilidad", "metodo": "POST", "crudo": "{roto"},
        {"ruta": "/api/config/accesibilidad", "metodo": "POST", "crudo": ""},
        {"ruta": "/api/config/profiles", "metodo": "POST", "json": {"perfil_activo": "mio", "perfiles": [{"id": "mio", "n": 1}], "extra": 1},
         "archivo": "{copia}/.prig_dataset/config_profiles.json"},
        {"ruta": "/api/config/profiles", "metodo": "POST", "json": {"perfiles": [{"id": "a"}]}},
        {"ruta": "/api/config/profiles", "metodo": "POST", "json": {"perfil_activo": None, "perfiles": []}},
        {"ruta": "/api/config/profiles", "metodo": "POST", "json": {"perfil_activo": 3, "perfiles": [1, {"a": 1}]}},
        {"ruta": "/api/config/profiles", "metodo": "POST", "json": {"perfil_activo": "x"}},
        {"ruta": "/api/config/profiles", "metodo": "POST", "json": {"perfiles": "no"}},
        {"ruta": "/api/config/profiles", "metodo": "POST", "json": [1]},
        {"ruta": "/api/config/profiles/reset", "metodo": "POST", "archivo": "{copia}/.prig_dataset/config_profiles.json"},
        {"ruta": "/api/config/estado_completo", "metodo": "POST",
         "json": {"apariencia": {"a": 1}, "sintaxis": "no", "perfiles": {"perfil_activo": "z", "perfiles": []}, "otro": {}},
         "archivo": "{copia}/.prig_dataset/config_profiles.json"},
        {"ruta": "/api/config/estado_completo"},
        {"ruta": "/api/flags", "metodo": "POST", "json": {"name": "learning_telemetry", "enabled": False}, "archivo": "{home}/.prig_flags.json"},
        {"ruta": "/api/flags", "metodo": "POST", "json": {"name": "learning_telemetry", "enabled": "yes"}, "archivo": "{home}/.prig_flags.json"},
        {"ruta": "/api/flags", "metodo": "POST", "json": {"name": "learning_telemetry"}, "archivo": "{home}/.prig_flags.json"},
        {"ruta": "/api/flags", "metodo": "POST", "json": {"name": "learning_telemetry", "enabled": "quizá"}},
        {"ruta": "/api/flags", "metodo": "POST", "json": {"name": 5, "enabled": [1]}},
        {"ruta": "/api/flags", "metodo": "POST", "json": {}},
        {"ruta": "/api/flags", "metodo": "POST", "json": {"name": "no_existe", "enabled": True}},
        {"ruta": "/api/flags"},
        # métodos que la ruta propia de Rust no atiende: tienen que llegar a Python por el proxy, con «/api»
        {"ruta": "/api/flags", "metodo": "POST", "json": {"nombre": "no_existe", "valor": True}},
        {"ruta": "/api/desafios/des_0000000000", "metodo": "DELETE"},
        {"ruta": "/api/workspace/segunda", "metodo": "POST", "json": {"path": None}},
        {"ruta": "/api/config/profiles"},
        {"ruta": "/api/config/apariencia"},
        {"ruta": "/api/config/sintaxis"},
        {"ruta": "/api/config/motor_movimiento"},
        {"ruta": "/api/config/audio_reactivo"},
        {"ruta": "/api/config/accesibilidad"},
        {"ruta": "/api/config/estado_completo"},
        {"ruta": "/api/explorador/atajos"},
        {"ruta": "/api/explorador/listar"},
        {"ruta": "/api/explorador/listar?ruta={home}/Documentos"},
        {"ruta": "/api/explorador/listar?ruta={home}&recursivo=true"},
        {"ruta": "/api/explorador/listar?ruta={home}&recursivo=xx"},
        {"ruta": "/api/explorador/listar?ruta=/etc"},
        {"ruta": "/api/explorador/listar?ruta={home}/no_existe"},
        {"ruta": "/api/explorador/listar?ruta={home}/Escritorio/nota.txt"},
        {"ruta": "/api/explorador/listar?ruta={proyecto}"},
        {"ruta": "/api/explorador/buscar?q=libro"},
        {"ruta": "/api/explorador/buscar?q=redes%20neuronales"},
        {"ruta": "/api/explorador/buscar?q=pdf&desde={home}/Descargas"},
        {"ruta": "/api/explorador/buscar"},
        {"ruta": "/api/ide/recientes"},
        {"ruta": "/api/workspace/directories"},
        {"ruta": "/api/workspace/directories?ruta={proyecto}/lib"},
        {"ruta": "/api/workspace/directories?ruta=/no/existe"},
        {"ruta": "/api/workspace/projects"},
        {"ruta": "/api/workspace/segunda"},
        {"ruta": "/api/flags"},
        # el panel del motor MoE: comparado 13 de 13 con Python antes de retirar su ruta (F10, tanda 9)
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
        {"ruta": "/api/books/list"},
        {"ruta": "/api/books/list?category=books"},
        {"ruta": "/api/books/list?category=PROJECTS"},
        {"ruta": "/api/books/list?category=all"},
        {"ruta": "/api/books/list?category=nada"},
        {"ruta": "/api/books/inventario?id=books/%C3%81lgebra_lineal-2ed.pdf", "solo_rust": True},
        {"ruta": "/api/books/ocultos", "solo_rust": True},
        {"ruta": "/api/books/delete", "metodo": "POST", "json": {"id": "books"}, "solo_rust": True},
        {"ruta": "/api/books/delete", "metodo": "POST", "json": {"id": "papers/x.pdf", "piezas": ["ficha"]}, "solo_rust": True},
        {"ruta": "/api/banco/simbolos", "solo_rust": True},
        {"ruta": "/api/banco/ficha?nombre=saludar", "solo_rust": True},
        {"ruta": "/api/banco/grafo", "solo_rust": True},
    ]
    for c in casos:
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
        if args.desafios:
            destino = os.path.join(p["home"], ".prig_desafios", "desafios")
            shutil.copytree(args.desafios, destino, dirs_exist_ok=True)
            with open(os.path.join(destino, "des_ffffffffff.json"), "w") as f:
                f.write("{roto")                                 # un desafío dañado
            nombres = sorted(n[:-5] for n in os.listdir(destino) if n.endswith(".json") and n != "des_ffffffffff.json")
            p["desafio"], p["desafio2"] = nombres[0], nombres[-1]
        pp, pr = puerto_libre(), puerto_libre()
        p["env"]["PRIG_PUERTO_RUST"] = str(pr)
        p["env"]["PRIG_KAGGLE_API"] = kaggle_falso()
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

        # el proyecto de prueba como espacio de trabajo (se guarda en el HOME temporal)
        r = pedir(f"http://127.0.0.1:{pp}", {"ruta": "/api/workspace/open", "metodo": "POST", "json": {"path": p["proyecto"]}})
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
            CONTENEDORES_CASO.clear()
            CONTENEDORES_CASO.update(c.get("contenedores", []))
            if c.get("solo_rust"):
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
                print(f"✗ {c.get('metodo', 'GET'):4} {c['ruta'][:70]}  el archivo escrito difiere: "
                      f"{(escrito_python or b'')[:200]!r} ≠ {(escrito_rust or b'')[:200]!r}")
                continue
            etiqueta = f"{c.get('metodo', 'GET'):4} {c['ruta'][:70]}"
            if c.get("solo_archivo"):
                # la respuesta depende de lo que cambió el otro lado (no se restaura todo): solo cuenta el archivo
                b = a
            if a[0] != b[0]:
                fallos += 1
                print(f"✗ {etiqueta}  estado {a[0]} (Python) ≠ {b[0]} (Rust)  {str(a[1])[:150]} | {str(b[1])[:150]}")
            elif a[1][0] != b[1][0] or diferencia(a[1][1], b[1][1]):
                fallos += 1
                d = diferencia(a[1][1], b[1][1]) if a[1][0] == b[1][0] else f"{a[1][0]} ≠ {b[1][0]}"
                print(f"✗ {etiqueta}  {d}")
            else:
                print(f"✓ {etiqueta}  {a[0]}")
        comparados = sum(1 for c in casos if not c.get("solo_rust"))
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
