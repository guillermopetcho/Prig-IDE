"""
Base de conocimiento unificada: un solo SQLite con búsqueda de texto completa.

Por qué no vale el recuperador actual: BM25 y TF-IDF se reconstruyen en memoria
cargando TODOS los fragmentos cada vez. Con 100 libros son cientos de miles de
afirmaciones — minutos de arranque y gigas de RAM. Aquí se usa FTS5, el índice de
texto completo que SQLite trae de serie: consultas en milisegundos sobre millones de
filas, sin dependencias nuevas y sin reconstruir nada.

Los .prigpack son el formato de TRANSPORTE. Esto es el formato de CONSULTA.

El diseño gira sobre una idea: el concepto canónico. "Weight decay", "regularización
L2" y "ridge" son tres nombres de lo mismo; si cada libro guarda el suyo, cien libros
son cien islas. Aquí se unifican y se marca cuáles cruzan campos, porque un concepto
puente es lo que permite explicar deep learning apoyándose en el cálculo que el
alumno ya sabe.
"""

import os
import json
import sqlite3
import unicodedata
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

SCHEMA_VERSION = "3.1"

ARTICULOS = {"el", "la", "los", "las", "un", "una", "unos", "unas",
             "de", "del", "the", "a", "an", "of"}

# Palabras que aparecen en casi toda pregunta y en casi toda afirmación. Si entran
# en la consulta de texto, "cómo se cocina una paella" recupera el libro de cálculo
# por culpa de "como" y "una", y el tutor acaba citando a Apostol sobre arroz.
PALABRAS_VACIAS = ARTICULOS | {
    "que", "como", "cual", "cuales", "para", "por", "con", "sin", "sobre", "entre",
    "este", "esta", "esto", "esos", "esas", "cuando", "donde", "porque", "pero",
    "mas", "muy", "son", "ser", "estar", "hay", "tiene", "hace", "puede", "debe",
    "explicame", "explica", "explicar", "dime", "quiero", "necesito", "saber",
    "funciona", "significa", "diferencia", "ejemplo", "ayuda", "ayudame",
    "and", "for", "with", "what", "how", "why", "does", "can", "should", "explain",
}


def palabras_contenido(texto: str) -> List[str]:
    """ Las palabras de una consulta que de verdad discriminan.

    Se normalizan con la misma raíz que los conceptos, para que "gradientes" en la
    pregunta encuentre "gradiente" en el libro.
    """
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    salida, vistas = [], set()
    for palabra in re.findall(r"[a-z0-9_+#]{3,}", t):
        if palabra in PALABRAS_VACIAS:
            continue
        raiz = _raiz(palabra)
        if raiz not in vistas:
            vistas.add(raiz)
            salida.append(palabra)
    return salida


