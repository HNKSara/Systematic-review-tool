# =============================================================
# config.py — DEFAULT CONFIGURATION (template)
# DO NOT put your personal settings here — use user_settings.py.
# This file can be overwritten by code updates safely.
# =============================================================


# ── OUTPUT ────────────────────────────────────────────────────
# CSV files are saved inside the results/ folder (created automatically).
OUTPUT_FILE         = "results/papers.csv"
OUTPUT_FILE_ARXIV   = "results/papers_arxiv.csv"
OUTPUT_FILE_PUBMED  = "results/papers_pubmed.csv"
OUTPUT_FILE_IEEE    = "results/papers_ieee.csv"
OUTPUT_FILE_SCOPUS  = "results/papers_scopus.csv"

# ── RUN SUMMARY TABLE ─────────────────────────────────────────
# Written by main.py (one row per DB) and appended by merge_external.py
# (one row per external file).
RUN_SUMMARY_CSV     = "results/run_summary.csv"
RUN_SUMMARY_COLUMNS = [
    "source", "query", "papers_found",
    "total_before_dedup", "total_after_dedup",
    "duplicates_with_internal", "start_year", "end_year",
]


# ── DUPLICATES LOG ────────────────────────────────────────────
# All removed duplicates (from both main.py and merge_external.py) are
# written here so nothing is silently discarded.
DUPLICATES_CSV    = "results/Duplicates.csv"
DUPLICATE_COLUMNS = [
    "database",       # source DB or filename the paper came from
    "title",
    "doi",
    "authors",
    "year",
    "published_in",   # journal / conference / publisher
    "duplicate_type", # "cross-database duplicate" | "self-duplicate (other_resources)" | "duplicate of papers.csv"
]


# =============================================================
# Load personal overrides from user_settings.py.
# user_settings.py is never touched by code updates.
# Any variable defined there replaces the default above.
# =============================================================
QUERY_GROUPS             = []
START_YEAR               = 0
END_YEAR                 = 0
CATEGORIZATION_DIMENSIONS = {}

try:
    from user_settings import *
except ImportError:
    print(
        "WARNING: user_settings.py not found. "
        "Copy the template below and save it as user_settings.py:\n"
        "  IEEE_API_KEY = ''\n"
        "  SCOPUS_API_KEY = ''\n"
        "  PUBMED_API_KEY = ''\n"
        "  START_YEAR = 0\n"
        "  END_YEAR   = 0\n"
        "  MAX_RESULTS = 0\n"
        "  QUERY_GROUPS = [['your terms'], ['your domain']]\n"
        "  CATEGORIZATION_DIMENSIONS = {'dimension': {'Category': ['keyword']}}\n"
    )
