"""Source adapters. Each turns one uploaded file into normalised records; the format is
detected from the header (or file shape for JSON), so the uploader never picks it. Source
ids are generic on purpose — no collection-tool names anywhere in this repo.

  comments_csv          one post's comments, raw or already scored (sentiment_fast/emotions_fast)
  apify_comments        third-party comment export (CSV or JSON): ids come from commentUrl / id
  generic_comments_csv  minimal contract: text required, legacy column aliases, synthetic ids
  post_metrics_csv      many posts' analytics snapshot (likes/comments/plays + images; optional)
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from persocial.config import REPO_ROOT
from persocial.ingest.dates import parse_local, snapshot_time_from_filename
from persocial.text import normalize, script_of

REPEAT_COMMENTER_THRESHOLD = 3          # legacy rule: >3 comments by one user on one post
_FILENAME_POST = re.compile(r"^(.+?)-comment--(\d+)", re.IGNORECASE)
_URL_POST = re.compile(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)")
_URL_COMMENT = re.compile(r"/c/(\d+)")

_ALIASES_PATH = REPO_ROOT / "shared" / "input-aliases.json"
with open(_ALIASES_PATH, encoding="utf-8") as _f:
    ALIASES = json.load(_f)


@dataclass
class CommentRow:
    ig_id: str
    post_code: str
    text: str
    owner_id: str | None = None
    username: str | None = None
    created_at: datetime | None = None
    like_count: int | None = None
    parent_ig_id: str | None = None
    repeat_commenter: bool = False
    sentiment: list[dict] | None = None       # [{label, score}] top first
    emotions: list[dict] | None = None        # [] = nothing above threshold
    scored_at: datetime | None = None
    model_version: str | None = None
    text_norm: str = ""
    script: str = "other"


@dataclass
class MetricRow:
    code: str
    username: str
    caption: str | None
    posted_at: datetime | None
    media_type: str | None
    video_url: str | None
    image_url: str | None
    like_count: int | None
    comment_count: int | None
    play_count: int | None
    engagement_rate: float | None
    follower_count: int | None
    following_count: int | None
    media_count: int | None


@dataclass
class Parsed:
    source: str
    comments: list[CommentRow] = field(default_factory=list)
    metrics: list[MetricRow] = field(default_factory=list)
    rejects: list[dict] = field(default_factory=list)
    rows_total: int = 0
    had_scores: bool = False
    reported_comment_count: int | None = None
    claim_id: str | None = None
    captured_at: datetime | None = None


def read_csv(data: bytes) -> tuple[list[str], list[dict]]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = [{(k or "").strip().strip('"'): (v or "") for k, v in r.items()} for r in reader]
    header = [(h or "").strip().strip('"') for h in (reader.fieldnames or [])]
    return header, rows


def detect(header: list[str]) -> str | None:
    h = set(header)
    if "commentUrl" in h:
        return "apify_comments"
    if "Code" in h and ("like_count" in h or "comment_count" in h):
        return "post_metrics_csv"
    if {"id", "text"} <= h and ("created_at" in h or "postID" in h):
        return "comments_csv"
    if "text" in h:
        return "generic_comments_csv"
    return None


def _url_post(url: str) -> str | None:
    m = _URL_POST.search(url or "")
    return m.group(1) if m else None


def _url_comment_id(url: str) -> str | None:
    m = _URL_COMMENT.search(url or "")
    return m.group(1) if m else None


def _alias(row: dict, field: str) -> str:
    for name in ALIASES.get(field, []):
        v = row.get(name)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _int(v: str | None) -> int | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _float(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _int_json(v) -> int | None:
    """likesCount from JSON-ish sources: 0 is a real count, only None/blank is missing."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    return _int(str(v))


def _scores(v: str | None) -> list[dict] | None:
    """None = column empty (unscored). [] = scored, nothing above threshold."""
    if v is None or not str(v).strip():
        return None
    try:
        parsed = json.loads(v)
    except ValueError:
        return None
    if not isinstance(parsed, list):
        return None
    out = [{"label": str(x["label"]), "score": float(x["score"])}
           for x in parsed if isinstance(x, dict) and "label" in x and "score" in x]
    return sorted(out, key=lambda x: x["score"], reverse=True)


def _finish(c: CommentRow) -> CommentRow:
    c.text_norm = normalize(c.text)
    c.script = script_of(c.text)
    return c


def _flag_repeaters(rows: list[CommentRow]) -> None:
    counts = Counter((r.post_code, r.username) for r in rows if r.username)
    for r in rows:
        if r.username and counts[(r.post_code, r.username)] > REPEAT_COMMENTER_THRESHOLD:
            r.repeat_commenter = True


