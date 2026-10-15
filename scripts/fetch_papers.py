#!/usr/bin/env python3
"""Fetch recent NBER working papers into docs/papers.json.

NBER's API doesn't allow browser (CORS) requests, so this runs ahead of time
(locally or in the GitHub Action) and the site reads the JSON it writes.

Papers already in papers.json are reused, so daily runs only fetch new ones.

Env vars:
  MAX_PAPERS         how many of the newest papers to keep (default 1000)
  ANTHROPIC_API_KEY  optional; if set, summaries are written by Claude,
                     otherwise the first couple of sentences of the abstract are used
"""

import html
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LISTING_URL = (
    "https://www.nber.org/api/v1/working_page_listing/contentType/working_paper"
    "/_/_/search?page={page}&perPage={per_page}"
)
OUT = Path(__file__).resolve().parent.parent / "docs" / "papers.json"
MAX_PAPERS = int(os.environ.get("MAX_PAPERS", "1000"))
HEADERS = {"User-Agent": "nber-tinder (personal paper browser)"}


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


def clean(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def list_recent(n):
    """Newest-first listing entries from the NBER API."""
    entries, page, per_page = [], 1, 100
    while len(entries) < n:
        data = json.loads(get(LISTING_URL.format(page=page, per_page=per_page)))
        results = data.get("results", [])
        if not results:
            break
        entries.extend(r for r in results if r.get("url", "").startswith("/papers/"))
        page += 1
    return entries[:n]


def fetch_detail(entry):
    """Full abstract and date from the paper's page (listing abstracts are truncated)."""
    pid = entry["url"].rsplit("/", 1)[-1]
    url = "https://www.nber.org" + entry["url"]
    abstract, date = clean(entry.get("abstract")), ""
    try:
        page = get(url)
        m = re.search(r'page-header__intro-inner">\s*<p>(.*?)</p>', page, re.S)
        if m:
            abstract = clean(m.group(1))
        m = re.search(r'citation_publication_date" content="(\d{4})/(\d{2})/(\d{2})', page)
        if m:
            date = "-".join(m.groups())
    except Exception as e:
        print(f"  could not fetch {url}: {e}", file=sys.stderr)

    year = date[:4] if date else (re.findall(r"\d{4}", entry.get("displaydate", "")) or [""])[0]
    return {
        "id": pid,
        "title": clean(entry.get("title")),
        "authors": [clean(a) for a in entry.get("authors", [])],
        "year": year,
        "date": date,
        "displaydate": entry.get("displaydate", ""),
        "url": url,
        "abstract": abstract,
    }


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

    def summarize(paper):
        response = client.messages.create(
            model="claude-opus-5-5",
            max_tokens=1024,
            output_config={"effort": "low"},
            system=(
                "You summarize economics working papers for someone deciding whether to read them. "
                "Reply with one or two plain sentences (max ~45 words) stating the question and the "
                "main finding. No preamble, no markdown."
            ),
            messages=[{"role": "user", "content": f"Title: {paper['title']}\n\nAbstract: {paper['abstract']}"}],
        )
        if response.stop_reason == "refusal":
            return None
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or None

    return summarize


def main():
    existing = {}
    if OUT.exists():
        existing = {p["id"]: p for p in json.loads(OUT.read_text())["papers"]}

    print(f"Listing the {MAX_PAPERS} newest papers…")
    entries = list_recent(MAX_PAPERS)
    new = [e for e in entries if e["url"].rsplit("/", 1)[-1] not in existing]
    print(f"{len(entries)} listed, {len(new)} new")

    with ThreadPoolExecutor(max_workers=4) as pool:
        fetched = list(pool.map(fetch_detail, new))

    summarize = make_summarizer()
    for p in fetched:
        p["summary"] = extractive_summary(p["abstract"])
        p["ai_summary"] = False
    for p in existing.values():
        p.setdefault("summary", extractive_summary(p.get("abstract", "")))

    if summarize:
        todo = [p for p in [*fetched, *existing.values()] if not p.get("ai_summary") and p.get("abstract")]
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

    by_id = {**existing, **{p["id"]: p for p in fetched}}
    keep = [by_id[e["url"].rsplit("/", 1)[-1]] for e in entries]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"updated": time.strftime("%Y-%m-%d"), "papers": keep},
        ensure_ascii=False, separators=(",", ":"),
    ))
    print(f"Wrote {len(keep)} papers to {OUT}")


if __name__ == "__main__":
    main()
