# NBER Swipe

Tinder for NBER working papers. Each card shows a paper's title, year, authors and a short summary of the abstract.

- **Swipe right** (or →, or ♥) to save it for later
- **Swipe left** (or ←, or ✕) to skip
- **Tap the card** (or Enter) to open the paper on nber.org
- **↺ / U** undoes the last swipe
- The **Saved** tab lists your read-later papers, with "Copy list" to export them

Swipes and saved papers live in each person's own browser (localStorage), so friends using the same link each get their own deck and list.

## Shared list (Google Sheet) and the Overlap tab

Optionally, everyone's swipes can also be logged to a Google Sheet you own. The app then asks each person for a name per device (e.g. "Danny – phone") and adds an **Overlap** tab: papers saved by more than one person, which pairs of people have the most saves in common, and per-person counts. People can choose "Keep private" instead.

One-time setup (~3 minutes):

1. Create a new Google Sheet (any name).
2. **Extensions → Apps Script**. Delete the starter code, paste in [`apps-script/Code.gs`](apps-script/Code.gs), and save.
3. **Deploy → New deployment** → gear icon → **Web app**. Set *Execute as*: **Me**, *Who has access*: **Anyone**. Click Deploy and approve the permissions prompt (Google warns because it's your own unverified script: Advanced → Go to project).
4. Copy the **Web app URL** (ends in `/exec`) into [`docs/config.js`](docs/config.js) as `sheetUrl`, and commit.

Swipes appear in a `swipes` tab in the Sheet (time, name, paper, decision R/L/U, title, year, link). If you later edit `Code.gs`, use **Deploy → Manage deployments → Edit → New version** so the URL stays the same.

Note: anyone with the app link can write rows to the Sheet (that's what lets friends join without accounts). They can't read or change anything else in your Google account.

## How it works

- `scripts/fetch_papers.py` pulls the ~1000 newest working papers from NBER's listing API, grabs each full abstract from the paper page, and writes `docs/papers.json`. Re-runs only fetch papers that are new.
- `docs/index.html` is the whole app: a static page that reads `papers.json` (and `config.js` for the optional Sheet URL).
- `apps-script/Code.gs` is the optional Google Sheet backend for the shared list.
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
