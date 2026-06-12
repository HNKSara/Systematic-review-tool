# =============================================================
# categorize_xlsx.py — Categorize INCLUDED papers in
# results/papers_validated_structure_human.xlsx using the
# Anthropic API, based on title + abstract only.
#
# Standalone script. Does not import or modify any other file
# except for read-only access to QUERY_GROUPS / CATEGORY_DISCOVERY
# (user_settings.py) and compact_query() (utils.py).
#
# Pass 1 — for every row where decision == "Include":
#   - Sends title + abstract + the review query (built from
#     QUERY_GROUPS) to the Anthropic API
#   - Asks for a JSON-only object with free-text labels for
#     healthcare_type, trustworthiness_type, agentic_part
#   - Writes the result into three columns
#   - Saves the xlsx file (after every row)
#
# Pass 2 — for each column listed in CATEGORY_DISCOVERY
# (user_settings.py), if it has more distinct labels than the
# configured maximum, sends the list of distinct labels to the
# Anthropic API once and asks it to merge them into that many
# broader categories, then rewrites the column using that mapping.
#
# Setup:
#   pip install anthropic
#   Set your API key as an environment variable:
#     export ANTHROPIC_API_KEY="sk-ant-..."
#   (or add ANTHROPIC_API_KEY = "sk-ant-..." to user_settings.py)
#
# Usage:
#   python categorize_xlsx.py
#   python categorize_xlsx.py --limit 10   # only the first 10 unprocessed rows
#   python categorize_xlsx.py --sleep 1.0  # extra delay between calls (seconds)
# =============================================================

import argparse
import datetime
import json
import os
import pathlib
import re
import sys
import time

import pandas as pd

try:
    import anthropic
except ImportError:
    print("ERROR: the 'anthropic' package is required. Install it with:")
    print("  pip install anthropic")
    sys.exit(1)

from utils import compact_query

DATA_PATH    = "results/papers_validated_structure_human.xlsx"
LOG_DIR      = pathlib.Path("logs")
MODEL        = "claude-sonnet-4-5-20250929"
MAX_TOKENS       = 300
MERGE_MAX_TOKENS = 4096
MAX_RETRIES  = 5
RETRY_BASE_S = 2.0   # exponential backoff base (seconds)

CATEGORY_COLUMNS = ["healthcare_type", "trustworthiness_type", "agentic_part"]
UNSPECIFIED = "unspecified"

# ── Pass 2: category discovery / merging ─────────────────────
# Optional. Set in user_settings.py as:
#   CATEGORY_DISCOVERY = {"healthcare_type": 7, "trustworthiness_type": 5}
# Maps a column in CATEGORY_COLUMNS to the maximum number of broader
# categories its free-text labels should be merged into (pass 2 below).
# Columns not listed here keep their pass-1 free-text labels as-is.
def get_category_discovery() -> dict:
    try:
        from user_settings import CATEGORY_DISCOVERY
    except ImportError:
        CATEGORY_DISCOVERY = {}
    return {k: v for k, v in CATEGORY_DISCOVERY.items() if k in CATEGORY_COLUMNS}

# Expected column structure of the xlsx file before categorization.
EXPECTED_COLUMNS = [
    "source_type", "title", "authors", "year", "doi_url", "url",
    "abstract", "decision", "reason",
]


# ── Setup ─────────────────────────────────────────────────────

def get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    try:
        import user_settings
        key = getattr(user_settings, "ANTHROPIC_API_KEY", "")
    except ImportError:
        key = ""
    if not key:
        print("ERROR: No Anthropic API key found.")
        print("Set it via:")
        print('  export ANTHROPIC_API_KEY="sk-ant-..."')
        print("or add to user_settings.py:")
        print('  ANTHROPIC_API_KEY = "sk-ant-..."')
        sys.exit(1)
    return key


def get_review_query() -> str:
    """Build a human-readable review query string from QUERY_GROUPS."""
    try:
        from user_settings import QUERY_GROUPS
    except ImportError:
        QUERY_GROUPS = []
    if not QUERY_GROUPS:
        print("ERROR: QUERY_GROUPS is empty in user_settings.py.")
        sys.exit(1)
    return compact_query(QUERY_GROUPS)


