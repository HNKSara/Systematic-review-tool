# Academic Paper Fetcher

Fetch and categorize research papers from **IEEE**, **ArXiv**, **Scopus**, and **PubMed** with a single command.
Results are saved as CSV files with automatic category labels per paper and a PDF summary report.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy the settings template and fill in your API keys and query
cp user_settings_template.py user_settings.py

# 3. Open user_settings.py and fill in your API keys, query, and date range

# 4. (Optional) Drop any external CSV exports into other_resources/

# 5. Run the full pipeline
python .
```

`python .` runs every step automatically in the correct order and prints a final run summary at the end.
All four databases are fetched **in parallel**, so total runtime equals the slowest database rather than their sum.

To run steps individually instead, see [Run Order](#run-order).

---

## Run Order

### Full pipeline — one command

```bash
python .
```

Runs all steps below in sequence. If `other_resources/` contains CSV files, the merge and re-validation steps are included automatically. If it is empty, they are skipped.

```
Step 1 ── main.py
          Fetches from IEEE, PubMed, Scopus, ArXiv in parallel.
          Deduplicates across databases.
          Categorizes every paper.
          Tags all papers: source_type = "internal".
          Prints run summary table (one row per database).
          Writes → results/papers.csv
                   results/papers_*.csv  (one per database)
                   results/Duplicates.csv
                   results/run_summary.csv
                   logs/run_<timestamp>.log

Step 2 ── validate.py
          Reads results/papers.csv.
          Applies quality checks and flags problems.
          Writes → results/papers_flagged.csv
                   results/papers_validated.csv
                   logs/validate_<timestamp>.log

Step 3 ── merge_external.py          (skipped if other_resources/ is empty)
          Reads all *.csv files from other_resources/.
          Auto-maps column names to the canonical format.
          Deduplicates against results/papers.csv.
          Tags new papers: source_type = "external".
          Appends new duplicates to results/Duplicates.csv.
          Appends one row per file to results/run_summary.csv.
          Writes → results/papers.csv  (updated in-place)
                   logs/merge_<timestamp>.log

Step 4 ── validate.py                (skipped if other_resources/ is empty)
          Re-runs quality checks on the merged papers.csv.
          Now sees both internal and external papers.
          Writes → results/papers_flagged.csv
                   results/papers_validated.csv
                   logs/validate_<timestamp>.log

Step 5 ── generate_report.py
          Reads papers.csv, run_summary.csv, papers_flagged.csv,
          papers_validated.csv and produces a 2-page PDF report.
          Writes → results/report_<timestamp>.pdf