def normalizar_nombre(nombre: str) -> str:
    """ Forma canónica para comparar nombres de concepto.

    Sin acentos, sin artículos, sin plural y sin signos: así "La Regularización L2",
    "regularizacion l2" y "regularizaciones L2" colapsan en la misma clave.
    """
    t = unicodedata.normalize("NFD", (nombre or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    palabras = [p for p in t.split() if p and p not in ARTICULOS]
    return " ".join(_raiz(p) for p in palabras)


def _raiz(palabra: str) -> str:
    """ Raíz aproximada, aplicada IGUAL al singular y al plural.

    En español el plural es +s tras vocal y +es tras consonante, así que a partir
    del plural solo no se puede decidir: "redes" viene de "red" pero "gradientes"
    de "gradiente". La salida es recortar también la -e final, de modo que ambas
    formas caigan en la misma raíz aunque esa raíz no sea una palabra real:

        red / redes             -> red
        gradiente / gradientes  -> gradient
        capa / capas            -> capa
    """
    if len(palabra) <= 3:
        return palabra
    if palabra.endswith("es") and len(palabra) > 4:
        palabra = palabra[:-2]
    elif palabra.endswith("s") and len(palabra) > 3:
        palabra = palabra[:-1]
    if palabra.endswith("e") and len(palabra) > 3:
        palabra = palabra[:-1]
    return palabra


class UnionFind:
    """ Fusión de conceptos: si A es alias de B y B de C, los tres son uno.

    Es la estructura correcta para esto — resolver las cadenas de alias a mano
    acaba en errores de transitividad y en conceptos duplicados a medias.
    """

    def __init__(self):
        self.padre: Dict[str, str] = {}

    def buscar(self, x: str) -> str:
        self.padre.setdefault(x, x)
        raiz = x
        while self.padre[raiz] != raiz:
            raiz = self.padre[raiz]
        while self.padre[x] != raiz:      # compresión de camino
            self.padre[x], x = raiz, self.padre[x]
        return raiz

    def unir(self, a: str, b: str):
        ra, rb = self.buscar(a), self.buscar(b)
        if ra != rb:
            # El nombre más corto manda: suele ser el canónico ("gradiente" sobre
            # "gradiente de la funcion de coste")
            if len(rb) < len(ra):
                ra, rb = rb, ra
            self.padre[rb] = ra

    def grupos(self) -> Dict[str, List[str]]:
        salida: Dict[str, List[str]] = {}
        for x in list(self.padre):
            salida.setdefault(self.buscar(x), []).append(x)
        return salida


class KnowledgeBase:
    def __init__(self, ruta: Optional[str] = None):
        base = os.path.expanduser("~/.prig_books/.index")
        os.makedirs(base, exist_ok=True)
        self.ruta = os.path.abspath(ruta or os.path.join(base, "knowledge.db"))
        self._init_tablas()

    def conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.ruta)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")   # lecturas mientras se importa
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_tablas(self):
        with self.conectar() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS books (
                source_id TEXT PRIMARY KEY, title TEXT, domain TEXT,
                sha256 TEXT, pages INTEGER, model_used TEXT,
                claims_verified INTEGER DEFAULT 0, imported_at TEXT
            );

            -- Concepto canónico: una fila por IDEA, no por nombre
            CREATE TABLE IF NOT EXISTS concepts (
                concept_id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                norm TEXT NOT NULL,
                domains TEXT,          -- json: campos donde aparece
                is_bridge INTEGER DEFAULT 0,
                mentions INTEGER DEFAULT 0,
                books INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_concepts_norm ON concepts(norm);
            CREATE INDEX IF NOT EXISTS idx_concepts_bridge ON concepts(is_bridge);

            -- Cualquier nombre por el que se pueda pedir un concepto
            -- is_primary: si este era el nombre con el que el libro titulaba el
            -- concepto, o solo un alias suyo. Decide el nombre canónico: "ridge"
            -- no debe desbancar a "regularización L2" solo por ser más corto.
            -- La clave incluye el LIBRO a propósito: un alias es la atribución de
            -- un nombre por parte de un libro concreto. Sin source_id en la clave,
            -- reimportar un libro pisa la fila de otro que usaba el mismo nombre y
            -- se pierde en silencio quién llamaba así al concepto.
            CREATE TABLE IF NOT EXISTS aliases (
                norm TEXT NOT NULL, concept_id TEXT NOT NULL,
                surface TEXT, source_id TEXT NOT NULL DEFAULT '',
                is_primary INTEGER DEFAULT 0,
                PRIMARY KEY (norm, concept_id, source_id)
            );
            CREATE INDEX IF NOT EXISTS idx_alias_norm ON aliases(norm);

            CREATE TABLE IF NOT EXISTS claims (
                claim_id TEXT PRIMARY KEY, concept_id TEXT, source_id TEXT,
                domain TEXT, type TEXT, text TEXT, quote TEXT,
                page INTEGER, confidence REAL,
                code_language TEXT, latex TEXT, bridges_to TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_claims_concept ON claims(concept_id);
            CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(type);
            CREATE INDEX IF NOT EXISTS idx_claims_domain ON claims(domain);
            CREATE INDEX IF NOT EXISTS idx_claims_lang ON claims(code_language);

            -- Búsqueda de texto completa: es lo que hace instantánea la consulta.
            -- Tabla FTS independiente (no external-content) para poder BORRAR filas
            -- por claim_id al reimportar un libro sin dejar residuos en el índice.
            CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
                claim_id UNINDEXED, text, quote, concept_names,
                tokenize='unicode61'
            );

            CREATE TABLE IF NOT EXISTS relations (
                source_concept TEXT, target_concept TEXT, type TEXT,
                quote TEXT, source_id TEXT, page INTEGER,
                cross_domain INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_rel_source ON relations(source_concept);
            CREATE INDEX IF NOT EXISTS idx_rel_target ON relations(target_concept);
            CREATE INDEX IF NOT EXISTS idx_rel_cross ON relations(cross_domain);

            CREATE TABLE IF NOT EXISTS symbols (
                symbol TEXT, meaning TEXT, concept_id TEXT,
                source_id TEXT, domain TEXT, page INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_sym_symbol ON symbols(symbol);

            -- Estructura del libro. Es lo que convierte "estudia regularización" en
            -- "lee el capítulo 7, páginas 224-241": sin el índice, un plan de
            -- estudio no puede decirte dónde está lo que tienes que leer.
            CREATE TABLE IF NOT EXISTS sections (
                section_id TEXT PRIMARY KEY, source_id TEXT, chapter_id TEXT,
                numero TEXT, titulo TEXT, pagina_inicio INTEGER, pagina_fin INTEGER,
                es_capitulo INTEGER DEFAULT 0, temas TEXT, resumen TEXT,
                prerrequisitos TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sec_libro ON sections(source_id);
            CREATE INDEX IF NOT EXISTS idx_sec_pagina ON sections(pagina_inicio);

            -- Figuras y tablas con su pie: dicen dónde mirar cuando algo se
            -- entiende mejor viéndolo que leyéndolo.
            CREATE TABLE IF NOT EXISTS figures (
                source_id TEXT, label TEXT, caption TEXT, tipo TEXT, page INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_fig_libro ON figures(source_id);

            -- Preguntas que el propio texto permite responder. Son la materia
            -- prima de los ejercicios: salen del libro, no de la imaginación.
            CREATE TABLE IF NOT EXISTS questions (
                source_id TEXT, texto TEXT, page INTEGER, concept_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_preg_libro ON questions(source_id);

            -- Ficha del libro: lo que un flujo de agentes dedujo sobre él en
            -- conjunto (nivel, qué asume, ruta de lectura, qué no cubre).
            CREATE TABLE IF NOT EXISTS book_profiles (
                source_id TEXT PRIMARY KEY, json TEXT, built_at TEXT, modelos TEXT
            );

            -- Dosier precomputado: todo lo que se sabe de un concepto, ya reunido
            CREATE TABLE IF NOT EXISTS dossiers (
                concept_id TEXT PRIMARY KEY, json TEXT, built_at TEXT
            );

            CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT);
            """)
            self._migrar_aliases(c)
            c.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)",
                      (SCHEMA_VERSION,))
            c.commit()

    @staticmethod
    def _migrar_aliases(c):
        """ Lleva las bases antiguas al esquema actual de `aliases`.

        Se hace aquí y no con ALTER TABLE porque cambia la clave primaria, y SQLite
        no permite alterarla: hay que reconstruir la tabla y volcar las filas.
        """
        columnas = {r[1] for r in c.execute("PRAGMA table_info(aliases);")}
        if not columnas:
            return
        clave = [r[1] for r in c.execute("PRAGMA table_info(aliases);") if r[5]]
        if "is_primary" in columnas and clave == ["norm", "concept_id", "source_id"]:
            return
        c.executescript("""
            CREATE TABLE IF NOT EXISTS aliases_nueva (
                norm TEXT NOT NULL, concept_id TEXT NOT NULL,
                surface TEXT, source_id TEXT NOT NULL DEFAULT '',
                is_primary INTEGER DEFAULT 0,
                PRIMARY KEY (norm, concept_id, source_id)
            );""")
        primary = "is_primary" if "is_primary" in columnas else "0"
        c.execute(f"""INSERT OR REPLACE INTO aliases_nueva
                      SELECT norm, concept_id, surface, COALESCE(source_id,''), {primary}
                      FROM aliases;""")
        c.executescript("""
            DROP TABLE aliases;
            ALTER TABLE aliases_nueva RENAME TO aliases;
            CREATE INDEX IF NOT EXISTS idx_alias_norm ON aliases(norm);
        """)

    # ------------------------------------------------------------------
    # Resolución de nombres
    # ------------------------------------------------------------------

    def resolver(self, nombre: str) -> Optional[Dict[str, Any]]:
        """ De cualquier nombre o alias al concepto canónico """
        norm = normalizar_nombre(nombre)
        if not norm:
            return None
        with self.conectar() as c:
            fila = c.execute("""
                SELECT co.* FROM concepts co
                JOIN aliases a ON a.concept_id = co.concept_id
                WHERE a.norm = ? LIMIT 1;""", (norm,)).fetchone()
            if fila is None:
                fila = c.execute("SELECT * FROM concepts WHERE norm = ? LIMIT 1;",
                                 (norm,)).fetchone()
            if fila is None:
                # Último recurso: coincidencia por prefijo, para nombres largos
                fila = c.execute("SELECT * FROM concepts WHERE norm LIKE ? "
                                 "ORDER BY LENGTH(norm) LIMIT 1;", (f"{norm}%",)).fetchone()
        if fila is None:
            return None
        d = dict(fila)
        d["domains"] = json.loads(d.get("domains") or "[]")
        return d

    # ------------------------------------------------------------------
    # Búsqueda
    # ------------------------------------------------------------------

    def buscar(self, consulta: str, limite: int = 20,
               dominios: Optional[List[str]] = None,
               tipos: Optional[List[str]] = None,
               lenguaje: Optional[str] = None) -> List[Dict[str, Any]]:
        """ Búsqueda de texto completa sobre todas las afirmaciones.

        FTS5 devuelve en milisegundos aunque haya cientos de miles de filas, y `rank`
        ya es una puntuación BM25 calculada por SQLite.
        """
        contenido = palabras_contenido(consulta)
        if not contenido:
            return []
        terminos = " OR ".join(f'"{t}"' for t in contenido)

        sql = """SELECT c.*, bm25(claims_fts) AS rank
                 FROM claims_fts JOIN claims c ON c.claim_id = claims_fts.claim_id
                 WHERE claims_fts MATCH ?"""
        params: List[Any] = [terminos]
        if dominios:
            sql += f" AND c.domain IN ({','.join('?' * len(dominios))})"
            params += dominios
        if tipos:
            sql += f" AND c.type IN ({','.join('?' * len(tipos))})"
            params += tipos
        if lenguaje:
            sql += " AND c.code_language = ?"
            params.append(lenguaje)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limite)

        with self.conectar() as c:
            return [dict(f) for f in c.execute(sql, params).fetchall()]

    def afirmaciones_de(self, concept_id: str, tipos: Optional[List[str]] = None,
                        limite: int = 50) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM claims WHERE concept_id = ?"
        params: List[Any] = [concept_id]
        if tipos:
            sql += f" AND type IN ({','.join('?' * len(tipos))})"
            params += tipos
        sql += " ORDER BY confidence DESC LIMIT ?"
        params.append(limite)
        with self.conectar() as c:
            return [dict(f) for f in c.execute(sql, params).fetchall()]

    # ------------------------------------------------------------------
    # Grafo de prerrequisitos
    # ------------------------------------------------------------------

    def prerrequisitos(self, concept_id: str, profundidad: int = 3) -> List[Dict[str, Any]]:
        """ Cierre transitivo de lo que hay que saber antes, ordenado de base a cima.

        Es lo que permite responder "para entender backpropagation necesitas antes la
        regla de la cadena, y antes las derivadas" — aunque cada eslabón venga de un
        libro y de un campo distintos.
        """
        vistos: Set[str] = {concept_id}
        capas: List[List[str]] = []
        frontera = [concept_id]

        with self.conectar() as c:
            for _ in range(profundidad):
                if not frontera:
                    break
                marcadores = ",".join("?" * len(frontera))
                filas = c.execute(f"""
                    SELECT DISTINCT target_concept FROM relations
                    WHERE source_concept IN ({marcadores})
                      AND type IN ('REQUIRES','PART_OF');""", frontera).fetchall()
                nuevos = [f["target_concept"] for f in filas
                          if f["target_concept"] and f["target_concept"] not in vistos]
                if not nuevos:
                    break
                vistos.update(nuevos)
                capas.append(nuevos)
                frontera = nuevos

            salida = []
            for nivel, grupo in enumerate(reversed(capas), start=1):   # de base a cima
                for cid in grupo:
                    fila = c.execute("SELECT * FROM concepts WHERE concept_id = ?;",
                                     (cid,)).fetchone()
                    if fila:
                        d = dict(fila)
                        d["domains"] = json.loads(d.get("domains") or "[]")
                        d["nivel"] = nivel
                        salida.append(d)
        return salida

    def puentes(self, limite: int = 50) -> List[Dict[str, Any]]:
        """ Conceptos presentes en más de un campo: el as bajo la manga del tutor """
        with self.conectar() as c:
            filas = c.execute("""SELECT * FROM concepts WHERE is_bridge = 1
                                 ORDER BY books DESC, mentions DESC LIMIT ?;""",
                              (limite,)).fetchall()
        salida = []
        for f in filas:
            d = dict(f)
            d["domains"] = json.loads(d.get("domains") or "[]")
            salida.append(d)
        return salida

    def estadisticas(self) -> Dict[str, Any]:
        with self.conectar() as c:
            def n(t):
                return c.execute(f"SELECT COUNT(*) FROM {t};").fetchone()[0]
            por_dominio = {f["domain"]: f["n"] for f in c.execute(
                "SELECT domain, COUNT(*) n FROM books GROUP BY domain;").fetchall()}
            return {
                "ruta": self.ruta,
                "libros": n("books"), "conceptos": n("concepts"),
                "afirmaciones": n("claims"), "relaciones": n("relations"),
                "simbolos": n("symbols"), "alias": n("aliases"),
                "dosieres": n("dossiers"),
                "puentes": c.execute(
                    "SELECT COUNT(*) FROM concepts WHERE is_bridge=1;").fetchone()[0],
                "relaciones_cruzadas": c.execute(
                    "SELECT COUNT(*) FROM relations WHERE cross_domain=1;").fetchone()[0],
                "libros_por_dominio": por_dominio,
                "tamano_mb": round(os.path.getsize(self.ruta) / (1024 * 1024), 2)
                if os.path.exists(self.ruta) else 0,
            }