def get_query_terms() -> list[str]:
    """
    Flatten all terms from QUERY_GROUPS into a single deduplicated list.
    Used as example/inspiration vocabulary for category labels — the LLM
    is not restricted to these terms, but they're offered as a starting
    point so labels stay grounded in the vocabulary used to define the
    review's search query.
    """
    try:
        from user_settings import QUERY_GROUPS
    except ImportError:
        QUERY_GROUPS = []
    seen: list[str] = []
    for group in QUERY_GROUPS:
        for term in group:
            if term not in seen:
                seen.append(term)
    return seen


# ── Prompt ────────────────────────────────────────────────────

def build_prompt(review_query: str, title: str, abstract: str) -> str:
    terms = get_query_terms()
    hint_block = ""
    if terms:
        terms_list = ", ".join(f'"{t}"' for t in terms)
        hint_block = f"""
For inspiration, here are terms from this review's search query: {terms_list}.
You may reuse one of these terms (or a close variant) as a label if it fits
a category below, but you are NOT limited to them — use whatever short label
best describes the paper for each category.
"""
    return f"""You are categorizing a paper that has already been included in a systematic literature review.

REVIEW QUERY (defines the topic/population of interest for this review):
{review_query}

PAPER TITLE:
{title}

PAPER ABSTRACT:
{abstract}
{hint_block}
Based STRICTLY on the title and abstract above (and using the review
query only as context for what is relevant), determine the following three
categories. For each one, write a short free-text label in your own words —
do not pick from a fixed list.

1. healthcare_type: the specific healthcare domain addressed by the paper
   (e.g. "mental health", "oncology", "radiology", "ICU", "primary care", etc.).
2. trustworthiness_type: the type of trustworthiness addressed by the paper
   (e.g. "reliability", "safety", "explainability", "transparency", "robustness",
   "privacy", "fairness", etc.).
3. agentic_part: the role or aspect of the multi-agent system addressed by the paper
   (e.g. "agent coordination", "decision-making", "communication", "autonomy",
   "human-agent interaction", etc.).

If a category cannot be determined from the title and abstract, return
"{UNSPECIFIED}" for that category.

Respond in JSON only, with exactly these three keys and no other text:
{{"healthcare_type": "...", "trustworthiness_type": "...", "agentic_part": "..."}}
"""


def build_merge_prompt(column: str, labels: list[str], n: int) -> str:
    labels_list = "\n".join(f'- "{label}"' for label in labels)
    terms = get_query_terms()
    hint_block = ""
    if terms:
        terms_list = ", ".join(f'"{t}"' for t in terms)
        hint_block = f"""
For inspiration, here are terms from this review's search query: {terms_list}.
You may reuse one of these terms (or a close variant) as a new category name
if it fits, but you are NOT limited to them.
"""
    return f"""You are organizing free-text labels assigned to papers in a systematic
literature review, for the "{column}" category.

Here are all the distinct labels currently in use ({len(labels)} total):
{labels_list}
{hint_block}
Group these labels into AT MOST {n} broader categories that best represent
the labels above. Choose short, descriptive names for each new category.
Every original label must be assigned to exactly one new category.

Prefer keeping topically or clinically distinct domains as their own
separate categories, rather than merging them into broad umbrella
categories, as long as the total stays within the limit above.

HARD REQUIREMENT: the number of DISTINCT category names you use across the
entire mapping must be {n} or fewer. Count the distinct values in your
mapping before responding — if it exceeds {n}, merge the smallest/most
similar categories together until at most {n} remain. This limit is strict
and must not be exceeded under any circumstances.

Respond in JSON only: a single object mapping every original label (exactly
as given above) to its new category name, with no other text:
{{"<original label>": "<new category name>", ...}}
"""


# ── API call with retry / rate-limit handling ────────────────

