# =============================================================
# merge_external.py — Merge CSVs from other_resources/ into
#                     papers.csv, tagging each row as internal
#                     or external via the source_type column.
#
# Usage:  python merge_external.py
#
# Reads all *.csv files from other_resources/.
# Deduplicates against results/papers.csv (by DOI, then title).
# Appends new non-duplicate rows back into results/papers.csv.
# Writes every detected duplicate to results/Duplicates.csv.
# Column names in external CSVs are auto-mapped to the canonical
# set via synonym matching; unmatched columns are left empty.
# Every run is logged to logs/merge_YYYYMMDD_HHMMSS.log.
# =============================================================

import sys
import datetime
import pathlib
import pandas as pd
from config import (
    DUPLICATES_CSV, DUPLICATE_COLUMNS, OUTPUT_FILE,
    RUN_SUMMARY_CSV, RUN_SUMMARY_COLUMNS,
)
from config import QUERY_GROUPS, START_YEAR, END_YEAR
from utils import Tee, compact_query, write_run_summary

LOGS_DIR        = pathlib.Path("logs")
RESULTS_DIR     = pathlib.Path("results")
OTHER_RESOURCES = pathlib.Path("other_resources")
PAPERS_CSV      = pathlib.Path(OUTPUT_FILE)
_DUPLICATES_CSV = pathlib.Path(DUPLICATES_CSV)

# Canonical column order (must match main.py's front_cols + cat_cols + abstract)
# source_type is always first: "internal" for fetched papers, "external" for imported ones.
CANONICAL_COLUMNS = [
    "source_type",
    "title", "authors", "year", "source", "doi", "doi_url", "url",
    "trustworthiness_property", "healthcare_area", "agent_architecture",
    "abstract",
]

# Synonym map: canonical_name → list of known aliases (lower-cased, stripped)
# Extend EXTERNAL_COLUMN_MAP in user_settings.py (or config.py) to add your own mappings.
_DEFAULT_SYNONYMS: dict[str, list[str]] = {
    "title":                    ["title", "paper title", "article title", "document title", "paper_title", "article_title", "document_title", "name"],
    "authors":                  ["authors", "author", "author(s)", "creator", "creators", "by"],
    "year":                     ["year", "publication year", "pub_year", "pub year", "published year", "date", "publication_year"],
    "source":                   ["source", "journal", "venue", "publisher", "database", "db", "publication", "conference", "journal title", "journal_title"],
    "doi":                      ["doi", "digital object identifier", "doi number"],
    "doi_url":                  ["doi_url", "doi url", "doi link", "doi_link"],
    "url":                      ["url", "link", "webpage", "web", "full text link", "full_text_link", "access link"],
    "trustworthiness_property": ["trustworthiness_property", "trustworthiness", "trust property", "trust_property"],
    "healthcare_area":          ["healthcare_area", "healthcare area", "medical area", "health area", "clinical area"],
    "agent_architecture":       ["agent_architecture", "agent architecture", "architecture", "agent type", "agent_type"],
    "abstract":                 ["abstract", "summary", "description", "paper abstract"],
}



def _load_user_synonym_overrides() -> dict[str, list[str]]:
    """Return EXTERNAL_COLUMN_MAP from config if defined, else {}."""
    try:
        import config  # type: ignore
        overrides = getattr(config, "EXTERNAL_COLUMN_MAP", {})
        if not isinstance(overrides, dict):
            print(f"WARNING: EXTERNAL_COLUMN_MAP in config must be a dict "
                  f"(got {type(overrides).__name__}). Ignoring.")
            return {}
        bad = {k: v for k, v in overrides.items() if not isinstance(v, list)}
        if bad:
            print(f"WARNING: EXTERNAL_COLUMN_MAP values must be lists. "
                  f"Ignoring bad keys: {list(bad.keys())}")
            overrides = {k: v for k, v in overrides.items() if isinstance(v, list)}
        return overrides
    except ImportError:
        return {}
    except Exception as e:
        print(f"WARNING: could not load EXTERNAL_COLUMN_MAP from config: {e}. Ignoring.")
        return {}


def _build_synonym_lookup(extra: dict[str, list[str]]) -> dict[str, str]:
    """
    Build a flat lookup: lowercased_alias → canonical_name.
    User-supplied extra mappings override defaults for the same canonical key.
    """
    merged = {k: list(v) for k, v in _DEFAULT_SYNONYMS.items()}
    for canonical, aliases in extra.items():
        merged.setdefault(canonical, [])
        merged[canonical] = aliases + merged[canonical]

    lookup: dict[str, str] = {}
    for canonical, aliases in merged.items():
        for alias in aliases:
            lookup[alias.lower().strip()] = canonical
    return lookup


