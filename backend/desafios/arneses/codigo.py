""" Lo que el servidor de Rust necesita del propio Python para crear e importar desafíos: compilar (con los
mensajes exactos de SyntaxError), reparar cuerpos vacíos, vaciar funciones con ast y extraer una función de
TheAlgorithms/Python con sus ejemplos. Se ejecuta con el mismo intérprete que comprueba los desafíos.

Entrada: _prig_codigo.json en la carpeta actual. Salida: una línea con MARCA y el JSON del resultado. """

import ast, json, os, re, sys

MARCA = "__PRIG_CODIGO__"


class ErrorDesafio(Exception):
    pass


# ---------------------------------------------------------------------------------------------- crear y replicar

def limpiar_codigo(codigo, lenguaje="python"):
    if not isinstance(codigo, str):
        return ""
    texto = codigo.strip()
    if texto.startswith("```"):
        lineas = texto.splitlines()
        if lineas and lineas[0].strip().startswith("```"):
            lineas = lineas[1:]
        if lineas and lineas[-1].strip() == "```":
            lineas = lineas[:-1]
        texto = "\n".join(lineas).strip()
    if texto.endswith("```"):
        texto = texto[:-3].rstrip()
    if lenguaje == "python":
        lineas_p = []
        for linea in texto.split("\n"):
            stripped = linea.lstrip()
            if stripped.startswith("//"):
                indent = len(linea) - len(stripped)
                lineas_p.append(" " * indent + "#" + stripped[2:])
            else:
                lineas_p.append(linea)
        texto = "\n".join(lineas_p)
    return texto


def vaciar_cuerpos(codigo):
    """ Vacía los cuerpos de funciones y métodos (pass), con sus firmas y docstrings """
    try:
        tree = ast.parse(codigo)
        nuevos_stmt = []
        for n in tree.body:
            if isinstance(n, ast.If):
                t = n.test
                if isinstance(t, ast.Compare) and getattr(getattr(t.left, "id", None), "strip", lambda: "")() == "__name__":
                    continue
            nuevos_stmt.append(n)
        tree.body = nuevos_stmt
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node)
                nuevos = []
                if doc:
                    nuevos.append(ast.Expr(value=ast.Constant(value=doc)))
                nuevos.append(ast.Pass())
                node.body = nuevos
        return ast.unparse(tree)
    except Exception:
        return codigo


def reparar_cuerpos_vacios(codigo, maximo=30):
    """ Añade `pass` a def/class/if… cuyo cuerpo es solo comentarios TODO o está vacío """
    codigo = limpiar_codigo(codigo, "python")
    lineas = codigo.split("\n")
    for _ in range(maximo):
        try:
            compile("\n".join(lineas), "<pagina>", "exec")
            break
        except SyntaxError as e:
            m = re.search(r"expected an indented block.*on line (\d+)", str(e.msg))
            cabecera = None
            if m:
                cabecera = int(m.group(1)) - 1
            elif "expected an indented block" in str(e.msg):
                idx = (e.lineno or 1) - 1
                while idx >= 0:
                    linea_strip = lineas[idx].strip()
                    if linea_strip.endswith(":") and any(linea_strip.startswith(kw) for kw in (
                        "def ", "class ", "if ", "elif ", "else:", "for ", "while ",
                        "try:", "except", "finally:", "with ", "async def ", "async for ", "async with "
                    )):
                        cabecera = idx
                        break
                    idx -= 1
            if cabecera is None or cabecera < 0 or cabecera >= len(lineas):
                break
            sangria = len(lineas[cabecera]) - len(lineas[cabecera].lstrip()) + 4
            i = cabecera + 1
            while i < len(lineas) and (not lineas[i].strip() or (lineas[i].strip().startswith("#")
                                                                    and len(lineas[i]) - len(lineas[i].lstrip()) >= sangria)):
                i += 1
            while i > cabecera + 1 and not lineas[i - 1].strip():
                i -= 1
            lineas.insert(i, " " * sangria + "pass")
    return "\n".join(lineas)


def sin_compilar(paginas):
    for p in paginas:
        try:
            compile(p["contenido"], p["nombre"], "exec")
        except SyntaxError as e:
            return f"{p['nombre']} (línea {e.lineno}: {e.msg})"
    return None


def pruebas_sin_compilar(pruebas):
    for i, fragmento in enumerate(pruebas, 1):
        try:
            compile(fragmento, f"<prueba {i}>", "exec")
        except SyntaxError as e:
            return f"prueba {i} (línea {e.lineno}: {e.msg})"
    return None


def preparar(cfg):
    """ Las páginas de Python de un desafío recién escrito por el modelo, listas para comprobar """
    paginas, referencia = cfg["paginas"], cfg["referencia"]
    if cfg.get("lenguaje") != "python":
        pass  # otro lenguaje que no es C++: solo se compila, como en tutor.py
    elif cfg.get("modo") == "replicar":
        for p in paginas:
            pr = next((r for r in referencia if r["nombre"] == p["nombre"]), None)
            if pr and p["contenido"].strip() == pr["contenido"].strip() and len(p["contenido"].strip()) > 30:
                vaciado = vaciar_cuerpos(p["contenido"])
                if vaciado.strip() != pr["contenido"].strip():
                    p["contenido"] = vaciado
            p["contenido"] = reparar_cuerpos_vacios(p["contenido"])
    else:
        for p in paginas:
            p["contenido"] = reparar_cuerpos_vacios(p["contenido"])
    if cfg.get("lenguaje") == "python":
        for p in referencia:
            p["contenido"] = reparar_cuerpos_vacios(p["contenido"])
    return {"paginas": paginas, "referencia": referencia,
            "rota": sin_compilar(paginas) or sin_compilar(referencia),
            "pruebas_rotas": pruebas_sin_compilar(cfg["pruebas"])}


