"""
Búsqueda web para el motor de IA. Encontrar los resultados (DuckDuckGo, con la biblioteca `ddgs` o su página
lite) sigue aquí, como herramienta; reordenarlos, descargar y leer las páginas en paralelo, la caché y el bloque
de contexto están en Rust (backend-rust/crates/prig-ia, web.rs), sin el GIL. El HTML se lee con html5ever.
"""
import os
import re
import json
import time
import hashlib
import urllib.parse
import requests
import warnings
from typing import List, Dict, Any, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings("ignore", category=RuntimeWarning, module="duckduckgo_search")

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from ddgs import DDGS
    HAS_DDGS = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        HAS_DDGS = True
    except ImportError:
        HAS_DDGS = False

def _rs():
    from nativo_rust import rust
    return rust().web


# Dominios oficiales organizados por ecosistema tecnológico
OFFICIAL_DOMAINS_BY_CATEGORY = {
    "python_data": [
        "docs.python.org", "numpy.org", "pandas.pydata.org", "scikit-learn.org",
        "pytorch.org", "tensorflow.org", "matplotlib.org", "scipy.org", "pypi.org"
    ],
    "web_frameworks": [
        "developer.mozilla.org", "fastapi.tiangolo.com", "flask.palletsprojects.com",
        "djangoproject.com", "react.dev", "nextjs.org", "vuejs.org", "nodejs.org"
    ],
    "devops_cloud": [
        "docs.docker.com", "kubernetes.io", "git-scm.com", "docs.github.com",
        "registry.terraform.io", "ansible.com"
    ],
    "academic_research": [
        "arxiv.org", "wikipedia.org", "paperswithcode.com"
    ],
    "code_repositories": [
        "github.com", "gitlab.com"
    ]
}

# Lista plana de dominios oficiales para matching rápido
ALL_OFFICIAL_DOMAINS = [domain for category in OFFICIAL_DOMAINS_BY_CATEGORY.values() for domain in category]

# Palabras clave que activan la auto-detección de búsqueda web
AUTO_SEARCH_TRIGGERS = [
    r"\b(cómo|como)\s+(hacer|usar|implementar|crear|configurar)\b",
    r"\b(ejemplo|tutorial|documentación|docs|oficial)\b",
    r"\b(error|exception|traceback|attributeerror|typeerror|importerror|valderror)\b",
    r"\b(novedades|versión|version|diferencia|vs|comparación)\b",
    r"\b(fastapi|python|pandas|numpy|pytorch|tensorflow|react|docker|kubernetes|flask|django|scikit-learn)\b",
    r"\b(sintaxis|método|metodo|función|funcion|clase|librería|libreria|paquete)\b"
]


class WebSearchCache:
    """ Sistema de caché local en disco para búsquedas y contenidos web (TTL de 24h) """

    def __init__(self, cache_dir: str = ".prig_web_cache", ttl_seconds: int = 86400):
        self.cache_dir = os.path.abspath(cache_dir)
        self.ttl_seconds = ttl_seconds
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_key(self, text: str) -> str:
        return hashlib.md5(text.strip().lower().encode("utf-8")).hexdigest()

    def get(self, query: str) -> Optional[Tuple[str, List[Dict[str, str]]]]:
        return _rs().cache_leer(self.cache_dir, query, float(self.ttl_seconds))

    def set(self, query: str, context: str, sources: List[Dict[str, str]]) -> None:
        _rs().cache_guardar(self.cache_dir, query, context, sources)


