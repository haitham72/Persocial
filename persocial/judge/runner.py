"""Judge runs. A run is a row in jobs (kind='judge'):
  review run   sheet_id set — the new comments of one upload; drives the reviewer queue
  teacher run  sample_size set (or a post) — labels data for fine-tuning, optionally judging
               every comment (judge_all) and optionally with a cloud model
Every verdict lands on the comment row (production) and in judge_labels (per model, for
fine-tuning); every model call is kept whole in judge_calls."""

from __future__ import annotations

import json
import random

from persocial import db, sheets
from persocial.config import settings
from persocial.judge import client
from persocial.judge.rules import load_lexicon
from persocial.judge.select import Item, draw_audit, group, select
from persocial.judge.taxonomy import apply_policy

_COLS = "c.ig_id, c.post_code, c.text, c.text_norm, c.script, c.sentiment, c.emotion, " \
        "greatest(c.sent_negative, c.sent_neutral, c.sent_positive) as sentiment_score"


def create_run(*, post_code: str | None = None, sheet_id: int | None = None,
               model_id: str | None = None, purpose: str = "review", sample: int | None = None,
               account: str | None = None, judge_all: bool = False, batch_size: int | None = None,
               no_cache: bool = False, enqueue: bool = True) -> int:
    """Same SQL function the web app calls. enqueue=False marks the job running for this
    process so no worker picks it up."""
    if model_id is None and settings().judge_model:
        model_id = settings().judge_model
    with db.tx() as conn:
        jid = conn.execute(
            "select public.create_judge_run(%s, %s, %s, %s, %s, %s, %s) as id",
            (post_code, sheet_id, model_id, purpose, sample, account, judge_all)).fetchone()["id"]
        conn.execute("update jobs set batch_size=%s, no_cache=%s where id=%s",
                     (batch_size, no_cache, jid))
        if not enqueue:
            conn.execute("update jobs set status='running', worker='inline', started_at=now() "
                         "where id=%s", (jid,))
    return jid


def _scope_rows(job: dict) -> list[dict]:
    if job["sheet_id"]:
        return db.fetch_all(
            f"""select {_COLS} from comments c join review_sheets s
                  on c.first_upload_id = s.upload_id and c.post_code = s.post_code
                where s.id = %s""", (job["sheet_id"],))
    if job["sample_size"]:
        return db.fetch_all(
            f"""select {_COLS} from comments c join posts p on p.code = c.post_code
                left join accounts a on a.id = p.account_id
                where c.scored_at is not null and (%(acc)s::text is null or a.username = %(acc)s)
                  and (%(post)s::text is null or c.post_code = %(post)s)
                order by md5(c.ig_id || %(seed)s::text) limit %(n)s""",
            {"acc": job["sample_account"], "post": job["post_code"], "seed": job["seed"],
             "n": job["sample_size"]})
    return db.fetch_all(f"select {_COLS} from comments c where c.post_code = %s", (job["post_code"],))


def _cached(model: str, prompt: str, norms: list[str]) -> dict[str, dict]:
    """Same text, same model, same prompt → reuse the label instead of paying for it again."""
    if not norms:
        return {}
    rows = db.fetch_all(
        """select distinct on (c.text_norm) c.text_norm, l.verdict, l.category, l.severity,
                  l.confidence, l.reason, l.call_id
           from judge_labels l join comments c on c.ig_id = l.ig_id
           where l.model = %s and l.prompt = %s
             and md5(c.text_norm) = any(array(select md5(x) from unnest(%s::text[]) x))
             and l.reason <> 'judge_error'
           order by c.text_norm, l.labeled_at desc""", (model, prompt, norms))
    return {r["text_norm"]: r for r in rows}


def _setting(key: str, default: float) -> float:
    row = db.fetch_one("select value from settings where key=%s", (key,))
    try:
        return float(row["value"]) if row else default
    except (TypeError, ValueError):
        return default


def _setting_str(key: str, default: str = "") -> str:
    row = db.fetch_one("select value from settings where key=%s", (key,))
    return row["value"] if row else default


