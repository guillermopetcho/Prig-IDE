
import sys, os, json, io, ast, contextlib, traceback

def _run(code, namespace):
    """ Ejecuta la celda imitando a Jupyter: la última expresión se muestra. """
    tree = ast.parse(code, filename="<celda>", mode="exec")
    last_expr = None
    if tree.body and isinstance(tree.body[-1], ast.Expr):
        last_expr = ast.Expression(tree.body.pop().value)

    if tree.body:
        exec(compile(tree, "<celda>", "exec"), namespace)

    if last_expr is not None:
        value = eval(compile(last_expr, "<celda>", "eval"), namespace)
        if value is not None:
            print(repr(value))


def _format_user_traceback():
    """ Traceback sin los marcos internos del driver, como haría Jupyter """
    exc_type, exc, tb = sys.exc_info()
    driver_file = os.path.abspath(__file__)
    while tb is not None and os.path.abspath(tb.tb_frame.f_code.co_filename) == driver_file:
        tb = tb.tb_next
    return "".join(traceback.format_exception(exc_type, exc, tb))


def main():
    protocol_out = sys.stdout
    namespace = {"__name__": "__main__", "__builtins__": __builtins__}

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except Exception:
            continue

        if request.get("command") == "shutdown":
            break

        buf_out, buf_err = io.StringIO(), io.StringIO()
        ok = True
        try:
            with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                _run(request.get("code", ""), namespace)
        except SystemExit:
            pass
        except BaseException:
            ok = False
            buf_err.write(_format_user_traceback())

        protocol_out.write(json.dumps({
            "ok": ok,
            "stdout": buf_out.getvalue(),
            "stderr": buf_err.getvalue()
        }) + "\n")
        protocol_out.flush()


main()
