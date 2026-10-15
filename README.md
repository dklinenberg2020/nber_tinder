# NBER Swipe

Tinder for economics working papers. Each card shows a paper's title, year, source, authors and a short summary of the abstract.

**Sources:** NBER, CEPR, IMF, ECB, Federal Reserve Board (FEDS and IFDP), Kiel Institute and PIIE.

- **Swipe right** (or →, or ♥) to save it for later
- **Swipe left** (or ←, or ✕) to skip
- **Tap the card** (or Enter) to open the paper
- **↺ / U** undoes the last swipe
- The **Saved** tab lists your read-later papers, with "Copy list" to export them

- **⚙︎** sets your topics and sources. Papers matching your topics come first, alternating two topic matches with one of the newest other papers. Defaults: Geoeconomics, Trade, Synthetic control; you can switch on others or add your own keywords. Matching uses the title, abstract, and (for CEPR/IMF/PIIE/Kiel) the paper's keywords and JEL codes.

Swipes, saved papers and topic settings live in each person's own browser (localStorage), so friends using the same link each get their own deck and list. Nothing is sent to a server.

## How it works

- `scripts/fetch_papers.py` builds `docs/papers.json`. Re-runs only fetch papers that are new, and if one source fails its earlier papers are kept.
  - NBER: the ~1000 newest papers from NBER's listing API, with full abstracts from each paper page.
  - Fed and ECB: their working paper RSS feeds (abstracts included); papers accumulate over time.
  - CEPR, IMF, PIIE, Kiel: the newest 150 of each from [RePEc/IDEAS](https://ideas.repec.org), since their own sites block automated access. IDEAS can lag the original release by a few days, and Kiel entries only carry a year.
- `docs/index.html` is the whole app: a static page that reads `papers.json`.
- `.github/workflows/update-papers.yml` re-runs the fetch daily and commits the new JSON.

## Hosting it (GitHub Pages)

1. Repo **Settings → Pages → Build and deployment**: Source "Deploy from a branch", branch `main`, folder `/docs`.
2. Share `https://<your-username>.github.io/nber_tinder/`.

## Summaries

By default the card shows the opening sentences of the abstract. For real one-to-two sentence summaries, add an `ANTHROPIC_API_KEY` repository secret (Settings → Secrets and variables → Actions). The next run summarizes every paper with Claude (one time, then only new papers).

## Running locally

```bash
python3 scripts/fetch_papers.py              # MAX_PAPERS / MAX_PER_SOURCE to fetch fewer
python3 -m http.server -d docs 8000          # open http://localhost:8000
```