```

### Running steps individually

Run any script on its own if you only need part of the pipeline:

```bash
python main.py            # Step 1 — fetch and categorize
python validate.py        # Step 2 / Step 4 — quality check
python merge_external.py  # Step 3 — merge external CSVs
python run_report.py      # Generate PDF report only (no re-fetch)
```

| Script | Run when… |
|---|---|
| `python .` | You want to run everything at once |
| `python main.py` | You want to re-fetch the latest papers from all databases |
| `python validate.py` | You want to check quality without re-fetching |
| `python merge_external.py` | You have new external CSVs to add without re-fetching |
| `python run_report.py` | You want a fresh PDF report from the current results |

---

## Project Structure

```
├── __main__.py                ← Entry point for `python .` — runs the full pipeline
├── run_report.py              ← Standalone report generator — reads results/ and writes PDF
├── user_settings_template.py  ← Start here — copy to user_settings.py and edit
├── user_settings.py           ← YOUR file — API keys, query, dates, categories (git-ignored)
├── config.py                  ← Default values — loaded first, then overridden by user_settings.py
├── main.py                    ← Fetches all databases (parallel), deduplicates, categorizes, saves CSVs
├── validate.py                ← Checks result quality and flags issues
├── merge_external.py          ← Merges external CSVs from other_resources/ into papers.csv
├── fetch_arxiv.py             ← ArXiv fetcher
├── fetch_pubmed.py            ← PubMed fetcher
├── fetch_ieee.py              ← IEEE Xplore fetcher
├── fetch_scopus.py            ← Scopus fetcher
├── categorize.py              ← Assigns category labels to each paper
├── generate_report.py         ← Generates a PDF report from results/ (charts + tables)
├── utils.py                   ← Shared utilities (Tee logger, query builder, run summary writer)
├── requirements.txt           ← Python dependencies
├── other_resources/           ← Drop external CSV files here before running the pipeline
├── results/                   ← All CSV output files (created automatically)
└── logs/                      ← Timestamped run logs (created automatically)
```

### Which file should I edit?

**Always edit `user_settings.py`** — this is the only file you need to change.
It holds your API keys, query terms, date range, and categorization rules.
It is listed in `.gitignore` so your keys are never committed.

`user_settings_template.py` is the committed starting point with empty keys and example values.
Copy it to `user_settings.py` once and edit that copy from then on.

`config.py` holds the base defaults and loads your overrides from `user_settings.py` automatically.
If `user_settings.py` is missing, the program prints a warning and falls back to the defaults.

---

## Configuring user_settings.py

Open `user_settings.py` (copied from `user_settings_template.py`) and fill in each section.

### API Keys

Each database has different access requirements:

| Database | Key required? | How to get it |
|---|---|---|
| **ArXiv** | No | Works immediately — no registration needed |
| **PubMed** | Optional | Free at https://www.ncbi.nlm.nih.gov/account/ — without key: 3 req/s, with key: 10 req/s |
| **IEEE** | Yes (free) | Register at https://developer.ieee.org/ — key can take up to 24 h to activate |
| **Scopus** | Yes (institutional) | Register at https://dev.elsevier.com/ — requires university subscription and VPN |

```python
IEEE_API_KEY   = "your_ieee_key"
SCOPUS_API_KEY = "your_scopus_key"
PUBMED_API_KEY = "your_pubmed_key"   # leave as "" to run without a key
```

> If you do not have a key for IEEE or Scopus, the script skips that database and continues with the others.

### Date Range

```python
START_YEAR = 2020
END_YEAR   = 2025
```

### Number of Results

```python
MAX_RESULTS = 100   # per database
```

Set to a large number like `10000` to retrieve everything available.
The script stops automatically when the database runs out of results.

### Search Query

The query is a list of groups:
- Terms **inside** a group are combined with **OR**
- Groups are combined with **AND**

```python
QUERY_GROUPS = [
    [
        "deep learning", "machine learning", "neural network", "artificial intelligence",
    ],
    [
        "healthcare", "clinical", "medical",
    ],
    [
        "prediction", "diagnosis", "prognosis", "detection",
    ],
]
```

This translates to:
```
("deep learning" OR "machine learning" OR "neural network" OR "artificial intelligence")
AND ("healthcare" OR "clinical" OR "medical")
AND ("prediction" OR "diagnosis" OR "prognosis" OR "detection")
```

Replace the lists with your own terms to search a completely different topic.

### Search Fields

Control which parts of a paper are searched in every database:

```python
SEARCH_FIELDS = {
    "all_fields": False,   # True = search everything (ignores the flags below)
    "title":      True,
    "abstract":   True,
    "keywords":   True,
}
```

**Option 1 — Search everything:** set `all_fields` to `True` to search across every field each database indexes.

| Database | What "all fields" covers |
|---|---|
| **ArXiv** | Title, abstract, authors, comments, journal reference |
| **PubMed** | Title, abstract, MeSH terms, authors, journal, affiliations, full text (when available) |
| **IEEE** | Title, abstract, index terms, authors, publication name, full text |
| **Scopus** | Title, abstract, keywords, authors, affiliations, funding, references |

**Option 2 — Choose specific fields:** keep `all_fields` as `False` and set individual flags.

| Goal | Setting |
|---|---|
| Title + abstract + keywords (default) | all three `True` |
| Title + abstract only | `"keywords": False` |
| Title only | `"abstract": False, "keywords": False` |
| Abstract + keywords only | `"title": False` |

Each database translates the flags into its own native query syntax automatically:

| Database | All three fields | Title only |
|---|---|---|
| **ArXiv** | `all:term` | `ti:term` |
| **PubMed** | `"term"[Title/Abstract] OR "term"[MeSH Terms]` | `"term"[Title]` |
| **IEEE** | `"Document Title":term OR Abstract:term OR "Index Terms":term` | `"Document Title":term` |
| **Scopus** | `TITLE-ABS-KEY(terms)` | `TITLE(terms)` |

### Categorization Dimensions

After fetching, every paper is automatically labeled across dimensions you define.
Each dimension becomes a column in the output CSV.

```python
CATEGORIZATION_DIMENSIONS = {
    "clinical_application": {
        "Medical Imaging":    ["imaging", "radiology", "mri", "ct scan"],
        "Disease Prediction": ["prediction", "prognosis", "risk stratification"],
        "Clinical NLP":       ["nlp", "clinical notes", "text mining"],
        # ...
    },
    "ml_method": {
        "Deep Learning":        ["deep learning", "neural network", "cnn", "transformer"],
        "Large Language Model": ["large language model", "llm", "gpt", "bert"],
        "Classical ML":         ["random forest", "svm", "logistic regression"],
        # ...
    },
}
```

**How matching works:** a paper matches a label if any keyword from its list appears in the title or abstract.
The **first** matching label wins — order matters.
Papers that match nothing are labeled `Unclassified`.

**To add a new dimension**, add a new key with its labels and keywords:

```python
"study_type": {
    "Survey / Review": ["survey", "review", "systematic review"],
    "Framework":       ["framework", "architecture", "proposed model"],
    "Empirical Study": ["experiment", "evaluation", "benchmark"],
},
```

The new column appears automatically in every CSV output file.

---

## Output Files

All files are saved inside `results/` (created automatically).

### From `main.py`

| File | Contents |
|---|---|
| `papers.csv` | All databases combined, deduplicated and categorized — the primary output |
| `papers_arxiv.csv` | ArXiv papers only |
| `papers_pubmed.csv` | PubMed papers only |
| `papers_ieee.csv` | IEEE papers only |
| `papers_scopus.csv` | Scopus papers only |
| `Duplicates.csv` | Every paper removed as a duplicate, with reason |
| `run_summary.csv` | One row per database — paper counts, deduplication totals, query, date range |

### From `validate.py`

| File | Contents |
|---|---|
| `papers_flagged.csv` | Papers with one or more quality issues and a `flags` column explaining each |
| `papers_validated.csv` | Clean subset — papers excluded only if ALL category dimensions are Unclassified |

### From `generate_report.py` / `run_report.py`

| File | Contents |
|---|---|
| `report_<timestamp>.pdf` | 2-page A4 landscape PDF report |

| Page | Contents |
|---|---|
| 1 | 3 metric boxes (Total Papers / Duplicates / Final Papers) · date range · search query · run summary table · papers-by-year chart · papers-by-database pie chart |
| 2 | Category distribution charts · Validation summary boxes (Total / Clean / Flagged / Validated / Excluded) · Flag frequency chart |

### From `merge_external.py`

| File | Contents |
|---|---|
| `papers.csv` | Updated in-place — internal papers plus any new external papers from `other_resources/` |
| `Duplicates.csv` | Updated with external duplicates appended |
| `run_summary.csv` | Updated with one row per external file |

### Column reference

Every `papers*.csv` file has these columns:

| Column | Description |
|---|---|
| `source_type` | `internal` — fetched via APIs; `external` — imported from `other_resources/` |
| `title` | Paper title |
| `authors` | Author names |
| `year` | Publication year |
| `source` | Database the paper came from (ArXiv, PubMed, IEEE, Scopus) |
| `doi` | DOI identifier (may be empty for ArXiv preprints) |
| `doi_url` | Clickable `https://doi.org/…` link (empty when no DOI) |
| `url` | Direct link to the paper page |
| *(your dimensions)* | One column per dimension in `CATEGORIZATION_DIMENSIONS` |
| `abstract` | Full abstract text |