def _map_columns(
    df: pd.DataFrame,
    lookup: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    """
    Rename df columns to canonical names where a synonym match exists.
    Returns (mapped_df, rename_map, unmapped_columns).
    Columns with no match are dropped; missing canonical columns are added as empty.
    """
    rename_map: dict[str, str] = {}
    unmapped:   list[str]      = []

    # Detect collisions: two source columns mapping to the same canonical name
    canonical_targets: dict[str, list[str]] = {}
    for col in df.columns:
        canonical = lookup.get(col.lower().strip())
        if canonical:
            canonical_targets.setdefault(canonical, []).append(col)
        else:
            unmapped.append(col)

    for canonical, src_cols in canonical_targets.items():
        if len(src_cols) > 1:
            print(f"  WARNING: columns {src_cols} all map to '{canonical}'. "
                  f"Keeping '{src_cols[0]}', ignoring the rest.")
        rename_map[src_cols[0]] = canonical

    df = df.rename(columns=rename_map)

    existing = [c for c in CANONICAL_COLUMNS if c in df.columns]
    df = df[existing]

    for col in CANONICAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    return df[CANONICAL_COLUMNS], rename_map, unmapped


_ENCODINGS = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]


def _read_csv_any_encoding(path: pathlib.Path) -> pd.DataFrame:
    """Try common encodings in order; raise the last error if all fail."""
    last_err: Exception = RuntimeError("no encodings tried")
    for enc in _ENCODINGS:
        try:
            return pd.read_csv(path, dtype=str, encoding=enc).fillna("")
        except UnicodeDecodeError as e:
            last_err = e
    raise last_err


def _normalize(value: object) -> str:
    """Lowercase-strip a value for deduplication comparison."""
    return str(value).strip().lower() if pd.notna(value) and str(value).strip() else ""


def _dup_record(row: pd.Series, dup_type: str) -> dict:
    """Build one row for Duplicates.csv from a paper row."""
    return {
        "database":       row.get("_source_file", ""),
        "title":          row.get("title", ""),
        "doi":            row.get("doi", ""),
        "authors":        row.get("authors", ""),
        "year":           row.get("year", ""),
        "published_in":   row.get("source", ""),
        "duplicate_type": dup_type,
    }


def _self_deduplicate(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict]]:
    """
    Remove rows duplicated within df itself (by DOI then title).
    Returns (unique_df, duplicate_records_for_Duplicates_csv).
    """
    seen_dois:   set[str]  = set()
    seen_titles: set[str]  = set()
    keep:        list[bool] = []
    dup_records: list[dict] = []

    for _, row in df.iterrows():
        doi   = _normalize(row.get("doi", ""))
        title = _normalize(row.get("title", ""))

        if doi and doi in seen_dois:
            dup_records.append(_dup_record(row, "self-duplicate (other_resources)"))
            keep.append(False)
            continue
        if title and title in seen_titles:
            dup_records.append(_dup_record(row, "self-duplicate (other_resources)"))
            keep.append(False)
            continue

        keep.append(True)
        if doi:
            seen_dois.add(doi)
        if title:
            seen_titles.add(title)

    return df[keep].reset_index(drop=True), dup_records


def _deduplicate_against_existing(
    new_rows: pd.DataFrame,
    existing: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict]]:
    """
    Return (unique_rows, duplicate_records) where unique_rows are rows from
    new_rows not already in existing, checked by DOI first then title.
    duplicate_records are formatted for Duplicates.csv.
    """
    seen_dois:   set[str] = set()
    seen_titles: set[str] = set()

    for _, row in existing.iterrows():
        doi   = _normalize(row.get("doi", ""))
        title = _normalize(row.get("title", ""))
        if doi:
            seen_dois.add(doi)
        if title:
            seen_titles.add(title)

    keep:         list[bool] = []
    dup_records:  list[dict] = []
    unidentified: int        = 0

    for _, row in new_rows.iterrows():
        doi   = _normalize(row.get("doi", ""))
        title = _normalize(row.get("title", ""))

        if not doi and not title:
            unidentified += 1
            keep.append(True)
            continue

        if doi and doi in seen_dois:
            dup_records.append(_dup_record(row, "duplicate of papers.csv"))
            keep.append(False)
            continue
        if title and title in seen_titles:
            dup_records.append(_dup_record(row, "duplicate of papers.csv"))
            keep.append(False)
            continue

        keep.append(True)
        if doi:
            seen_dois.add(doi)
        if title:
            seen_titles.add(title)

    if unidentified:
        print(f"  WARNING: {unidentified} row(s) have no title and no DOI — "
              f"cannot deduplicate, included as-is.")

    return new_rows[keep].reset_index(drop=True), dup_records


