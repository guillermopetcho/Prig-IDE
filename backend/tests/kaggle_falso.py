"""
Servidor falso de la API de Kaggle para las pruebas (sin red y sin cuenta).

Imita lo medido contra www.kaggle.com/api/v1, con los campos repetidos que devuelve
(«title», «titleNullable», «hasTitle»):

  · kernels/list y competitions/*  piden cuenta (401 sin ella o con el token MALO_…)
  · kernels/pull, datasets/*       funcionan sin cuenta
  · datasets/download y competitions/data/download-all  devuelven un zip
  · la competición «con-reglas» responde 403 al descargar (reglas sin aceptar)

    python kaggle_falso.py 8792     lo deja escuchando en ese puerto
"""

import io
import json
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TOKEN_MALO = "MALO_token_12345678901234"

TRAIN = "PassengerId,Survived,Pclass,Sex,Age,Cabin\n" + "\n".join(
    f"{i},{i % 2},{1 + i % 3},{'male' if i % 3 else 'female'},{'' if i % 5 == 0 else 20 + i},{'' if i % 4 else 'C' + str(i)}"
    for i in range(1, 41)) + "\n"

IPYNB = {
    "cells": [
        {"cell_type": "markdown", "source": ["# Titanic\n", "Predecir quién sobrevive."]},
        {"cell_type": "code", "source": ["import pandas as pd\n", "df = pd.read_csv('/kaggle/input/titanic/train.csv')"], "outputs": []},
        {"cell_type": "code", "source": "df.head()", "outputs": []},
        {"cell_type": "code", "source": "df2 = pd.read_csv('../input/titanic-dataset/Titanic-Dataset.csv')", "outputs": []},
        {"cell_type": "code", "source": "print('fin')", "outputs": []},
    ],
    "metadata": {}, "nbformat": 4, "nbformat_minor": 4,
}


def _repetido(**campos):
    """ Como la API real: cada campo también en «xNullable» y «hasX» """
    salida = {}
    for k, v in campos.items():
        salida[k] = v
        salida[k + "Nullable"] = v
        salida["has" + k[0].upper() + k[1:]] = v is not None
    return salida


NOTEBOOKS = {
    "a/uno": {"title": "Uno", "author": "a", "totalVotes": 10},
    "alexisbcook/titanic-tutorial": {"title": "Titanic Tutorial", "author": "alexisbcook", "totalVotes": 30000},
}

LISTA_KERNELS = [
    {"ref": "a/uno", "title": "Uno", "author": "a", "totalVotes": 10, "language": "python", "kernelType": "notebook"},
    {"ref": "b/dos", "title": "Dos", "author": "b", "totalVotes": 5, "language": "r", "kernelType": "notebook"},
    {"ref": "c/tres", "title": "Tres", "author": "c", "totalVotes": 1, "language": "python", "kernelType": "script"},
]

DATASET = _repetido(ref="yasserh/titanic-dataset", title="Titanic Dataset", subtitle="Titanic Survival Prediction Dataset",
                    ownerName="M Yasser H", creatorName="M Yasser H", totalBytes=61194, usabilityRating=1.0,
                    licenseName="CC0: Public Domain", voteCount=1200, downloadCount=90000, viewCount=500000,
                    kernelCount=800, lastUpdated="2021-12-24T14:53:08Z", currentVersionNumber=1,
                    thumbnailImageUrl=None, url="https://www.kaggle.com/datasets/yasserh/titanic-dataset",
                    description="### Descripción\n\nEl hundimiento del **Titanic**.\n\n- 891 pasajeros")
DATASET["tags"] = [{"name": "tabular"}, {"name": "beginner"}]
DATASET_2 = _repetido(ref="z/casas", title="Casas", subtitle="Precios", ownerName="z", totalBytes=10 ** 9,
                      usabilityRating=0.5, voteCount=3, downloadCount=10, kernelCount=0, lastUpdated="2025-01-01T00:00:00Z")

