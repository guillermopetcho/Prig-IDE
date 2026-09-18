"""
Servidor falso de la API de Gemini para las pruebas (sin red y sin gastar cuota).

Imita lo medido contra generativelanguage.googleapis.com:
  · GET  /v1beta/models                       lista paginada; clave mala → 400 API_KEY_INVALID
  · POST /v1beta/models/{m}:streamGenerateContent?alt=sse   eventos «data: {json}»

Qué responde depende de la instrucción de sistema: un desafío en JSON, la caja de
razonamiento o un texto corto. Antes del texto manda una parte de pensamiento
("thought": true) que el motor debe ignorar.

    python gemini_falso.py 8791     lo deja escuchando en ese puerto
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CLAVE_VALIDA = "AIzaPRUEBA_valida_1234567890abcd"
# Formato nuevo de AI Studio (desde el 28 de mayo de 2026): empieza por «AQ.» y lleva puntos
CLAVE_AQ = "AQ.Ab8RN6PRUEBA_formato-nuevo.x9Yz12345678"
CLAVE_SIN_CUOTA = "AIzaPRUEBA_sin_cuota_1234567890"

DESAFIO = {
    "titulo": "Contar vocales",
    "enunciado": "Escribe `contar_vocales(texto)` que devuelva cuántas vocales tiene.\n\n- `contar_vocales('hola')` → 2",
    "nivel": "principiante",
    "conceptos": ["cadenas", "bucles"],
    "paginas": [{"nombre": "vocales.py", "descripcion": "La función", "contenido": "def contar_vocales(texto):\n    # TODO\n"}],
    "referencia": [{"nombre": "vocales.py", "contenido": "def contar_vocales(texto):\n    return sum(1 for c in texto.lower() if c in 'aeiou')\n"}],
    "pruebas": ["from vocales import contar_vocales\nassert contar_vocales('hola') == 2",
                "from vocales import contar_vocales\nassert contar_vocales('') == 0",
                "from vocales import contar_vocales\nassert contar_vocales('AEIOU') == 5",
                "from vocales import contar_vocales\nassert contar_vocales('xyz') == 0"],
}

RAZONAMIENTO = "\n".join(f"## {i}. {t}\n*¿Pregunta {i}?*\nRespuesta del paso {i}.\n" for i, t in enumerate(
    ["Qué me piden", "Ejemplos a mano y casos límite", "Descomponer el problema", "Qué estrategia usar y por qué",
     "El algoritmo paso a paso", "Cómo comprobarlo y cuánto cuesta"], 1))

ANALISIS = ("## Dónde estás\nHas resuelto varios desafíos.\n## Lo que se te resiste\nLos bucles.\n"
            "## Cómo estás aprendiendo\nUsas poco la caja de razonamiento.\n"
            "## Plan para las próximas tres sesiones\n- **bucles** — porque fallaste ahí\n- **diccionarios** — para afianzar\n"
            "## Cómo sabrás que avanzaste\nResolver uno sin pistas.\n"
            '```json\n{"temas": ["bucles", "diccionarios"]}\n```')

MODELOS = [
    {"name": "models/gemini-3-flash", "displayName": "Gemini 3 Flash", "supportedGenerationMethods": ["generateContent", "countTokens"], "thinking": True},
    {"name": "models/gemini-3.1-flash-lite", "displayName": "Gemini 3.1 Flash-Lite", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-embedding-001", "displayName": "Embedding", "supportedGenerationMethods": ["embedContent"]},
    {"name": "models/gemini-2.5-flash-preview-tts", "displayName": "TTS", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemma-3-27b-it", "displayName": "Gemma 3", "supportedGenerationMethods": ["generateContent"]},
]

ERROR_CLAVE = {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT",
                         "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]}}
ERROR_AQ = {"error": {"code": 401, "message": "Request had invalid authentication credentials. Expected OAuth 2 access token, "
                                           "login cookie or other valid authentication credential.", "status": "UNAUTHENTICATED",
                      "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "ACCESS_TOKEN_TYPE_UNSUPPORTED"}]}}
ERROR_CUOTA = {"error": {"code": 429, "message": "You exceeded your current quota.", "status": "RESOURCE_EXHAUSTED"}}


class Manejador(BaseHTTPRequestHandler):
    peticiones = []

    def log_message(self, *a):
        pass

    def _json(self, codigo, datos):
        cuerpo = json.dumps(datos).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _clave(self):
        clave = self.headers.get("x-goog-api-key")
        Manejador.peticiones.append({"ruta": self.path, "clave_en_url": "key=" in self.path, "clave": clave})
        if clave == CLAVE_SIN_CUOTA:
            self._json(429, ERROR_CUOTA)
            return False
        if clave not in (CLAVE_VALIDA, CLAVE_AQ):
            # Medido contra Google: una «AQ.» desconocida da 401; una «AIza» mala, 400 API_KEY_INVALID
            self._json(401, ERROR_AQ) if (clave or "").startswith("AQ.") else self._json(400, ERROR_CLAVE)
            return False
        return True

    def do_GET(self):
        if not self.path.startswith("/v1beta/models") or not self._clave():
            return
        if "pageToken=pagina2" in self.path:
            return self._json(200, {"models": MODELOS[2:]})
        self._json(200, {"models": MODELOS[:2], "nextPageToken": "pagina2"})

    def do_POST(self):
        largo = int(self.headers.get("Content-Length") or 0)
        cuerpo = json.loads(self.rfile.read(largo) or b"{}")
        if not self._clave():
            return
        Manejador.peticiones[-1]["cuerpo"] = cuerpo
        if "no-existe" in self.path:
            return self._json(404, {"error": {"code": 404, "message": "models/no-existe is not found", "status": "NOT_FOUND"}})
        sistema = json.dumps(cuerpo.get("systemInstruction") or {}, ensure_ascii=False)
        pregunta = json.dumps(cuerpo.get("contents") or [], ensure_ascii=False)
        if "BLOQUEAR" in pregunta:
            eventos = [{"promptFeedback": {"blockReason": "SAFETY"}}]
        else:
            if "CREADOR DE DESAFÍOS" in sistema:
                texto = "```json\n" + json.dumps(DESAFIO, ensure_ascii=False) + "\n```"
            elif "RESOLUCIÓN DE PROBLEMAS" in sistema:
                texto = RAZONAMIENTO
            elif "AVANCE" in sistema:
                texto = ANALISIS
            else:
                texto = "Respuesta de Gemini de prueba."
            trozos = [texto[i:i + 40] for i in range(0, len(texto), 40)]
            eventos = [{"candidates": [{"content": {"role": "model", "parts": [{"text": "pienso en secreto", "thought": True}]}}]}]
            eventos += [{"candidates": [{"content": {"role": "model", "parts": [{"text": t}]}}]} for t in trozos]
            eventos.append({"candidates": [{"content": {"role": "model", "parts": [{"text": ""}]}, "finishReason": "STOP"}],
                            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20}})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for e in eventos:
            self.wfile.write(f"data: {json.dumps(e, ensure_ascii=False)}\r\n\r\n".encode())
            self.wfile.flush()


def arrancar(puerto: int = 0):
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{servidor.server_address[1]}/v1beta", servidor


if __name__ == "__main__":
    url, srv = arrancar(int(sys.argv[1]) if len(sys.argv) > 1 else 8791)
    print(url, flush=True)
    threading.Event().wait()
