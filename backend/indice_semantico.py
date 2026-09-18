"""
Índice semántico de conceptos: elegir bien QUÉ se le da al modelo.

El problema que resuelve no es de compresión sino de puntería. Medido sobre la base
de pruebas, la búsqueda por palabras acertaba el 90 % de las veces pero metía en el
contexto un 38 % de tokens de conceptos que no venían a cuento. Ese material no es
neutro: ocupa presupuesto y compite por la atención del modelo con lo que sí importa.

La causa es que el solapamiento de palabras no es relevancia. A la pregunta «¿cómo sé
hacia dónde mover los pesos para bajar el error?», BM25 puntúa MEJOR a
«regularización L2» que a «gradiente», porque la palabra «pesos» aparece más veces en
las afirmaciones sobre regularización. Un umbral sobre BM25 se quedaría con el
concepto equivocado. Es un fallo semántico y hace falta una herramienta semántica.

Dos decisiones que salieron de medir, no de suponer:

  · EL MODELO ES MULTILINGÜE. `nomic-embed-text` acertó 4 de 7 con preguntas en
    castellano y 6 de 7 con las mismas preguntas traducidas al inglés: el problema
    era el idioma. `bge-m3` acierta 6 de 7 en castellano, con un margen entre el
    primero y el segundo tres veces mayor.
  · EL EMBEBEDOR VA EN CPU. En una tarjeta de 6 GB no caben el generador (4,7 GB) y
    el embebedor (1,2 GB) a la vez: Ollama expulsa uno, y cada consulta pagaría
    unos 11 segundos de recargas. En CPU tarda 72 ms por pregunta y el generador no
    se mueve de la GPU. Con RAM de sobra, es gratis.
"""

import os
import json
import math
import time
import struct
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from knowledge_base import KnowledgeBase

MODELO_POR_DEFECTO = "bge-m3"
# Por debajo de esta fracción de la mejor puntuación, el concepto se descarta.
# Medido: con 0,95 la precisión sube del 62 % al 89 % y el ruido baja del 38 % al
# 18 %. Con 0,90 la precisión se queda en el 73 %.
UMBRAL_RELATIVO = 0.95
MAX_CONCEPTOS = 5


