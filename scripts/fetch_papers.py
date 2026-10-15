#!/usr/bin/env python3
"""Fetch recent working papers from several sources into docs/papers.json.

Sources:
  NBER          nber.org listing API (+ paper page for the full abstract)
  Fed           Federal Reserve Board FEDS and IFDP RSS feeds
  ECB           ECB working paper RSS feed
  CEPR, IMF,    RePEc/IDEAS series listings (+ paper page for the abstract);
  PIIE, Kiel    their own sites block automated access

The source sites don't allow browser (CORS) requests, so this runs ahead of time
(locally or in the GitHub Action) and the site reads the JSON it writes.
Papers already in papers.json are reused, so daily runs only fetch new ones.
If one source fails, its previously fetched papers are kept.

Env vars:
  MAX_PAPERS         newest NBER papers to keep (default 1000)
  MAX_PER_SOURCE     newest papers to keep for each other source (default 150)
  ANTHROPIC_API_KEY  optional; if set, summaries are written by Claude,
                     otherwise the first couple of sentences of the abstract are used
"""

import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "papers.json"
MAX_PAPERS = int(os.environ.get("MAX_PAPERS", "1000"))
MAX_PER_SOURCE = int(os.environ.get("MAX_PER_SOURCE", "150"))
HEADERS = {"User-Agent": "nber-tinder/1.0 (personal paper browser; github.com/dklinenberg2020/nber_tinder)"}

