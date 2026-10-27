"""End-to-end check of the Colab path against a real Supabase project, without Colab:
executes the notebook's own client cell (extracted from colab/score_csv.ipynb) with this
machine's GPU standing in for Colab's, through the deployed colab-api Edge Function.

  DATABASE_URL=<cloud session pooler> uv run python -m scripts.colab_e2e

Creates post ZZTCOLAB with synthetic unscored comments, runs the notebook loop with a
small save-every so several save points happen, verifies, then deletes the test data.
"""

from __future__ import annotations

import csv
import io
import json
import sys

from persocial import db
from persocial.config import REPO_ROOT
from persocial.ingest.service import ingest_file
from persocial.scoring import core

POST = "ZZTCOLAB"
N = 230


def _csv() -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "owner_id", "username", "text", "created_at", "postID", "comment_number"])
    texts = ["Beautiful shot, MashAllah", "This is terrible, shame on you", "ما شاء الله تبارك الله",
             "Where is this place?", "Worst decision ever", "❤️❤️❤️", "الله يبارك فيك",
             "Send me a DM for crypto profits", "Love from India", "Not impressed at all"]
    for i in range(N):
        w.writerow([str(8_800_000_000 + i), str(500 + i), f"tester{i % 37}", f"{texts[i % len(texts)]} #{i}",
                    "20/10/2026, 09:00:00", POST, str(N)])
    return buf.getvalue().encode()


def cleanup() -> None:
    with db.tx() as conn:
        conn.execute("delete from notifications where post_code=%s", (POST,))
        conn.execute("delete from jobs where post_code=%s", (POST,))
        conn.execute("delete from judge_calls where post_code=%s", (POST,))
        conn.execute("delete from posts where code=%s", (POST,))
        conn.execute("delete from uploads where filename like %s", (f"{POST}%",))
        conn.execute("delete from accounts where username='zz_colab_test'")


def main() -> None:
    env = {l.split("=", 1)[0]: l.split("=", 1)[1].strip().strip('"')
           for l in (REPO_ROOT / ".env").read_text().splitlines() if "=" in l and not l.startswith("#")}
    cleanup()
    res = ingest_file(f"{POST}-comment--{N}.csv", _csv(), account_hint="zz_colab_test")
    print(f"ingested: +{res.rows_inserted}, sheets {res.sheet_ids}")

    nb = json.loads((REPO_ROOT / "colab" / "score_csv.ipynb").read_text())
    client_src = "".join(nb["cells"][4]["source"])
    sys.modules["scoring_core"] = core                     # what %%writefile provides in Colab
    import time

    import requests
    # what the notebook's setup cell provides in Colab
    ns = {"API_URL": env["COLAB_API_URL"], "TOKEN": env["COLAB_TOKEN"],
          "requests": requests, "time": time, "json": json}
    exec(client_src, ns)  # noqa: S102 -- dev-only harness running the notebook's own client code

    pending = ns["api"]("pending")
    print("pending via Edge Function:", [(p["code"], p["n_unscored"]) for p in pending if p["code"] == POST])
    ns["run"]([POST], save_every=100)
    st = db.fetch_one("""select count(scored_at) as scored, count(*) as n, min(scored_by) as by
                         from comments where post_code=%s""", (POST,))
    post = db.fetch_one("select n_scored, n_negative, claimed_by from posts where code=%s", (POST,))
    sheet = db.fetch_one("select status from review_sheets where post_code=%s", (POST,))
    print(f"scored {st['scored']}/{st['n']} by {st['by']} · post counts {dict(post)} · sheet {sheet['status']}")
    ok = st["scored"] == N and post["n_scored"] == N and post["claimed_by"] is None
    cleanup()
    print("E2E", "PASSED" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