class IndiceSemantico:
    def __init__(self, kb: Optional[KnowledgeBase] = None,
                 modelo: str = MODELO_POR_DEFECTO,
                 base_url: str = "http://localhost:11434",
                 en_cpu: bool = True):
        self.kb = kb or KnowledgeBase()
        self.modelo = modelo
        self.base = base_url.rstrip("/")
        self.en_cpu = en_cpu
        self._cache: Optional[Dict[str, List[float]]] = None
        self._crear_tabla()

    def _crear_tabla(self):
        with self.kb.conectar() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS vectores (
                concept_id TEXT PRIMARY KEY, vector BLOB, dimension INTEGER,
                modelo TEXT, indexado_en TEXT);""")
            c.commit()

    # ==================================================================
    # Llamada al embebedor
    # ==================================================================

    def disponible(self) -> bool:
        """ ¿Está el modelo de embeddings descargado?

        Se comprueba antes de usarlo porque todo esto es OPCIONAL: sin él, la
        búsqueda por palabras sigue funcionando igual que antes. Media biblioteca
        indexada y media sin indexar también tiene que funcionar.
        """
        try:
            with urllib.request.urlopen(f"{self.base}/api/tags", timeout=5) as r:
                nombres = {m["name"] for m in json.load(r).get("models", [])}
        except Exception:
            return False
        modelo = self._ajustes()["modelo"]
        return any(n == modelo or n.startswith(modelo + ":") for n in nombres)

    def _ajustes(self) -> Dict[str, Any]:
        """ Modelo, dimensiones y truncado elegidos en Modelos → Embeddings """
        try:
            from ollama_opciones import config
            e = config().embeddings()
        except Exception:
            e = {}
        return {"modelo": e.get("modelo") or self.modelo, "dimensiones": e.get("dimensiones"),
                "truncar": e.get("truncar", True)}

    def embeber(self, textos: List[str], timeout: int = 600) -> List[List[float]]:
        if not textos:
            return []
        ajustes = self._ajustes()
        cuerpo = {"model": ajustes["modelo"], "input": textos, "keep_alive": "30m"}
        if ajustes["dimensiones"]:
            cuerpo["dimensions"] = ajustes["dimensiones"]
        if not ajustes["truncar"]:
            cuerpo["truncate"] = False
        if self.en_cpu:
            # Forzar CPU es lo que permite que el generador no se mueva de la GPU
            cuerpo["options"] = {"num_gpu": 0}
        req = urllib.request.Request(f"{self.base}/api/embed",
                                     data=json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r).get("embeddings") or []

    # ==================================================================
    # Construir el índice
    # ==================================================================

    def indexar(self, compilador=None, lote: int = 64) -> Dict[str, Any]:
        """ Embebe el bloque compilado de cada concepto.

        Se embebe el bloque compilado y no la prosa original porque ya contiene lo
        mismo en menos texto; medido, la calidad de recuperación es idéntica (6 de 7
        en ambos casos) y el índice se construye antes.
        """
        if not self.disponible():
            return {"ok": False, "motivo": f"'{self.modelo}' no está descargado. "
                                           f"Instálalo con: ollama pull {self.modelo}"}
        if compilador is None:
            from contexto_modelo import CompiladorContexto
            compilador = CompiladorContexto(self.kb)

        with self.kb.conectar() as c:
            conceptos = [dict(r) for r in c.execute(
                "SELECT concept_id, canonical_name FROM concepts WHERE mentions > 0;")]
        if not conceptos:
            return {"ok": True, "conceptos": 0, "segundos": 0.0}

        textos, ids = [], []
        for x in conceptos:
            bloque = compilador.bloque(x["concept_id"])
            if not bloque:
                compilado = compilador.compilar_concepto(x["concept_id"])
                bloque = (compilador.render_concepto(compilado) if compilado
                          else x["canonical_name"])
            textos.append(bloque)
            ids.append(x["concept_id"])

        t0 = time.time()
        vectores: List[List[float]] = []
        for i in range(0, len(textos), lote):
            vectores += self.embeber(textos[i:i + lote])
        if len(vectores) != len(ids):
            return {"ok": False, "motivo": "el embebedor devolvió menos vectores "
                                           "de los pedidos"}

        ahora = datetime.now().isoformat()
        with self.kb.conectar() as c:
            c.execute("DELETE FROM vectores;")
            for cid, v in zip(ids, vectores):
                c.execute("INSERT OR REPLACE INTO vectores VALUES (?,?,?,?,?);",
                          (cid, _empaquetar(v), len(v), self._ajustes()["modelo"], ahora))
            c.commit()
        self._cache = None
        return {"ok": True, "conceptos": len(ids), "dimension": len(vectores[0]),
                "segundos": round(time.time() - t0, 1), "modelo": self.modelo,
                "en_cpu": self.en_cpu}

    # ==================================================================
    # Consultar
    # ==================================================================

    def _vectores(self) -> Dict[str, List[float]]:
        if self._cache is None:
            with self.kb.conectar() as c:
                try:
                    filas = c.execute("SELECT concept_id, vector FROM vectores;").fetchall()
                except Exception:
                    filas = []
            self._cache = {f["concept_id"]: _desempaquetar(f["vector"]) for f in filas}
        return self._cache

    def hay_indice(self) -> bool:
        return bool(self._vectores())

    def puntuar(self, pregunta: str,
                concept_ids: Optional[List[str]] = None) -> List[Tuple[float, str]]:
        """ Cuánto se parece cada concepto a la pregunta, de más a menos """
        vectores = self._vectores()
        if not vectores:
            return []
        candidatos = ([(cid, vectores[cid]) for cid in concept_ids if cid in vectores]
                      if concept_ids else list(vectores.items()))
        if not candidatos:
            return []
        try:
            qv = self.embeber([pregunta], timeout=60)[0]
        except Exception:
            return []
        # Otro modelo u otras dimensiones que las del índice: comparar vectores de
        # tamaños distintos daría basura. Sin resultado, se usa la búsqueda por palabras.
        if len(qv) != len(candidatos[0][1]):
            return []
        return sorted(((_coseno(qv, v), cid) for cid, v in candidatos), reverse=True)

    def filtrar(self, pregunta: str, concept_ids: List[str],
                umbral: float = UMBRAL_RELATIVO,
                maximo: int = MAX_CONCEPTOS) -> Optional[List[str]]:
        """ De una lista de candidatos, los que de verdad vienen a cuento.

        Devuelve None si no se puede decidir (sin índice, sin modelo, error de red):
        quien llama sigue entonces con su lista original. Una mejora opcional no
        puede convertirse en un punto de fallo.
        """
        if len(concept_ids) <= 1:
            return None
        puntuados = self.puntuar(pregunta, concept_ids)
        if not puntuados:
            return None
        mejor = puntuados[0][0]
        if mejor <= 0:
            return None
        elegidos = [cid for s, cid in puntuados if s >= mejor * umbral][:maximo]
        return elegidos or [puntuados[0][1]]

    def buscar(self, pregunta: str, limite: int = 5,
               umbral: float = UMBRAL_RELATIVO) -> List[Dict[str, Any]]:
        """ Conceptos parecidos a la pregunta, sin partir de candidatos.

        Para cuando la búsqueda por palabras no encuentra nada: ahí una pregunta
        parafraseada que no comparte vocabulario con el libro no tiene otra forma
        de llegar a su concepto.
        """
        puntuados = self.puntuar(pregunta)
        if not puntuados:
            return []
        mejor = puntuados[0][0]
        salida = []
        with self.kb.conectar() as c:
            for s, cid in puntuados[:limite]:
                if s < mejor * umbral:
                    break
                f = c.execute("SELECT * FROM concepts WHERE concept_id = ?;",
                              (cid,)).fetchone()
                if f:
                    salida.append({**dict(f), "parecido": round(s, 3)})
        return salida

    def estado(self) -> Dict[str, Any]:
        with self.kb.conectar() as c:
            try:
                fila = c.execute("""SELECT COUNT(*) n, MAX(indexado_en) cuando,
                                           MAX(modelo) modelo, MAX(dimension) dim
                                    FROM vectores;""").fetchone()
            except Exception:
                fila = None
        ajustes = self._ajustes()
        indexado_con = None
        with self.kb.conectar() as c:
            try:
                f = c.execute("SELECT modelo, dimension FROM vectores LIMIT 1;").fetchone()
                indexado_con = {"modelo": f["modelo"], "dimension": f["dimension"]} if f else None
            except Exception:
                indexado_con = None
        return {
            "modelo": ajustes["modelo"],
            "dimensiones_pedidas": ajustes["dimensiones"],
            "truncar": ajustes["truncar"],
            "indexado_con": indexado_con,
            "necesita_reindexar": bool(indexado_con and (
                indexado_con["modelo"] != ajustes["modelo"]
                or (ajustes["dimensiones"] and indexado_con["dimension"] != ajustes["dimensiones"]))),
            "descargado": self.disponible(),
            "en_cpu": self.en_cpu,
            "conceptos_indexados": fila["n"] if fila else 0,
            "dimension": fila["dim"] if fila else 0,
            "indexado_en": fila["cuando"] if fila else None,
        }


# ===========================================================================
# Los vectores se guardan en binario: un float por cuatro bytes en vez de los
# veinte que ocuparía escrito en JSON. Con mil conceptos de 1024 dimensiones son
# 4 MB contra 20.
# ===========================================================================

def _empaquetar(v: List[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


def _desempaquetar(b: bytes) -> List[float]:
    return list(struct.unpack(f"{len(b) // 4}f", b))


def _coseno(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    producto = na = nb = 0.0
    for x, y in zip(a, b):
        producto += x * y
        na += x * x
        nb += y * y
    return producto / math.sqrt(na * nb) if na and nb else 0.0
