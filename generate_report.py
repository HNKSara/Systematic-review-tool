# =============================================================
# generate_report.py — Generate a PDF report from results/.
# Run:  python generate_report.py
# Output: results/report_YYYYMMDD_HHMMSS.pdf
# =============================================================

import datetime
import pathlib
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages
import pandas as pd

from config import CATEGORIZATION_DIMENSIONS, QUERY_GROUPS, START_YEAR, END_YEAR
from utils import compact_query

RESULTS_DIR    = pathlib.Path("results")
PAPERS_CSV     = RESULTS_DIR / "papers.csv"
FLAGGED_CSV    = RESULTS_DIR / "papers_flagged.csv"
VALIDATED_CSV  = RESULTS_DIR / "papers_validated.csv"
DUPLICATES_CSV = RESULTS_DIR / "Duplicates.csv"
SUMMARY_CSV    = RESULTS_DIR / "run_summary.csv"

# ── Palette ───────────────────────────────────────────────────
C_BLUE    = "#2c7bb6"
C_GREEN   = "#1a9641"
C_RED     = "#d7191c"
C_ORANGE  = "#fdae61"
C_GREY    = "#cccccc"
C_BG      = "#f4f6f9"
C_TEXT    = "#2d2d2d"
CHART_COLORS = [
    "#2c7bb6", "#1a9641", "#fdae61", "#d7191c",
    "#9C27B0", "#00BCD4", "#795548", "#FF5722",
]

PAGE_W, PAGE_H = 11.69, 8.27   # A4 landscape (inches)


def _load(path: pathlib.Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    except Exception:
        return None



def _normalize_categories(df: pd.DataFrame) -> pd.DataFrame:
    cat_cols = list(CATEGORIZATION_DIMENSIONS.keys())
    for col in cat_cols:
        if col in df.columns:
            df[col] = df[col].replace("", "Unclassified")
    return df


def _fig() -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(PAGE_W, PAGE_H))
    ax.axis("off")
    fig.patch.set_facecolor("white")
    return fig, ax


# ── Page builders ──────────────────────────────────────────────

