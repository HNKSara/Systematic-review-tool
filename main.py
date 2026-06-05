# =============================================================
# main.py — Orchestrator: runs all fetchers, deduplicates,
#            categorizes, and saves results to CSV.
# Run:  python main.py
# =============================================================

import sys
import datetime
import pathlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

import fetch_arxiv
import fetch_pubmed
import fetch_ieee
import fetch_scopus
from categorize import categorize_all, summarize
from config import (
    OUTPUT_FILE,
    OUTPUT_FILE_ARXIV, OUTPUT_FILE_PUBMED,
    OUTPUT_FILE_IEEE,  OUTPUT_FILE_SCOPUS,
    DUPLICATES_CSV, DUPLICATE_COLUMNS,
    RUN_SUMMARY_CSV, RUN_SUMMARY_COLUMNS,
)
from config import QUERY_GROUPS, START_YEAR, END_YEAR
from utils import Tee, compact_query, write_run_summary

LOGS_DIR    = pathlib.Path("logs")
RESULTS_DIR = pathlib.Path("results")
LOGS_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)


def _save_run_summary(
    db_counts:    dict[str, int],
    dup_papers:   list[dict],
) -> None:
    q = compact_query(QUERY_GROUPS)
    # Count duplicates per source so before/after are per-database
    from collections import Counter
    dup_per_source = Counter(p.get("source", "") for p in dup_papers)
    rows = [
        {
            "source":                   label,
            "query":                    q,
            "papers_found":             count,
            "total_before_dedup":       count,
            "total_after_dedup":        count - dup_per_source.get(label, 0),
            "duplicates_with_internal": dup_per_source.get(label, 0),
            "start_year":               START_YEAR,
            "end_year":                 END_YEAR,
        }
        for label, count in db_counts.items()
    ]
    write_run_summary(rows, RUN_SUMMARY_COLUMNS, RUN_SUMMARY_CSV, overwrite=True)


def deduplicate(papers: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Remove duplicate papers.
    Two papers are duplicates if they share the same DOI (non-empty)
    or if their titles are identical (case-insensitive).
    Returns (unique_papers, duplicate_papers).
    """
    seen_dois:   set[str] = set()
    seen_titles: set[str] = set()
    unique:     list[dict] = []
    duplicates: list[dict] = []

    for p in papers:
        doi   = p.get("doi", "").strip().lower()
        title = p.get("title", "").strip().lower()

        if doi and doi in seen_dois:
            duplicates.append(p)
            continue
        if title and title in seen_titles:
            duplicates.append(p)
            continue

        if doi:
            seen_dois.add(doi)
        if title:
            seen_titles.add(title)

        unique.append(p)

    return unique, duplicates


def _write_duplicates_csv(duplicates: list[dict]) -> None:
    """Write cross-database duplicates to Duplicates.csv (fresh file each main.py run)."""
    records = [
        {
            "database":       p.get("source", ""),
            "title":          p.get("title", ""),
            "doi":            p.get("doi", ""),
            "authors":        p.get("authors", ""),
            "year":           p.get("year", ""),
            "published_in":   p.get("source", ""),
            "duplicate_type": "cross-database duplicate",
        }
        for p in duplicates
    ]
    df = pd.DataFrame(records, columns=DUPLICATE_COLUMNS)
    try:
        df.to_csv(DUPLICATES_CSV, index=False, encoding="utf-8-sig")
        print(f"Saved {len(df)} cross-database duplicate(s) to '{DUPLICATES_CSV}'.")
    except PermissionError:
        print(f"WARNING: could not write '{DUPLICATES_CSV}' — file may be open in another program.")
    except Exception as e:
        print(f"WARNING: could not write '{DUPLICATES_CSV}': {e}")


def main() -> None:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path  = LOGS_DIR / f"run_{timestamp}.log"
    log_file  = open(log_path, "w", encoding="utf-8")
    sys.stdout = Tee(sys.__stdout__, log_file)

    try:
        print(f"Run started: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Log file:    {log_path}")
        print("=" * 55)
        print("Fetching papers from all databases in parallel...")
        print("=" * 55)

        # ── Run all fetchers in parallel (all are network I/O bound) ─
        _print_lock = threading.Lock()

        def _locked_fetch_and_save(fetcher, output_file, label):
            papers = categorize_all(fetcher.fetch())
            with _print_lock:
                try:
                    pd.DataFrame(papers).to_csv(output_file, index=False, encoding="utf-8-sig")
                    print(f"  [{label}] → saved to '{output_file}'")
                except Exception as e:
                    print(f"[{label}] WARNING: could not write '{output_file}': {e}")
                print("- " * 27)
            return label, papers

        sources = [
            (fetch_ieee,   OUTPUT_FILE_IEEE,   "IEEE"),
            (fetch_pubmed, OUTPUT_FILE_PUBMED, "PubMed"),
            (fetch_scopus, OUTPUT_FILE_SCOPUS, "Scopus"),
            (fetch_arxiv,  OUTPUT_FILE_ARXIV,  "ArXiv"),
        ]

        all_papers: list[dict] = []
        db_counts:  dict[str, int] = {}

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(_locked_fetch_and_save, f, o, l): l
                for f, o, l in sources
            }
            for future in as_completed(futures):
                _label = futures[future]
                try:
                    _label, _papers = future.result()
                    all_papers += _papers
                    db_counts[_label] = len(_papers)
                except Exception as e:
                    print(f"[{_label}] ERROR: {e}. Skipping this source and continuing.")
                    db_counts[_label] = 0

        print(f"\nTotal before deduplication: {len(all_papers)}")

        # ── Deduplicate ───────────────────────────────────────────
        unique_papers, dup_papers = deduplicate(all_papers)
        print(f"Total after  deduplication: {len(unique_papers)}")
        print(f"Cross-database duplicates:  {len(dup_papers)}")

        _write_duplicates_csv(dup_papers)
        _save_run_summary(db_counts, dup_papers)

        categorized = unique_papers

        # ── Summary ───────────────────────────────────────────────
        print("\n" + "=" * 55)
        print("Category distribution:")
        print("=" * 55)
        summarize(categorized)

        # ── Save to CSV ───────────────────────────────────────────
        df = pd.DataFrame(categorized)

        # Add a universal doi_url column for every paper that has a DOI
        df["doi_url"] = df["doi"].apply(
            lambda d: f"https://doi.org/{d.strip()}" if str(d).strip() else ""
        )

        # Mark all fetched papers as internal
        df["source_type"] = "internal"

        # Column order: source_type first, then identifiers → links → categories → abstract
        front_cols = ["source_type", "title", "authors", "year", "source", "doi", "doi_url", "url"]
        cat_cols   = [c for c in df.columns if c not in front_cols + ["abstract"]]
        back_cols  = ["abstract"]
        ordered    = [c for c in front_cols + cat_cols + back_cols if c in df.columns]
        df = df[ordered]

        df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
        print(f"\nSaved {len(df)} papers to '{OUTPUT_FILE}'.")
        print(f"\nRun finished: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        raise
    finally:
        sys.stdout = sys.__stdout__
        log_file.close()
        print(f"Log saved to '{log_path}'.")


if __name__ == "__main__":
    main()
