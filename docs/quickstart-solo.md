# Solo quickstart (Tier 1 headless triage)

One account, no server, no login. Takes a fresh checkout to `triage.html`
in five commands (Windows PowerShell shown; macOS/Linux notes at the end).
Model downloads are one-time and excluded from the timing: the scoring
models (~1.1 GB) land in the shared Hugging Face cache on first `models pull`.

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[scoring]"
.venv\Scripts\persocial models pull
.venv\Scripts\persocial run examples/sample/apify.json --out triage --no-judge
start triage.html
```

What each step does:

1. Fresh virtual environment (`.venv` is gitignored, never committed).
2. Installs the CLI with the local-scoring libraries (`torch`, `transformers`).
   Base install without `[scoring]` still parses, stores and reports, but
   scoring needs the models. The torch wheel is large (~2 GB on Windows);
   for a CPU-only install, put torch on the CPU index first
   (`pip install torch --index-url https://download.pytorch.org/whl/cpu`,
   then `pip install -e .` without `[scoring]` — scoring still works, the
   CLI defaults to `--device cpu`).
3. Pre-downloads the two Hugging Face scoring models. First `run` without
   this prints the size (~1.1 GB) and points here instead of stalling.
4. Parses the sample export into a local SQLite store (`./.persocial/`),
   scores every comment on CPU, and writes `triage.xlsx`, `triage.csv` and
   `triage.html` next to it. `--no-judge` gives an NLP-only triage; re-runs
   are incremental (already stored comments add 0).
5. Opens the self-contained report: sortable table, filters by
   verdict/category/language, per-row "open on Instagram" links, summary
   header. Works offline from `file://`.

Try it on the sample data, then on your own export:

```powershell
.venv\Scripts\persocial run <your-comments.csv-or.json> --out triage --no-judge
```

`persocial run` accepts an Apify comments export (CSV or JSON) or a generic
comments CSV — see `docs/input-format.md`. All sample usernames start with
`demo_`; your export keeps its real usernames locally and they never leave
the machine (see `SECURITY.md`).

## With a judge (optional)

Point the flagged-comments judge at a local OpenAI-compatible server
(LM Studio, Ollama) and drop `--no-judge`:

```powershell
$env:PERSOCIAL_JUDGE_MODEL = "<your-local-model-id>"
.venv\Scripts\persocial run <your-file> --out triage
```

Default endpoint `http://127.0.0.1:1234/v1` (`PERSOCIAL_JUDGE_BASE_URL`).
With no reachable endpoint the CLI prints a one-line hint and falls back to
`--no-judge` instead of crashing. Only judge calls ever leave the machine,
and only to the endpoint you configure.

## macOS / Linux

Same five commands with `:` separators and `open`:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[scoring]"
.venv/bin/persocial models pull
.venv/bin/persocial run examples/sample/apify.json --out triage --no-judge
open triage.html
```

## Next

- `persocial doctor` — checks Python, models, judge reachability and store,
  with a one-line fix per failure.
- `docs/input-format.md` — the Apify recipe and the generic CSV contract.
- `docs/taxonomy.md` — what the judge flags and how packs extend it.
