"""
Leer y escribir un repositorio de Prig Hub (formato 1, ver docs/prig-hub.md).

Regla de lectura: NUNCA fallar por un archivo mal escrito. Lo que no se entiende se salta,
se anota en `avisos` y se sigue: un repositorio editado a mano con un error de sangría no
debe dejar a nadie sin sus cursos. Los campos desconocidos se ignoran (versiones futuras
del formato pueden añadir campos sin romper las anteriores).

Escritura: agregar un elemento AÑADE texto al final del archivo, así se conservan los
comentarios y el orden que el usuario escribió a mano. Editar o quitar sí reescribe la lista.
"""

import os
import re
from typing import Any, Dict, List, Optional, Tuple

import yaml

from . import enlaces

FORMATO = 1
TIPOS_REPO = ("perfil", "pack")
NIVELES = ("principiante", "intermedio", "avanzado")
MANIFIESTO = "prig.yaml"
MARCA_README = "<!-- generado por Prig Hub: si lo editas a mano, borra esta línea y Prig no lo tocará -->"
ID_VALIDO = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,60}$")
MAX_ARCHIVO = 512 * 1024
MAX_ELEMENTOS = 2000
LICENCIA_MIT = """MIT License

Copyright (c) {anio} {autor}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


class ErrorFormato(Exception):
    pass


# ============================================================================ utilidades

def slug(texto: str, maximo: int = 50) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:maximo].strip("-") or "sin-nombre"


def _leer_texto(ruta: str, avisos: List[Dict[str, str]], nombre: str) -> Optional[str]:
    try:
        if os.path.getsize(ruta) > MAX_ARCHIVO:
            avisos.append({"archivo": nombre, "mensaje": "Es demasiado grande (más de 512 KB): se ignora."})
            return None
        with open(ruta, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        avisos.append({"archivo": nombre, "mensaje": f"No se pudo leer: {e}"})
        return None


def _yaml(texto: str, avisos, nombre: str):
    try:
        return yaml.safe_load(texto)
    except yaml.YAMLError as e:
        marca = getattr(e, "problem_mark", None)
        donde = f" (línea {marca.line + 1})" if marca else ""
        avisos.append({"archivo": nombre, "mensaje": f"YAML mal escrito{donde}: se ignora el archivo."})
        return None


def _texto(v, maximo=300) -> str:
    return str(v).strip()[:maximo] if v is not None and not isinstance(v, (dict, list)) else ""


def _etiquetas(v) -> List[str]:
    if isinstance(v, str):
        v = [x for x in re.split(r"[,\s]+", v) if x]
    if not isinstance(v, list):
        return []
    return [slug(x, 30) for x in v if _texto(x)][:20]


def _nivel(v) -> str:
    n = _texto(v).lower()
    return n if n in NIVELES else ""


def cabecera(texto: str) -> Tuple[Dict[str, Any], str, Optional[str]]:
    """ (datos de la cabecera YAML entre ---, cuerpo, error) de un Markdown """
    m = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)(.*)$", texto or "", re.S)
    if not m:
        return {}, texto or "", None
    try:
        datos = yaml.safe_load(m.group(1)) or {}
        if not isinstance(datos, dict):
            return {}, m.group(2), "La cabecera no es una lista de campos."
        return datos, m.group(2), None
    except yaml.YAMLError:
        return {}, m.group(2), "La cabecera YAML está mal escrita."


def con_cabecera(datos: Dict[str, Any], cuerpo: str) -> str:
    limpios = {k: v for k, v in datos.items() if v not in (None, "", [], {})}
    return "---\n" + yaml.safe_dump(limpios, allow_unicode=True, sort_keys=False).strip() + "\n---\n\n" + (cuerpo or "").strip() + "\n"


# ============================================================================ lectura

def leer_manifiesto(carpeta: str, avisos: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    texto = _leer_texto(os.path.join(carpeta, MANIFIESTO), avisos, MANIFIESTO)
    if texto is None:
        return None
    datos = _yaml(texto, avisos, MANIFIESTO)
    if not isinstance(datos, dict):
        if datos is not None:
            avisos.append({"archivo": MANIFIESTO, "mensaje": "Debe ser una lista de campos (clave: valor)."})
        return None
    formato = datos.get("formato")
    if not isinstance(formato, int) or formato < 1:
        avisos.append({"archivo": MANIFIESTO, "mensaje": "Falta «formato: 1»; se lee como formato 1."})
        formato = 1
    elif formato > FORMATO:
        avisos.append({"archivo": MANIFIESTO, "mensaje": f"Lo creó una versión más nueva de Prig (formato {formato}); "
                                                         "se lee lo que se entiende."})
    tipo = _texto(datos.get("tipo")).lower()
    if tipo not in TIPOS_REPO:
        avisos.append({"archivo": MANIFIESTO, "mensaje": f"«tipo» debe ser perfil o pack (es «{tipo or 'nada'}»); se trata como pack."})
        tipo = "pack"
    autor = datos.get("autor") if isinstance(datos.get("autor"), dict) else {"nombre": _texto(datos.get("autor"))}
    licencia = datos.get("licencia") if isinstance(datos.get("licencia"), dict) else {}
    titulo = _texto(datos.get("titulo"), 120)
    if not titulo:
        avisos.append({"archivo": MANIFIESTO, "mensaje": "Falta «titulo»."})
    enlaces_ = []
    lista = datos.get("enlaces")
    for u in (lista if isinstance(lista, list) else []):
        try:
            enlaces_.append(enlaces.reconocer(str(u)))
        except enlaces.EnlaceInvalido:
            avisos.append({"archivo": MANIFIESTO, "mensaje": f"Enlace no válido en «enlaces»: {str(u)[:80]}"})
    return {
        "formato": formato, "tipo": tipo, "titulo": titulo or os.path.basename(os.path.abspath(carpeta)),
        "descripcion": _texto(datos.get("descripcion"), 600),
        "autor": {"nombre": _texto(autor.get("nombre"), 80), "github": _texto(autor.get("github"), 60)},
        "idioma": _texto(datos.get("idioma"), 10), "nivel": _nivel(datos.get("nivel")),
        "etiquetas": _etiquetas(datos.get("etiquetas")), "version": _texto(datos.get("version"), 30),
        "licencia": {"contenido": _texto(licencia.get("contenido"), 40), "codigo": _texto(licencia.get("codigo"), 40)},
        "enlaces": enlaces_,
    }


def leer_lista(carpeta: str, nombre: str, avisos, solo_personas: Optional[bool] = None) -> List[Dict[str, Any]]:
    """ personas.yaml, recursos.yaml o suscripciones.yaml: una lista de entradas con url """
    texto = _leer_texto(os.path.join(carpeta, nombre), avisos, nombre)
    if texto is None:
        return []
    datos = _yaml(texto, avisos, nombre)
    if datos is None:
        return []
    if not isinstance(datos, list):
        avisos.append({"archivo": nombre, "mensaje": "Debe ser una lista (cada entrada empieza por «- url: …»)."})
        return []
    salida, vistas = [], set()
    for i, e in enumerate(datos[:MAX_ELEMENTOS], 1):
        if isinstance(e, str):
            e = {"url": e}
        if not isinstance(e, dict) or not _texto(e.get("url"), 2000):
            avisos.append({"archivo": nombre, "mensaje": f"Entrada {i}: falta «url»; se salta."})
            continue
        try:
            info = enlaces.reconocer(_texto(e["url"], 2000))
        except enlaces.EnlaceInvalido as err:
            avisos.append({"archivo": nombre, "mensaje": f"Entrada {i}: {err}"})
            continue
        tipo = _texto(e.get("tipo")).lower() or info["tipo"]
        if tipo not in enlaces.TIPOS:
            avisos.append({"archivo": nombre, "mensaje": f"Entrada {i}: tipo «{tipo}» desconocido; se usa «{info['tipo']}»."})
            tipo = info["tipo"]
        if solo_personas is True:
            tipo = "persona"
        id_ = _texto(e.get("id"), 80)
        if id_ and not ID_VALIDO.match(id_):
            avisos.append({"archivo": nombre, "mensaje": f"Entrada {i}: id «{id_}» no válido (minúsculas, números y guiones); se usa el del enlace."})
            id_ = ""
        clave = f"id:{id_}" if id_ else info["clave"]
        if clave in vistas:
            avisos.append({"archivo": nombre, "mensaje": f"Entrada {i}: repetida ({info['url']}); se salta."})
            continue
        vistas.add(clave)
        minutos = e.get("minutos")
        salida.append({
            **info, "tipo": tipo, "clave": clave, "id": id_,
            "titulo": _texto(e.get("titulo"), 200), "etiquetas": _etiquetas(e.get("etiquetas")),
            "nivel": _nivel(e.get("nivel")), "nota": _texto(e.get("nota"), 1000),
            "minutos": int(minutos) if isinstance(minutos, (int, float)) and 0 < minutos < 100000 else None,
            "miniatura": _texto(e.get("miniatura") or e.get("imagen"), 500),
            "playlist": _texto(e.get("playlist"), 100),
        })
    return salida


_PASO = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.*)$")
_ENLACE_MD = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")


def leer_ruta(texto: str, id_: str, nombre: str, avisos) -> Optional[Dict[str, Any]]:
    datos, cuerpo, error = cabecera(texto)
    if error:
        avisos.append({"archivo": nombre, "mensaje": error})
    titulo = _texto(datos.get("titulo"), 150)
    if not titulo:
        avisos.append({"archivo": nombre, "mensaje": "Falta «titulo» en la cabecera; se usa el nombre del archivo."})
        titulo = id_.replace("-", " ").capitalize()
    pasos, intro, actual = [], [], None
    for linea in cuerpo.splitlines():
        m = _PASO.match(linea)                         # solo los elementos de primer nivel (sin sangría)
        if m:
            actual = {"texto": m.group(1).strip(), "extra": []}
            pasos.append(actual)
        elif actual is not None and (linea.startswith((" ", "\t")) or not linea.strip()):
            actual["extra"].append(linea.strip())
        elif actual is None:
            intro.append(linea)
        else:
            actual = None
            intro.append(linea)
    salida = []
    for i, p in enumerate(pasos, 1):
        texto = " ".join([p["texto"]] + [x for x in p["extra"] if x]).strip()
        enlace = _ENLACE_MD.search(texto)
        paso = {"n": i, "texto": _ENLACE_MD.sub(lambda m: m.group(1), texto)[:600], "titulo": "", "destino": None}
        if enlace:
            paso["titulo"] = enlace.group(1).strip()[:200]
            destino = enlace.group(2).strip()
            if destino.startswith("desafio:"):
                did = destino[len("desafio:"):]
                paso["destino"] = {"tipo": "desafio", "id": did, "clave": f"desafio:{did}"}
            else:
                try:
                    info = enlaces.reconocer(destino)
                    paso["destino"] = {**info}
                except enlaces.EnlaceInvalido:
                    avisos.append({"archivo": nombre, "mensaje": f"Paso {i}: el enlace «{destino[:80]}» no es válido."})
        salida.append(paso)
    if not salida:
        avisos.append({"archivo": nombre, "mensaje": "La ruta no tiene pasos (cada paso es un elemento de lista: «- [Título](enlace)»)."})
    return {"id": id_, "titulo": titulo, "descripcion": _texto(datos.get("descripcion"), 600),
            "nivel": _nivel(datos.get("nivel")), "etiquetas": _etiquetas(datos.get("etiquetas")),
            "introduccion": "\n".join(intro).strip()[:4000], "pasos": salida}


def _archivos_py(carpeta: str, avisos, nombre: str) -> List[Dict[str, str]]:
    salida = []
    if not os.path.isdir(carpeta):
        return salida
    for n in sorted(os.listdir(carpeta)):
        ruta = os.path.join(carpeta, n)
        if not os.path.isfile(ruta) or os.path.islink(ruta):
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,40}\.py", n):
            avisos.append({"archivo": f"{nombre}/{n}", "mensaje": "Nombre de archivo no válido para una página (letras, números y _, terminado en .py); se ignora."})
            continue
        texto = _leer_texto(ruta, avisos, f"{nombre}/{n}")
        if texto is not None:
            salida.append({"nombre": n, "contenido": texto})
    return salida


def leer_desafio(carpeta: str, id_: str, avisos) -> Optional[Dict[str, Any]]:
    nombre = f"desafios/{id_}"
    texto = _leer_texto(os.path.join(carpeta, "desafio.md"), avisos, f"{nombre}/desafio.md")
    if texto is None:
        avisos.append({"archivo": nombre, "mensaje": "Falta desafio.md; se ignora el desafío."})
        return None
    datos, enunciado, error = cabecera(texto)
    if error:
        avisos.append({"archivo": f"{nombre}/desafio.md", "mensaje": error})
    inicio = _archivos_py(os.path.join(carpeta, "inicio"), avisos, f"{nombre}/inicio")
    solucion = _archivos_py(os.path.join(carpeta, "solucion"), avisos, f"{nombre}/solucion")
    pruebas = _archivos_py(os.path.join(carpeta, "pruebas"), avisos, f"{nombre}/pruebas")
    problemas = []
    if not inicio:
        problemas.append("no tiene código de partida (inicio/)")
    if not pruebas:
        problemas.append("no tiene pruebas (pruebas/)")
    if not solucion:
        problemas.append("no tiene solución de referencia (solucion/)")
    elif sorted(p["nombre"] for p in solucion) != sorted(p["nombre"] for p in inicio):
        problemas.append("solucion/ e inicio/ no tienen los mismos archivos")
    lenguaje = _texto(datos.get("lenguaje")).lower() or "python"
    if lenguaje != "python":
        problemas.append(f"lenguaje «{lenguaje}» todavía no se puede comprobar (solo python)")
    if problemas:
        avisos.append({"archivo": nombre, "mensaje": "No se podrá verificar: " + "; ".join(problemas) + "."})
    return {"id": id_, "titulo": _texto(datos.get("titulo"), 150) or id_.replace("-", " ").capitalize(),
            "nivel": _nivel(datos.get("nivel")), "etiquetas": _etiquetas(datos.get("etiquetas")),
            "lenguaje": lenguaje, "minutos": datos.get("minutos") if isinstance(datos.get("minutos"), int) else None,
            "enunciado": enunciado.strip()[:20000], "inicio": inicio, "solucion": solucion, "pruebas": pruebas,
            "verificable": not problemas}


def leer_repo(carpeta: str) -> Dict[str, Any]:
    """ Todo el contenido de un repositorio de Prig Hub, con los avisos de lo que no se entendió """
    avisos: List[Dict[str, str]] = []
    manifiesto = leer_manifiesto(carpeta, avisos)
    if manifiesto is None:
        raise ErrorFormato("No es un repositorio de Prig Hub: falta prig.yaml o no se puede leer."
                           + (f" {avisos[0]['mensaje']}" if avisos else ""))
    personas = leer_lista(carpeta, "personas.yaml", avisos, solo_personas=True)
    recursos = [r for r in leer_lista(carpeta, "recursos.yaml", avisos)]
    for r in recursos:
        if r["tipo"] == "persona":
            avisos.append({"archivo": "recursos.yaml", "mensaje": f"{r['url']} es una persona: mejor en personas.yaml."})
    suscripciones = leer_lista(carpeta, "suscripciones.yaml", avisos) if manifiesto["tipo"] == "perfil" else []
    rutas = []
    d_rutas = os.path.join(carpeta, "rutas")
    if os.path.isdir(d_rutas):
        for n in sorted(os.listdir(d_rutas)):
            if not n.endswith(".md"):
                continue
            id_ = n[:-3]
            if not ID_VALIDO.match(id_):
                avisos.append({"archivo": f"rutas/{n}", "mensaje": "Nombre de archivo no válido (minúsculas, números y guiones); se ignora."})
                continue
            texto = _leer_texto(os.path.join(d_rutas, n), avisos, f"rutas/{n}")
            if texto is not None:
                r = leer_ruta(texto, id_, f"rutas/{n}", avisos)
                if r:
                    rutas.append(r)
    desafios = []
    d_des = os.path.join(carpeta, "desafios")
    if os.path.isdir(d_des):
        for n in sorted(os.listdir(d_des)):
            ruta = os.path.join(d_des, n)
            if not os.path.isdir(ruta):
                continue
            if not ID_VALIDO.match(n):
                avisos.append({"archivo": f"desafios/{n}", "mensaje": "Nombre de carpeta no válido; se ignora."})
                continue
            d = leer_desafio(ruta, n, avisos)
            if d:
                desafios.append(d)
    ids_desafio = {d["id"] for d in desafios}
    for r in rutas:
        for p in r["pasos"]:
            if p["destino"] and p["destino"].get("tipo") == "desafio" and p["destino"]["id"] not in ids_desafio:
                avisos.append({"archivo": f"rutas/{r['id']}.md", "mensaje": f"Paso {p['n']}: no existe el desafío «{p['destino']['id']}»."})
    return {"manifiesto": manifiesto, "personas": personas, "recursos": recursos, "suscripciones": suscripciones,
            "rutas": rutas, "desafios": desafios, "avisos": avisos}


# ============================================================================ escritura

def _dump_entrada(e: Dict[str, Any]) -> str:
    orden = ("url", "titulo", "tipo", "etiquetas", "nivel", "minutos", "nota", "id")
    limpia = {k: e[k] for k in orden if e.get(k) not in (None, "", [])}
    texto = yaml.safe_dump([limpia], allow_unicode=True, sort_keys=False, width=100)
    return texto


def agregar_entrada(carpeta: str, nombre: str, entrada: Dict[str, Any]):
    """ Añade una entrada al final de una lista YAML sin reescribir lo que había """
    ruta = os.path.join(carpeta, nombre)
    previo = ""
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            previo = f.read()
        try:
            datos = yaml.safe_load(previo) if previo.strip() else []
        except yaml.YAMLError:
            raise ErrorFormato(f"{nombre} tiene un error de escritura: arréglalo a mano antes de agregar.")
        if datos not in (None, []) and not isinstance(datos, list):
            raise ErrorFormato(f"{nombre} no es una lista: arréglalo a mano antes de agregar.")
        if datos in (None, []):
            # Lista vacía escrita como «[]»: se quita para poder seguir con «- url: …» (los comentarios quedan)
            previo = "".join(l for l in previo.splitlines(keepends=True) if l.strip() not in ("[]", "---"))
    separador = "" if not previo or previo.endswith("\n") else "\n"
    _escribir(ruta, previo + separador + _dump_entrada(entrada))


def reescribir_lista(carpeta: str, nombre: str, entradas: List[Dict[str, Any]], cabecera_texto: str = ""):
    texto = cabecera_texto + "".join(_dump_entrada(e) for e in entradas) if entradas else (cabecera_texto + "[]\n")
    _escribir(os.path.join(carpeta, nombre), texto)


def entradas_crudas(carpeta: str, nombre: str) -> List[Any]:
    try:
        with open(os.path.join(carpeta, nombre), encoding="utf-8") as f:
            datos = yaml.safe_load(f.read())
        return datos if isinstance(datos, list) else []
    except (FileNotFoundError, yaml.YAMLError):
        return []


def _escribir(ruta: str, texto: str):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta + ".tmp", "w", encoding="utf-8") as f:
        f.write(texto)
    os.replace(ruta + ".tmp", ruta)


def escribir_manifiesto(carpeta: str, datos: Dict[str, Any]):
    orden = ("formato", "tipo", "titulo", "descripcion", "autor", "idioma", "nivel", "etiquetas", "version", "licencia", "enlaces")
    limpio = {}
    for k in orden:
        v = datos.get(k)
        if isinstance(v, dict):
            v = {kk: vv for kk, vv in v.items() if vv not in (None, "", [])}
        if v not in (None, "", [], {}):
            limpio[k] = v
    limpio["formato"] = datos.get("formato") or FORMATO
    _escribir(os.path.join(carpeta, MANIFIESTO),
              "# Prig Hub · formato de repositorio: https://github.com/guillermopetcho/Prig-IDE/blob/main/docs/prig-hub.md\n"
              + yaml.safe_dump(limpio, allow_unicode=True, sort_keys=False, width=100))


def escribir_ruta(carpeta: str, id_: str, titulo: str, pasos: List[Dict[str, str]], descripcion: str = "",
                  nivel: str = "", etiquetas: Optional[List[str]] = None, introduccion: str = ""):
    if not ID_VALIDO.match(id_):
        raise ErrorFormato("Id de ruta no válido.")
    lineas = []
    for p in pasos:
        titulo_p = (p.get("titulo") or "").replace("]", ")").strip() or "Paso"
        destino = p.get("destino") or ""
        nota = (p.get("nota") or "").strip()
        lineas.append(f"1. [{titulo_p}]({destino})" + (f" — {nota}" if nota else ""))
    cuerpo = ((introduccion.strip() + "\n\n") if introduccion.strip() else "") + "\n".join(lineas)
    _escribir(os.path.join(carpeta, "rutas", f"{id_}.md"),
              con_cabecera({"titulo": titulo, "descripcion": descripcion, "nivel": nivel, "etiquetas": etiquetas or []}, cuerpo))


def escribir_desafio(carpeta: str, id_: str, titulo: str, enunciado: str, inicio, solucion, pruebas,
                     nivel: str = "", etiquetas: Optional[List[str]] = None):
    if not ID_VALIDO.match(id_):
        raise ErrorFormato("Id de desafío no válido.")
    base = os.path.join(carpeta, "desafios", id_)
    _escribir(os.path.join(base, "desafio.md"),
              con_cabecera({"titulo": titulo, "nivel": nivel, "etiquetas": etiquetas or [], "lenguaje": "python"}, enunciado))
    for sub, paginas in (("inicio", inicio), ("solucion", solucion), ("pruebas", pruebas)):
        for p in paginas:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,40}\.py", p["nombre"]):
                raise ErrorFormato(f"Nombre de archivo no válido: {p['nombre']}")
            _escribir(os.path.join(base, sub, p["nombre"]), p["contenido"])


def escribir_licencia(carpeta: str, autor: str, contenido: str = "CC-BY-4.0", codigo: str = "MIT"):
    from datetime import date
    texto = (f"# Licencias\n\n"
             f"- **Contenido** (listas, rutas y enunciados): [{contenido}](https://spdx.org/licenses/{contenido}.html). "
             f"Puedes compartirlo y adaptarlo citando la fuente.\n"
             f"- **Código** (`desafios/*/inicio`, `solucion` y `pruebas`): {codigo}, texto completo abajo.\n\n---\n\n")
    if codigo == "MIT":
        texto += LICENCIA_MIT.format(anio=date.today().year, autor=autor or "los autores")
    _escribir(os.path.join(carpeta, "LICENSE.md"), texto)


ICONOS_TIPO = {"curso": "🎓", "video": "▶️", "lista": "📺", "notebook": "📓", "dataset": "🗂️", "competicion": "🏆",
               "repositorio": "📦", "archivo": "📄", "modelo": "🧠", "articulo": "📰", "ejercicio": "🧩", "web": "🔗",
               "persona": "👤"}


def generar_readme(carpeta: str, datos: Dict[str, Any], url_repo: str = "") -> bool:
    """ Portada del repositorio para quien lo mire en GitHub sin Prig. Solo reescribe un
    README que lleve la marca de Prig (o que no exista). """
    ruta = os.path.join(carpeta, "README.md")
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            if MARCA_README not in f.read():
                return False
    m = datos["manifiesto"]
    lin = [MARCA_README, "", f"# {m['titulo']}", ""]
    if m["descripcion"]:
        lin += [m["descripcion"], ""]
    meta = [x for x in (("Perfil de Prig" if m["tipo"] == "perfil" else "Pack de Prig"),
                        m["nivel"], f"v{m['version']}" if m["version"] else "", ", ".join(m["etiquetas"])) if x]
    lin += [" · ".join(meta), ""]
    if url_repo:
        lin += [f"> Ábrelo en [Prig IDE](https://github.com/guillermopetcho/Prig-IDE): **Prig Hub → Agregar enlace** → `{url_repo}`", ""]
    if m["enlaces"]:
        lin += ["## Dónde encontrarme", ""] + [f"- [{e['url']}]({e['url']})" for e in m["enlaces"]] + [""]
    if datos["rutas"]:
        lin += ["## Rutas", ""]
        for r in datos["rutas"]:
            lin.append(f"- [{r['titulo']}](rutas/{r['id']}.md) · {len(r['pasos'])} pasos" + (f" — {r['descripcion']}" if r["descripcion"] else ""))
        lin.append("")
    if datos["recursos"]:
        lin += ["## Recursos", ""]
        for e in datos["recursos"]:
            lin.append(f"- {ICONOS_TIPO.get(e['tipo'], '🔗')} [{e['titulo'] or e['url']}]({e['url']})"
                       + (f" — {e['nota']}" if e["nota"] else ""))
        lin.append("")
    if datos["personas"]:
        lin += ["## Personas que sigo", ""]
        for e in datos["personas"]:
            lin.append(f"- [{e['titulo'] or e['url']}]({e['url']}) · {enlaces.PLATAFORMAS.get(e['plataforma'], e['plataforma'])}")
        lin.append("")
    if datos["desafios"]:
        lin += ["## Desafíos", ""] + [f"- [{d['titulo']}](desafios/{d['id']}/desafio.md)" for d in datos["desafios"]] + [""]
    if datos.get("suscripciones"):
        lin += ["## Sigo en Prig", ""] + [f"- [{s['titulo'] or s['url']}]({s['url']})" for s in datos["suscripciones"]] + [""]
    lin += ["---", "", "Formato: [Prig Hub v1](https://github.com/guillermopetcho/Prig-IDE/blob/main/docs/prig-hub.md) · "
                       "Licencias en [LICENSE.md](LICENSE.md)", ""]
    _escribir(ruta, "\n".join(lin))
    return True
