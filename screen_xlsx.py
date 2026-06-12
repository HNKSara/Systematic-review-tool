# =============================================================
# screen_xlsx.py — Screen papers in
# results/papers_validated_structure_human.xlsx using the
# Anthropic API (Include / Exclude / Unclear).
#
# Standalone script. Does not import or modify any other file
# except for read-only access to QUERY_GROUPS (user_settings.py)
# and compact_query() (utils.py).
#
# For every row where decision is empty/NaN:
#   - Sends title + abstract + the review query (built from
#     QUERY_GROUPS) to the Anthropic API
#   - Asks for a JSON-only object with decision and reason
#   - Writes the result into the decision/reason columns
#   - Saves the xlsx file (after every row)
#
# Before screening, the script checks that the file's columns
# match the expected structure exactly. If they don't, it stops
# and asks you to fix the table first.
#
# Setup:
#   pip install anthropic
#   Set your API key as an environment variable:
#     export ANTHROPIC_API_KEY="sk-ant-..."
#   (or add ANTHROPIC_API_KEY = "sk-ant-..." to user_settings.py)
#
# Usage:
#   python screen_xlsx.py
#   python screen_xlsx.py --limit 10   # only the first 10 unscreened rows
#   python screen_xlsx.py --sleep 1.0  # extra delay between calls (seconds)
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
MAX_TOKENS   = 300
MAX_RETRIES  = 5
RETRY_BASE_S = 2.0   # exponential backoff base (seconds)

VALID_DECISIONS = {"Include", "Exclude", "Unclear"}

# Expected column structure of the xlsx file. If the file's columns
# don't match this exactly (same names, same order), the script stops
# and asks the user to fix the table before screening.
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


# ── Prompt ────────────────────────────────────────────────────

def build_prompt(review_query: str, title: str, abstract: str) -> str:
    return f"""You are screening a paper for a systematic literature review.

REVIEW QUERY (defines the population, intervention, outcome and study
design of interest for this review):
{review_query}

PAPER TITLE:
{title}

PAPER ABSTRACT:
{abstract}

Based STRICTLY on the title and abstract above, decide whether this paper
should be included in the review.

Respond in JSON only, with exactly these two keys and no other text:
{{"decision": "Include" | "Exclude" | "Unclear", "reason": "..."}}

- "Include": the paper clearly matches the review query.
- "Exclude": the paper clearly does not match the review query.
- "Unclear": there is not enough information in the title/abstract to decide.

Keep "reason" to one short sentence.
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


def screen_paper(
    client: "anthropic.Anthropic",
    review_query: str,
    title: str,
    abstract: str,
) -> tuple[str, str]:
    """
    Call the Anthropic API for a single paper.
    Returns (decision, reason). On unrecoverable error, returns
    ("Unclear", <error message>).
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

            decision = str(data.get("decision", "")).strip()
            reason   = str(data.get("reason", "")).strip()

            if decision not in VALID_DECISIONS:
                decision = "Unclear"
            if not reason:
                reason = "No reason provided by model."
            return decision, reason

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
            return "Unclear", "Could not parse model response."

        except Exception as e:
            print(f"    Unexpected error: {type(e).__name__}: {e}")
            return "Unclear", f"Unexpected error: {e}"

    print(f"    API call failed after {MAX_RETRIES} retries.")
    return "Unclear", "API call failed after retries."


# ── Main ──────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Screen papers in the final xlsx with the Anthropic API.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only screen the first N unscreened rows (for testing).")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="Extra delay (seconds) between API calls to stay under rate limits.")
    args = parser.parse_args()

    LOG_DIR.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path  = LOG_DIR / f"screening_xlsx_{timestamp}.log"
    log_file  = open(log_path, "w", encoding="utf-8")

    class _Tee:
        def write(self, data):
            sys.__stdout__.write(data)
            log_file.write(data)
        def flush(self):
            sys.__stdout__.flush()
            log_file.flush()

    sys.stdout = _Tee()

    print(f"Screening started : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Log file          : {log_path}")
    print(f"Model             : {MODEL}")

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

    actual_columns = list(df.columns)
    if actual_columns != EXPECTED_COLUMNS:
        print(f"\nERROR: '{DATA_PATH}' does not have the expected column structure.")
        print(f"\nExpected columns (in order):\n  {EXPECTED_COLUMNS}")
        print(f"\nFound columns (in order):\n  {actual_columns}")
        print(f"\nPlease fix the table so its columns match the expected structure exactly, then re-run.")
        sys.stdout = sys.__stdout__
        log_file.close()
        sys.exit(1)

    df["decision"] = df["decision"].astype("object")
    df["reason"]   = df["reason"].astype("object")

    client = anthropic.Anthropic(api_key=api_key)

    to_process = df.index[df["decision"].isna() | (df["decision"].astype(str).str.strip() == "")].tolist()
    if args.limit is not None:
        to_process = to_process[:args.limit]

    print(f"Total papers       : {len(df)}")
    print(f"Already screened   : {len(df) - len(df.index[df['decision'].isna() | (df['decision'].astype(str).str.strip() == '')])}")
    print(f"To screen this run : {len(to_process)}\n")

    for i, idx in enumerate(to_process, start=1):
        title    = str(df.at[idx, "title"]) if pd.notna(df.at[idx, "title"]) else ""
        abstract = str(df.at[idx, "abstract"]) if pd.notna(df.at[idx, "abstract"]) else ""

        if not abstract.strip():
            decision, reason = "Unclear", "No abstract available for screening."
        else:
            decision, reason = screen_paper(client, review_query, title, abstract)

        df.at[idx, "decision"] = decision
        df.at[idx, "reason"]   = reason

        short_title = title[:60] + "…" if len(title) > 60 else title
        print(f"  [{i:>4}/{len(to_process)}] {decision:<8} — {short_title}")

        df.to_excel(DATA_PATH, index=False)

        if args.sleep > 0:
            time.sleep(args.sleep)

    print(f"\nDone. Saved results to '{DATA_PATH}'.")
    print("\n── Decision summary ──")
    print(df["decision"].value_counts(dropna=False).to_string())
    print(f"\nScreening finished: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    sys.stdout = sys.__stdout__
    log_file.close()
    print(f"Log saved to '{log_path}'.")


if __name__ == "__main__":
    main()
