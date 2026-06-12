# =============================================================
# download_papers.py — Download PDFs from papers_validated.csv
#
# For each paper in results/papers_validated.csv:
#   - Groups papers by database (source column)
#   - Creates results/downloaded_papers/<source>/ subfolders
#   - Renames files as  <index>_<sanitized_title>.pdf
#     where index is the paper's order within its source group
#   - Skips individual files that already exist (safe to re-run)
#
# PDF resolution strategy (tried in order):
#   1. ArXiv  — convert abstract URL to direct PDF URL
#   2. Unpaywall API — searches ALL open-access locations for a
#      direct pdf URL (catches ArXiv preprints of Scopus/IEEE papers)
#   3. Publisher patterns — Springer (10.1007/10.1186), Frontiers (10.3389)
#   4. Landing page scrape — follow doi_url/url, read the
#      <meta name="citation_pdf_url"> tag that most publishers embed
#   5. doi_url / url as a direct download attempt
#
# Run:  python download_papers.py
# =============================================================

import json
import re
import sys
import time
import datetime
import pathlib

import pandas as pd
import requests

VALIDATED_CSV  = "results/papers_validated.csv"
DOWNLOAD_DIR   = pathlib.Path("results/downloaded_papers")
LOG_DIR        = pathlib.Path("logs")

# Email required by Unpaywall's terms of use (no API key needed)
UNPAYWALL_EMAIL = "maral.nikfar@gmail.com"

REQUEST_DELAY   = 1.0   # seconds between requests
REQUEST_TIMEOUT = 30    # seconds per request

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ── Helpers ───────────────────────────────────────────────────