def parse_comments_csv(filename: str, rows: list[dict]) -> Parsed:
    out = Parsed(source="comments_csv", rows_total=len(rows))
    m = _FILENAME_POST.match(filename.rsplit("/", 1)[-1])
    file_post = m.group(1) if m else None
    if m:
        out.reported_comment_count = int(m.group(2))
    has_spam_col = any("Spam" in r for r in rows[:1])
    for i, r in enumerate(rows, start=2):            # line 1 is the header
        ig_id = (r.get("id") or "").strip()
        post = (r.get("postID") or "").strip() or file_post
        if not ig_id or not post:
            out.rejects.append({"line": i, "reason": "missing id or post code",
                                  "id": ig_id[:40]})
            continue
        sent, emo = _scores(r.get("sentiment_fast")), _scores(r.get("emotions_fast"))
        if out.reported_comment_count is None:
            out.reported_comment_count = _int(r.get("comment_number"))
        if r.get("claim_id"):
            out.claim_id = r["claim_id"].strip()
        out.comments.append(_finish(CommentRow(
            ig_id=ig_id, post_code=post, text=r.get("text") or "",
            owner_id=(r.get("owner_id") or "").strip() or None,
            username=(r.get("username") or "").strip() or None,
            created_at=parse_local(r.get("created_at")),
            repeat_commenter=has_spam_col and str(r.get("Spam", "")).strip() in ("1", "1.0", "True"),
            sentiment=sent, emotions=emo if sent is not None else None,
            scored_at=parse_local(r.get("updated_at")) if sent is not None else None,
            model_version=(r.get("model_version") or "").strip() or None,
        )))
    if not has_spam_col:
        _flag_repeaters(out.comments)
    out.had_scores = any(c.sentiment is not None for c in out.comments)
    return out


def parse_apify_comments(filename: str, rows: list[dict]) -> Parsed:
    out = Parsed(source="apify_comments", rows_total=len(rows))
    for i, r in enumerate(rows, start=2):
        url = r.get("commentUrl") or ""
        pm, cm = _url_post(url), _url_comment_id(url)
        post = pm or (_url_post(r.get("postUrl") or "") or "")
        ig_id = cm or (r.get("id") or "").strip()
        if not ig_id or not post:
            out.rejects.append({"line": i, "reason": "no comment id / post code in commentUrl"})
            continue
        out.comments.append(_finish(CommentRow(
            ig_id=ig_id, post_code=post, text=r.get("text") or "",
            owner_id=(r.get("owner/id") or "").strip() or None,
            username=(r.get("ownerUsername") or r.get("owner/username") or "").strip() or None,
            created_at=parse_local(r.get("timestamp")),
            like_count=_int(r.get("likesCount")),
        )))
        replies = r.get("replies") or ""
        if isinstance(replies, str) and replies.strip().startswith("["):
            try:
                for rep in json.loads(replies):
                    rid = str(rep.get("id") or "").strip()
                    if rid:
                        out.comments.append(_finish(CommentRow(
                            ig_id=rid, post_code=post, text=rep.get("text") or "",
                            owner_id=str((rep.get("owner") or {}).get("id") or "") or None,
                            username=rep.get("ownerUsername") or None,
                            created_at=parse_local(rep.get("timestamp")),
                            like_count=_int_json(rep.get("likesCount")),
                            parent_ig_id=ig_id,
                        )))
            except (ValueError, AttributeError):
                out.rejects.append({"line": i, "reason": "unreadable replies column (parent kept)"})
    _flag_repeaters(out.comments)
    return out


