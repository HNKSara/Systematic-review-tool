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


def _group_duplicate_records(records: list[tuple[str, str, str]]):
    """
    Union-Find grouping of records that share a non-empty DOI or an
    identical (lowercased, stripped) title — the same rule used elsewhere
    in the pipeline to detect duplicates.

    records: list of (source_label, title, doi).
    Returns (norm, groups) where:
      - norm:   [(label, title, doi_norm, title_norm), ...] — one per record
      - groups: dict mapping a group's root index to the list of member
                indices (every record sharing identity ends up in one group)
    """
    norm = [
        (label, title, (doi or "").strip().lower(), (title or "").strip().lower())
        for label, title, doi in records
    ]

    parent = list(range(len(norm)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    doi_first:   dict[str, int] = {}
    title_first: dict[str, int] = {}
    for i, (_, _, doi_norm, title_norm) in enumerate(norm):
        if doi_norm:
            if doi_norm in doi_first:
                union(i, doi_first[doi_norm])
            else:
                doi_first[doi_norm] = i
        if title_norm:
            if title_norm in title_first:
                union(i, title_first[title_norm])
            else:
                title_first[title_norm] = i

    groups: dict[int, list[int]] = {}
    for i in range(len(norm)):
        groups.setdefault(find(i), []).append(i)

    return norm, groups


def duplicate_source_labels(records: list[tuple[str, str, str]]) -> dict[str, str]:
    """
    Map each duplicated paper's normalized identity (its DOI if present,
    else its lowercased/stripped title) to a dash-joined, sorted, de-duplicated
    string of every source label the paper was found in — e.g. "PubMed-Scopus".

    records: list of (source_label, title, doi). Only papers found in 2+
    distinct sources are included in the returned lookup.
    """
    norm, groups = _group_duplicate_records(records)

    lookup: dict[str, str] = {}
    for idxs in groups.values():
        labels = sorted({norm[i][0] for i in idxs})
        if len(labels) < 2:
            continue
        combo = "-".join(labels)
        for i in idxs:
            _, _, doi_norm, title_norm = norm[i]
            key = doi_norm or title_norm
            if key:
                lookup[key] = combo

    return lookup


def build_duplicate_matrix(records: list[tuple[str, str, str]]):
    """
    Compute a pairwise duplicate matrix from (source_label, title, doi) records.

    records: list of (source_label, title, doi) — one entry per paper,
    e.g. [("Scopus", "Some Paper", "10.1000/xyz"), ("ArXiv", "Some Paper", "")].
    Two papers are considered the same if they share a non-empty DOI or an
    identical (lowercased, stripped) title — the same rule used elsewhere
    in the pipeline to detect duplicates.

    Returns None if fewer than two distinct source labels are present, else
    (labels, matrix, counts_by_label, overall_dup, dup_groups) where:
      - labels:          sorted list of source labels
      - matrix[a][b]:    number of papers from source `a` also found in `b`
                         (for a == b: number of papers duplicated *within*
                         that same source, i.e. self-duplicates)
      - counts_by_label: total papers fetched per source
      - overall_dup[a]:  set of record indices from `a` that are duplicated
                         in at least one other source
      - dup_groups:      list of (source_combo_tuple, title) for every paper
                         that appears in 2+ sources
    """
    from itertools import combinations
    from collections import Counter

    norm, groups = _group_duplicate_records(records)
    labels = sorted({label for label, _, _, _ in norm})
    if len(labels) < 2:
        return None

    dup_groups = []
    for idxs in groups.values():
        db_set = tuple(sorted({norm[i][0] for i in idxs}))
        if len(db_set) > 1:
            dup_groups.append((db_set, norm[idxs[0]][1]))

    # ── Pairwise matrix ────────────────────────────────────────
    counts_by_label = Counter(label for label, _, _, _ in norm)
    matrix = {a: {b: 0 for b in labels} for a in labels}
    overall_dup = {a: set() for a in labels}

    # Diagonal: self-duplicates — papers duplicated within the same source
    for a in labels:
        seen_dois:   set[str] = set()
        seen_titles: set[str] = set()
        self_dups = 0
        for i, (label, _title, doi_norm, title_norm) in enumerate(norm):
            if label != a:
                continue
            if (doi_norm and doi_norm in seen_dois) or (title_norm and title_norm in seen_titles):
                self_dups += 1
                continue
            if doi_norm:
                seen_dois.add(doi_norm)
            if title_norm:
                seen_titles.add(title_norm)
        matrix[a][a] = self_dups

    for a, b in combinations(labels, 2):
        idx_a = [i for i, (l, *_rest) in enumerate(norm) if l == a]
        idx_b = [i for i, (l, *_rest) in enumerate(norm) if l == b]
        doi_a   = {norm[i][2] for i in idx_a if norm[i][2]}
        doi_b   = {norm[i][2] for i in idx_b if norm[i][2]}
        title_a = {norm[i][3] for i in idx_a if norm[i][3]}
        title_b = {norm[i][3] for i in idx_b if norm[i][3]}
        doi_overlap, title_overlap = doi_a & doi_b, title_a & title_b

        match_a = [i for i in idx_a
                   if (norm[i][2] and norm[i][2] in doi_overlap)
                   or (norm[i][3] and norm[i][3] in title_overlap)]
        match_b = [i for i in idx_b
                   if (norm[i][2] and norm[i][2] in doi_overlap)
                   or (norm[i][3] and norm[i][3] in title_overlap)]
        matrix[a][b] = len(match_a)
        matrix[b][a] = len(match_b)
        overall_dup[a].update(match_a)
        overall_dup[b].update(match_b)

    return labels, matrix, counts_by_label, overall_dup, dup_groups


def print_duplicate_overview(records: list[tuple[str, str, str]]) -> None:
    """
    Print a pairwise duplicate matrix and a grouped listing of every paper
    that appears in 2+ sources, tagged with ALL the sources it was found in.

    records: list of (source_label, title, doi) — one entry per paper,
    e.g. [("Scopus", "Some Paper", "10.1000/xyz"), ("ArXiv", "Some Paper", "")].
    """
    from collections import Counter

    result = build_duplicate_matrix(records)
    if result is None:
        return
    labels, matrix, counts_by_label, overall_dup, dup_groups = result

    col_w = max(8, max(len(l) for l in labels) + 2)
    header = " " * (col_w + 2) + "".join(f"{l:>{col_w}}" for l in labels) + f"{'fetched':>{col_w}}"
    print("\nDuplicate matrix — cell[row, col] = papers from ROW also found in COL")
    print("(diagonal = papers duplicated within that same source)\n")
    print(header)
    print("-" * len(header))
    for a in labels:
        row = f"{a:<{col_w + 2}}"
        for b in labels:
            cell = matrix[a][b]
            row += f"{cell if (a != b or cell) else '—':>{col_w}}"
        row += f"{counts_by_label[a]:>{col_w}}"
        print(row)
    print("-" * len(header))
    total_row = f"{'Duplicates':<{col_w + 2}}"
    for a in labels:
        total_row += f"{len(overall_dup[a]):>{col_w}}"
    print(total_row)
    print(f"{'(unique to it)':<{col_w + 2}}" +
          "".join(f"{counts_by_label[a] - len(overall_dup[a]):>{col_w}}" for a in labels))

    # ── Grouped listing ────────────────────────────────────────
    if dup_groups:
        combo_counts = Counter(g[0] for g in dup_groups)
        print(f"\nDuplicate groups by source combination ({len(dup_groups)} paper(s) total):\n")
        for combo, count in sorted(combo_counts.items(), key=lambda x: (-x[1], x[0])):
            print(f"  [{', '.join(combo)}]: {count} paper(s)")

        dup_groups.sort(key=lambda g: (-len(g[0]), g[0]))
        print("\nEach duplicated paper, tagged with every source it was found in:\n")
        for db_set, title in dup_groups:
            tag = "[" + ", ".join(db_set) + "]"
            short = title if len(title) <= 88 else title[:85] + "..."
            print(f"  {tag:<28s} {short}")
    print()


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
