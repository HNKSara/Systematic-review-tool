# =============================================================
# __main__.py — Run the full pipeline in order:
#   1. main.py          — fetch, deduplicate, categorize
#   2. validate.py      — quality check on fetched papers
#   3. merge_external.py — merge CSVs from other_resources/
#   4. validate.py      — quality check on merged papers
#
# Usage:  python .
#         python -m GetPapersfromDifferentDBS
# =============================================================

import pathlib

# Skip merge step if other_resources/ is empty
OTHER_RESOURCES = pathlib.Path("other_resources")


def _separator(label: str) -> None:
    print("\n" + "=" * 55)
    print(f"  STEP: {label}")
    print("=" * 55 + "\n")


def run_pipeline() -> None:
    # ── Step 1: Fetch ─────────────────────────────────────────
    _separator("Fetch papers from all databases  (main.py)")
    from main import main as fetch_main
    fetch_main()

    # ── Step 2: Validate fetched papers ───────────────────────
    _separator("Validate fetched papers  (validate.py)")
    from validate import run as validate_run
    validate_run()

    # ── Step 3: Merge external CSVs (if any) ──────────────────
    has_external = any(OTHER_RESOURCES.glob("*.csv")) if OTHER_RESOURCES.exists() else False

    if has_external:
        _separator("Merge external CSVs  (merge_external.py)")
        from merge_external import main as merge_main
        merge_main()

        # ── Step 4: Re-validate after merge ───────────────────
        _separator("Re-validate after merge  (validate.py)")
        validate_run()
    else:
        print(f"\nNo CSV files found in '{OTHER_RESOURCES}/' — skipping merge step.")

    # ── Final summary ─────────────────────────────────────────
    from config import RUN_SUMMARY_CSV, RUN_SUMMARY_COLUMNS
    from utils import write_run_summary

    summary_path = pathlib.Path(RUN_SUMMARY_CSV)
    if summary_path.exists():
        try:
            _separator("Pipeline complete — Run Summary")
            write_run_summary([], RUN_SUMMARY_COLUMNS, RUN_SUMMARY_CSV, overwrite=False)
        except Exception:
            pass

    # ── PDF report ────────────────────────────────────────────
    _separator("Generating PDF report  (generate_report.py)")
    from generate_report import generate
    generate()


if __name__ == "__main__":
    run_pipeline()
