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
        key = self._get_key(query)
        filepath = os.path.join(self.cache_dir, f"{key}.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if time.time() - data.get("timestamp", 0) < self.ttl_seconds:
                    return data.get("context", ""), data.get("sources", [])
            except Exception as e:
                print(f"⚠️ Error leyendo caché de búsqueda: {e}")
        return None

    def set(self, query: str, context: str, sources: List[Dict[str, str]]) -> None:
        key = self._get_key(query)
        filepath = os.path.join(self.cache_dir, f"{key}.json")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump({
                    "query": query,
                    "timestamp": time.time(),
                    "context": context,
                    "sources": sources
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Error guardando en caché de búsqueda: {e}")


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
        if not prompt or len(prompt.strip()) < 4:
            return False
        
        prompt_lower = prompt.lower()
        for pattern in AUTO_SEARCH_TRIGGERS:
            if re.search(pattern, prompt_lower):
                return True
        return False

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
        """ Algoritmo de Re-Ranking que asigna puntuaciones de relevancia según dominios oficiales y densidad de palabras clave """
        query_words = set(re.findall(r"\w+", query.lower()))

        def compute_score(item: Dict[str, str]) -> float:
            score = 0.0
            href = item.get("href", "").lower()
            title = item.get("title", "").lower()
            snippet = item.get("snippet", "").lower()

            # Puntuación por dominio oficial (+50 puntos)
            if any(domain in href for domain in ALL_OFFICIAL_DOMAINS):
                score += 50.0

            # Coincidencia de palabras en título y snippet
            title_words = set(re.findall(r"\w+", title))
            snippet_words = set(re.findall(r"\w+", snippet))

            title_matches = len(query_words.intersection(title_words))
            snippet_matches = len(query_words.intersection(snippet_words))

            score += title_matches * 10.0
            score += snippet_matches * 3.0

            # Penalización a sitios agregadores de anuncios/SEO genérico
            if any(bad in href for bad in ["geeksforgeeks.org", "javatpoint.com"]):
                score -= 10.0

            return score

        scored_items = sorted(items, key=compute_score, reverse=True)
        
        # Eliminar URLs duplicadas
        seen_urls = set()
        unique_items = []
        for item in scored_items:
            url = item.get("href")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_items.append(item)

        return unique_items[:self.max_results]

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
        if not url or not url.startswith("http"):
            return ""
        try:
            res = requests.get(url, headers=self.headers, timeout=self.timeout)
            if res.status_code != 200:
                return ""

            if HAS_BS4:
                soup = BeautifulSoup(res.text, "html.parser")
                for element in soup(["script", "style", "nav", "footer", "header", "form", "aside", "noscript", "svg"]):
                    element.extract()

                lines = []
                for elem in soup.find_all(["h1", "h2", "h3", "p", "pre", "code", "li"]):
                    txt = elem.get_text(strip=True)
                    if txt:
                        if elem.name in ["h1", "h2", "h3"]:
                            lines.append(f"\n### {txt}")
                        elif elem.name in ["pre", "code"]:
                            lines.append(f"```\n{txt}\n```")
                        else:
                            lines.append(txt)

                full_text = "\n".join(lines)
                full_text = re.sub(r'\n{3,}', '\n\n', full_text)
                return full_text[:self.max_chars_per_page]
            else:
                clean_text = re.sub(r'<[^>]+>', ' ', res.text)
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                return clean_text[:self.max_chars_per_page]
        except Exception as e:
            print(f"⚠️ Error leyendo contenido de {url}: {e}")
            return ""

    def get_web_context(self, query: str) -> Tuple[str, List[Dict[str, str]]]:
        """ Busca en internet con caché local, Re-Ranking y extrae contenidos para el prompt de la IA """
        # 1. Verificar si existe en caché local
        if self.cache:
            cached_data = self.cache.get(query)
            if cached_data:
                return cached_data[0], cached_data[1]

        # 2. Ejecutar búsqueda web y Re-Ranking
        search_results = self.search(query, prefer_official=True)
        if not search_results:
            return "", []

        sources_info = []
        fetched_pages = []

        # Emparejar cada resultado con SU url: usar dos listas y zip() las desalineaba
        # en cuanto un resultado venía sin href, atribuyendo el contenido a otra fuente.
        fetchable = [r for r in search_results if r.get("href")]

        # 3. Extraer páginas web en paralelo
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_url = {executor.submit(self.fetch_url_content, item["href"]): item for item in fetchable}
            for future in future_to_url:
                item = future_to_url[future]
                try:
                    content = future.result()
                    if content and len(content.strip()) > 50:
                        domain = urllib.parse.urlparse(item["href"]).netloc
                        sources_info.append({
                            "title": item["title"],
                            "url": item["href"],
                            "domain": domain,
                            "snippet": item.get("snippet", "")
                        })
                        fetched_pages.append(f"📌 **Fuente [{domain}]**: {item['title']}\n**URL**: {item['href']}\n\n{content}\n")
                except Exception as e:
                    print(f"Error extrayendo URL: {e}")

        if not fetched_pages:
            for item in search_results:
                domain = urllib.parse.urlparse(item["href"]).netloc if item.get("href") else "Web"
                sources_info.append({
                    "title": item.get("title", "Sin título"),
                    "url": item.get("href", ""),
                    "domain": domain,
                    "snippet": item.get("snippet", "")
                })
                fetched_pages.append(
                    f"📌 **Fuente [{domain}]**: {item.get('title', 'Sin título')}\n"
                    f"**URL**: {item.get('href', '')}\n**Resumen**: {item.get('snippet', '')}\n"
                )

        context_str = "\n---\n🌐 **INFORMACIÓN Y DOCUMENTACIÓN OFICIAL DE INTERNET (RAG)**:\n" + "\n---\n".join(fetched_pages) + "\n---\n"

        # 4. Guardar resultado en caché local
        if self.cache:
            self.cache.set(query, context_str, sources_info)

        return context_str, sources_info
