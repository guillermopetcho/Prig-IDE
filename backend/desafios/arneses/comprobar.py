
import contextlib, doctest, importlib, io, json, sys, traceback, unittest, builtins

builtins.input = lambda *args, **kwargs: ""
sys.stdin = io.StringIO("")

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
