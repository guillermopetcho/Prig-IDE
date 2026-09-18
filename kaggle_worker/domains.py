"""
Taxonomía de dominios y sus puentes.

Seis dominios no son seis bibliotecas separadas: el valor está justamente en los
CONCEPTOS PUENTE, los que aparecen en más de uno. El gradiente es análisis
matemático y es descenso de gradiente; una convolución es física de señales y es
capa convolucional; la complejidad algorítmica es teoría y es por qué tu bucle en
Python tarda.

Cuando el tutor explica algo, un concepto puente le permite anclar lo nuevo en algo
que el alumno ya sabe de otro campo. Eso es el as bajo la manga.
"""

DOMAINS = {
    "math": {
        "name": "Matemáticas",
        "icon": "fa-square-root-variable",
        # Bilingüe a propósito: los libros técnicos se titulan casi siempre en
        # inglés ("Deep Learning", "Effective Modern C++"), y clasificar por el
        # nombre del archivo era lo primero que se intentaba. Con listas solo en
        # español todos puntuaban cero y caían en el dominio por defecto.
        "keywords": ["álgebra", "cálculo", "derivada", "integral", "matriz", "vector",
                     "probabilidad", "estadística", "teorema", "demostración", "norma",
                     "autovalor", "gradiente", "optimización convexa", "serie", "límite",
                     "matemáticas", "análisis matemático", "geometría", "topología",
                     "ecuación diferencial",
                     "mathematics", "math", "calculus", "algebra", "linear algebra",
                     "derivative", "integral", "matrix", "probability", "statistics",
                     "theorem", "proof", "eigenvalue", "convex optimization",
                     "analysis", "geometry", "topology", "differential equation",
                     "discrete mathematics", "number theory"],
    },
    "physics": {
        "name": "Física",
        "icon": "fa-atom",
        "keywords": ["física", "energía", "fuerza", "onda", "campo", "partícula",
                     "termodinámica", "entropía", "mecánica", "cuántica", "señal",
                     "frecuencia", "conservación", "hamiltoniano", "lagrangiano",
                     "relatividad", "electromagnetismo", "óptica",
                     "physics", "energy", "force", "wave", "particle",
                     "thermodynamics", "entropy", "mechanics", "quantum", "signal",
                     "frequency", "hamiltonian", "lagrangian", "relativity",
                     "electromagnetism", "optics", "statistical mechanics"],
    },
    "cpp": {
        "name": "C++",
        "icon": "fa-code",
        "keywords": ["puntero", "referencia", "plantilla", "template", "stl", "raii",
                     "constructor", "destructor", "memoria", "stack", "heap",
                     "sobrecarga", "compilador", "cabecera",
                     "c++", "cpp", "pointer", "reference", "smart pointer",
                     "move semantics", "modern c++", "metaprogramming", "compiler",
                     "header", "standard library", "overload", "concurrency",
                     "undefined behavior"],
    },
    "python": {
        "name": "Python",
        "icon": "fa-brands fa-python",
        "keywords": ["lista", "diccionario", "comprensión", "generador", "decorador",
                     "numpy", "pandas", "iterador", "contexto", "excepción", "módulo",
                     "python", "dict", "list comprehension", "generator", "decorator",
                     "iterator", "context manager", "exception", "module", "package",
                     "asyncio", "type hint", "dataclass", "matplotlib", "scipy",
                     "fluent python", "pythonic"],
    },
    "machine_learning": {
        "name": "Machine Learning",
        "icon": "fa-diagram-project",
        "keywords": ["regresión", "clasificación", "sobreajuste", "validación cruzada",
                     "característica", "entrenamiento", "supervisado", "clustering",
                     "árbol de decisión", "svm", "métrica", "sesgo", "varianza",
                     "aprendizaje automático", "aprendizaje máquina", "no supervisado",
                     "machine learning", "statistical learning", "pattern recognition",
                     "regression", "classification", "overfitting", "cross validation",
                     "feature", "supervised", "unsupervised", "decision tree",
                     "random forest", "gradient boosting", "bias", "variance",
                     "data mining", "predictive", "scikit"],
    },
    "deep_learning": {
        "name": "Deep Learning",
        "icon": "fa-brain",
        "keywords": ["red neuronal", "redes neuronales", "capa oculta", "activación",
                     "backpropagation", "retropropagación", "tensor", "perceptron",
                     "convolución", "transformer", "atención", "embedding", "dropout",
                     "optimizador", "época", "lote", "gradiente descendente",
                     "aprendizaje profundo",
                     "deep learning", "neural network", "neural networks", "deep neural",
                     "hidden layer", "activation", "convolutional", "cnn", "rnn", "lstm",
                     "attention", "self-attention", "pytorch", "tensorflow", "keras",
                     "fine-tuning", "large language model", "generative", "diffusion"],
    },
}
# Dependencias declaradas: A sostiene a B. Dirigen el orden pedagógico y permiten
# decir "para entender esto necesitas antes aquello de este otro campo".
DOMAIN_EDGES = [
    ("math", "physics"),
    ("math", "machine_learning"),
    ("math", "deep_learning"),
    ("physics", "deep_learning"),          # señales, energía, difusión
    ("python", "machine_learning"),
    ("python", "deep_learning"),
    ("cpp", "deep_learning"),              # núcleos de cálculo, rendimiento
    ("machine_learning", "deep_learning"),
]