COMPETICIONES = [
    _repetido(ref="https://www.kaggle.com/competitions/titanic", url="https://www.kaggle.com/competitions/titanic",
              title="Titanic - Machine Learning from Disaster", description="Start here! Predict survival on the Titanic",
              organizationName="Kaggle", category="Getting Started", reward="Knowledge", teamCount=9914,
              deadline="2030-01-01T00:00:00Z", evaluationMetric="Categorization Accuracy", maxTeamSize=10,
              maxDailySubmissions=10, userHasEntered=False, thumbnailImageUrl=None),
    _repetido(ref="https://www.kaggle.com/competitions/con-reglas", url="https://www.kaggle.com/competitions/con-reglas",
              title="Con reglas", description="Hay que aceptar las reglas", category="Featured", reward="$10,000",
              teamCount=12, deadline="2027-01-01T00:00:00Z", evaluationMetric="RMSE"),
]


def _zip(archivos):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nombre, contenido in archivos.items():
            z.writestr(nombre, contenido)
    return buf.getvalue()


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

    def _zip(self, datos):
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _con_cuenta(self):
        cab = self.headers.get("Authorization") or ""
        if not cab or cab.endswith(TOKEN_MALO):
            self._json(401, {"code": 401, "message": "Unauthenticated"})
            return False
        return True

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        ruta = u.path.split("/api/v1/", 1)[-1]
        Manejador.peticiones.append({"ruta": ruta, "params": q, "auth": bool(self.headers.get("Authorization"))})
        if ruta == "kernels/list":
            return self._con_cuenta() and self._json(200, LISTA_KERNELS)
        if ruta == "kernels/pull":
            ref = f"{q.get('userName')}/{q.get('kernelSlug')}"
            if ref not in NOTEBOOKS:
                return self._json(404, {})
            meta = {"ref": ref, "currentVersionNumber": 5, "language": "python", "kernelType": "notebook",
                    "competitionDataSources": ["titanic"], "datasetDataSources": ["yasserh/titanic-dataset"],
                    "kernelDataSources": [], **NOTEBOOKS[ref]}
            return self._json(200, {"metadata": meta, "blob": {"source": json.dumps(IPYNB), "kernelType": "notebook"}})
        if ruta == "datasets/list":
            return self._json(200, [DATASET, DATASET_2] if q.get("page", "1") == "1" else [])
        if ruta == "datasets/view/yasserh/titanic-dataset":
            return self._json(200, DATASET)
        if ruta == "datasets/view/z/casas":
            return self._json(200, DATASET_2)
        if ruta == "datasets/list/yasserh/titanic-dataset":
            return self._json(200, {"datasetFiles": [{"name": "Titanic-Dataset.csv", "totalBytes": len(TRAIN), "columns": []}],
                                    "nextPageToken": ""})
        if ruta == "datasets/list/z/casas":
            return self._json(200, {"datasetFiles": [{"name": "casas.csv", "totalBytes": 10 ** 9}], "nextPageToken": ""})
        if ruta == "datasets/download/yasserh/titanic-dataset":
            return self._zip(_zip({"Titanic-Dataset.csv": TRAIN}))
        if ruta.startswith("competitions/"):
            if not self._con_cuenta():
                return
            if ruta == "competitions/list":
                return self._json(200, COMPETICIONES if q.get("page", "1") == "1" else [])
            if ruta.startswith("competitions/data/list/"):
                return self._json(200, {"files": [{"name": "train.csv", "totalBytes": len(TRAIN)},
                                                  {"name": "test.csv", "totalBytes": 100}]})
            if ruta == "competitions/data/download-all/titanic":
                return self._zip(_zip({"train.csv": TRAIN, "test.csv": "PassengerId\n1\n"}))
            if ruta == "competitions/data/download-all/con-reglas":
                return self._json(403, {"code": 403, "message": "You must accept this competition's rules"})
        self._json(404, {})


def arrancar(puerto: int = 0):
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{servidor.server_address[1]}/api/v1", servidor


if __name__ == "__main__":
    url, srv = arrancar(int(sys.argv[1]) if len(sys.argv) > 1 else 8792)
    print(url, flush=True)
    threading.Event().wait()
