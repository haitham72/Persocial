"""Generates colab/score_csv.ipynb. The scoring code is embedded verbatim from
persocial/scoring/core.py, so it is edited in one place only; tests fail if the committed
notebook is stale.

In Colab: Runtime → Change runtime type → GPU, add two secrets (key icon on the left):
  COLAB_API_URL  https://<project>.supabase.co/functions/v1/colab-api
  COLAB_TOKEN    the value set with `supabase secrets set COLAB_TOKEN=...`
then Runtime → Run all.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "persocial" / "scoring" / "core.py"
OUT = ROOT / "colab" / "score_csv.ipynb"

INTRO = """# persocial · Colab scorer

Scores comments (sentiment + emotion) on Colab's GPU. Two ways to use it:

**A · CSV (works with the local database, no cloud needed)**
1. Web app → Scoring → **Export next post as CSV**.
2. Here: **Runtime → Change runtime type → T4 GPU** → run the first cells, then the
   **CSV mode** cell → choose the CSV → the scored file downloads.
3. Web app → Upload → drop the scored CSV. Scores attach and the post's lease is released.

**B · Direct (cloud database)** — set the `COLAB_API_URL` and `COLAB_TOKEN` secrets
(🔑 on the left), run all, use the form at the bottom. Scores are saved to the cloud
every *Save every* comments."""

SETUP = """%pip install -q transformers pandas ipywidgets requests
import json, time, requests, torch
from google.colab import userdata, output
output.enable_custom_widget_manager()
try:                       # only needed for mode B (direct to the cloud database)
    API_URL, TOKEN = userdata.get("COLAB_API_URL"), userdata.get("COLAB_TOKEN")
except Exception:
    API_URL = TOKEN = None
print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none — CPU will be slow")"""

CLIENT = '''from scoring_core import Scorer

def api(action, **kw):
    r = requests.post(API_URL, headers={"x-colab-token": TOKEN},
                      json={"action": action, **kw}, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"{action}: {r.status_code} {r.text[:300]}")
    return r.json()

_scorer = None
def scorer():
    global _scorer
    if _scorer is None:
        _scorer = Scorer("auto")
    return _scorer

def run(post_codes=None, save_every=5000, log=print, bar=None):
    """Lease one post at a time; score its unscored comments in save_every chunks; each
    submit is a save point that keeps the lease alive. Stops when nothing is left."""
    s = scorer()
    runner = f"colab:{s.device_name}"
    total = 0
    while True:
        leases = api("claim", post_codes=post_codes, n=1, runner=runner)
        if not leases:
            log(f"✅ done — nothing left to score. {total} comments scored this session.")
            return total
        code, todo = leases[0]["post_code"], leases[0]["n_unscored"]
        log(f"▶ post {code}: {todo} comments")
        done = 0
        try:
            while True:
                chunk = api("comments", post_code=code, limit=save_every)
                if not chunk:
                    break
                t0 = time.time()
                res = s.score([c["text"] for c in chunk])
                rows = [{"ig_id": c["ig_id"], "sentiment": a, "emotions": b}
                        for c, (a, b) in zip(chunk, res)]
                out = api("submit", post_code=code, rows=rows, runner=runner)
                done += out["written"]; total += out["written"]
                rate = len(chunk) / max(time.time() - t0, 1e-6)
                log(f"   saved {done}/{todo} · {rate:.0f}/s · {out['remaining']} left")
                if bar is not None:
                    bar.value = done / max(todo, 1)
                if out["remaining"] == 0:
                    break
        except Exception as e:
            api("release", post_code=code)
            log(f"✖ {code}: {e} — lease released, run again to retry")
            raise
        if post_codes:
            post_codes = [p for p in post_codes if p != code] or None
            if post_codes is None:
                log(f"✅ done — selected posts scored. {total} comments this session.")
                return total'''

CSV_MODE = '''# ── Mode A: score a CSV exported from the web app (Scoring → Export next post as CSV) ──
from google.colab import files
from scoring_core import score_csv
for name, data in files.upload().items():
    open(name, "wb").write(data)
    out = name.rsplit(".", 1)[0] + "-scored.csv"
    print(name, "→", out, score_csv(name, out))
    files.download(out)       # then: web app → Upload → drop this file'''

GUI = '''# ── Mode B: direct to the cloud database (needs COLAB_API_URL / COLAB_TOKEN secrets) ──
if not API_URL:
    raise SystemExit("Mode B needs the COLAB_API_URL and COLAB_TOKEN secrets — use mode A above instead.")
import ipywidgets as W
from IPython.display import display

pending = api("pending")
n_left = sum(p["n_unscored"] for p in pending)
scope = W.Dropdown(options=[(f"All unanalysed comments ({n_left:,} in {len(pending)} posts)", "all"),
                            ("Pick posts", "pick")], description="Scope", layout=W.Layout(width="520px"))
search = W.Text(placeholder="search post id or account", description="Search", layout=W.Layout(width="520px"))
def _opts(q=""):
    q = q.lower()
    return [(f"{p['code']} · @{p['username'] or '?'} · {p['n_unscored']:,} left"
             + (" · claimed" if p["claimed"] else ""), p["code"])
            for p in pending if not q or q in p["code"].lower() or q in (p["username"] or "").lower()]
posts = W.SelectMultiple(options=_opts(), rows=10, description="Posts", layout=W.Layout(width="520px"))
save_every = W.Dropdown(options=[("1,000", 1000), ("5,000", 5000), ("10,000", 10000)], value=5000,
                        description="Save every")
start = W.Button(description="Start", button_style="success", icon="play")
bar = W.FloatProgress(min=0, max=1, description="Post")
log = W.Output(layout=W.Layout(border="1px solid #ddd", max_height="320px", overflow="auto"))
pick_box = W.VBox([search, posts])
pick_box.layout.display = "none"
scope.observe(lambda c: setattr(pick_box.layout, "display", "" if c["new"] == "pick" else "none"), "value")
search.observe(lambda c: setattr(posts, "options", _opts(c["new"])), "value")

def _go(_):
    start.disabled = True
    codes = list(posts.value) if scope.value == "pick" else None
    if scope.value == "pick" and not codes:
        with log: print("pick at least one post"); start.disabled = False; return
    with log:
        try:
            run(codes, save_every.value, log=print, bar=bar)
        finally:
            start.disabled = False
start.on_click(_go)
display(W.VBox([scope, pick_box, save_every, start, bar, log]))'''


def _cell(kind: str, src: str) -> dict:
    cell = {"cell_type": kind, "metadata": {}, "source": src.splitlines(keepends=True)}
    if kind == "code":
        cell.update(execution_count=None, outputs=[])
    return cell


def notebook() -> dict:
    core = CORE.read_text(encoding="utf-8")
    return {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"accelerator": "GPU", "colab": {"provenance": []},
                     "kernelspec": {"name": "python3", "display_name": "Python 3"}},
        "cells": [
            _cell("markdown", INTRO),
            _cell("code", SETUP),
            _cell("code", "%%writefile scoring_core.py\n" + core),
            _cell("code", CSV_MODE),
            _cell("code", CLIENT),
            _cell("code", GUI),
        ],
    }


def build() -> str:
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(notebook(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return str(OUT)


if __name__ == "__main__":
    print(build())
