# Demo script (records `assets/demo.gif`)

Three minutes, synthetic data only. Follow this script so a recording matches the docs.

## Solo (0:00–1:30)

1. Terminal, repo root:
   `persocial run examples/sample/apify.json --out triage --no-judge`
   (324 comments in, three files out — show the summary line).
2. Open `triage.html`. Show the summary header (counts per category).
3. Filter **Category → spam_scam**: ~11 hidden-suggested rows. Open one
   "open on Instagram" link (shows the per-row deep link).
4. Switch the filter to **Verdict → To review**: the harassment/threat rows
   a human must read.

## Team (1:30–3:00)

1. Inbox → **Board**: four columns from `queue_comments`.
2. Drag a scam card `new` → `in_review`; click **assign to me**.
   Point at the red SLA badge on the overdue card.
3. Open the card drawer (clock icon): status control + assign control +
   the audit timeline with actor + timestamp.
4. Decide **hide** on the scam card; show the timeline gaining the row.

## Capture notes

- 1280×720 window, light theme, reviewer account `smoke@example.com`
  against the seeded stack (`scripts/seed_smoke.py`).
- No real comments, usernames or media on screen at any point.
- End on the board with the decided card in `done`.