### Duplicates.csv column reference

| Column | Description |
|---|---|
| `database` | Source database or filename the duplicate came from |
| `title` | Paper title |
| `doi` | DOI |
| `authors` | Authors |
| `year` | Publication year |
| `published_in` | Journal, conference, or publisher |
| `duplicate_type` | `cross-database duplicate` · `duplicate of papers.csv` · `self-duplicate (other_resources)` |

### run_summary.csv column reference

| Column | Description |
|---|---|
| `source` | Database name or external filename |
| `query` | Full search query from `QUERY_GROUPS` |
| `papers_found` | Papers retrieved before deduplication |
| `total_before_dedup` | Total across all sources before deduplication |
| `total_after_dedup` | Total after deduplication |
| `duplicates_with_internal` | Papers already in `papers.csv` (external rows only) |
| `start_year` | `START_YEAR` at time of run |
| `end_year` | `END_YEAR` at time of run |

---

## Merging External CSVs

If you have papers exported manually from databases like IEEE Xplore, Web of Science, or Google Scholar, you can merge them into the final dataset without re-running the fetchers.

1. Export your papers as CSV from the external tool.
2. Drop the CSV file(s) into the `other_resources/` folder.
3. Run `python .` or run `merge_external.py` directly:

```bash
python merge_external.py
```

Column names in your external CSVs do not need to match the canonical format — the script auto-maps common column name variants (e.g. `Document Title` → `title`, `Publication Year` → `year`, `DOI` → `doi`). Columns that cannot be mapped are ignored; canonical columns missing from the file are left empty.