class WebSearchEngine:
    """ Motor de búsqueda web avanzado, rascado de documentación oficial y RAG con Re-Ranking """

    def __init__(self, max_results: int = 4, max_chars_per_page: int = 2500, timeout: int = 5, use_cache: bool = True):
        self.max_results = max_results
        self.max_chars_per_page = max_chars_per_page
        self.timeout = timeout
        self.cache = WebSearchCache() if use_cache else None
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def should_auto_search(self, prompt: str) -> bool:
        """ Evalúa si la consulta del usuario requiere información o documentación de internet """
        return _rs().pide_internet(prompt)

    def search_duckduckgo_ddgs(self, query: str) -> List[Dict[str, str]]:
        """ Búsqueda estructurada a través de DDGS """
        results = []
        if not HAS_DDGS:
            return results
        try:
            with DDGS() as ddgs:
                ddg_results = list(ddgs.text(query, max_results=self.max_results * 2))
                for item in ddg_results:
                    results.append({
                        "title": item.get("title", "Sin título"),
                        "href": item.get("href", ""),
                        "snippet": item.get("body", "")
                    })
        except Exception as e:
            print(f"⚠️ Aviso búsqueda DDGS: {e}")
        return results

    def search_duckduckgo_lite(self, query: str) -> List[Dict[str, str]]:
        """ Fallback de búsqueda raspando DuckDuckGo Lite HTML """
        results = []
        try:
            url = "https://lite.duckduckgo.com/lite/"
            data = {"q": query}
            res = requests.post(url, data=data, headers=self.headers, timeout=self.timeout)
            if res.status_code != 200:
                return results

            if HAS_BS4:
                soup = BeautifulSoup(res.text, "html.parser")
                links = soup.find_all("a", class_="result-link")
                snippets = soup.find_all("td", class_="result-snippet")

                for i in range(min(len(links), self.max_results * 2)):
                    title = links[i].get_text(strip=True)
                    href = links[i].get("href", "")
                    snippet = snippets[i].get_text(strip=True) if i < len(snippets) else ""
                    if href.startswith("//"):
                        href = "https:" + href
                    results.append({"title": title, "href": href, "snippet": snippet})
        except Exception as e:
            print(f"⚠️ Aviso búsqueda DDG Lite: {e}")
        return results

    def search_github_code_examples(self, query: str) -> List[Dict[str, str]]:
        """ Búsqueda orientada a encontrar ejemplos prácticos de código en GitHub """
        results = []
        github_query = f"{query} site:github.com"
        results = self.search_duckduckgo_ddgs(github_query)
        if not results:
            results = self.search_duckduckgo_lite(github_query)
        return results

    def score_and_rerank(self, query: str, items: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """ Re-Ranking: dominios oficiales y palabras de la consulta en título y resumen; sin URLs repetidas """
        return _rs().reordenar(query, list(items), self.max_results)

    def search(self, query: str, prefer_official: bool = True) -> List[Dict[str, str]]:
        """ Ejecuta búsqueda combinada con Re-Ranking de fuentes """
        search_query = query
        if prefer_official and not any(domain in query.lower() for domain in ["site:", "http"]):
            search_query = f"{query} official docs documentation"

        raw_results = self.search_duckduckgo_ddgs(search_query)
        if not raw_results:
            raw_results = self.search_duckduckgo_lite(search_query)

        # Si la consulta trata sobre código, buscar también en GitHub
        if any(w in query.lower() for w in ["ejemplo", "código", "codigo", "implementación", "github"]):
            github_results = self.search_github_code_examples(query)
            raw_results.extend(github_results)

        return self.score_and_rerank(query, raw_results)

    def fetch_url_content(self, url: str) -> str:
        """ Extrae y limpia el texto principal de una página web HTML """
        return _rs().leer_pagina(url or "", float(self.timeout), self.max_chars_per_page)

    def get_web_context(self, query: str) -> Tuple[str, List[Dict[str, str]]]:
        """ Busca en internet con caché local, Re-Ranking y extrae contenidos para el prompt de la IA """
        if self.cache:
            cached_data = self.cache.get(query)
            if cached_data:
                return cached_data[0], cached_data[1]
        search_results = self.search(query, prefer_official=True)
        if not search_results:
            return "", []
        # descargar y leer las páginas (en paralelo, en Rust) y armar el contexto
        context_str, sources_info = _rs().contexto(list(search_results), float(self.timeout), self.max_chars_per_page)
        if self.cache:
            self.cache.set(query, context_str, sources_info)
        return context_str, sources_info
