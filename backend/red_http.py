"""
HTTP con conexiones reutilizadas para las integraciones (GitHub, Kaggle, YouTube, Prig Hub).

`requests.get` y `urllib.request.urlopen` abren una conexión nueva en cada llamada: con GitHub o YouTube eso son
~150 ms de conexión y saludo TLS por petición, y abrir un repositorio o buscar un vídeo hace varias. Aquí solo cambia
el envío: lo hace Rust (prig_nativo.http, el cliente compartido del proceso, sin el GIL), que guarda las conexiones
abiertas. Todo lo demás lo sigue haciendo la biblioteca de siempre, con su propio código:

  · Estilo `requests` (`get`, `post`, `put`, `delete`, `request`): una `requests.Session` nueva por llamada (como
    `requests.get`) con un adaptador de transporte que envía por Rust. Parámetros, cabeceras, autenticación,
    redirecciones, `history` y excepciones son los de `requests`. Con `stream=True`, `verify`/`cert` distintos de lo
    normal o un `proxies` explícito, el adaptador de siempre (urllib3).
  · Estilo `urllib` (`urlopen`): un abridor de urllib cuyo manejador HTTP/HTTPS envía por Rust; redirecciones,
    `HTTPError` y cabeceras por defecto son las de urllib.

Diferencias escritas: el cliente añade `Accept: */*` si la petición no trae `Accept` (urllib no lo manda); no se
pide compresión (`Accept-Encoding`), así que el servidor manda el cuerpo sin comprimir (el contenido es el mismo); el
tiempo es total por petición, no por operación de socket.
"""
import datetime
import io
import urllib.error
import urllib.request
import urllib.response
from email.message import Message
from typing import Optional

import requests
from requests.adapters import BaseAdapter, HTTPAdapter
from requests.structures import CaseInsensitiveDict
from requests.utils import get_encoding_from_headers


def _rs():
    from nativo_rust import rust
    return rust().http


def _segundos(timeout) -> Optional[float]:
    if timeout is None:
        return None
    if isinstance(timeout, tuple):
        partes = [t for t in timeout if t is not None]
        return float(sum(partes)) if partes else None
    return float(timeout)


def _cuerpo(body) -> Optional[bytes]:
    if body is None:
        return None
    if hasattr(body, "read"):
        return body.read()
    return body.encode("utf-8") if isinstance(body, str) else bytes(body)


# ---------------------------------------------------------------------------------------------- estilo requests
class AdaptadorRust(BaseAdapter):
    """ Adaptador de transporte de `requests` que envía por el cliente de Rust (sin seguir redirecciones: eso lo
    hace la Session, con las reglas de requests) """

    def __init__(self):
        super().__init__()
        self._urllib3 = None

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        if stream or verify is not True or cert or any((proxies or {}).values()) and not _proxies_de_entorno(proxies):
            if self._urllib3 is None:
                self._urllib3 = HTTPAdapter()
            return self._urllib3.send(request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies)
        cabeceras = [(k, v) for k, v in request.headers.items() if k.lower() != "accept-encoding"]
        inicio = datetime.datetime.now()
        estado, razon, cabs, cuerpo, url = _rs().enviar(request.method, request.url, cabeceras, _cuerpo(request.body),
                                                        _segundos(timeout), False)
        r = requests.Response()
        r.status_code, r.reason, r._content, r.url = estado, razon, cuerpo, url
        r._content_consumed = True
        r.headers = CaseInsensitiveDict()
        for k, v in cabs:                             # como urllib3: las repetidas, unidas con «, »
            r.headers[k] = f"{r.headers[k]}, {v}" if k in r.headers else v
        r.encoding = get_encoding_from_headers(r.headers)
        r.request = request
        r.connection = self
        r.elapsed = datetime.datetime.now() - inicio
        return r

    def close(self):
        if self._urllib3 is not None:
            self._urllib3.close()


def _proxies_de_entorno(proxies) -> bool:
    """ Los proxies que la Session saca de HTTP_PROXY/HTTPS_PROXY: el cliente de Rust ya los respeta solo """
    import urllib.request as ur
    entorno = ur.getproxies()
    return all(entorno.get(k) == v for k, v in (proxies or {}).items() if v)


_ADAPTADOR = AdaptadorRust()


def request(method: str, url: str, **kw) -> requests.Response:
    with requests.Session() as s:
        s.mount("http://", _ADAPTADOR)
        s.mount("https://", _ADAPTADOR)
        return s.request(method=method, url=url, **kw)


def get(url: str, params=None, **kw) -> requests.Response:
    return request("GET", url, params=params, **kw)


def post(url: str, data=None, json=None, **kw) -> requests.Response:
    return request("POST", url, data=data, json=json, **kw)


def put(url: str, data=None, **kw) -> requests.Response:
    return request("PUT", url, data=data, **kw)


def delete(url: str, **kw) -> requests.Response:
    return request("DELETE", url, **kw)


# ---------------------------------------------------------------------------------------------- estilo urllib
class _Manejador:
    """ El envío de urllib (lo que hacía `do_open` con http.client) por el cliente de Rust """

    def _abrir(self, req):
        req.selector.encode("ascii")                  # como http.client: una ruta con «ñ» sin codificar no se envía
        cabeceras = dict(req.unredirected_hdrs)
        cabeceras.update({k: v for k, v in req.headers.items() if k not in cabeceras})
        cabeceras = [(k, v) for k, v in cabeceras.items() if k.lower() not in ("host", "connection")]
        try:
            estado, razon, cabs, cuerpo, url = _rs().enviar(req.get_method(), req.full_url, cabeceras,
                                                            _cuerpo(req.data), _segundos_urllib(req.timeout), False)
        except requests.RequestException as e:
            raise urllib.error.URLError(e) from None
        mensaje = Message()
        for k, v in cabs:
            mensaje[k] = v
        r = urllib.response.addinfourl(io.BytesIO(cuerpo), mensaje, req.full_url, estado)
        r.msg = razon
        r.reason = razon
        return r


def _segundos_urllib(t) -> Optional[float]:
    # sin `timeout`, urllib guarda un centinela (el tiempo por defecto de socket, que es «sin tope»)
    return float(t) if isinstance(t, (int, float)) and not isinstance(t, bool) else None


class _ManejadorHTTP(_Manejador, urllib.request.HTTPHandler):
    def http_open(self, req):
        return self._abrir(req)


class _ManejadorHTTPS(_Manejador, urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self._abrir(req)


_ABRIDOR = urllib.request.build_opener(_ManejadorHTTP, _ManejadorHTTPS)


def urlopen(url, data=None, timeout: Optional[float] = None):
    if timeout is None:
        return _ABRIDOR.open(url, data)
    return _ABRIDOR.open(url, data, timeout)
