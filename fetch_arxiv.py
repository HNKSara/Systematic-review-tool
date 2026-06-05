# =============================================================
# fetch_arxiv.py — Fetch papers from ArXiv
# No API key required.
# ArXiv API docs: https://arxiv.org/help/api/user-manual
# =============================================================

import time
import requests
import xml.etree.ElementTree as ET
from config import QUERY_GROUPS, START_YEAR, END_YEAR, MAX_RESULTS, SEARCH_FIELDS

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = "http://www.w3.org/2005/Atom"


def _wrap_arxiv(term: str, search_fields: dict) -> str:
    """Wrap a single term with the appropriate ArXiv field prefix(es)."""
    if search_fields.get("all_fields"):
        return f"all:{term}"          # search across every field ArXiv indexes

    use_title    = search_fields.get("title", True)
    use_abstract = search_fields.get("abstract", True)

    if use_title and use_abstract:
        return f"(ti:{term} OR abs:{term})"
    if use_title:
        return f"ti:{term}"
    if use_abstract:
        return f"abs:{term}"
    return f"all:{term}"              # fallback


def build_query(query_groups: list[list[str]], search_fields: dict = SEARCH_FIELDS) -> str:
    """Convert QUERY_GROUPS into ArXiv query syntax using SEARCH_FIELDS."""
    group_parts = []
    for group in query_groups:
        terms = [f'"{t}"' if " " in t else t for t in group]
        wrapped = [_wrap_arxiv(t, search_fields) for t in terms]
        group_parts.append("(" + " OR ".join(wrapped) + ")")
    return " AND ".join(group_parts)


def parse_year(date_str: str) -> int:
    """Extract 4-digit year from an ArXiv date string like '2023-04-12T00:00:00Z'."""
    try:
        return int(date_str[:4])
    except (ValueError, TypeError):
        return 0


def fetch(
    query_groups: list[list[str]] = QUERY_GROUPS,
    start_year: int = START_YEAR,
    end_year: int = END_YEAR,
    max_results: int = MAX_RESULTS,
) -> list[dict]:
    """
    Fetch papers from ArXiv and return a list of paper dicts.
    Each dict contains: title, abstract, authors, year, doi, url, source.
    """
    query = build_query(query_groups)
    # ArXiv date filter must be appended as a submittedDate range
    date_filter = f"submittedDate:[{start_year}0101 TO {end_year}1231]"
    full_query = f"({query}) AND {date_filter}"

    papers = []
    batch_size = min(100, max_results)  # ArXiv max per request is 100
    start_index = 0

    while start_index < max_results:
        params = {
            "search_query": full_query,
            "start":        start_index,
            "max_results":  min(batch_size, max_results - start_index),
            "sortBy":       "submittedDate",
            "sortOrder":    "descending",
        }

        response = None
        for attempt in range(5):
            try:
                response = requests.get(ARXIV_API_URL, params=params, timeout=60)
            except requests.exceptions.ReadTimeout:
                wait = 20 * (attempt + 1)
                print(f"[ArXiv] Timeout. Waiting {wait}s before retry {attempt + 1}/5...")
                time.sleep(wait)
                continue
            print(
                f"  [ArXiv] Request —"
                f"  search_query: {params['search_query']}\n"
                f"                start       : {params['start']}\n"
                f"                max_results : {params['max_results']}"
            )
            if response.status_code in (429, 503):
                retry_after = response.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() \
                       else min(30 * (2 ** attempt), 300)  # 30, 60, 120, 240, 300
                reason = "Rate limited" if response.status_code == 429 else "Service unavailable"
                print(f"[ArXiv] {reason} ({response.status_code}). Waiting {wait}s before retry {attempt + 1}/5...")
                time.sleep(wait)
                continue
            break
        if response is None or response.status_code in (429, 503):
            print("[ArXiv] All retries failed. Returning results collected so far.")
            break
        response.raise_for_status()

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as e:
            print(f"[ArXiv] Failed to parse response XML: {e}. Skipping this batch.")
            start_index += batch_size
            continue
        entries = root.findall(f"{{{ATOM_NS}}}entry")

        if not entries:
            break

        for entry in entries:
            def text(tag):
                node = entry.find(f"{{{ATOM_NS}}}{tag}")
                return node.text.strip() if node is not None and node.text else ""

            year = parse_year(text("published"))
            if not (start_year <= year <= end_year):
                continue

            authors = [
                author.find(f"{{{ATOM_NS}}}name").text.strip()
                for author in entry.findall(f"{{{ATOM_NS}}}author")
                if author.find(f"{{{ATOM_NS}}}name") is not None
            ]

            # DOI link (arxiv may provide one)
            doi = ""
            for link in entry.findall(f"{{{ATOM_NS}}}link"):
                if link.attrib.get("title") == "doi":
                    doi = link.attrib.get("href", "")
                    break

            arxiv_url = text("id")

            papers.append({
                "title":    text("title").replace("\n", " "),
                "abstract": text("summary").replace("\n", " "),
                "authors":  ", ".join(authors),
                "year":     year,
                "doi":      doi,
                "url":      arxiv_url,
                "source":   "ArXiv",
            })

        start_index += len(entries)
        if len(entries) < batch_size:
            break

        time.sleep(3)   # ArXiv polite-access guideline: ~1 req/3s

    print(f"[ArXiv] Retrieved {len(papers)} papers.")
    return papers


if __name__ == "__main__":
    from utils import run_fetcher
    from config import OUTPUT_FILE_ARXIV
    run_fetcher(fetch, OUTPUT_FILE_ARXIV)
