# NBER Swipe

Tinder for NBER working papers. Each card shows a paper's title, year, authors and a short summary of the abstract.

- **Swipe right** (or →, or ♥) to save it for later
- **Swipe left** (or ←, or ✕) to skip
- **Tap the card** (or Enter) to open the paper on nber.org
- **↺ / U** undoes the last swipe
- The **Saved** tab lists your read-later papers, with "Copy list" to export them

Swipes and saved papers live in each person's own browser (localStorage), so friends using the same link each get their own deck and list. Nothing is sent to a server.

## How it works

- `scripts/fetch_papers.py` pulls the ~1000 newest working papers from NBER's listing API, grabs each full abstract from the paper page, and writes `docs/papers.json`. Re-runs only fetch papers that are new.
- `docs/index.html` is the whole app: a static page that reads `papers.json`.
- `.github/workflows/update-papers.yml` re-runs the fetch daily and commits the new JSON.

## Hosting it (GitHub Pages)

1. Repo **Settings → Pages → Build and deployment**: Source "Deploy from a branch", branch `main`, folder `/docs`.
2. Share `https://<your-username>.github.io/nber_tinder/`.

## Summaries

By default the card shows the opening sentences of the abstract. For real one-to-two sentence summaries, add an `ANTHROPIC_API_KEY` repository secret (Settings → Secrets and variables → Actions). The next run summarizes every paper with Claude (one time, then only new papers).

## Running locally

```bash
python3 scripts/fetch_papers.py              # MAX_PAPERS=200 to fetch fewer
python3 -m http.server -d docs 8000          # open http://localhost:8000
```
