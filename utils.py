# =============================================================
# utils.py — Shared utilities used by main.py, merge_external.py,
#             and validate.py.
# =============================================================

import pathlib
import pandas as pd


class Tee:
    """Writes every print() to both the terminal and a log file simultaneously."""
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for s in self.streams:
            s.write(data)
    def flush(self):
        for s in self.streams:
            s.flush()


def compact_query(query_groups: list[list[str]]) -> str:
    """Build a compact human-readable query string from QUERY_GROUPS."""
    return " AND ".join("(" + " OR ".join(g) + ")" for g in query_groups)


def run_fetcher(fetch_fn, output_file: str) -> None:
    """Fetch, categorize, and save to CSV — used by each fetcher's __main__ block."""
    import pandas as pd
    from categorize import categorize_all
    results = categorize_all(fetch_fn())
    pd.DataFrame(results).to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"Saved {len(results)} papers to '{output_file}'.")


def write_run_summary(
    new_rows:  list[dict],
    columns:   list[str],
    csv_path:  str,
    overwrite: bool = False,
) -> None:
    """
    Print the run summary table and save it to csv_path.

    overwrite=True  — replace any existing file (used by main.py).
    overwrite=False — read existing rows first and append (used by merge_external.py).
    """
    existing_rows: list[dict] = []
    path = pathlib.Path(csv_path)

    if not overwrite and path.exists():
        try:
            existing_rows = (
                pd.read_csv(path, dtype=str, encoding="utf-8-sig")
                .fillna("")
                .to_dict("records")
            )
        except Exception as e:
            print(f"  WARNING: could not read '{csv_path}': {e}.")

    all_rows = existing_rows + new_rows
    df = pd.DataFrame(all_rows, columns=columns)

    print("\n" + "=" * 55)
    print("Run Summary")
    print("=" * 55)
    display = df.copy()
    if "query" in display.columns:
        display["query"] = display["query"].apply(
            lambda q: (str(q)[:60] + "…") if len(str(q)) > 60 else str(q)
        )
    print(display.to_string(index=False))

    try:
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"\nRun summary saved to '{csv_path}'.")
    except PermissionError:
        print(f"WARNING: could not write '{csv_path}' — file may be open.")
    except Exception as e:
        print(f"WARNING: could not write '{csv_path}': {e}")