# Conceptos que sabemos de antemano que cruzan campos. Sirven de semilla para la
# resolución: si dos libros de dominios distintos usan uno de estos nombres, es la
# misma idea aunque el texto no lo diga.
KNOWN_BRIDGES = {
    "gradiente":            ["math", "deep_learning"],
    "derivada":             ["math", "deep_learning"],
    "regla de la cadena":   ["math", "deep_learning"],
    "matriz":               ["math", "machine_learning", "deep_learning"],
    "producto escalar":     ["math", "physics", "deep_learning"],
    "convolución":          ["math", "physics", "deep_learning"],
    "entropía":             ["physics", "machine_learning", "deep_learning"],
    "distribución de probabilidad": ["math", "machine_learning"],
    "optimización":         ["math", "machine_learning", "deep_learning"],
    "descenso de gradiente":["math", "machine_learning", "deep_learning"],
    "vector":               ["math", "physics", "deep_learning"],
    "tensor":               ["math", "physics", "deep_learning"],
    "norma":                ["math", "machine_learning"],
    "autovalor":            ["math", "machine_learning"],
    "transformada de fourier": ["math", "physics", "deep_learning"],
    "complejidad algorítmica": ["cpp", "python", "machine_learning"],
    "memoria":              ["cpp", "python"],
    "array":                ["cpp", "python", "deep_learning"],
    "paralelismo":          ["cpp", "python", "deep_learning"],
    "regularización":       ["math", "machine_learning", "deep_learning"],
}

CODE_LANGUAGES = ["python", "cpp", "pseudocode", "math", "none"]


def domain_valido(d: str) -> bool:
    return d in DOMAINS


def _normalizar(texto: str) -> str:
    """ Minúsculas, sin acentos y con los separadores convertidos en espacios.

    Sin esto, "Redes_Neuronales.md" no casaba con la palabra clave "red neuronal"
    y un libro de deep learning acababa clasificado como machine learning.
    """
    import re as _re
    import unicodedata as _ud
    t = _ud.normalize("NFD", texto.lower())
    t = "".join(c for c in t if _ud.category(c) != "Mn")
    t = _re.sub(r"[_\-./]+", " ", t)
    return _re.sub(r"\s+", " ", t).strip()


