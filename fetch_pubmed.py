# =============================================================
# fetch_pubmed.py — Fetch papers from PubMed (NCBI)
# API key is optional but increases rate limits.
# NCBI E-utilities docs: https://www.ncbi.nlm.nih.gov/books/NBK25499/
# =============================================================

import time
import requests
from config import QUERY_GROUPS, START_YEAR, END_YEAR, MAX_RESULTS, PUBMED_API_KEY, SEARCH_FIELDS

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# PubMed allows 3 req/sec without key, 10 req/sec with key
REQUEST_DELAY = 0.11 if PUBMED_API_KEY else 0.34


def _pubmed_tags(search_fields: dict) -> list[str]:
    """Return the PubMed field tags to apply to every term."""
    if search_fields.get("all_fields"):
        return ["[All Fields]"]       # search authors, journal, MeSH, full text, etc.

    use_title    = search_fields.get("title", True)
    use_abstract = search_fields.get("abstract", True)
    use_keywords = search_fields.get("keywords", True)

    tags = []
    if use_title and use_abstract:
        tags.append("[Title/Abstract]")
    elif use_title:
        tags.append("[Title]")
    elif use_abstract:
        tags.append("[Abstract]")

    if use_keywords:
        tags.append("[MeSH Terms]")

    return tags if tags else ["[Title/Abstract]"]  # fallback


def build_query(
    query_groups: list[list[str]],
    start_year: int,
    end_year: int,
    search_fields: dict = SEARCH_FIELDS,
) -> str:
    """Convert QUERY_GROUPS into PubMed query syntax using SEARCH_FIELDS."""
    tags = _pubmed_tags(search_fields)
    group_parts = []
    for group in query_groups:
        term_parts = []
        for term in group:
            field_terms = [f'"{term}"{tag}' for tag in tags]
            term_parts.append("(" + " OR ".join(field_terms) + ")" if len(field_terms) > 1 else field_terms[0])
        group_parts.append("(" + " OR ".join(term_parts) + ")")
    date_filter = f'("{start_year}/01/01"[PDAT]:"{end_year}/12/31"[PDAT])'
    return " AND ".join(group_parts) + f" AND {date_filter}"


def get_pmids(query: str, max_results: int) -> list[str]:
    """Run esearch and return a list of PubMed IDs."""
    params = {
        "db":       "pubmed",
        "term":     query,
        "retmax":   max_results,
        "retmode":  "json",
        "usehistory": "n",
    }
    if PUBMED_API_KEY:
        params["api_key"] = PUBMED_API_KEY

    response = requests.get(ESEARCH_URL, params=params, timeout=30)
    print(
        f"  [PubMed esearch] Request —"
        f"  term  : {params['term']}\n"
        f"                   retmax: {params['retmax']}"
    )
    response.raise_for_status()
    data = response.json()
    return data.get("esearchresult", {}).get("idlist", [])


def get_summaries(pmids: list[str]) -> dict:
    """Fetch eSummary (metadata) for a batch of PMIDs, returns dict keyed by PMID."""
    params = {
        "db":      "pubmed",
        "id":      ",".join(pmids),
        "retmode": "json",
    }
    if PUBMED_API_KEY:
        params["api_key"] = PUBMED_API_KEY

    response = requests.get(ESUMMARY_URL, params=params, timeout=30)
    print(
        f"  [PubMed esummary] Request —"
        f"  db    : {params['db']}\n"
        f"                    id count: {len(pmids)}"
    )
    response.raise_for_status()
    result = response.json().get("result", {})
    result.pop("uids", None)  # remove the uids list, keep only the records
    return result


def get_abstracts_batch(pmids: list[str]) -> dict:
    """Fetch abstracts for a list of PMIDs via efetch. Returns dict {pmid: abstract}."""
    import xml.etree.ElementTree as ET

    params = {
        "db":      "pubmed",
        "id":      ",".join(pmids),
        "rettype": "abstract",
        "retmode": "xml",
    }
    if PUBMED_API_KEY:
        params["api_key"] = PUBMED_API_KEY

    response = requests.get(EFETCH_URL, params=params, timeout=30)
    print(
        f"  [PubMed efetch] Request —"
        f"  db      : {params['db']}\n"
        f"                   rettype : {params['rettype']}\n"
        f"                   id count: {len(pmids)}"
    )
    response.raise_for_status()

    abstracts = {}
    root = ET.fromstring(response.content)
    for article in root.findall(".//PubmedArticle"):
        pmid_node = article.find(".//PMID")
        pmid = pmid_node.text if pmid_node is not None else ""
        abstract_nodes = article.findall(".//AbstractText")
        abstract = " ".join(
            (n.text or "") for n in abstract_nodes if n.text
        ).strip()
        abstracts[pmid] = abstract
    return abstracts


def fetch(
    query_groups: list[list[str]] = QUERY_GROUPS,
    start_year: int = START_YEAR,
    end_year: int = END_YEAR,
    max_results: int = MAX_RESULTS,
) -> list[dict]:
    """
    Fetch papers from PubMed and return a list of paper dicts.
    Each dict contains: title, abstract, authors, year, doi, url, source.
    """
    query = build_query(query_groups, start_year, end_year)
    try:
        pmids = get_pmids(query, max_results)
    except Exception as e:
        print(f"[PubMed] Failed to fetch paper IDs: {e}. Returning empty results.")
        return []
    if not pmids:
        print("[PubMed] No results found.")
        return []

    time.sleep(REQUEST_DELAY)

    # Fetch summaries and abstracts in batches of 20
    papers = []
    batch_size = 20
    for i in range(0, len(pmids), batch_size):
        batch = pmids[i : i + batch_size]
        try:
            summaries = get_summaries(batch)
        except Exception as e:
            print(f"[PubMed] Failed to fetch summaries for batch {i // batch_size + 1}: {e}. Skipping batch.")
            continue
        time.sleep(REQUEST_DELAY)
        try:
            abstracts = get_abstracts_batch(batch)
        except Exception as e:
            print(f"[PubMed] Failed to fetch abstracts for batch {i // batch_size + 1}: {e}. Papers will have no abstract.")
            abstracts = {}
        time.sleep(REQUEST_DELAY)

        for pmid in batch:
            summary = summaries.get(pmid, {})
            if not summary:
                continue

            title = summary.get("title", "")
            pub_date = summary.get("pubdate", "")
            year = int(pub_date[:4]) if pub_date and pub_date[:4].isdigit() else 0

            authors_list = [
                a.get("name", "")
                for a in summary.get("authors", [])
            ]

            doi = ""
            for id_obj in summary.get("articleids", []):
                if id_obj.get("idtype") == "doi":
                    doi = id_obj.get("value", "")
                    break

            papers.append({
                "title":    title,
                "abstract": abstracts.get(pmid, ""),
                "authors":  ", ".join(authors_list),
                "year":     year,
                "doi":      doi,
                "url":      f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "source":   "PubMed",
            })

    print(f"[PubMed] Retrieved {len(papers)} papers.")
    return papers


if __name__ == "__main__":
    from utils import run_fetcher
    from config import OUTPUT_FILE_PUBMED
    run_fetcher(fetch, OUTPUT_FILE_PUBMED)
