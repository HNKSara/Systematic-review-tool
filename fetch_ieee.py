# =============================================================
# fetch_ieee.py — Fetch papers from IEEE Xplore
# Requires a free API key from https://developer.ieee.org/
# IEEE API docs: https://developer.ieee.org/docs/read/IEEE_Xplore_API_Docs
# =============================================================

import time
import requests
from config import QUERY_GROUPS, START_YEAR, END_YEAR, MAX_RESULTS, IEEE_API_KEY, SEARCH_FIELDS

IEEE_API_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"


def _wrap_ieee(term: str, search_fields: dict) -> str:
    """Wrap a single term with IEEE Xplore field qualifier(s)."""
    if search_fields.get("all_fields"):
        return term                    # no qualifier = IEEE searches all fields

    use_title    = search_fields.get("title", True)
    use_abstract = search_fields.get("abstract", True)
    use_keywords = search_fields.get("keywords", True)

    parts = []
    if use_title:
        parts.append(f'("Document Title":{term})')
    if use_abstract:
        parts.append(f'(Abstract:{term})')
    if use_keywords:
        parts.append(f'("Index Terms":{term})')

    if not parts:
        return term                    # fallback: unqualified search
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"


def build_query(query_groups: list[list[str]], search_fields: dict = SEARCH_FIELDS) -> str:
    """Convert QUERY_GROUPS into IEEE Xplore boolean query syntax using SEARCH_FIELDS."""
    group_parts = []
    for group in query_groups:
        terms = [f'"{t}"' for t in group]
        wrapped = [_wrap_ieee(t, search_fields) for t in terms]
        group_parts.append("(" + " OR ".join(wrapped) + ")")
    return " AND ".join(group_parts)


def fetch(
    query_groups: list[list[str]] = QUERY_GROUPS,
    start_year: int = START_YEAR,
    end_year: int = END_YEAR,
    max_results: int = MAX_RESULTS,
    api_key: str = IEEE_API_KEY,
) -> list[dict]:
    """
    Fetch papers from IEEE Xplore and return a list of paper dicts.
    Each dict contains: title, abstract, authors, year, doi, url, source.
    """
    if api_key == "YOUR_IEEE_API_KEY" or not api_key:
        print("[IEEE] Skipping: no API key set. Add your key to config.py → IEEE_API_KEY.")
        return []

    query  = build_query(query_groups)
    papers = []
    start_record = 1
    batch_size = min(200, max_results)  # IEEE max per request is 200

    while len(papers) < max_results:
        params = {
            "apikey":       api_key,
            "querytext":    query,
            "start_year":   start_year,
            "end_year":     end_year,
            "max_records":  min(batch_size, max_results - len(papers)),
            "start_record": start_record,
            "sort_order":   "desc",
            "sort_field":   "publication_year",
        }

        response = None
        for attempt in range(5):
            try:
                response = requests.get(IEEE_API_URL, params=params, timeout=30)
            except requests.exceptions.RequestException as e:
                wait = 10 * (attempt + 1)
                print(f"[IEEE] Connection error: {e}. Waiting {wait}s before retry {attempt + 1}/5...")
                time.sleep(wait)
                continue
            print(
                f"  [IEEE] Request —"
                f"  querytext  : {params['querytext']}\n"
                f"               start_year : {params['start_year']}\n"
                f"               end_year   : {params['end_year']}\n"
                f"               max_records: {params['max_records']}"
            )
            if response.status_code == 401:
                print("[IEEE] Invalid API key. Check config.py → IEEE_API_KEY.")
                return papers
            if response.status_code == 403:
                print("[IEEE] Access forbidden (403). Your key may not be activated yet "
                      "(activation can take up to 24h) or the daily quota is exceeded.")
                return papers
            if response.status_code in (429, 503):
                wait = 30 * (attempt + 1)
                reason = "Rate limited" if response.status_code == 429 else "Service unavailable"
                print(f"[IEEE] {reason} ({response.status_code}). Waiting {wait}s before retry {attempt + 1}/5...")
                time.sleep(wait)
                continue
            break

        if response is None or response.status_code in (429, 503):
            print("[IEEE] All retries failed. Returning results collected so far.")
            break
        response.raise_for_status()

        data = response.json()
        articles = data.get("articles", [])
        total_found = data.get("total_records", 0)

        if not articles:
            break

        for article in articles:
            authors_list = [
                a.get("full_name", "")
                for a in article.get("authors", {}).get("authors", [])
            ]

            papers.append({
                "title":    article.get("title", ""),
                "abstract": article.get("abstract", ""),
                "authors":  ", ".join(authors_list),
                "year":     article.get("publication_year", 0),
                "doi":      article.get("doi", ""),
                "url":      article.get("html_url", ""),
                "source":   "IEEE",
            })

        start_record += len(articles)
        if start_record > total_found:
            break

        time.sleep(1)  # be polite to the API

    print(f"[IEEE] Retrieved {len(papers)} papers.")
    return papers


if __name__ == "__main__":
    from utils import run_fetcher
    from config import OUTPUT_FILE_IEEE
    run_fetcher(fetch, OUTPUT_FILE_IEEE)
