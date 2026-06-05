# =============================================================
# categorize.py — Assign category labels to papers
# Uses keyword matching on title + abstract (case-insensitive).
# All dimensions and keywords are defined in config.py.
# =============================================================

from config import CATEGORIZATION_DIMENSIONS


def categorize_paper(paper: dict, dimensions: dict = CATEGORIZATION_DIMENSIONS) -> dict:
    """
    Add one key per dimension to the paper dict.
    Value is the first matching category label, or "Unclassified".
    """
    text = (paper.get("title", "") + " " + paper.get("abstract", "")).lower()

    for dimension, categories in dimensions.items():
        paper[dimension] = "Unclassified"
        for label, keywords in categories.items():
            if any(kw.lower() in text for kw in keywords):
                paper[dimension] = label
                break  # first match wins; reorder categories in config.py to change priority

    return paper


def categorize_all(papers: list[dict]) -> list[dict]:
    """Apply categorize_paper to every paper in the list."""
    return [categorize_paper(p) for p in papers]


def summarize(papers: list[dict]) -> None:
    """Print a simple count breakdown per dimension."""
    for dimension in CATEGORIZATION_DIMENSIONS:
        counts: dict[str, int] = {}
        for p in papers:
            label = p.get(dimension, "Unclassified")
            counts[label] = counts.get(label, 0) + 1
        print(f"\n── {dimension} ──")
        for label, count in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"  {label}: {count}")


if __name__ == "__main__":
    # Quick smoke test with a dummy paper
    dummy = {
        "title":    "Explainable Multi-Agent AI for Safe Clinical Decision Support",
        "abstract": "We propose a transparent, privacy-preserving multi-agent system "
                    "for clinical decision support in hospital settings.",
        "source":   "test",
    }
    result = categorize_paper(dummy)
    for k, v in result.items():
        print(f"{k}: {v}")