NBER_LISTING = (
    "https://www.nber.org/api/v1/working_page_listing/contentType/working_paper"
    "/_/_/search?page={page}&perPage={per_page}"
)
FED_FEEDS = {
    "FEDS": "https://www.federalreserve.gov/feeds/feds.xml",
    "IFDP": "https://www.federalreserve.gov/feeds/ifdp.xml",
}
ECB_FEED = "https://www.ecb.europa.eu/rss/wppub.html"
IDEAS_SERIES = {  # source label -> RePEc series path on ideas.repec.org
    "CEPR": "cpr/ceprdp",
    "IMF": "imf/imfwpa",
    "PIIE": "iie/wpaper",
    "Kiel": "zbw/ifwkwp",
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


# ---------- helpers ----------

def get(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:  # network hiccups: back off and retry
            if attempt == retries - 1:
                raise
            print(f"  retry {url}: {e}", file=sys.stderr)
            time.sleep(2 ** attempt)


MOJIBAKE = re.compile("[Â-ô][\u0080-¿ŒœŠšŸŽžƒˆ˜"
                      "–—‘-„†-•…‰‹›€™]{1,3}")


def fix_mojibake(s):
    """IDEAS sometimes serves doubly UTF-8-encoded text ("nonâ€‘benchmarked").

    Repaired piece by piece, so one unrecoverable character doesn't block the rest.
    """
    def repair(m):
        for enc in ("cp1252", "latin-1"):
            try:
                return m.group(0).encode(enc).decode("utf-8")
            except UnicodeError:
                pass
        return m.group(0)

    s = s.replace("â€\u009d", "”")
    s = MOJIBAKE.sub(repair, s)
    return re.sub(r"â€(?=\W|$)", "”", s)  # closing quote whose last byte (0x9d) was dropped


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return fix_mojibake(re.sub(r"\s+", " ", html.unescape(text)).strip())


def display_date(date):
    """'2026-09-14' or '2026-09' -> 'September 2026'."""
    m = re.match(r"(\d{4})-(\d{2})", date or "")
    return f"{MONTHS[int(m.group(2)) - 1]} {m.group(1)}" if m else (date or "")[:4]


def rss_date(s):
    try:
        return email.utils.parsedate_to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        return ""


def paper(pid, source, title, authors, date, url, abstract, keywords=""):
    return {
        "id": pid,
        "source": source,
        "title": clean(title),
        "authors": [clean(a) for a in authors if clean(a)],
        "year": (date or "")[:4],
        "date": date or "",
        "displaydate": display_date(date),
        "url": url,
        "abstract": clean(abstract),
        "keywords": clean(keywords),
    }


# ---------- sources ----------
# Each source returns (stubs, detail): stubs newest-first, each with an "id";
# detail(stub) returns the full paper. Stubs already in papers.json are not refetched.

def nber_source():
    entries, page, per_page = [], 1, 100
    while len(entries) < MAX_PAPERS:
        data = json.loads(get(NBER_LISTING.format(page=page, per_page=per_page)))
        results = data.get("results", [])
        if not results:
            break
        for r in results:
            if r.get("url", "").startswith("/papers/"):
                r["id"] = r["url"].rsplit("/", 1)[-1]  # e.g. w35885 (kept unprefixed: saved swipes use it)
                entries.append(r)
        page += 1

    def detail(entry):
        url = "https://www.nber.org" + entry["url"]
        abstract, date = entry.get("abstract"), ""
        try:
            page_html = get(url)
            m = re.search(r'page-header__intro-inner">\s*<p>(.*?)</p>', page_html, re.S)
            if m:
                abstract = m.group(1)
            m = re.search(r'citation_publication_date" content="(\d{4})/(\d{2})/(\d{2})', page_html)
            if m:
                date = "-".join(m.groups())
        except Exception as e:
            print(f"  could not fetch {url}: {e}", file=sys.stderr)
        if not date:
            m = re.search(r"(\w+) (\d{4})", entry.get("displaydate", ""))
            if m and m.group(1) in MONTHS:
                date = f"{m.group(2)}-{MONTHS.index(m.group(1)) + 1:02d}"
        return paper(entry["id"], "NBER", entry.get("title"), entry.get("authors", []), date, url, abstract)

    return entries[:MAX_PAPERS], detail


def fed_source():
    stubs = []
    for series, feed in FED_FEEDS.items():
        for item in ET.fromstring(get(feed)).iter("item"):
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "")
            authors_html, _, abstract = desc.partition("<br><br>")
            authors = re.split(r",\s*(?:and\s+)?|\s+and\s+", clean(authors_html))
            title = re.sub(r"^(FEDS|IFDP) (Paper|Note)s?:\s*", "", item.findtext("title", ""))
            slug = link.rstrip("/").rsplit("/", 1)[-1].removesuffix(".htm")
            stubs.append(paper(f"fed:{slug}", f"Fed {series}", title, authors,
                               rss_date(item.findtext("pubDate", "")), link, abstract))
    stubs.sort(key=lambda p: p["date"], reverse=True)
    return stubs, lambda p: p


def ecb_source():
    stubs = []
    for item in ET.fromstring(get(ECB_FEED)).iter("item"):
        link = item.findtext("link", "").strip().replace("europa.eu//", "europa.eu/")
        m = re.search(r"wp(\d+)", link)
        pid = f"ecb:{m.group(1)}" if m else "ecb:" + link
        stubs.append(paper(pid, "ECB", item.findtext("title", ""), [],
                           rss_date(item.findtext("pubDate", "")), link, item.findtext("description", "")))
    return stubs, lambda p: p


def ideas_source(label, series):
    listing = get(f"https://ideas.repec.org/s/{series}.html")
    listing = listing[listing.find("<h2>Content"):]
    stubs = []
    for m in re.finditer(r'<B>[^<]*<A HREF="(/p/[^"]+\.html)">(.*?)</A></B>', listing):
        handle = m.group(1).rsplit("/", 1)[-1].removesuffix(".html")
        stubs.append({"id": f"{label.lower()}:{handle}", "path": m.group(1), "title": m.group(2)})

    def detail(stub):
        url = "https://ideas.repec.org" + stub["path"]
        page_html = get(url)
        time.sleep(0.3)  # be polite to IDEAS

        def meta(name):
            m = re.search(rf'<META NAME="{name}" CONTENT="([^"]*)"', page_html, re.I)
            return html.unescape(m.group(1)) if m else ""

        m = re.search(r'<div id="abstract-body">(.*?)</div>', page_html, re.S)
        abstract = m.group(1) if m else ""
        date = (meta("citation_publication_date") or meta("date")).replace("/", "-")[:10]
        if not re.match(r"\d{4}(-(0[1-9]|1[0-2])(-\d\d)?)?$", date):  # e.g. "2019-13" on some entries
            date = date[:4]
        # "Last, First & Last, First" -> ["First Last", ...]
        authors = [" ".join(reversed([x.strip() for x in a.split(",", 1)])) for a in meta("author").split(" & ")]
        keywords = "; ".join(x for x in (meta("keywords"), "JEL: " + meta("jel_code") if meta("jel_code") else "") if x)
        return paper(stub["id"], label, meta("title") or stub["title"], authors, date, url, abstract, keywords)

    return stubs[:MAX_PER_SOURCE], detail


SOURCES = {
    "NBER": nber_source,
    "Fed": fed_source,
    "ECB": ecb_source,
    **{label: (lambda label=label, series=series: ideas_source(label, series)) for label, series in IDEAS_SERIES.items()},
}


# ---------- summaries ----------

def extractive_summary(abstract, limit=420):
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", abstract)
    out = ""
    for s in sentences:
        if out and len(out) + len(s) > limit:
            break
        out = f"{out} {s}".strip()
    return out if len(out) <= limit + 80 else out[:limit].rsplit(" ", 1)[0] + "…"


def make_summarizer():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic

    client = anthropic.Anthropic()

    def summarize(p):
        response = client.messages.create(
            model="claude-opus-5-5",
            max_tokens=1024,
            output_config={"effort": "low"},
            system=(
                "You summarize economics working papers for someone deciding whether to read them. "
                "Reply with one or two plain sentences (max ~45 words) stating the question and the "
                "main finding. No preamble, no markdown."
            ),
            messages=[{"role": "user", "content": f"Title: {p['title']}\n\nAbstract: {p['abstract']}"}],
        )
        if response.stop_reason == "refusal":
            return None
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or None

    return summarize


# ---------- main ----------

def approx_sort_date(year, backfill):
    """Sort position for a paper whose date is only a year.

    Seen for the first time in a later daily run: it just came out, so today.
    Part of the first fetch of a source: middle of that year (or of the year so far).
    """
    today = time.strftime("%Y-%m-%d")
    if not year or year >= today[:4]:
        if not backfill:
            return today
        return f"{today[:4]}-{max(1, int(today[5:7]) // 2):02d}-15"
    return f"{year}-07-01"


def source_of(p):
    s = p.get("source", "NBER")
    return "Fed" if s.startswith("Fed") else s


def main():
    existing = {}
    if OUT.exists():
        data = json.loads(OUT.read_text())
        for p in data["papers"] + data.get("duplicates", []):
            p.setdefault("source", "NBER")
            existing[p["id"]] = p

    result = []
    for name, make in SOURCES.items():
        old = [p for p in existing.values() if source_of(p) == name]
        cap = MAX_PAPERS if name == "NBER" else MAX_PER_SOURCE
        try:
            stubs, detail = make()
            new = [s for s in stubs if s["id"] not in existing]
            print(f"{name}: {len(stubs)} listed, {len(new)} new")
            workers = 2 if name in IDEAS_SERIES else 4
            with ThreadPoolExecutor(max_workers=workers) as pool:
                fetched = {p["id"]: p for p in pool.map(lambda s: _safe(detail, s), new) if p}
            for p in fetched.values():
                p["summary"], p["ai_summary"] = extractive_summary(p["abstract"]), False
                if len(p["date"]) < 7:  # year-only date (some IDEAS series): estimate where it sorts
                    p["sort_date"] = approx_sort_date(p["year"], backfill=not old)
            by_id = {p["id"]: p for p in old} | fetched
            # current listing first, then older papers that dropped off the listing/feed
            listed = [by_id[s["id"]] for s in stubs if s["id"] in by_id]
            listed_ids = {p["id"] for p in listed}
            rest = sorted((p for p in old if p["id"] not in listed_ids), key=lambda p: p["date"], reverse=True)
            result += (listed + rest)[:cap]
        except Exception as e:
            print(f"{name}: FAILED ({e}); keeping {len(old)} previously fetched papers", file=sys.stderr)
            result += old

    for p in result:
        p.setdefault("summary", extractive_summary(p.get("abstract", "")))
        p.setdefault("keywords", "")

    summarize = make_summarizer()
    if summarize:
        todo = [p for p in result if not p.get("ai_summary") and p.get("abstract")]
        print(f"Summarizing {len(todo)} abstracts with Claude…")

        def run(p):
            try:
                s = summarize(p)
                if s:
                    p["summary"], p["ai_summary"] = s, True
            except Exception as e:
                print(f"  summary failed for {p['id']}: {e}", file=sys.stderr)

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(run, todo))

    result = [p for p in result if p.get("title")]
    result.sort(key=lambda p: p.get("sort_date") or p.get("date", ""), reverse=True)
    # The same paper is often posted in several series (e.g. IMF and CEPR). Keep the earliest
    # listing, so a paper someone already swiped doesn't come back when another series posts it.
    # Duplicates are stored separately so later runs don't fetch them again.
    seen_titles, deduped, duplicates = set(), [], []
    for p in reversed(result):
        key = re.sub(r"[^a-z0-9]", "", p["title"].lower())
        (duplicates if key in seen_titles else deduped).append(p)
        seen_titles.add(key)
    result = deduped[::-1]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"updated": time.strftime("%Y-%m-%d"), "papers": result, "duplicates": duplicates},
        ensure_ascii=False, separators=(",", ":"),
    ))
    counts = {}
    for p in result:
        counts[source_of(p)] = counts.get(source_of(p), 0) + 1
    print(f"Wrote {len(result)} papers to {OUT}: {counts} ({len(duplicates)} cross-listed duplicates hidden)")


def _safe(detail, stub):
    try:
        return detail(stub)
    except Exception as e:
        print(f"  skipped {stub['id']}: {e}", file=sys.stderr)
        return None


if __name__ == "__main__":
    main()