def _extract_json(text: str) -> dict:
    """
    Parse the model's JSON response. Strips markdown code fences if present
    and falls back to extracting the first {...} block.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _unspecified_result() -> dict:
    return {col: UNSPECIFIED for col in CATEGORY_COLUMNS}


def categorize_paper(
    client: "anthropic.Anthropic",
    review_query: str,
    title: str,
    abstract: str,
) -> dict:
    """
    Call the Anthropic API for a single paper.
    Returns a dict with free-text healthcare_type / trustworthiness_type /
    agentic_part labels. On unrecoverable error, all fall back to
    "unspecified".
    """
    prompt = build_prompt(review_query, title, abstract)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            data = _extract_json(raw_text)

            result = {}
            for col in CATEGORY_COLUMNS:
                value = str(data.get(col, "")).strip()
                result[col] = value if value else UNSPECIFIED
            return result

        except anthropic.RateLimitError as e:
            wait = RETRY_BASE_S * (2 ** (attempt - 1))
            print(f"    Rate limited (attempt {attempt}/{MAX_RETRIES}) — waiting {wait:.0f}s...")
            time.sleep(wait)

        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            wait = RETRY_BASE_S * (2 ** (attempt - 1))
            print(f"    API error (attempt {attempt}/{MAX_RETRIES}): {e} — waiting {wait:.0f}s...")
            time.sleep(wait)

        except json.JSONDecodeError as e:
            print(f"    Could not parse model response as JSON: {e}")
            return _unspecified_result()

        except Exception as e:
            print(f"    Unexpected error: {type(e).__name__}: {e}")
            return _unspecified_result()

    print(f"    API call failed after {MAX_RETRIES} retries.")
    return _unspecified_result()


def _enforce_category_limit(
    client: "anthropic.Anthropic",
    column: str,
    mapping: dict,
    n: int,
    max_attempts: int = 2,
) -> dict:
    """
    If `mapping` uses more than `n` distinct category names, ask the model to
    consolidate the category names themselves down to at most `n`, then
    re-map every original label through that consolidation. Tries up to
    `max_attempts` times; if still over the limit, returns the mapping as-is.
    """
    for _ in range(max_attempts):
        categories = sorted(set(mapping.values()))
        if len(categories) <= n:
            return mapping

        prompt = (
            f"You previously grouped free-text labels for the \"{column}\" category "
            f"into {len(categories)} categories, but the limit is {n}.\n\n"
            f"Here are the {len(categories)} category names currently in use:\n"
            + "\n".join(f'- "{c}"' for c in categories)
            + f"\n\nConsolidate these into AT MOST {n} categories by merging the "
            "most similar ones together. Choose short, descriptive names for the "
            "final categories.\n\n"
            "Respond in JSON only: a single object mapping every category name "
            "above (exactly as given) to its new, consolidated category name, "
            "with no other text:\n"
            '{"<current category name>": "<consolidated category name>", ...}'
        )
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MERGE_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            consolidation = {str(k): str(v).strip() for k, v in _extract_json(raw_text).items()}
        except Exception as e:
            print(f"    Could not enforce category limit: {type(e).__name__}: {e}")
            return mapping

        mapping = {label: consolidation.get(cat, cat) for label, cat in mapping.items()}

    return mapping


def merge_categories(
    client: "anthropic.Anthropic",
    column: str,
    labels: list[str],
    n: int,
) -> dict:
    """
    Call the Anthropic API once to merge a list of distinct free-text labels
    for `column` into at most `n` broader categories.
    Returns a dict mapping each original label to its new category name.
    On unrecoverable error, returns {} (caller should leave labels as-is).
    """
    prompt = build_merge_prompt(column, labels, n)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MERGE_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            mapping = {str(k): str(v).strip() for k, v in _extract_json(raw_text).items()}
            return _enforce_category_limit(client, column, mapping, n)

        except anthropic.RateLimitError as e:
            wait = RETRY_BASE_S * (2 ** (attempt - 1))
            print(f"    Rate limited (attempt {attempt}/{MAX_RETRIES}) — waiting {wait:.0f}s...")
            time.sleep(wait)

        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            wait = RETRY_BASE_S * (2 ** (attempt - 1))
            print(f"    API error (attempt {attempt}/{MAX_RETRIES}): {e} — waiting {wait:.0f}s...")
            time.sleep(wait)

        except json.JSONDecodeError as e:
            print(f"    Could not parse model response as JSON: {e}")
            return {}

        except Exception as e:
            print(f"    Unexpected error: {type(e).__name__}: {e}")
            return {}

    print(f"    API call failed after {MAX_RETRIES} retries.")
    return {}


# ── Main ──────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Categorize included papers in the final xlsx with the Anthropic API.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only categorize the first N not-yet-categorized rows (for testing).")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="Extra delay (seconds) between API calls to stay under rate limits.")
    args = parser.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path  = LOG_DIR / f"categorize_xlsx_{timestamp}.log"
    log_file  = open(log_path, "w", encoding="utf-8")

    class _Tee:
        def write(self, data):
            sys.__stdout__.write(data)
            log_file.write(data)
        def flush(self):
            sys.__stdout__.flush()
            log_file.flush()

    sys.stdout = _Tee()

    print(f"Categorization started : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Log file               : {log_path}")
    print(f"Model                  : {MODEL}")

    if not os.path.exists(DATA_PATH):
        print(f"ERROR: '{DATA_PATH}' not found.")
        sys.stdout = sys.__stdout__
        log_file.close()
        sys.exit(1)

    api_key      = get_api_key()
    review_query = get_review_query()
    print(f"Review query: {review_query}\n")

    print(f"Reading '{DATA_PATH}' ...")
    df = pd.read_excel(DATA_PATH)

    actual_columns = [c for c in df.columns if c not in CATEGORY_COLUMNS]
    if actual_columns != EXPECTED_COLUMNS:
        print(f"\nERROR: '{DATA_PATH}' does not have the expected column structure.")
        print(f"\nExpected columns (in order):\n  {EXPECTED_COLUMNS}")
        print(f"\nFound columns (in order):\n  {actual_columns}")
        print(f"\nPlease fix the table so its columns match the expected structure exactly, then re-run.")
        sys.stdout = sys.__stdout__
        log_file.close()
        sys.exit(1)

    for col in CATEGORY_COLUMNS:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)
        if col not in EXPECTED_COLUMNS:
            df = df[[c for c in df.columns if c != col] + [col]]

    client = anthropic.Anthropic(api_key=api_key)

    included = df.index[df["decision"].astype(str).str.strip() == "Include"]
    not_yet_done = df.index[
        (df["decision"].astype(str).str.strip() == "Include")
        & (df[CATEGORY_COLUMNS].apply(lambda r: r.str.strip().eq("").any(), axis=1))
    ].tolist()

    to_process = not_yet_done
    if args.limit is not None:
        to_process = to_process[:args.limit]

    print(f"Total papers           : {len(df)}")
    print(f"Included papers        : {len(included)}")
    print(f"Already categorized    : {len(included) - len(not_yet_done)}")
    print(f"To categorize this run : {len(to_process)}\n")

    for i, idx in enumerate(to_process, start=1):
        title    = str(df.at[idx, "title"]) if pd.notna(df.at[idx, "title"]) else ""
        abstract = str(df.at[idx, "abstract"]) if pd.notna(df.at[idx, "abstract"]) else ""

        if not abstract.strip():
            result = _unspecified_result()
        else:
            result = categorize_paper(client, review_query, title, abstract)

        for col in CATEGORY_COLUMNS:
            df.at[idx, col] = result[col]

        short_title = title[:60] + "…" if len(title) > 60 else title
        summary = " | ".join(f"{col}={result[col]}" for col in CATEGORY_COLUMNS)
        print(f"  [{i:>4}/{len(to_process)}] {short_title}")
        print(f"           {summary}")

        df.to_excel(DATA_PATH, index=False)

        if args.sleep > 0:
            time.sleep(args.sleep)

    print(f"\nDone. Saved results to '{DATA_PATH}'.")

    # ── Pass 2: merge free-text labels into broader categories ───
    category_discovery = get_category_discovery()
    included_mask = df["decision"].astype(str).str.strip() == "Include"
    for col, n in category_discovery.items():
        values = df.loc[included_mask, col].astype(str).str.strip()
        labels = sorted(v for v in values.unique() if v and v != UNSPECIFIED)

        if len(labels) <= n:
            print(f"\n'{col}' already has {len(labels)} label(s) (<= {n}) — skipping merge.")
            continue

        print(f"\nMerging {len(labels)} '{col}' labels into at most {n} categories...")
        mapping = merge_categories(client, col, labels, n)
        if not mapping:
            print(f"  Merge failed for '{col}' — leaving labels as-is.")
            continue

        df.loc[included_mask, col] = df.loc[included_mask, col].map(
            lambda v: mapping.get(str(v).strip(), v)
        )
        print(f"  Merged into: {sorted(set(mapping.values()))}")

    if category_discovery:
        df.to_excel(DATA_PATH, index=False)

    print("\n── Category summaries ──")
    for col in CATEGORY_COLUMNS:
        print(f"\n{col}:")
        print(df.loc[df["decision"].astype(str).str.strip() == "Include", col].value_counts().to_string())

    print(f"\nCategorization finished: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    sys.stdout = sys.__stdout__
    log_file.close()
    print(f"Log saved to '{log_path}'.")


if __name__ == "__main__":
    main()
