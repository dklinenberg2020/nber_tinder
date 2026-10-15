/**
 * NBER Swipe: shared swipe log backed by this Google Sheet.
 *
 * Setup: in the Sheet, Extensions → Apps Script, paste this file, then
 * Deploy → New deployment → Web app, Execute as "Me", Who has access "Anyone".
 * Put the /exec URL it gives you in docs/config.js.
 *
 * POST (body = JSON, sent as text/plain): {name, events: [{id, title, url, year, dir, ts}]}
 *   dir: "R" saved, "L" skipped, "U" undone / removed from saved
 * GET: latest decision per (name, paper), as JSON.
 */

const SHEET = "swipes";
const HEADER = ["time", "name", "paper", "decision", "title", "year", "url"];

function sheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(SHEET);
  if (!sh) {
    sh = ss.insertSheet(SHEET);
    sh.appendRow(HEADER);
    sh.setFrozenRows(1);
  }
  return sh;
}

// Keep text short and stop the Sheet from treating it as a formula.
function cell_(v, max) {
  let s = String(v == null ? "" : v).slice(0, max || 300);
  if (/^[=+\-@]/.test(s)) s = "'" + s;
  return s;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  const name = cell_(body.name, 60).trim();
  const events = (body.events || []).slice(0, 500);
  if (!name || !events.length) return json_({ ok: false, error: "missing name or events" });

  const rows = events
    .filter((ev) => /^w\d+$/.test(ev.id) && ["R", "L", "U"].indexOf(ev.dir) >= 0)
    .map((ev) => [
      new Date(Number(ev.ts) || Date.now()),
      name,
      ev.id,
      ev.dir,
      cell_(ev.title, 300),
      cell_(ev.year, 4),
      "https://www.nber.org/papers/" + ev.id,
    ]);

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const sh = sheet_();
    if (rows.length) sh.getRange(sh.getLastRow() + 1, 1, rows.length, HEADER.length).setValues(rows);
  } finally {
    lock.releaseLock();
  }
  return json_({ ok: true, added: rows.length });
}

function doGet() {
  const values = sheet_().getDataRange().getValues().slice(1);
  values.sort((a, b) => new Date(a[0]) - new Date(b[0]));

  const latest = {}; // "name|paper" -> row
  values.forEach((r) => { latest[r[1] + "|" + r[2]] = r; });

  const people = {};
  const papers = {};
  Object.keys(latest).forEach((k) => {
    const [, name, id, dir, title, year, url] = latest[k];
    people[name] = people[name] || { saved: 0, skipped: 0 };
    if (dir === "R") {
      people[name].saved++;
      papers[id] = papers[id] || { id: id, title: String(title).replace(/^'/, ""), year: String(year), url: url, savedBy: [] };
      papers[id].savedBy.push(name);
    } else if (dir === "L") {
      people[name].skipped++;
    }
  });
  return json_({ people: people, papers: Object.values(papers) });
}