class _Judge:
    """Judges items for one job: verdict cache, per-post batches, call capture. Returns how
    many comments among the given items were flagged (hide/review)."""

    def __init__(self, job: dict, model: dict, prompt: dict):
        self.job, self.model, self.prompt = job, model, prompt
        self.bs = max(1, int(job["batch_size"] or model["batch_size"]))
        self.review = job["purpose"] == "review"
        self.done = 0
        self.unique = 0
        self._posts: dict[str, dict] = {}

    def _post(self, code: str) -> dict:
        if code not in self._posts:
            self._posts[code] = db.fetch_one(
                """select p.caption, a.username from posts p
                   left join accounts a on a.id = p.account_id where p.code=%s""", (code,)) or {}
        return self._posts[code]

    def _write(self, conn, g: list[Item], v: dict, call_id: int | None, cached=False) -> int:
        verdict, welfare = apply_policy(v["verdict"], v["category"], v["severity"])
        reason = ("cached: " if cached else "") + (v.get("reason") or "")
        rep = g[0].ig_id
        m, p, jid = self.model["id"], self.prompt["version"], self.job["id"]
        for it in g:
            conn.execute(
                """insert into judge_labels (ig_id, model, prompt, verdict, category, severity,
                     confidence, reason, job_id, call_id)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (ig_id, model, prompt) do update set verdict=excluded.verdict,
                     category=excluded.category, severity=excluded.severity,
                     confidence=excluded.confidence, reason=excluded.reason,
                     job_id=excluded.job_id, call_id=excluded.call_id, labeled_at=now()""",
                (it.ig_id, m, p, verdict, v["category"], v["severity"], v.get("confidence"),
                 reason, jid, call_id))
            if self.review:              # teacher runs only label; reviewers' view is untouched
                conn.execute(
                    """update comments set judge_selection=%s, judge_signals=%s, verdict=%s,
                         category=%s, severity=%s, confidence=%s, welfare=%s, judge_reason=%s,
                         judge_model=%s, judge_prompt=%s, judged_at=now(), judge_job_id=%s,
                         judged_as_copy_of=%s where ig_id=%s""",
                    (it.selection, ",".join(it.signals) or None, verdict, v["category"],
                     v["severity"], v.get("confidence"), welfare, reason, m, p, jid,
                     None if it.ig_id == rep else rep, it.ig_id))
        return len(g) if verdict in ("hide", "review") else 0

    def __call__(self, items: list[Item]) -> int:
        groups = group(items)
        self.unique += len(groups)
        flagged = 0
        cache = {} if self.job["no_cache"] else _cached(
            self.model["id"], self.prompt["version"], [k for k in groups if not k.isdigit()])
        todo = []
        with db.tx() as conn:
            for key, g in groups.items():
                hit = cache.get(key)
                if hit:
                    flagged += self._write(conn, g, hit, hit["call_id"], cached=True)
                    self.done += 1
                else:
                    todo.append(g)
        by_post: dict[str, list] = {}
        for g in todo:      # batches never mix posts: each carries its own account + caption
            by_post.setdefault(g[0].post_code, []).append(g)
        for code, gs in by_post.items():
            post = self._post(code)
            for i in range(0, len(gs), self.bs):
                chunk = gs[i:i + self.bs]
                res = client.judge_batch(self.model, self.prompt["system_prompt"],
                                         [(g[0].ig_id, g[0].text) for g in chunk],
                                         post.get("username") or "", post.get("caption") or "")
                with db.tx() as conn:
                    call_id = None
                    for rec in res.calls:
                        user = rec.request["messages"][-1]["content"] if rec.request.get("messages") else ""
                        call_id = conn.execute(
                            """insert into judge_calls (job_id, model, prompt, post_code,
                                 user_payload, response_text, parse_status, item_ids, latency_ms,
                                 prompt_tokens, output_tokens, error)
                               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                            (self.job["id"], self.model["id"], self.prompt["version"], code,
                             user if isinstance(user, str) else json.dumps(user),
                             rec.response_text, rec.parse_status, [g[0].ig_id for g in chunk],
                             rec.latency_ms, rec.prompt_tokens, rec.output_tokens,
                             rec.error)).fetchone()["id"]
                    for g in chunk:
                        flagged += self._write(conn, g, res.verdicts[g[0].ig_id], call_id)
                    self.done += len(chunk)
                    conn.execute("update jobs set n_done=%s, n_unique=%s where id=%s",
                                 (self.done, self.unique, self.job["id"]))
        return flagged


def _tiebreak(job: dict, prompt: dict) -> dict:
    """Second opinion on shaky primary hides (review runs only). Both models hide
    -> hide ("tiebreak:confirmed"); any split -> review ("tiebreak:split"). The
    tiebreak model's own verdicts land in judge_labels under its own key."""
    zero = {"n": 0, "agree": 0}
    tb_id = _setting_str("tiebreak_model")
    if not tb_id or tb_id == job["model"]:
        return zero
    tb_model = db.fetch_one("select * from models where id=%s", (tb_id,))
    if not tb_model or not tb_model["enabled"]:
        return zero
    try:
        client.ensure_loaded(tb_model)
    except client.ModelNotLoaded:
        return zero
    thr = _setting("tiebreak_below_conf", 0.7)
    rows = db.fetch_all(
        f"""select {_COLS} from comments c
            where c.judge_job_id = %s and c.verdict = 'hide'
              and (c.confidence is null or c.confidence < %s)""",
        (job["id"], thr))
    if not rows:
        return zero
    items = []
    for r in rows:
        it = Item(r["ig_id"], r["text"] or "", r["text_norm"] or "", r["script"],
                  r.get("sentiment"), r.get("sentiment_score"), r.get("emotion"),
                  r.get("post_code") or "")
        it.selection = "tiebreak"
        it.signals = ["tiebreak"]
        items.append(it)
    tb = _Judge(job, tb_model, prompt)
    tb.review = False  # labels only; the resolution below owns the comment rows
    tb(items)
    agree = 0
    with db.tx() as conn:
        for it in items:
            tie = conn.execute(
                "select verdict, category from judge_labels "
                "where ig_id=%s and model=%s and prompt=%s",
                (it.ig_id, tb_id, prompt["version"])).fetchone()
            if tie and tie["verdict"] == "hide":
                agree += 1
                conn.execute(
                    "update comments set verdict='hide', judge_reason="
                    "'tiebreak:confirmed ' || coalesce(judge_reason,'') where ig_id=%s",
                    (it.ig_id,))
            else:
                tcat = tie["category"] if tie else "none"
                conn.execute(
                    "update comments set verdict='review', category=%s, severity=2, "
                    "judge_reason='tiebreak:split ' || coalesce(judge_reason,'') "
                    "where ig_id=%s", (tcat, it.ig_id))
        conn.execute("update jobs set n_tiebreak=%s, tiebreak_agree=%s where id=%s",
                     (len(items), agree, job["id"]))
    return {"n": len(items), "agree": agree}

def _autohide(job: dict) -> int:
    """Auto-hide rule on the job's final hides (review runs only). Shadow records
    what would have hidden; live also stamps the decision, never overriding a
    human. Runs after the tiebreak so it sees resolved verdicts."""
    mode = _setting_str("autohide_mode", "shadow")
    if job["purpose"] != "review" or mode not in ("shadow", "live"):
        return 0
    sev = _setting("autohide_min_sev", 3)
    conf = _setting("autohide_min_conf", 0.9)
    rows = db.fetch_all(
        """select ig_id from comments
           where judge_job_id = %s and verdict = 'hide' and severity >= %s
             and confidence >= %s""", (job["id"], sev, conf))
    if not rows:
        db.execute("update jobs set n_autohide = 0 where id = %s", (job["id"],))
        return 0
    with db.tx() as conn:
        for r in rows:
            conn.execute(
                """insert into auto_actions (ig_id, job_id, action, mode)
                   values (%s, %s, 'hide', %s) on conflict (ig_id, job_id) do nothing""",
                (r["ig_id"], job["id"], mode))
        if mode == "live":
            note = f"auto-hide rule (S{int(sev)}, conf>={conf})"
            conn.execute(
                """update comments set decision = 'hide', decision_note = %s
                   where judge_job_id = %s and verdict = 'hide' and severity >= %s
                     and confidence >= %s and decision is null""",
                (note, job["id"], sev, conf))
        conn.execute("update jobs set n_autohide = %s where id = %s", (len(rows), job["id"]))
    return len(rows)

def execute(job_id: int) -> dict:
    job = db.fetch_one("select * from jobs where id=%s", (job_id,))
    model = db.fetch_one("select * from models where id=%s", (job["model"],))
    prompt = db.fetch_one("select * from prompts where version=%s", (job["prompt"],))
    client.ensure_loaded(model)
    try:
        rows = _scope_rows(job)
        sel = select(rows, load_lexicon(), judge_all=job["judge_all"])
        judge = _Judge(job, model, prompt)
        db.execute("update jobs set n_scope=%s, n_candidates=%s, n_total=%s where id=%s",
                   (len(rows), len(sel.candidates), len(sel.candidates), job_id))
        cand_flagged = judge(sel.candidates)

        # Adaptive audit: X candidates → X random others; draw X more while the judge flags
        # ≥ audit_expand_at of the latest draw (the NLP is missing things on this scope).
        rounds = []
        if not job["judge_all"] and sel.pool:
            expand_at = _setting("audit_expand_at", 0.2)
            budget = int((len(sel.candidates) + len(sel.pool)) * _setting("audit_max_share", 0.5))
            k = max(int(_setting("audit_min", 5)), len(sel.candidates))
            rng = random.Random(job["seed"])
            audited = 0
            while sel.pool and audited < budget:
                draw = draw_audit(sel.pool, min(k, budget - audited), rng, len(rounds) + 1)
                if not draw:
                    break
                rate = judge(draw) / len(draw)
                audited += len(draw)
                rounds.append({"round": len(rounds) + 1, "drawn": len(draw),
                               "rate": round(rate, 3), "expand": rate >= expand_at})
                db.execute("""update jobs set n_audit=%s, audit_rounds=%s, audit_last_rate=%s
                              where id=%s""", (audited, len(rounds), rate, job_id))
                if rate < expand_at:
                    break

        tb = _tiebreak(job, prompt) if job["purpose"] == "review" else {"n": 0, "agree": 0}
        ah = _autohide(job)
        db.execute("update jobs set status='done', finished_at=now() where id=%s", (job_id,))
        db.execute("select public.refresh_post_counts(array(select distinct post_code from comments "
                   "where judge_job_id = %s))", (job_id,))
        if job["sheet_id"]:
            sheets.mark_ready(job["sheet_id"])
        return {"job_id": job_id, "candidates": len(sel.candidates),
                "candidate_flagged": cand_flagged, "audit_rounds": rounds,
                "tiebreak": tb["n"], "tiebreak_agree": tb["agree"],
                "autohide": ah,
                "unique": judge.unique, "judged": judge.done}
    except Exception as e:
        db.execute("update jobs set status='failed', error=%s, finished_at=now() where id=%s",
                   (str(e)[:500], job_id))
        if job["sheet_id"]:
            sheets.fail(job["sheet_id"], str(e))
        raise
