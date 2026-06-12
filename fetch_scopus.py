# =============================================================
# fetch_scopus.py — Fetch papers from Elsevier Scopus
# Requires an API key from https://dev.elsevier.com/
# You MUST be on an institutional/university network (or VPN).
# Scopus API docs: https://dev.elsevier.com/documentation/ScopusSearchAPI.wadl
# =============================================================

import time
import requests
from config import QUERY_GROUPS, START_YEAR, END_YEAR, MAX_RESULTS, SCOPUS_API_KEY, SEARCH_FIELDS

SCOPUS_API_URL      = "https://api.elsevier.com/content/search/scopus"
SCOPUS_ABSTRACT_URL = "https://api.elsevier.com/content/abstract/eid/"


def fetch_abstract(eid: str, headers: dict) -> str:
    """Fetch full abstract for one paper using the Scopus Abstract Retrieval API."""
    if not eid:
        return ""
    try:
        response = requests.get(
            SCOPUS_ABSTRACT_URL + eid,
            headers=headers,
            params={"field": "dc:description"},
            timeout=30,
        )
        if response.status_code != 200:
            return ""
        data = response.json()
        return (
            data.get("abstracts-retrieval-response", {})
                .get("coredata", {})
                .get("dc:description", "")
        )
    except Exception:
        return ""


def _scopus_field_wrapper(terms_str: str, search_fields: dict) -> str:
    """Wrap a group of OR'd terms in Scopus field function(s)."""
    if search_fields.get("all_fields"):
        return f"ALL({terms_str})"    # searches title, abstract, keywords, authors, affiliations, etc.

    use_title    = search_fields.get("title", True)
    use_abstract = search_fields.get("abstract", True)
    use_keywords = search_fields.get("keywords", True)

    # Use the convenient TITLE-ABS-KEY() shorthand when all three are active
    if use_title and use_abstract and use_keywords:
        return f"TITLE-ABS-KEY({terms_str})"

    parts = []
    if use_title:
        parts.append(f"TITLE({terms_str})")
    if use_abstract:
        parts.append(f"ABS({terms_str})")
    if use_keywords:
        parts.append(f"KEY({terms_str})")

    return "(" + " OR ".join(parts) + ")" if parts else f"TITLE-ABS-KEY({terms_str})"


def build_query(
    query_groups: list[list[str]],
    start_year: int,
    end_year: int,
    search_fields: dict = SEARCH_FIELDS,
) -> str:
    """Convert QUERY_GROUPS into Scopus query syntax using SEARCH_FIELDS."""
    group_parts = []
    for group in query_groups:
        terms_str = " OR ".join(f'"{t}"' for t in group)
        group_parts.append(_scopus_field_wrapper(terms_str, search_fields))

    year_filter = f"PUBYEAR > {start_year - 1} AND PUBYEAR < {end_year + 1}"
    return " AND ".join(group_parts) + f" AND {year_filter}"


def fetch(
    query_groups: list[list[str]] = QUERY_GROUPS,
    start_year: int = START_YEAR,
    end_year: int = END_YEAR,
    max_results: int = MAX_RESULTS,
    api_key: str = SCOPUS_API_KEY,
) -> list[dict]:
    """
    Fetch papers from Scopus and return a list of paper dicts.
    Each dict contains: title, abstract, authors, year, doi, url, source.
    Abstracts are fetched individually via the Abstract Retrieval API — the Scopus
    Search API does not return abstracts no matter which fields are requested.
    """
    if api_key == "YOUR_SCOPUS_API_KEY" or not api_key:
        print("[Scopus] Skipping: no API key set. Add your key to config.py → SCOPUS_API_KEY.")
        return []

    query = build_query(query_groups, start_year, end_year)
    headers = {
        "X-ELS-APIKey": api_key,
        "Accept":        "application/json",
    }

    papers = []
    start_index = 0
    # Request up to 200 per batch; the API caps it at the tier limit automatically.
    batch_size = 200

    while len(papers) < max_results:
        params = {
            "query":  query,
            "count":  min(batch_size, max_results - len(papers)),
            "start":  start_index,
            # dc:description fetches the abstract in the same batch request —
            # eliminates the need for one individual Abstract Retrieval call per paper.
            "field":  "dc:title,dc:creator,prism:coverDate,prism:doi,prism:url,eid",
        }

        try:
            response = requests.get(SCOPUS_API_URL, headers=headers, params=params, timeout=30)
        except requests.exceptions.RequestException as e:
            print(f"[Scopus] Connection error: {e}. Returning results collected so far.")
            break
        print(
            f"  [Scopus] Request —"
            f"  query: {params['query']}\n"
            f"                count: {params['count']}\n"
            f"                start: {params['start']}"
        )

        if response.status_code == 401:
            print("[Scopus] Unauthorized. Check your API key and institutional access.")
            break
        if response.status_code in (429, 503):
            wait = 60 if response.status_code == 429 else 30
            reason = "Rate limited" if response.status_code == 429 else "Service unavailable"
            print(f"[Scopus] {reason} ({response.status_code}). Waiting {wait}s...")
            time.sleep(wait)
            continue
        response.raise_for_status()

        data = response.json()
        search_results = data.get("search-results", {})
        entries = search_results.get("entry", [])
        total_found = int(search_results.get("opensearch:totalResults", 0))

        if not entries or entries == [{"@_fa": "true", "error": "Result set was empty"}]:
            break

        for entry in entries:
            pub_date = entry.get("prism:coverDate", "")
            year = int(pub_date[:4]) if pub_date and pub_date[:4].isdigit() else 0
            eid  = entry.get("eid", "")

            # The Search API doesn't return abstracts regardless of requested fields —
            # fetch each one individually via the Abstract Retrieval API.
            abstract = fetch_abstract(eid, headers)
            time.sleep(0.5)

            papers.append({
                "title":    entry.get("dc:title", ""),
                "abstract": abstract,
                "authors":  entry.get("dc:creator", ""),
                "year":     year,
                "doi":      entry.get("prism:doi", ""),
                "url":      (
                    f"https://doi.org/{entry['prism:doi']}"
                    if entry.get("prism:doi")
                    else f"https://www.scopus.com/record/display.uri?eid={eid}"
                ),
                "source":   "Scopus",
            })

        start_index += len(entries)
        if start_index >= total_found:
            break

        time.sleep(1)

    print(f"[Scopus] Retrieved {len(papers)} papers.")
    return papers


if __name__ == "__main__":
    from utils import run_fetcher
    from config import OUTPUT_FILE_SCOPUS
    run_fetcher(fetch, OUTPUT_FILE_SCOPUS)