# ---------------------------------------------------------------------------------------------- TheAlgorithms

def solo_biblioteca_estandar(arbol):
    for nodo in ast.walk(arbol):
        modulos = []
        if isinstance(nodo, ast.Import):
            modulos = [a.name for a in nodo.names]
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            modulos = [nodo.module]
        for m in modulos:
            raiz = m.split(".")[0]
            # pytest solo se usa para marcar pruebas; en la carpeta de ejecución hay un sustituto
            if raiz not in sys.stdlib_module_names and raiz not in ("__future__", "pytest"):
                return raiz
    return None


def nombres_usados(nodo, docstring):
    usados = {n.id for n in ast.walk(nodo) if isinstance(n, ast.Name)}
    usados |= {n.attr for n in ast.walk(nodo) if isinstance(n, ast.Attribute)}
    for linea in docstring.splitlines():
        if linea.strip().startswith((">>>", "...")):
            usados |= set(re.findall(r"[A-Za-z_]\w*", linea))
    return usados


def thealgorithms(cfg):
    """ La función con ejemplos (la pedida o la principal), lo que necesita del archivo y sus ejemplos """
    fuente, funcion = cfg["fuente"], cfg.get("funcion")
    try:
        arbol = ast.parse(fuente)
    except SyntaxError:
        raise ErrorDesafio("No se pudo leer ese archivo.")
    externa = solo_biblioteca_estandar(arbol)
    if externa:
        raise ErrorDesafio(f"Este algoritmo usa «{externa}», que no viene con Python: elige otro.")

    definiciones = {n.name: n for n in arbol.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    for n in arbol.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            objetivos = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in objetivos:
                if isinstance(t, ast.Name) and not t.id.startswith("__"):
                    definiciones.setdefault(t.id, n)
    candidatas = []
    for n in arbol.body:
        doc = ast.get_docstring(n) if isinstance(n, ast.FunctionDef) else None
        if doc and ">>>" in doc and not n.name.startswith("_") and n.name != "main":
            candidatas.append((doc.count(">>>"), n))
    if not candidatas:
        raise ErrorDesafio("Este archivo no tiene funciones con ejemplos comprobables.")
    if funcion:
        elegida = next((n for _, n in candidatas if n.name == funcion), None)
        if elegida is None:
            raise ErrorDesafio(f"No hay una función «{funcion}» con ejemplos en ese archivo.")
    else:
        # La primera con varios ejemplos: suele ser la principal del archivo
        elegida = next((n for c, n in candidatas if c >= 3), candidatas[0][1])
    doc = ast.get_docstring(elegida)

    # Qué más hace falta: definiciones que usa la función o sus ejemplos (transitivo)
    necesarias, pendientes = set(), [elegida]
    while pendientes:
        actual = pendientes.pop()
        doc_actual = (ast.get_docstring(actual) or "") if isinstance(actual, (ast.FunctionDef, ast.ClassDef)) else ""
        for nombre in nombres_usados(actual, doc_actual):
            if nombre in definiciones and nombre != elegida.name and nombre not in necesarias:
                necesarias.add(nombre)
                pendientes.append(definiciones[nombre])
    lineas = fuente.splitlines()

    def texto(nodo):
        inicio = (nodo.decorator_list[0].lineno if getattr(nodo, "decorator_list", None) else nodo.lineno) - 1
        return "\n".join(lineas[inicio:nodo.end_lineno])

    cabecera = [texto(n) for n in arbol.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    # Solo lo que la función necesita, en el orden del archivo (una constante puede usar otra)
    usados = {id(definiciones[n]) for n in necesarias}
    apoyo = [texto(n) for n in arbol.body if id(n) in usados]

    cuerpo_inicio = elegida.body[1].lineno - 1 if len(elegida.body) > 1 else elegida.body[0].end_lineno
    firma_y_doc = "\n".join(lineas[(elegida.decorator_list[0].lineno if elegida.decorator_list else elegida.lineno) - 1:cuerpo_inicio])
    sangria = " " * (elegida.body[0].col_offset)
    partida = f"{firma_y_doc}\n{sangria}# Escribe aquí tu solución\n{sangria}raise NotImplementedError\n"

    def pagina(principal):
        bloques = cabecera + apoyo + [principal]
        return "\n\n\n".join(b for b in bloques if b.strip()) + "\n"

    ejemplos = "\n".join(l for l in doc.splitlines() if l.strip())
    return {
        "funcion": elegida.name,
        "otras_funciones": [n.name for _, n in candidatas if n.name != elegida.name][:10],
        "partida": pagina(partida), "completa": pagina(texto(elegida)),
        "prosa": doc.split(">>>")[0].strip(), "ejemplos": ejemplos[ejemplos.find(">>>"):],
        "firma": lineas[elegida.lineno - 1].strip(),
    }


OPERACIONES = {"preparar": preparar, "thealgorithms": thealgorithms}

if __name__ == "__main__":
    with open("_prig_codigo.json", encoding="utf-8") as f:
        cfg = json.load(f)
    try:
        salida = {"ok": OPERACIONES[cfg["operacion"]](cfg)}
    except ErrorDesafio as e:
        salida = {"error": str(e)}
    except Exception as e:
        salida = {"excepcion": f"{type(e).__name__}: {e}"}
    print(MARCA + json.dumps(salida, ensure_ascii=False))