def _write_duplicates_csv(new_records: list[dict]) -> None:
    """
    Merge new_records into Duplicates.csv.

    Rows already written by main.py (cross-database duplicates) are preserved.
    Re-running merge_external.py will not double-add the same entries: existing
    rows with the same (doi + duplicate_type) or (title + duplicate_type) are
    skipped before writing.
    """
    existing_rows: list[dict] = []
    if _DUPLICATES_CSV.exists():
        try:
            ex = pd.read_csv(_DUPLICATES_CSV, dtype=str, encoding="utf-8-sig").fillna("")
            existing_rows = ex.to_dict("records")
        except Exception as e:
            print(f"  WARNING: could not read existing '{_DUPLICATES_CSV}': {e}. "
                  f"Starting fresh.")

    # Build seen sets from existing rows to avoid re-adding on re-run
    seen: set[tuple] = set()
    for r in existing_rows:
        doi   = str(r.get("doi", "")).strip().lower()
        title = str(r.get("title", "")).strip().lower()
        dtype = str(r.get("duplicate_type", "")).strip().lower()
        if doi:
            seen.add((doi, dtype))
        elif title:
            seen.add((title, dtype))

    deduplicated_new: list[dict] = []
    for r in new_records:
        doi   = str(r.get("doi", "")).strip().lower()
        title = str(r.get("title", "")).strip().lower()
        dtype = str(r.get("duplicate_type", "")).strip().lower()
        key   = (doi, dtype) if doi else (title, dtype)
        if key in seen:
            continue
        seen.add(key)
        deduplicated_new.append(r)

    all_records = existing_rows + deduplicated_new
    df = pd.DataFrame(all_records, columns=DUPLICATE_COLUMNS)
    try:
        df.to_csv(_DUPLICATES_CSV, index=False, encoding="utf-8-sig")
        added = len(deduplicated_new)
        total = len(df)
        print(f"Saved {total} duplicate record(s) to '{_DUPLICATES_CSV}' "
              f"({added} new, {total - added} existing).")
    except PermissionError:
        print(f"WARNING: could not write '{_DUPLICATES_CSV}' — file may be open in another program.")
    except Exception as e:
        print(f"WARNING: could not write '{_DUPLICATES_CSV}': {e}")


def _save_run_summary(
    file_paper_counts: dict[str, int],
    existing_dups:     list[dict],
    total_added:       int,
) -> None:
    q            = compact_query(QUERY_GROUPS)
    total_before = sum(file_paper_counts.values())
    rows = [
        {
            "source":                   fname,
            "query":                    q,
            "papers_found":             found,
            "total_before_dedup":       total_before,
            "total_after_dedup":        total_added,
            "duplicates_with_internal": sum(1 for r in existing_dups if r.get("database") == fname),
            "start_year":               START_YEAR,
            "end_year":                 END_YEAR,
        }
        for fname, found in file_paper_counts.items()
    ]
    write_run_summary(rows, RUN_SUMMARY_COLUMNS, RUN_SUMMARY_CSV, overwrite=False)


