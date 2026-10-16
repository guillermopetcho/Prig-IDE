"""Diferencial de knowledge/indexing/bm25_index.py y vector_index.py: Python puro (REFERENCIA) contra Rust. Con
corpus al azar (y el catálogo real de la biblioteca, si se pasa, abierto solo para leer), las mismas búsquedas
tienen que dar los mismos fragmentos en el mismo orden y las mismas puntuaciones, bit a bit.

    .venv/bin/python herramientas/diferencial_plataforma/indices.py [semilla] [vueltas] [catalog.db]
"""
import importlib.util, json, os, random, sqlite3, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import PRIG  # noqa: E402
sys.path.insert(0, PRIG)
from backend.knowledge.indexing import bm25_index as bn, vector_index as vn  # noqa: E402

# las versiones de Python puro de la referencia
d = tempfile.mkdtemp()
for nombre in ("bm25_index", "vector_index"):
    codigo = subprocess.run(["git", "-C", PRIG, "show", f"{_referencia.REFERENCIA}:backend/knowledge/indexing/{nombre}.py"],
                            capture_output=True, text=True, check=True).stdout
    open(os.path.join(d, nombre + ".py"), "w").write(codigo.replace("from .db_catalog import DBCatalog", "DBCatalog = None"))
sys.path.insert(0, d)
import bm25_index as bv, vector_index as vv  # noqa: E402

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 60
R = random.Random(semilla)
fallos, cuentas = [], {}
PALABRAS = ["modelo", "red", "neuronal", "Gradiente", "gradiente", "descenso", "pérdida", "ñandú", "ΣΑΣ", "x_1", "2024",
            "learning", "rate", "árbol", "decisión", "İstanbul", "naïve", "café", "é", "²", "a", "de", "la"]


class Catalogo:
    def __init__(self, filas):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE chunks (chunk_id, source_id, chapter_id, section_id, content, content_type, page_start)")
        self.db.executemany("INSERT INTO chunks VALUES (?,?,?,?,?,?,?)", filas)

    def get_connection(self):
        class C:
            def __enter__(s): return self.db
            def __exit__(s, *a): return False
        return C()


def texto():
    return " ".join(R.choice(PALABRAS) for _ in range(R.randint(0, 40))) + R.choice(["", ".", "\n", " -- "])


def comparar(nombre, a, b, ctx):
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    ra = [(x[0]["chunk_id"], repr(x[1])) for x in a]
    rb = [(x[0]["chunk_id"], repr(x[1])) for x in b]
    if ra != rb and len(fallos) < 10:
        fallos.append({"prueba": nombre, "ctx": ctx, "viejo": str(ra)[:600], "nuevo": str(rb)[:600]})


def probar(cat, consultas, etiqueta):
    b_v, b_n = bv.BM25Index(cat), bn.BM25Index(cat)
    v_v, v_n = vv.VectorIndex(cat), vn.VectorIndex(cat)
    for q in consultas:
        k = R.choice([30, 5, 1000])
        comparar(f"bm25{etiqueta}", b_v.search(q, k), b_n.search(q, k), q)
        comparar(f"vectorial{etiqueta}", v_v.search(q, k), v_n.search(q, k), q)


for _ in range(N):
    filas = [(f"c{i}", "s", "ch", "se", texto(), "text", 1) for i in range(R.randint(0, 40))]
    probar(Catalogo(filas), [texto() for _ in range(5)], "")

if len(sys.argv) > 3:
    real = sqlite3.connect(f"file:{sys.argv[3]}?mode=ro", uri=True)
    real.row_factory = sqlite3.Row
    filas = [tuple(r) for r in real.execute("SELECT chunk_id, source_id, chapter_id, section_id, content, content_type, page_start FROM chunks")]
    print("fragmentos reales:", len(filas))
    probar(Catalogo(filas), ["descenso de gradiente", "random forest", "learning rate schedule", "pandas groupby", "función de pérdida",
                             "red neuronal convolucional", "overfitting regularization", "the", "a b c"], "_real")
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos)}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
