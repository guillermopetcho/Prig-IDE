"""Sustituto mínimo de pytest para los tests de Exercism que solo lo usan para marcar tareas."""
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