def main() -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    RESULTS_DIR.mkdir(exist_ok=True)
    OTHER_RESOURCES.mkdir(exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path  = LOGS_DIR / f"merge_{timestamp}.log"
    try:
        log_file = open(log_path, "w", encoding="utf-8")
    except OSError as e:
        print(f"WARNING: could not create log file '{log_path}': {e}. Logging to terminal only.")
        log_file = None

    if log_file:
        sys.stdout = Tee(sys.__stdout__, log_file)

    try:
        print(f"Merge started: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Log file:      {log_path}")
        print("=" * 55)
        print("Merging external CSVs into papers.csv...")
        print("=" * 55)

        # ── Build column synonym lookup ───────────────────────
        user_overrides = _load_user_synonym_overrides()
        if user_overrides:
            print(f"User column overrides loaded: {list(user_overrides.keys())}")
        synonym_lookup = _build_synonym_lookup(user_overrides)

        # ── Load existing papers.csv ──────────────────────────
        print()
        if PAPERS_CSV.exists():
            existing_df = pd.read_csv(PAPERS_CSV, dtype=str, encoding="utf-8-sig").fillna("")
            # Backfill source_type for papers written before this column was added
            if "source_type" not in existing_df.columns:
                existing_df.insert(0, "source_type", "internal")
            else:
                existing_df["source_type"] = existing_df["source_type"].replace("", "internal")
            print(f"Existing papers.csv: {len(existing_df)} papers loaded.")
        else:
            existing_df = pd.DataFrame(columns=CANONICAL_COLUMNS)
            print(f"WARNING: '{PAPERS_CSV}' not found — treating as empty.")
        print("- " * 27)

        # ── Read and map each CSV from other_resources/ ───────
        csv_files = sorted(OTHER_RESOURCES.glob("*.csv"))
        if not csv_files:
            print(f"No CSV files found in '{OTHER_RESOURCES}/'. Nothing to merge.")
            return

        all_new:           list[pd.DataFrame] = []
        file_paper_counts: dict[str, int]    = {}

        for csv_path in csv_files:
            print(f"\n[{csv_path.name}]")
            try:
                df = _read_csv_any_encoding(csv_path)
                file_paper_counts[csv_path.name] = len(df)
                print(f"  Rows:    {len(df)}")
                print(f"  Columns ({len(df.columns)}): {list(df.columns)}")

                mapped, rename_map, unmapped = _map_columns(df, synonym_lookup)

                if rename_map:
                    print(f"  Mapped:")
                    for src, dst in rename_map.items():
                        print(f"    '{src}'  →  '{dst}'")
                if unmapped:
                    print(f"  Ignored (no canonical match): {unmapped}")

                filled = [c for c in CANONICAL_COLUMNS
                          if c not in rename_map.values() and c != "source_type"]
                if filled:
                    print(f"  Left empty: {filled}")

                # Flag all rows from external files
                mapped["source_type"]  = "external"
                # Tag every row with its source filename for Duplicates.csv tracking
                mapped["_source_file"] = csv_path.name

                all_new.append(mapped)
                print(f"  → {len(mapped)} rows accepted.")

            except Exception as e:
                print(f"  WARNING: could not read '{csv_path.name}': {e}")

        print("\n" + "- " * 27)

        if not all_new:
            print("No valid rows loaded from other_resources/. Nothing to merge.")
            return

        new_df = pd.concat(all_new, ignore_index=True)
        print(f"Total rows from other_resources/: {len(new_df)}")

        all_dup_records: list[dict] = []

        # ── Self-deduplication within external files ──────────
        new_df, self_dups = _self_deduplicate(new_df)
        all_dup_records.extend(self_dups)

        if self_dups:
            print(f"Self-duplicates removed ({len(self_dups)}):")
            for rec in self_dups:
                print(f"  - {rec['title']}")
        else:
            print("Self-duplicates removed: 0")
        print(f"After self-dedup: {len(new_df)} rows")

        # ── Deduplicate against papers.csv ────────────────────
        unique_new, existing_dups = _deduplicate_against_existing(new_df, existing_df)
        all_dup_records.extend(existing_dups)

        print(f"\nDuplicates with papers.csv: {len(existing_dups)}")
        for rec in existing_dups:
            print(f"  ✗ {rec['title']}")

        print(f"New unique papers to add:   {len(unique_new)}")
        for _, row in unique_new.iterrows():
            print(f"  ✓ {row.get('title', '(no title)')}")

        # ── Write Duplicates.csv ──────────────────────────────
        print("\n" + "- " * 27)
        if all_dup_records:
            _write_duplicates_csv(all_dup_records)
        else:
            print("No duplicates found — Duplicates.csv not written.")

        # ── Run summary table ─────────────────────────────────
        _save_run_summary(file_paper_counts, existing_dups, len(unique_new))

        # ── Build merged papers.csv = existing + unique new ──
        print("\n" + "=" * 55)
        for col in CANONICAL_COLUMNS:
            if col not in existing_df.columns:
                existing_df[col] = "internal" if col == "source_type" else ""
        existing_aligned = existing_df[CANONICAL_COLUMNS]

        # Drop the internal tracking column before saving
        unique_new = unique_new.drop(columns=["_source_file"], errors="ignore")

        merged_df = pd.concat([existing_aligned, unique_new], ignore_index=True)
        try:
            merged_df.to_csv(PAPERS_CSV, index=False, encoding="utf-8-sig")
            print(f"Saved {len(merged_df)} papers to '{PAPERS_CSV}'.")
            print(f"  {len(existing_aligned)} internal  +  {len(unique_new)} external (new)")
        except PermissionError:
            print(f"ERROR: could not write '{PAPERS_CSV}' — file may be open in another program.")
            raise

        print(f"\nMerge finished: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        raise
    finally:
        sys.stdout = sys.__stdout__
        if log_file:
            log_file.close()
            print(f"Log saved to '{log_path}'.")


if __name__ == "__main__":
    main()
