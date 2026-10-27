"""Job queue on the jobs table. Workers claim with FOR UPDATE SKIP LOCKED, so any number of
workers (4080 box, 5070 box, a Mac) run against the same database without two of them
taking the same job. Worker heartbeats are settings rows 'worker:<host>'."""

from __future__ import annotations

import socket

from persocial import db

WORKER_ID = socket.gethostname()


def claim(kinds: list[str], worker_id: str = WORKER_ID, models: list[str] | None = None) -> dict | None:
    """models: only claim jobs for these model ids (None = any)."""
    with db.tx() as conn:
        job = conn.execute(
            """select * from jobs where status='queued' and kind = any(%s)
                 and (%s::text[] is null or model = any(%s::text[]))
               order by created_at for update skip locked limit 1""", (kinds, models, models)).fetchone()
        if not job:
            return None
        conn.execute("""update jobs set status='running', worker=%s, started_at=now(), error=null,
                        attempts=attempts+1 where id=%s""", (worker_id, job["id"]))
        return job


def finish(job_id: int, error: str | None = None) -> None:
    db.execute("""update jobs set status=%s, error=%s, finished_at=now() where id=%s""",
               ("failed" if error else "done", error, job_id))


def heartbeat(device: str, models: list[str] | tuple = (), worker_id: str = WORKER_ID) -> None:
    """value = '<device>;<loaded LM Studio models>' — see workers_live() in SQL."""
    db.execute("""insert into settings (key, value) values (%s, %s)
                  on conflict (key) do update set value = excluded.value, updated_at = now()""",
               (f"worker:{worker_id}", f"{device};{','.join(sorted(models))}"))


def live_workers(max_age_s: int = 90) -> list[dict]:
    return db.fetch_all("""select substr(key, 8) as worker, split_part(value, ';', 1) as device,
                                  split_part(value, ';', 2) as models, updated_at
                           from settings where key like 'worker:%%'
                             and updated_at > now() - make_interval(secs => %s)""", (max_age_s,))


def requeue_stale(max_age_min: int = 30) -> int:
    """A worker that died mid-job leaves it 'running'; hand it back."""
    return db.execute(
        """update jobs set status='queued', worker=null where status='running'
           and started_at < now() - make_interval(mins => %s) and attempts < 3""", (max_age_min,))
