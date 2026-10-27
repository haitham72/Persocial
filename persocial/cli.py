"""persocial CLI. Every command takes --target local|cloud (default local; cloud reads the
CLOUD_DATABASE_URL from .env).

  persocial bootstrap                         seed models / prompt v1 / lexicon (idempotent)
  persocial member add EMAIL [--admin]        allow a Google account in
  persocial backfill --comments DIR --dataset DIR
  persocial worker [--score]                  judge jobs (+ score unscored posts with --score)
  persocial judge --sheet ID | --post CODE | --sample N [--account A] [--model ID] [--all]
  persocial notebook                          regenerate colab/score_csv.ipynb from core.py
  persocial dataset [--min-tier single|agree|human]   fine-tuning JSONL from stored judge calls
  persocial run INPUT [--out triage] [--format xlsx,csv,html] [--packs generic,gulf_ar]
                      [--no-judge] [--device cpu|cuda|mps]
  persocial models pull                       pre-download the HF scoring models
  persocial doctor                            check python, models, judge endpoint, store
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _use_cloud() -> None:
    from persocial.config import REPO_ROOT
    for line in (REPO_ROOT / ".env").read_text().splitlines():
        if line.startswith("CLOUD_DATABASE_URL="):
            url = line.split("=", 1)[1].strip().strip('"').replace(":6543/", ":5432/")
            os.environ["DATABASE_URL"] = url
            return
    sys.exit("CLOUD_DATABASE_URL missing in .env")


def _backfill(args) -> None:
    from persocial import db, media
    from persocial.ingest.service import ingest_file
    t0 = time.time()
    if args.dataset:
        for f in sorted((Path(args.dataset) / "postUpdate").glob("*.csv")):
            r = ingest_file(f.name, f.read_bytes())
            print(f"metrics {f.name}: +{r.rows_inserted} posts, {r.rows_updated} updated"
                  f"{' (already loaded)' if r.duplicate_file else ''}", flush=True)
    if args.comments:
        for folder in sorted(Path(args.comments).glob("*_sentiments")):
            account = folder.name.removesuffix("_sentiments")
            acc = {"files": 0, "rows": 0, "inserted": 0, "existing": 0, "scored": 0, "rejected": 0, "dup_files": 0}
            for f in sorted(folder.glob("*.csv")):
                r = ingest_file(f.name, f.read_bytes(), account_hint=account, create_sheets=False)
                acc["files"] += 1
                acc["dup_files"] += r.duplicate_file
                acc["rows"] += r.rows_total
                acc["inserted"] += r.rows_inserted
                acc["existing"] += r.rows_updated
                acc["scored"] += r.rows_scored
                acc["rejected"] += r.rows_rejected
            print(f"{account}: {json.dumps(acc)}", flush=True)
    if args.dataset:
        ds = Path(args.dataset)
        print("media:", media.import_folder(ds / "img_small", ds / "profiles"), flush=True)
    t = db.fetch_one("""select (select count(*) from comments) comments,
        (select count(*) from comments where scored_at is not null) scored,
        (select count(*) from posts) posts, (select count(*) from posts where status='pending') pending""")
    print(f"\ndone in {time.time() - t0:.0f}s · db now: {json.dumps(t)}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="persocial")
    p.add_argument("--target", choices=["local", "cloud"], default="local")
    sub = p.add_subparsers(dest="cmd", required=True)
    bs = sub.add_parser("bootstrap")
    bs.add_argument("--demo", action="store_true",
                    help="also load the synthetic examples/sample data (idempotent)")
    m = sub.add_parser("member")
    m.add_argument("action", choices=["add", "remove"])
    m.add_argument("email")
    m.add_argument("--admin", action="store_true")
    b = sub.add_parser("backfill")
    b.add_argument("--comments")
    b.add_argument("--dataset")
    w = sub.add_parser("worker")
    w.add_argument("--score", action="store_true")
    j = sub.add_parser("judge")
    j.add_argument("--sheet", type=int)
    j.add_argument("--post")
    j.add_argument("--sample", type=int)
    j.add_argument("--account")
    j.add_argument("--model")
    j.add_argument("--batch-size", type=int)
    j.add_argument("--all", action="store_true", help="judge every comment in scope")
    sub.add_parser("notebook")
    ds = sub.add_parser("dataset")
    ds.add_argument("--min-tier", choices=["single", "agree", "human"], default="single")
    ds.add_argument("--name")
    r = sub.add_parser("run", help="Tier 1 headless triage into a local SQLite store")
    r.add_argument("input")
    r.add_argument("--out", default="triage")
    r.add_argument("--format", default="xlsx,csv,html")
    r.add_argument("--packs", default=None)
    r.add_argument("--no-judge", action="store_true")
    r.add_argument("--device", default="cpu")
    m = sub.add_parser("models")
    m.add_argument("action", choices=["pull"])
    sub.add_parser("doctor")
    args = p.parse_args(argv)
    if args.target == "cloud":
        _use_cloud()

    if args.cmd == "bootstrap":
        from persocial.bootstrap import ensure_defaults
        ensure_defaults()
        print("defaults ensured")
        if args.demo:
            from persocial.bootstrap import load_demo
            print(load_demo())
    elif args.cmd == "member":
        from persocial import db
        if args.action == "add":
            db.execute("""insert into members (email, role) values (lower(%s), %s)
                          on conflict (email) do update set role=excluded.role, active=true""",
                       (args.email, "admin" if args.admin else "reviewer"))
        else:
            db.execute("update members set active=false where email=lower(%s)", (args.email,))
        print("ok")
    elif args.cmd == "backfill":
        _backfill(args)
    elif args.cmd == "worker":
        from persocial.worker import run
        run(score=args.score)
    elif args.cmd == "judge":
        if not (args.sheet or args.post or args.sample):
            sys.exit("give --sheet, --post or --sample")
        from persocial.judge import runner
        jid = runner.create_run(sheet_id=args.sheet, post_code=args.post, model_id=args.model,
                                purpose="teacher" if args.sample else "review",
                                sample=args.sample, account=args.account, judge_all=args.all,
                                batch_size=args.batch_size, enqueue=False)
        t0 = time.time()
        print(f"job {jid} …", flush=True)
        print(runner.execute(jid), f"{time.time() - t0:.1f}s")
    elif args.cmd == "dataset":
        from persocial.dataset import export
        print(json.dumps(export(args.name, min_tier=args.min_tier), indent=1))
    elif args.cmd == "run":
        from persocial.local.run import run as tier1_run
        formats = tuple(f.strip() for f in (args.format or "").split(",") if f.strip())
        bad = [f for f in formats if f not in ("xlsx", "csv", "html")]
        if bad:
            sys.exit(f"unknown --format: {','.join(bad)} (xlsx,csv,html)")
        try:
            out = tier1_run(args.input, out=args.out, formats=formats or ("xlsx",),
                            packs=args.packs, no_judge=args.no_judge, device=args.device)
        except (ValueError, FileNotFoundError) as e:
            sys.exit(f"error: {e}")
        print(f"done: {out['judged']} judged / {out['comments']} comments")
    elif args.cmd == "models":
        from persocial.local.models import pull
        pull()
    elif args.cmd == "doctor":
        from persocial.local.doctor import main as doctor_main
        sys.exit(doctor_main())
    elif args.cmd == "notebook":
        from scripts.build_colab_notebook import build
        print(build())


if __name__ == "__main__":
    main()
