"""Long-running worker: `persocial worker` (judge jobs) or `persocial worker --score`
(also scores unscored posts on this machine's GPU/Metal/CPU). Run any number of them on
different machines against the same database; jobs and leases use SKIP LOCKED."""

from __future__ import annotations

import time
import traceback

from persocial import db, jobs
from persocial.config import settings
from persocial.judge import client, runner
from persocial.scoring import claims


def _runnable_models(loaded: set[str]) -> list[str]:
    """Remote models always; local ones only once the operator has loaded them in LM Studio.
    Queued jobs for an unloaded local model wait (and say so) instead of triggering a load."""
    models = db.fetch_all("select id, base_url, model, label from models where enabled")
    ok = [m["id"] for m in models if not client.is_local(m) or m["model"] in loaded]
    for m in models:
        if m["id"] not in ok:
            db.execute("""update jobs set error=%s where status='queued' and model=%s
                          and error is distinct from %s""",
                       (w := f"waiting: load {m['label']} in LM Studio with thinking off", m["id"], w))
    return ok


def run(score: bool = False, idle_sleep: float = 3.0) -> None:
    scorer = None
    device = "judge-only"
    if score:
        from persocial.scoring.core import Scorer
        scorer = Scorer(settings().scoring_device, settings().scoring_batch_size)
        device = scorer.runner
    print(f"worker {jobs.WORKER_ID} up · {device}", flush=True)
    last_beat = 0.0
    loaded: set[str] = set()
    while True:
        if time.time() - last_beat > 30:
            loaded = client.loaded_local_models()
            jobs.heartbeat(device, loaded)
            jobs.requeue_stale()
            last_beat = time.time()
        job = jobs.claim(["judge"], models=_runnable_models(loaded))
        if job:
            print(f"judge job {job['id']} ({job['purpose']}, sheet={job['sheet_id']}, "
                  f"post={job['post_code']})", flush=True)
            try:
                print(runner.execute(job["id"]), flush=True)
                jobs.finish(job["id"])
            except Exception as e:  # noqa: BLE001 — a bad job must not kill the worker
                traceback.print_exc()
                jobs.finish(job["id"], error=str(e)[:500])
            continue
        if scorer is not None:
            try:
                out = claims.score_locally(scorer)
                if out:
                    print(f"scored {out}", flush=True)
                    continue
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        time.sleep(idle_sleep)