def sanitize_filename(text: str, max_len: int = 80) -> str:
    text = re.sub(r'[\\/*?:"<>|]', "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:max_len]


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(BROWSER_HEADERS)
    return s


# ── PDF URL strategies ────────────────────────────────────────

def arxiv_pdf_url(abstract_url: str) -> str:
    url = abstract_url.replace("http://", "https://")
    url = url.replace("/abs/", "/pdf/")
    if not url.endswith(".pdf"):
        url += ".pdf"
    return url


def unpaywall_pdf_url(doi: str, session: requests.Session) -> str:
    """
    Query Unpaywall across ALL open-access locations for a direct PDF URL.
    Searching all locations (not just best_oa_location) finds ArXiv
    preprints that Scopus/IEEE/PubMed papers often have.
    """
    if not doi:
        return ""
    try:
        api_url = f"https://api.unpaywall.org/v2/{doi.strip()}?email={UNPAYWALL_EMAIL}"
        r = session.get(api_url, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return ""
        data = r.json()
        for loc in data.get("oa_locations", []):
            pdf = loc.get("url_for_pdf")
            if pdf:
                return pdf
        return ""
    except Exception:
        return ""


def publisher_pdf_url(doi: str, session: requests.Session) -> str:
    """
    Direct PDF URL for known open-access publisher patterns.
    Springer link.springer.com works for 10.1007 and some 10.1186.
    Frontiers requires following the DOI redirect and replacing /full → /pdf.
    """
    if not doi:
        return ""
    if doi.startswith("10.1007") or doi.startswith("10.1186"):
        return f"https://link.springer.com/content/pdf/{doi}.pdf"
    if doi.startswith("10.3389"):
        try:
            r = session.get(f"https://doi.org/{doi}", timeout=REQUEST_TIMEOUT,
                            allow_redirects=True)
            canonical = r.url
            if "/full" in canonical:
                return canonical.replace("/full", "/pdf")
            return canonical.rstrip("/") + "/pdf"
        except Exception:
            return ""
    return ""


def landing_page_pdf_url(page_url: str, session: requests.Session) -> str:
    """
    Visit a publisher landing page and extract the PDF URL from the
    <meta name="citation_pdf_url"> tag — a standard tag that most
    academic publishers embed so Google Scholar can index the PDF.
    Returns empty string when the tag is absent or the request fails.
    """
    if not page_url:
        return ""
    try:
        r = session.get(page_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        for pat in [
            r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url',
        ]:
            m = re.findall(pat, r.text, re.I)
            if m:
                return m[0]
        return ""
    except Exception:
        return ""


def is_pdf(response: requests.Response) -> bool:
    ct = response.headers.get("Content-Type", "")
    return "application/pdf" in ct or response.content[:4] == b"%PDF"


def try_download(url: str, dest: pathlib.Path, session: requests.Session) -> bool:
    """Download url → dest. Returns True only if response is a real PDF."""
    if not url:
        return False
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True,
                        headers={"Accept": "application/pdf,*/*"})
        if not is_pdf(r):
            return False
        dest.write_bytes(r.content)
        return True
    except Exception:
        return False


# ── Main ──────────────────────────────────────────────────────

def download(validated_csv: str = VALIDATED_CSV) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path  = LOG_DIR / f"download_{timestamp}.log"

    log_file = open(log_path, "w", encoding="utf-8")

    class _Tee:
        def write(self, data):
            sys.__stdout__.write(data)
            log_file.write(data)
        def flush(self):
            sys.__stdout__.flush()
            log_file.flush()

    sys.stdout = _Tee()

    print(f"Download started : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Log file         : {log_path}")

    if not pathlib.Path(validated_csv).exists():
        print(f"File not found: {validated_csv}")
        print("Run validate.py first.")
        sys.stdout = sys.__stdout__
        log_file.close()
        return

    df = pd.read_csv(validated_csv, dtype=str).fillna("")
    print(f"Papers loaded    : {len(df)}")

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    session = _make_session()

    total_ok = total_skip = total_fail = 0

    for source, group in df.groupby("source", sort=False):
        source_dir = DOWNLOAD_DIR / sanitize_filename(str(source))
        source_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n── {source}  ({len(group)} papers)  → {source_dir}")

        ok = skip = fail = 0

        for local_idx, (_, row) in enumerate(group.iterrows(), start=1):
            title = str(row.get("title", "untitled"))
            fname = f"{local_idx}_{sanitize_filename(title)}.pdf"
            dest  = source_dir / fname

            # Per-file skip: safe to re-run after a partial download
            if dest.exists() and dest.stat().st_size > 0:
                print(f"  [{local_idx:>4}] SKIP (exists) — {fname}")
                skip += 1
                continue

            src   = str(row.get("source",  "")).strip()
            doi   = str(row.get("doi",     "")).strip()
            url   = str(row.get("url",     "")).strip()
            doi_url = str(row.get("doi_url", "")).strip()

            # ── Build candidate list ──────────────────────────
            candidates: list[tuple[str, str]] = []   # (label, url)

            if src == "ArXiv" and url:
                candidates.append(("arxiv-pdf", arxiv_pdf_url(url)))
            else:
                oa = unpaywall_pdf_url(doi, session)
                if oa:
                    candidates.append(("unpaywall", oa))
                time.sleep(REQUEST_DELAY)

                pub = publisher_pdf_url(doi, session)
                if pub:
                    candidates.append(("publisher-pattern", pub))

                # Landing page scrape: use doi_url for PubMed (URL points to
                # PubMed database page, not the publisher), url for others
                page_for_scrape = doi_url or url or (f"https://doi.org/{doi}" if doi else "")
                if page_for_scrape:
                    lp = landing_page_pdf_url(page_for_scrape, session)
                    if lp and lp not in [c[1] for c in candidates]:
                        candidates.append(("landing-page-meta", lp))
                    time.sleep(REQUEST_DELAY)

            if doi_url and doi_url not in [c[1] for c in candidates]:
                candidates.append(("doi_url-direct", doi_url))
            if url and url not in [c[1] for c in candidates]:
                candidates.append(("url-direct", url))
            if doi and not doi_url and not url:
                candidates.append(("doi-fallback", f"https://doi.org/{doi}"))

            # ── Try each candidate ────────────────────────────
            downloaded = False
            used_label = ""
            for label, cand_url in candidates:
                if try_download(cand_url, dest, session):
                    downloaded = True
                    used_label = label
                    break
                time.sleep(REQUEST_DELAY)

            if downloaded:
                size_kb = dest.stat().st_size // 1024
                print(f"  [{local_idx:>4}] OK   {size_kb:>5} KB  [{used_label}] — {fname}")
                ok += 1
            else:
                if not candidates:
                    reason = "no URL available"
                else:
                    reason = "all sources failed (bot-protected or paywalled)"
                print(f"  [{local_idx:>4}] FAIL ({reason}) — {fname}")
                fail += 1

            time.sleep(REQUEST_DELAY)

        total_ok   += ok
        total_skip += skip
        total_fail += fail
        print(f"  → {ok} downloaded, {skip} skipped (exists), {fail} failed")

    # ── Summary ───────────────────────────────────────────────
    print("\n" + "=" * 55)
    print("Download summary")
    print("=" * 55)
    print(f"  Downloaded : {total_ok}")
    print(f"  Skipped    : {total_skip}  (already on disk)")
    print(f"  Failed     : {total_fail}  (bot-protected or paywalled)")
    print(f"  Output     : {DOWNLOAD_DIR.resolve()}")
    print(f"\nDownload finished: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    sys.stdout = sys.__stdout__
    log_file.close()
    print(f"Log saved to '{log_path}'.")


if __name__ == "__main__":
    download()