def _casa(clave: str, blob: str) -> bool:
    """ Coincidencia tolerante al plural: "redes neuronales" casa con "red neuronal" """
    clave = _normalizar(clave)
    if clave in blob:
        return True
    partes = clave.split()
    if not partes:
        return False
    # Cada palabra en singular o plural, en orden y contiguas
    import re as _re
    patron = r"\s+".join(_re.escape(p) + r"(?:es|s)?" for p in partes)
    return bool(_re.search(patron, blob))


def sugerir_dominio(texto: str, nombre_archivo: str = "") -> str:
    """ Propuesta de dominio por palabras clave. El usuario confirma o corrige:
    adivinar mal el dominio de un libro contamina todo lo que salga de él. """
    blob_titulo = _normalizar(nombre_archivo)
    blob_texto = _normalizar(texto[:8000])

    puntos = {}
    for d, info in DOMAINS.items():
        # El título pesa más: es la declaración de intenciones del autor
        en_titulo = sum(1 for k in info["keywords"] if _casa(k, blob_titulo))
        en_texto = sum(1 for k in info["keywords"] if _casa(k, blob_texto))
        puntos[d] = en_titulo * 5 + en_texto

    mejor = max(puntos, key=puntos.get)
    return mejor if puntos[mejor] > 0 else "machine_learning"


def sugerir_dominio_con_confianza(texto: str, nombre_archivo: str = "") -> dict:
    """ Igual que `sugerir_dominio`, pero diciendo si la propuesta vale algo.

    Devolver el dominio por defecto sin más es engañoso: parece una clasificación
    y es un encogimiento de hombros. Quien revisa cien libros necesita saber cuáles
    mirar, y son exactamente los que salen con `seguro=False`.
    """
    puntos = puntuar_dominios(texto, nombre_archivo)
    orden = sorted(puntos.items(), key=lambda kv: -kv[1])
    mejor, punto_mejor = orden[0]
    segundo = orden[1][1] if len(orden) > 1 else 0
    if punto_mejor == 0:
        return {"dominio": "machine_learning", "puntos": 0, "seguro": False,
                "motivo": "ninguna palabra clave coincide; es solo el valor por defecto"}
    if punto_mejor - segundo < 2:
        return {"dominio": mejor, "puntos": punto_mejor, "seguro": False,
                "motivo": f"muy parejo con {orden[1][0]} ({punto_mejor} vs {segundo})"}
    return {"dominio": mejor, "puntos": punto_mejor, "seguro": True, "motivo": ""}


def puntuar_dominios(texto: str, nombre_archivo: str = "") -> dict:
    """ Puntuación de todos los dominios, para poder enseñar la duda al usuario """
    blob_titulo = _normalizar(nombre_archivo)
    blob_texto = _normalizar(texto[:8000])
    return {d: sum(1 for k in info["keywords"] if _casa(k, blob_titulo)) * 5 +
               sum(1 for k in info["keywords"] if _casa(k, blob_texto))
            for d, info in DOMAINS.items()}


def dominios_relacionados(dominio: str) -> list:
    """ Dominios conectados en cualquier dirección, para expandir una búsqueda """
    rel = set()
    for a, b in DOMAIN_EDGES:
        if a == dominio:
            rel.add(b)
        elif b == dominio:
            rel.add(a)
    return sorted(rel)


def distancia_dominios(a: str, b: str) -> int:
    """ Saltos entre dos dominios en el grafo. 0 mismo, 1 vecino, 2 con escala.
    Sirve para ordenar: una fuente del mismo campo pesa más que una lejana. """
    if a == b:
        return 0
    visitados, frontera, saltos = {a}, [a], 0
    while frontera and saltos < 4:
        saltos += 1
        siguiente = []
        for nodo in frontera:
            for vecino in dominios_relacionados(nodo):
                if vecino == b:
                    return saltos
                if vecino not in visitados:
                    visitados.add(vecino)
                    siguiente.append(vecino)
        frontera = siguiente
    return 99