**Custom column mappings:** if your external CSV uses non-standard column names, add a mapping in `user_settings.py`:

```python
EXTERNAL_COLUMN_MAP = {
    "title":   ["Paper Name", "Article"],
    "authors": ["Contributor", "Written By"],
    "year":    ["Pub Year", "Published"],
}
```

---

## Logs

Every run creates a timestamped log in the `logs/` folder:

| Script | Log file pattern | Contents |
|---|---|---|
| `main.py` | `logs/run_<timestamp>.log` | API requests, paper counts, category summary, rate-limit warnings, duplicate count |
| `validate.py` | `logs/validate_<timestamp>.log` | Full validation report, flag breakdown, validated/excluded counts |
| `merge_external.py` | `logs/merge_<timestamp>.log` | Per-file column mapping, duplicate details, final counts |

---

## Validating Results

```bash
python validate.py
```

**Checks applied to each paper:**

| Check | Flag written |
|---|---|
| Abstract is missing | `no abstract` |
| Abstract is fewer than 30 words | `abstract too short (<30 words)` |
| No DOI | `no DOI` |
| No authors | `no authors` |
| Year outside `START_YEAR`–`END_YEAR` | `year X out of range` |
| Any category dimension matched nothing | `dimension=Unclassified` (shown as `Unclassified` in report) |
| No URL | `no URL` |

**Output:**
- `results/papers_flagged.csv` — every paper that triggered at least one flag
- `results/papers_validated.csv` — papers excluded **only** if **all** category dimensions are Unclassified
- `logs/validate_<timestamp>.log` — full report

---

## Running a Single Database

```bash
python fetch_arxiv.py    # → results/papers_arxiv.csv
python fetch_pubmed.py   # → results/papers_pubmed.csv
python fetch_ieee.py     # → results/papers_ieee.csv
python fetch_scopus.py   # → results/papers_scopus.csv
```

---

## Known Limitations

| Database | Limitation |
|---|---|
| **ArXiv** | Date filtering is by submission date, not journal publication date. |
| **PubMed** | Without an API key, rate is capped at 3 requests/second. |
| **IEEE** | Free API tier has a monthly request quota and returns at most 200 records per request. Keys can take up to 24 hours to activate. |
| **Scopus** | Requires an active institutional subscription and university network/VPN. |

---

## Requirements

- Python 3.10 or higher
- `requests` — HTTP calls to all APIs
- `pandas` — building and saving the CSV
- `matplotlib` — PDF report charts

```bash
pip install -r requirements.txt
```

---

## Sample Run Report

The results below are from a real run on **2026-06-05**, searching for **Trustworthy AI in Healthcare Multi-Agent Systems** (2022–2026).

### Search Query

```
(deep learning OR machine learning OR neural network)
AND (healthcare OR clinical OR medical)
AND (prediction OR diagnosis OR detection)
```

Date range: **2022 – 2026**

### Paper Counts

| Source | Found | After Dedup | Duplicates Removed |
|---|---|---|---|
| PubMed | 42 | 42 | 0 |
| Scopus | 401 | 362 | 39 |
| ArXiv | 0 | 0 | 0 |
| IEEE (API) | 0 | 0 | 0 |
| IEEE export CSV *(external)* | 82 | 39 | 43 |
| **Total** | **525** | **443** | **82** |

Internal pipeline (APIs): **404 papers** · External merge: **+39 new papers** · Grand total: **443 papers**

---

### Validation Summary

| Metric | Count |
|---|---|
| Total papers | 443 |
| Flagged papers (quality issues) | — |
| Excluded (all dimensions Unclassified) | 90 |
| **Validated papers** | **353** |

---

### Category Distribution

**Trustworthiness Property**

| Category | Papers |
|---|---|
| Security | 43 |
| Safety | 33 |
| Explainability | 24 |
| Privacy | 24 |
| Fairness | 7 |
| Robustness | 3 |
| Accountability | 2 |
| Transparency | 2 |
| Unclassified | 266 |

**Healthcare Area**

| Category | Papers |
|---|---|
| General Healthcare | 130 |
| Clinical Decision Support | 23 |
| Patient Monitoring | 19 |
| Medical Imaging | 7 |
| Drug Discovery | 7 |
| Mental Health | 4 |
| EHR / Health Records | 3 |
| Unclassified | 211 |

**Agent Architecture**

| Category | Papers |
|---|---|
| Multi-Agent | 105 |
| Agentic AI | 80 |
| Agent-General | 33 |
| Unclassified | 186 |

---

*Report generated by `generate_report.py`. Full PDF report saved to `results/`.*