def page_cover(pdf: PdfPages, df: pd.DataFrame) -> None:
    fig, ax = _fig()

    # Header bar
    fig.add_axes([0, 0.90, 1, 0.10]).set(facecolor=C_BLUE)
    plt.gca().axis("off")

    ax.text(0.5, 0.945, "Research Paper Analysis Report",
            ha="center", va="center", fontsize=22, fontweight="bold",
            color="white", transform=fig.transFigure)
    ax.text(0.5, 0.905, f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d  %H:%M')}",
            ha="center", va="center", fontsize=9, color="white",
            transform=fig.transFigure)

    dupes = _load(DUPLICATES_CSV)

    # ── Metric boxes ──────────────────────────────────────────
    metrics = [
        ("Total Papers", str(len(df) + (len(dupes) if dupes is not None else 0)), C_BLUE),
        ("Duplicates",   str(len(dupes)) if dupes is not None else "—",           C_RED),
        ("Final Papers", str(len(df)),                                            C_GREEN),
    ]

    n = len(metrics)
    box_w = 0.14
    gap   = (1.0 - n * box_w) / (n + 1)
    y_box = 0.78
    box_h = 0.10

    for i, (label, value, color) in enumerate(metrics):
        x = gap + i * (box_w + gap)
        rect = mpatches.FancyBboxPatch(
            (x, y_box), box_w, box_h,
            boxstyle="round,pad=0.01", linewidth=1.5,
            edgecolor=color, facecolor=color + "22",
            transform=fig.transFigure, clip_on=False,
        )
        fig.add_artist(rect)
        ax.text(x + box_w / 2, y_box + box_h * 0.65, value,
                ha="center", va="center", fontsize=18, fontweight="bold",
                color=color, transform=fig.transFigure)
        ax.text(x + box_w / 2, y_box + box_h * 0.20, label,
                ha="center", va="center", fontsize=8, color=C_TEXT,
                transform=fig.transFigure)

    # ── Query & date range ────────────────────────────────────
    q = compact_query(QUERY_GROUPS) if QUERY_GROUPS else "—"
    wrapped = "\n".join(textwrap.wrap(q, width=145))
    ax.text(0.04, 0.682, "Date range:",
            ha="left", va="top", fontsize=10, fontweight="bold",
            color=C_TEXT, transform=fig.transFigure)
    ax.text(0.18, 0.682, f"{START_YEAR} – {END_YEAR}",
            ha="left", va="top", fontsize=10, color="#555555",
            transform=fig.transFigure)
    ax.text(0.04, 0.658, "Query:",
            ha="left", va="top", fontsize=10, fontweight="bold",
            color=C_TEXT, transform=fig.transFigure)
    ax.text(0.13, 0.658, wrapped,
            ha="left", va="top", fontsize=9, color="#555555",
            transform=fig.transFigure, style="italic", linespacing=1.5,
            wrap=True, clip_on=True)

    # ── Run summary table ─────────────────────────────────────
    summary = _load(SUMMARY_CSV)
    if summary is not None:
        dupes_df = _load(DUPLICATES_CSV)
        per_db_dupes: dict[str, int] = {}
        if dupes_df is not None and "database" in dupes_df.columns:
            per_db_dupes = dupes_df["database"].value_counts().to_dict()

        display_cols = ["source", "papers_found", "duplicates_with_internal"]
        headers = ["Source", "Found", "Duplicates", "Final"]

        data = summary.reindex(columns=display_cols, fill_value="—")
        data["source"] = data["source"].apply(lambda s: s[:40] + "…" if len(s) > 40 else s)

        if per_db_dupes:
            def _fill_dupes(row):
                if str(row["duplicates_with_internal"]) in ("", "0", "—"):
                    return str(per_db_dupes.get(row["source"], 0))
                return row["duplicates_with_internal"]
            data["duplicates_with_internal"] = data.apply(_fill_dupes, axis=1)

        def _compute_final(row):
            try:
                return str(int(row["papers_found"]) - int(row["duplicates_with_internal"]))
            except (ValueError, TypeError):
                return "—"
        data["final"] = data.apply(_compute_final, axis=1)

        table_ax = fig.add_axes([0.04, 0.02, 0.50, 0.58])
        table_ax.axis("off")

        tbl = table_ax.table(
            cellText=data.values.tolist(),
            colLabels=headers,
            loc="center",
            cellLoc="center",
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(9)
        tbl.scale(1, 1.8)
        tbl.auto_set_column_width(col=list(range(len(headers))))

        for (row, col), cell in tbl.get_celld().items():
            if row == 0:
                cell.set_facecolor(C_BLUE)
                cell.set_text_props(color="white", fontweight="bold")
            elif row % 2 == 0:
                cell.set_facecolor("#eaf2fb")
            else:
                cell.set_facecolor("white")
            cell.set_edgecolor(C_GREY)

    # ── DB pie chart (right of table, small gap) ─────────────
    ax_pie = fig.add_axes([0.57, 0.08, 0.17, 0.52])
    src_counts = df["source"].value_counts()
    wedges, texts, autotexts = ax_pie.pie(
        src_counts.values, labels=src_counts.index,
        autopct="%1.0f%%", colors=CHART_COLORS[:len(src_counts)],
        startangle=140, pctdistance=0.78,
    )
    for t in texts + autotexts:
        t.set_fontsize(7)
    ax_pie.set_title("By Database", fontsize=8, fontweight="bold", color=C_TEXT)

    # ── Year bar chart (small gap from pie) ───────────────────
    ax_year = fig.add_axes([0.77, 0.10, 0.13, 0.17])
    year_counts = df["year"].value_counts().sort_index()
    bars = ax_year.bar(year_counts.index, year_counts.values, color=C_BLUE, edgecolor="white")
    ax_year.bar_label(bars, padding=1, fontsize=5)
    ax_year.set_title("By Year", fontsize=8, fontweight="bold", color=C_TEXT)
    ax_year.set_xlabel("Year", fontsize=6)
    ax_year.set_ylabel("Papers", fontsize=6)
    ax_year.tick_params(axis="x", rotation=45, labelsize=5)
    ax_year.tick_params(axis="y", labelsize=5)
    ax_year.spines[["top", "right"]].set_visible(False)
    ax_year.set_facecolor(C_BG)

    pdf.savefig(fig)
    plt.close(fig)


# ── Figure builders (used standalone or combined) ──────────────

def _build_year_and_source_fig(df: pd.DataFrame) -> plt.Figure:
    fig = plt.figure(figsize=(PAGE_W, PAGE_H))
    fig.patch.set_facecolor("white")
    fig.suptitle("Distribution by Year and Database", fontsize=16,
                 fontweight="bold", color=C_BLUE, y=0.97)

    ax1 = fig.add_subplot(1, 2, 1)
    year_counts = df["year"].value_counts().sort_index()
    bars = ax1.bar(year_counts.index, year_counts.values, color=C_BLUE, edgecolor="white")
    ax1.bar_label(bars, padding=3, fontsize=8)
    ax1.set_title("Papers by Year", fontsize=12, color=C_TEXT)
    ax1.set_xlabel("Year", fontsize=9)
    ax1.set_ylabel("Papers", fontsize=9)
    ax1.tick_params(axis="x", rotation=45, labelsize=8)
    ax1.spines[["top", "right"]].set_visible(False)
    ax1.set_facecolor(C_BG)

    ax2 = fig.add_subplot(1, 2, 2)
    src_counts = df["source"].value_counts()
    colors = CHART_COLORS[:len(src_counts)]
    wedges, texts, autotexts = ax2.pie(
        src_counts.values, labels=src_counts.index,
        autopct="%1.1f%%", colors=colors,
        startangle=140, pctdistance=0.75,
    )
    for t in texts + autotexts:
        t.set_fontsize(9)
    ax2.set_title("Papers by Database", fontsize=12, color=C_TEXT)

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    return fig


def _build_categories_fig(df: pd.DataFrame) -> plt.Figure | None:
    dims = [d for d in CATEGORIZATION_DIMENSIONS if d in df.columns]
    if not dims:
        return None

    n = len(dims)
    fig, axes = plt.subplots(1, n, figsize=(PAGE_W, PAGE_H))
    if n == 1:
        axes = [axes]
    fig.patch.set_facecolor("white")
    fig.suptitle("Category Distributions", fontsize=16,
                 fontweight="bold", color=C_BLUE, y=0.98)

    for ax, dim in zip(axes, dims):
        counts = df[dim].value_counts()
        total  = counts.sum()

        unclass = counts.pop("Unclassified") if "Unclassified" in counts else None
        if unclass is not None:
            counts["Unclassified"] = unclass

        labels = [f"{v}  ({c / total * 100:.1f}%)" for v, c in counts.items()]
        colors = CHART_COLORS[:len(counts) - (1 if unclass is not None else 0)] + (
            [C_GREY] if unclass is not None else []
        )

        bars = ax.barh(range(len(counts)), counts.values,
                       color=colors, edgecolor="white", height=0.6)
        ax.set_yticks(range(len(counts)))
        ax.set_yticklabels(labels, fontsize=8.5)
        ax.bar_label(bars, padding=4, fontsize=8, color=C_TEXT)
        ax.invert_yaxis()
        ax.set_title(dim.replace("_", " ").title(), fontsize=11,
                     fontweight="bold", color=C_TEXT, pad=10)
        ax.set_xlabel("Papers", fontsize=8.5)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(left=False)
        ax.set_facecolor(C_BG)
        ax.set_xlim(right=counts.values.max() * 1.18)

    plt.tight_layout(rect=[0, 0, 1, 0.94])
    return fig


def _build_validation_fig(df: pd.DataFrame) -> plt.Figure | None:
    flagged   = _load(FLAGGED_CSV)
    validated = _load(VALIDATED_CSV)
    if flagged is None and validated is None:
        return None

    fig = plt.figure(figsize=(PAGE_W, PAGE_H))
    fig.patch.set_facecolor("white")
    fig.suptitle("Validation Report", fontsize=16,
                 fontweight="bold", color=C_BLUE, y=0.97)

    total     = len(df)
    n_flagged = len(flagged) if flagged is not None else 0
    n_valid   = len(validated) if validated is not None else 0
    n_clean   = total - n_flagged

    for i, (label, value, color) in enumerate([
        ("Total",     total,           C_BLUE),
        ("Clean",     n_clean,         C_GREEN),
        ("Flagged",   n_flagged,       C_ORANGE),
        ("Validated", n_valid,         C_GREEN),
        ("Excluded",  total - n_valid, C_RED),
    ]):
        ax_box = fig.add_axes([0.05 + i * 0.19, 0.72, 0.15, 0.18])
        ax_box.set_facecolor(color + "22")
        for spine in ax_box.spines.values():
            spine.set_edgecolor(color)
            spine.set_linewidth(2)
        ax_box.set_xticks([]); ax_box.set_yticks([])
        ax_box.text(0.5, 0.60, str(value), ha="center", va="center",
                    fontsize=22, fontweight="bold", color=color,
                    transform=ax_box.transAxes)
        ax_box.text(0.5, 0.28, label, ha="center", va="center",
                    fontsize=9, color=C_TEXT, transform=ax_box.transAxes)

    if flagged is not None and "flags" in flagged.columns and len(flagged) > 0:
        _cat_prefixes = tuple(k + "=" for k in CATEGORIZATION_DIMENSIONS)
        all_flags: dict[str, int] = {}
        for flags_str in flagged["flags"]:
            raw = str(flags_str).replace(";", "|")
            for f in raw.split("|"):
                f = f.strip()
                if not f:
                    continue
                if f.startswith(_cat_prefixes):
                    f = "Unclassified"
                all_flags[f] = all_flags.get(f, 0) + 1

        if all_flags:
            ax_flags = fig.add_axes([0.08, 0.08, 0.84, 0.56])
            sorted_flags = sorted(all_flags.items(), key=lambda x: -x[1])
            labels  = [f[0] for f in sorted_flags]
            values  = [f[1] for f in sorted_flags]
            colors  = [C_RED if "abstract" in l or "authors" in l
                       else C_ORANGE if "DOI" in l or "URL" in l
                       else C_GREY for l in labels]
            bars = ax_flags.barh(range(len(labels)), values,
                                 color=colors, edgecolor="white", height=0.55)
            ax_flags.set_yticks(range(len(labels)))
            ax_flags.set_yticklabels(labels, fontsize=9)
            ax_flags.bar_label(bars, padding=4, fontsize=9)
            ax_flags.invert_yaxis()
            ax_flags.set_title("Flag Frequency", fontsize=11,
                               fontweight="bold", color=C_TEXT)
            ax_flags.set_xlabel("Papers flagged", fontsize=9)
            ax_flags.spines[["top", "right", "left"]].set_visible(False)
            ax_flags.tick_params(left=False)
            ax_flags.set_facecolor(C_BG)
            ax_flags.set_xlim(right=max(values) * 1.18)

    return fig


# ── Page wrappers (individual pages, kept for standalone use) ──

def page_year_and_source(pdf: PdfPages, df: pd.DataFrame) -> None:
    fig = _build_year_and_source_fig(df)
    pdf.savefig(fig)
    plt.close(fig)


def page_categories(pdf: PdfPages, df: pd.DataFrame) -> None:
    fig = _build_categories_fig(df)
    if fig is not None:
        pdf.savefig(fig)
        plt.close(fig)


def page_validation(pdf: PdfPages, df: pd.DataFrame) -> None:
    fig = _build_validation_fig(df)
    if fig is not None:
        pdf.savefig(fig)
        plt.close(fig)


def page_combined_last_three(pdf: PdfPages, df: pd.DataFrame) -> None:
    """Year+source, categories, and validation drawn directly as subplots on one page."""
    flagged   = _load(FLAGGED_CSV)
    validated = _load(VALIDATED_CSV)
    dims = [d for d in CATEGORIZATION_DIMENSIONS if d in df.columns]

    fig = plt.figure(figsize=(PAGE_W, PAGE_H))
    fig.patch.set_facecolor("white")
    fig.suptitle("Research Overview", fontsize=13, fontweight="bold",
                 color=C_BLUE, y=0.99)

    gs = fig.add_gridspec(1, 2, wspace=0.45, left=0.22, right=0.97,
                          top=0.93, bottom=0.07,
                          width_ratios=[1, 1.4])

    # ── Left: category charts ─────────────────────────────────
    if dims:
        gs_mid = gs[0].subgridspec(len(dims), 1, hspace=0.55)
        for idx, dim in enumerate(dims):
            ax_cat = fig.add_subplot(gs_mid[idx])
            counts = df[dim].value_counts()
            total  = counts.sum()
            unclass = counts.pop("Unclassified") if "Unclassified" in counts else None
            if unclass is not None:
                counts["Unclassified"] = unclass
            labels = [f"{v}  ({c / total * 100:.1f}%)" for v, c in counts.items()]
            clrs = CHART_COLORS[:len(counts) - (1 if unclass else 0)] + (
                [C_GREY] if unclass else []
            )
            bars = ax_cat.barh(range(len(counts)), counts.values,
                               color=clrs, edgecolor="white", height=0.6)
            ax_cat.set_yticks(range(len(counts)))
            ax_cat.set_yticklabels(labels, fontsize=7)
            ax_cat.bar_label(bars, padding=3, fontsize=7, color=C_TEXT)
            ax_cat.invert_yaxis()
            ax_cat.set_title(dim.replace("_", " ").title(), fontsize=10,
                             fontweight="bold", color=C_TEXT)
            ax_cat.set_xlabel("Papers", fontsize=7)
            ax_cat.spines[["top", "right", "left"]].set_visible(False)
            ax_cat.tick_params(left=False)
            ax_cat.set_facecolor(C_BG)
            ax_cat.set_xlim(right=counts.values.max() * 1.18)
    else:
        ax_empty = fig.add_subplot(gs[0])
        ax_empty.axis("off")

    # ── Right: validation boxes + flag chart ──────────────────
    gs_right = gs[1].subgridspec(2, 1, hspace=0.5, height_ratios=[1, 1.4])

    ax_boxes = fig.add_subplot(gs_right[0])
    ax_boxes.axis("off")
    ax_boxes.set_title("Validation Report", fontsize=10, fontweight="bold", color=C_BLUE)

    if flagged is not None or validated is not None:
        total     = len(df)
        n_flagged = len(flagged) if flagged is not None else 0
        n_valid   = len(validated) if validated is not None else 0
        n_clean   = total - n_flagged
        boxes_data = [
            ("Total",     total,           C_BLUE,   None),
            ("Clean",     n_clean,         C_GREEN,  None),
            ("Flagged",   n_flagged,       C_ORANGE, None),
            ("Validated", n_valid,         C_GREEN,  None),
            ("Excluded",  total - n_valid, C_RED,    None),
        ]
        nb = len(boxes_data)
        bw = 1.0 / nb - 0.03
        for i, (lbl, val, col, note) in enumerate(boxes_data):
            bx = i * (bw + 0.03) + 0.01
            rect = mpatches.FancyBboxPatch(
                (bx, 0.05), bw, 0.88,
                boxstyle="round,pad=0.02", linewidth=1.2,
                edgecolor=col, facecolor=col + "22",
                transform=ax_boxes.transAxes, clip_on=False,
            )
            ax_boxes.add_patch(rect)
            ax_boxes.text(bx + bw / 2, 0.62, str(val), ha="center", va="center",
                          fontsize=12, fontweight="bold", color=col,
                          transform=ax_boxes.transAxes)
            ax_boxes.text(bx + bw / 2, 0.30, lbl, ha="center", va="center",
                          fontsize=7, color=C_TEXT, transform=ax_boxes.transAxes)
            if note:
                ax_boxes.text(bx + bw / 2, 0.12, note, ha="center", va="center",
                              fontsize=5.5, color="#777777", style="italic",
                              transform=ax_boxes.transAxes)

    ax_flags = fig.add_subplot(gs_right[1])
    if flagged is not None and "flags" in flagged.columns and len(flagged) > 0:
        _cat_prefixes = tuple(k + "=" for k in CATEGORIZATION_DIMENSIONS)
        all_flags: dict[str, int] = {}
        for flags_str in flagged["flags"]:
            raw = str(flags_str).replace(";", "|")
            for f in raw.split("|"):
                f = f.strip()
                if not f:
                    continue
                if f.startswith(_cat_prefixes):
                    f = "Unclassified"
                all_flags[f] = all_flags.get(f, 0) + 1
        if all_flags:
            sorted_flags = sorted(all_flags.items(), key=lambda x: -x[1])
            flag_labels = [f[0] for f in sorted_flags]
            flag_values = [f[1] for f in sorted_flags]
            flag_colors = [C_RED if "abstract" in l or "authors" in l
                           else C_ORANGE if "DOI" in l or "URL" in l
                           else C_GREY for l in flag_labels]
            bars = ax_flags.barh(range(len(flag_labels)), flag_values,
                                 color=flag_colors, edgecolor="white", height=0.55)
            ax_flags.set_yticks(range(len(flag_labels)))
            ax_flags.set_yticklabels(flag_labels, fontsize=7)
            ax_flags.bar_label(bars, padding=3, fontsize=7)
            ax_flags.invert_yaxis()
            ax_flags.set_title("Flag Frequency", fontsize=10,
                               fontweight="bold", color=C_TEXT)
            ax_flags.set_xlabel("Papers flagged", fontsize=7)
            ax_flags.spines[["top", "right", "left"]].set_visible(False)
            ax_flags.tick_params(left=False)
            ax_flags.set_facecolor(C_BG)
            ax_flags.set_xlim(right=max(flag_values) * 1.18)
        else:
            ax_flags.axis("off")
    else:
        ax_flags.axis("off")

    pdf.savefig(fig)
    plt.close(fig)


# ── Main ──────────────────────────────────────────────────────

def generate(output_path: pathlib.Path | None = None) -> pathlib.Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    if output_path is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = RESULTS_DIR / f"report_{ts}.pdf"

    df = _load(PAPERS_CSV)
    if df is None:
        print(f"ERROR: '{PAPERS_CSV}' not found. Run main.py first.")
        raise SystemExit(1)

    df = _normalize_categories(df)

    print(f"Generating report → '{output_path}' ...")
    with PdfPages(output_path) as pdf:
        page_cover(pdf, df)
        print("  ✓ Cover page")
        page_combined_last_three(pdf, df)
        print("  ✓ Overview (year, categories, validation)")

        info = pdf.infodict()
        info["Title"]   = "Research Paper Analysis Report"
        info["Subject"] = f"Papers fetched {START_YEAR}–{END_YEAR}"
        info["Creator"] = "generate_report.py"

    print(f"\nReport saved to '{output_path}'.")
    return output_path


if __name__ == "__main__":
    generate()
