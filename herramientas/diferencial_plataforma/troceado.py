"""Diferencial de knowledge/ingestion/semantic_chunker.py y structure_detector.py: Python puro (REFERENCIA) contra
Rust. Páginas al azar (espacios raros, \\r\\n, sangrías, frases enormes, código, fórmulas) y, si se pasan, PDF reales:
los mismos fragmentos, campo por campo (menos `created_at`; los símbolos como conjunto, porque Python los saca de un
`set` en orden al azar).

    .venv/bin/python herramientas/diferencial_plataforma/troceado.py [semilla] [vueltas] [libro.pdf ...]
"""
import copy, json, os, random, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _referencia  # noqa: E402
from _referencia import PRIG  # noqa: E402
sys.path.insert(0, PRIG)
sys.path.insert(0, os.path.join(PRIG, "backend"))
from backend.knowledge.ingestion import semantic_chunker as sn  # noqa: E402

d = tempfile.mkdtemp()
os.makedirs(os.path.join(d, "viejo_troceo"))
open(os.path.join(d, "viejo_troceo", "__init__.py"), "w").close()
for nombre in ("semantic_chunker", "structure_detector"):
    codigo = subprocess.run(["git", "-C", PRIG, "show", f"{_referencia.REFERENCIA}:backend/knowledge/ingestion/{nombre}.py"],
                            capture_output=True, text=True, check=True).stdout
    open(os.path.join(d, "viejo_troceo", nombre + ".py"), "w").write(codigo)
sys.path.insert(0, d)
from viejo_troceo import semantic_chunker as sv  # noqa: E402

semilla = int(sys.argv[1]) if len(sys.argv) > 1 else 1
N = int(sys.argv[2]) if len(sys.argv) > 2 else 100
R = random.Random(semilla)
fallos, cuentas = [], {}
PIEZAS = ["Hola", "mundo", "modelo", "Árbol", "ñandú", "Él", "x = y", "$a+b$", "$$", "\\alpha", "\\frac", "def f", "class A",
          "import os", "from x", "return", "for i in range", "torch.nn", "np.array", "Teorema", "proof", "Definición",
          "algoritmo", "Step 1", "ejemplo", "Ejercicio", "∂", "∑", "∫", "1.2", "Capítulo", "42", "İ", "ſ", "ﬁ",
          "a" * 90, "b" * 700]
SEPS = [" ", " ", " ", "  ", ". ", ": ", "? ", "! ", "\n", "\n\n", "\r\n", "\r\n\r\n", "\n   ", "\x1c", "\x1f", "\xa0",
        " ", "　", "\t", ".\n", ".\x1d", ". \n\n "]


def texto():
    return "".join(R.choice(PIEZAS) + R.choice(SEPS) for _ in range(R.randint(0, 120)))


def estructura():
    def sec():
        a = R.choice([None, 0, R.randint(1, 12)])
        return {"section_id": R.choice([None, "", f"s{R.randint(0, 9)}"]), "chapter_id": R.choice([None, "", f"c{R.randint(0, 9)}"]),
                "start_page": a, "end_page": R.choice([None, 0, (a or 0) + R.randint(0, 5)])}
    return {"sections": [sec() for _ in range(R.randint(0, 6))], "chapters": [sec() for _ in range(R.randint(0, 6))]}


def normal(fragmentos):
    salida = []
    for f in fragmentos:
        f = dict(f)
        f.pop("created_at", None)
        f["symbols"] = sorted(f["symbols"])
        salida.append(f)
    return salida


def comparar(nombre, a, b, ctx):
    cuentas[nombre] = cuentas.get(nombre, 0) + 1
    if a != b and len(fallos) < 10:
        fallos.append({"prueba": nombre, "ctx": str(ctx)[:400], "viejo": str(a)[:800], "nuevo": str(b)[:800]})


def simbolos_ok(viejo, nuevo):
    # más de 10 distintos: Python se queda con 10 cualesquiera del set; aquí con los 10 primeros
    for a, b in zip(viejo, nuevo):
        if len(a["symbols"]) == 10:
            a["symbols"] = b["symbols"] = None


def probar(doc, est, tope, etiqueta):
    va = normal(sv.SemanticChunker.chunk_document(copy.deepcopy(doc), copy.deepcopy(est), "src", tope))
    nu = normal(sn.SemanticChunker.chunk_document(copy.deepcopy(doc), copy.deepcopy(est), "src", tope))
    simbolos_ok(va, nu)
    comparar(f"fragmentar{etiqueta}", va, nu, (tope, est))


for _ in range(N):
    t = texto()
    tope = R.choice([1, 5, 20, 60, 200, 500, 2000])
    comparar("parrafos", sv.SemanticChunker._parrafos(t), sn.SemanticChunker._parrafos(t), t)
    comparar("partir", sv.SemanticChunker._partir(t, tope), sn.SemanticChunker._partir(t, tope), (tope, t))
    a = sv.StructureDetector.detect_structure(t)
    b = sn.StructureDetector.detect_structure(t)
    a["symbols"], b["symbols"] = sorted(a["symbols"]), sorted(b["symbols"])
    if len(a["symbols"]) == 10:
        a["symbols"] = b["symbols"] = None
    comparar("clasificar", a, b, t)
    doc = {"pages": [{"page_num": i + 1, "text": texto()} for i in range(R.randint(0, 8))]}
    probar(doc, estructura(), tope, "")

for ruta in sys.argv[3:]:
    from backend.knowledge.ingestion.pdf_parser import PDFParser
    from backend.knowledge.ingestion.toc_extractor import TOCExtractor
    doc = PDFParser.parse_document(ruta)
    est = TOCExtractor.extract_structure(doc, "src")
    for tope in (500, 150):
        probar(doc, est, tope, "_real")
    print("libro:", os.path.basename(ruta), len(doc["pages"]), "páginas")
print(json.dumps({"semilla": semilla, "cuentas": cuentas, "fallos": len(fallos)}, ensure_ascii=False))
for f in fallos:
    print(json.dumps(f, ensure_ascii=False))