def parse_apify_json(filename: str, data: bytes) -> Parsed:
    """Apify export as a JSON array (or an object wrapping one under comments/data/items).
    Nested `owner{}` and `replies[]` are flattened into flat CommentRows with parent_ids."""
    try:
        payload = json.loads(data.decode("utf-8-sig", errors="strict"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"invalid JSON: {e}") from None
    if isinstance(payload, dict):
        for k in ("comments", "data", "items"):
            if isinstance(payload.get(k), list):
                payload = payload[k]
                break
        else:
            raise ValueError("JSON is not an array of comments (or wrapped in comments/data/items)")
    if not isinstance(payload, list):
        raise ValueError("JSON is not an array of comments")  # noqa: TRY004 -- callers catch ValueError
    out = Parsed(source="apify_comments", rows_total=len(payload))
    for i, r in enumerate(payload, start=1):
        if not isinstance(r, dict):
            out.rejects.append({"line": i, "reason": "not an object"})
            continue
        url = str(r.get("commentUrl") or "")
        post = _url_post(url) or _url_post(str(r.get("postUrl") or ""))
        ig_id = str(r.get("id") or "").strip() or _url_comment_id(url) or ""
        if not ig_id or not post:
            out.rejects.append({"line": i, "reason": "no comment id / post code"})
            continue
        owner = r.get("owner") if isinstance(r.get("owner"), dict) else {}
        out.comments.append(_finish(CommentRow(
            ig_id=ig_id, post_code=post, text=str(r.get("text") or ""),
            owner_id=str(owner.get("id") or "") or None,
            username=str(owner.get("username") or r.get("ownerUsername") or "") or None,
            created_at=parse_local(str(r.get("timestamp") or "") or None),
            like_count=_int_json(r.get("likesCount")),
        )))
        replies = r.get("replies")
        if isinstance(replies, str) and replies.strip().startswith("["):
            try:
                replies = json.loads(replies)
            except ValueError:
                replies = None
        if isinstance(replies, list):
            for rep in replies:
                if not isinstance(rep, dict):
                    continue
                rid = str(rep.get("id") or "").strip()
                if not rid:
                    continue
                rowner = rep.get("owner") if isinstance(rep.get("owner"), dict) else {}
                out.comments.append(_finish(CommentRow(
                    ig_id=rid, post_code=post, text=str(rep.get("text") or ""),
                    owner_id=str(rowner.get("id") or "") or None,
                    username=str(rowner.get("username") or rep.get("ownerUsername") or "") or None,
                    created_at=parse_local(str(rep.get("timestamp") or "") or None),
                    like_count=_int_json(rep.get("likesCount")),
                    parent_ig_id=ig_id,
                )))
        elif replies is not None:
            out.rejects.append({"line": i, "reason": "unreadable replies (parent kept)"})
    _flag_repeaters(out.comments)
    return out


def parse_generic_comments(filename: str, rows: list[dict]) -> Parsed:
    """Minimal CSV contract: text required; legacy column aliases via shared/input-aliases.json;
    missing id is synthesized deterministically as sha1(post|username|timestamp|text)."""
    out = Parsed(source="generic_comments_csv", rows_total=len(rows))
    for i, r in enumerate(rows, start=2):
        text = (r.get("text") or "").strip()
        if not text:
            out.rejects.append({"line": i, "reason": "missing text"})
            continue
        post = _alias(r, "post_id") or _url_post(_alias(r, "post_url"))
        if not post:
            out.rejects.append({"line": i, "reason": "no post_id or post_url"})
            continue
        username = _alias(r, "username") or None
        ts_raw = _alias(r, "timestamp")
        ig_id = _alias(r, "comment_id")
        if not ig_id:
            ig_id = hashlib.sha1(f"{post}|{username or ''}|{ts_raw}|{text}".encode()).hexdigest()
        out.comments.append(_finish(CommentRow(
            ig_id=ig_id, post_code=post, text=text,
            owner_id=_alias(r, "author_id") or None,
            username=username,
            created_at=parse_local(ts_raw or None),
            like_count=_int(_alias(r, "likes") or None),
            parent_ig_id=_alias(r, "parent_id") or None,
        )))
    _flag_repeaters(out.comments)
    return out


def parse_post_metrics(filename: str, rows: list[dict]) -> Parsed:
    out = Parsed(source="post_metrics_csv", rows_total=len(rows))
    out.captured_at = snapshot_time_from_filename(filename)
    for i, r in enumerate(rows, start=2):
        code = (r.get("Code") or "").strip()
        user = (r.get("username") or "").strip()
        if not code or not user:
            out.rejects.append({"line": i, "reason": "missing Code or username"})
            continue
        video = (r.get("video_url") or "").strip() or None
        out.metrics.append(MetricRow(
            code=code, username=user, caption=r.get("caption_text") or None,
            posted_at=parse_local(r.get("created_at")),
            media_type="carousel" if (r.get("carousel_media") or "").strip()
                       else ("video" if video else "image"),
            video_url=video,
            image_url=(r.get("img_small") or r.get("img_origin") or "").strip() or None,
            like_count=_int(r.get("like_count")), comment_count=_int(r.get("comment_count")),
            play_count=_int(r.get("play_count")), engagement_rate=_float(r.get("engagement_rate")),
            follower_count=_int(r.get("user_follower_count")),
            following_count=_int(r.get("user_following_count")), media_count=_int(r.get("user_media_count")),
        ))
    return out


PARSERS = {
    "comments_csv": parse_comments_csv,
    "apify_comments": parse_apify_comments,
    "generic_comments_csv": parse_generic_comments,
    "post_metrics_csv": parse_post_metrics,
}


def parse_file(filename: str, data: bytes) -> Parsed:
    head = data.lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"[") or filename.lower().endswith(".json"):
        return parse_apify_json(filename, data)
    header, rows = read_csv(data)
    source = detect(header)
    if source is None:
        raise ValueError(f"unrecognised CSV header: {', '.join(header[:12])}")
    return PARSERS[source](filename, rows)
