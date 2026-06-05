# =============================================================
# validate.py — Check result quality and flag suspicious rows
# Run:  python validate.py
# Output: results/papers_flagged.csv  +  printed report
#         logs/validate_<timestamp>.log
# =============================================================

import sys
import datetime
import pathlib
import pandas as pd
from config import OUTPUT_FILE
from config import START_YEAR, END_YEAR, CATEGORIZATION_DIMENSIONS
from utils import Tee

LOGS_DIR = pathlib.Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

FLAGGED_FILE = "results/papers_flagged.csv"


# ── Individual checks ─────────────────────────────────────────
# Each function receives a DataFrame row and returns a flag string
# or empty string if the row is clean.
# Add your own checks at the bottom of this section.

def flag_missing_abstract(row) -> str:
    if not str(row.get("abstract", "")).strip():
        return "no abstract"
    return ""

def flag_short_abstract(row) -> str:
    abstract = str(row.get("abstract", "")).strip()
    if abstract and len(abstract.split()) < 30:
        return "abstract too short (<30 words)"
    return ""

def flag_missing_doi(row) -> str:
    if not str(row.get("doi", "")).strip():
        return "no DOI"
    return ""

def flag_missing_authors(row) -> str:
    if not str(row.get("authors", "")).strip():
        return "no authors"
    return ""

def flag_year_out_of_range(row) -> str:
    try:
        year = int(row.get("year", 0))
    except (ValueError, TypeError):
        return "invalid year"
    if not (START_YEAR <= year <= END_YEAR):
        return f"year {year} out of range ({START_YEAR}–{END_YEAR})"
    return ""

def flag_unclassified(row) -> str:
    issues = []
    for dim in CATEGORIZATION_DIMENSIONS:
        if row.get(dim) == "Unclassified":
            issues.append(f"{dim}=Unclassified")
    return "; ".join(issues)

def flag_missing_url(row) -> str:
    if not str(row.get("url", "")).strip():
        return "no URL"
    return ""


# ── Registry — add/remove checks here ────────────────────────
CHECKS = [
    flag_missing_abstract,
    flag_short_abstract,
    flag_missing_doi,
    flag_missing_authors,
    flag_year_out_of_range,
    flag_unclassified,
    flag_missing_url,
]


# ── Runner ────────────────────────────────────────────────────

def run(csv_path: str = OUTPUT_FILE) -> pd.DataFrame:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path  = LOGS_DIR / f"validate_{timestamp}.log"
    log_file  = open(log_path, "w", encoding="utf-8")
    sys.stdout = Tee(sys.__stdout__, log_file)

    print(f"Validation started: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Log file:           {log_path}")

    if not pathlib.Path(csv_path).exists():
        print(f"File not found: {csv_path}")
        print("Run main.py first to generate results.")
        sys.stdout = sys.__stdout__
        log_file.close()
        return pd.DataFrame()

    df = pd.read_csv(csv_path, dtype=str).fillna("")

    # Apply all checks and collect flags per row
    def collect_flags(row):
        flags = [fn(row) for fn in CHECKS]
        return " | ".join(f for f in flags if f)

    df["flags"] = df.apply(collect_flags, axis=1)
    flagged = df[df["flags"] != ""]

    # ── Print report ──────────────────────────────────────────
    print("=" * 55)
    print(f"Validation report  —  {csv_path}")
    print("=" * 55)
    print(f"Total papers     : {len(df)}")
    print(f"Clean papers     : {len(df) - len(flagged)}")
    print(f"Flagged papers   : {len(flagged)}")

    print("\n── Source breakdown ──────────────────────────────────")
    print(df["source"].value_counts().to_string())

    print("\n── Year distribution ─────────────────────────────────")
    print(df["year"].value_counts().sort_index().to_string())

    print("\n── Flag breakdown ────────────────────────────────────")
    all_flags = []
    for flags_str in df["flags"]:
        all_flags.extend([f.strip() for f in flags_str.split("|") if f.strip()])
    flag_counts: dict[str, int] = {}
    for f in all_flags:
        flag_counts[f] = flag_counts.get(f, 0) + 1
    for flag, count in sorted(flag_counts.items(), key=lambda x: -x[1]):
        print(f"  {count:>4}  {flag}")

    print("\n── Category distribution ─────────────────────────────")
    for dim in CATEGORIZATION_DIMENSIONS:
        if dim in df.columns:
            print(f"\n  {dim}:")
            print(df[dim].value_counts().to_string())

    # ── Save flagged CSV ──────────────────────────────────────
    pathlib.Path("results").mkdir(exist_ok=True)
    flagged.to_csv(FLAGGED_FILE, index=False, encoding="utf-8-sig")
    print(f"\nFlagged rows saved to '{FLAGGED_FILE}'.")

    # ── Save validated CSV ────────────────────────────────────
    # A paper is excluded only if ALL category dimensions are Unclassified
    # (strong signal it is not relevant to the query).
    # "no abstract" and "no DOI" are not grounds for exclusion — they are
    # API limitations, not relevance problems.
    dims = list(CATEGORIZATION_DIMENSIONS.keys())
    all_unclassified = df[dims].apply(
        lambda row: all(v == "Unclassified" for v in row), axis=1
    )
    validated = df[~all_unclassified].drop(columns=["flags"])
    validated_path = "results/papers_validated.csv"
    validated.to_csv(validated_path, index=False, encoding="utf-8-sig")

    print(f"\n── Validated results ─────────────────────────────────")
    print(f"  Excluded (all dimensions Unclassified) : {all_unclassified.sum()}")
    print(f"  Kept in validated file                 : {len(validated)}")
    print(f"  Saved to '{validated_path}'.")
    print(f"\nValidation finished: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    sys.stdout = sys.__stdout__
    log_file.close()
    print(f"Log saved to '{log_path}'.")

    return flagged


if __name__ == "__main__":
    run()
