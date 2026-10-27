"""WP4 input-adapter tests: apify CSV/JSON, generic CSV, alias map, 3-file parity.

The fixtures in examples/sample/ are the full WP5 synthetic set (300 top-level
comments + 24 replies with identical content across all three formats, written
by examples/make_sample_comments.py). The parity test compares the three
parses against each other (not hardcoded counts) plus structural guards:
every row flattened, parents linked, demo_* usernames (G1.8).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json

from persocial.config import REPO_ROOT
from persocial.ingest import parsers
from persocial.ingest.parsers import detect, parse_file

SAMPLE = REPO_ROOT / "examples" / "sample"


def _csv_bytes(rows: list[dict], header: list[str]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in header})
    return buf.getvalue().encode("utf-8")


APIFY_HEADER = ["commentUrl", "id", "likesCount", "owner/id", "owner/username",
                "ownerUsername", "postUrl", "replies", "repliesCount", "text", "timestamp"]


def _apify_row(i: int = 0, **kw) -> dict:
    base = {"commentUrl": "https://www.instagram.com/p/DBK001/c/90001/",
            "id": "90001", "likesCount": "12", "owner/id": "501",
            "owner/username": "demo_layla", "ownerUsername": "demo_layla",
            "postUrl": "https://www.instagram.com/p/DBK001/",
            "replies": "", "repliesCount": "0",
            "text": "Love this one!", "timestamp": "2026-03-01T10:00:00Z"}
    base.update(kw)
    return base


def test_apify_csv_parses_and_relaxes_ids():
    data = _csv_bytes([_apify_row(), _apify_row(id="abc-xyz", commentUrl="",
                                                postUrl="https://www.instagram.com/p/DBK002/")],
                      APIFY_HEADER)
    out = parse_file("export.csv", data)
    assert out.source == "apify_comments"
    assert [c.ig_id for c in out.comments] == ["90001", "abc-xyz"]
    assert [c.post_code for c in out.comments] == ["DBK001", "DBK002"]
    assert out.comments[0].username == "demo_layla"
    assert out.rejects == []


def test_apify_json_parses_with_nested_owner_and_replies():
    payload = [{"commentUrl": "https://www.instagram.com/p/DBK001/c/90002/",
                "id": "90002", "likesCount": 3,
                "owner": {"id": "502", "username": "demo_omar"},
                "postUrl": "https://www.instagram.com/p/DBK001/",
                "text": "How much?", "timestamp": "2026-03-01T10:05:00Z",
                "replies": [{"id": "91001", "likesCount": 5,
                             "owner": {"id": "500", "username": "demo_bakery"},
                             "text": "85, order ahead!",
                             "timestamp": "2026-03-01T11:00:00Z"}]}]
    out = parse_file("export.json", json.dumps(payload).encode("utf-8"))
    assert out.source == "apify_comments"
    assert len(out.comments) == 2
    parent, reply = out.comments
    assert (parent.ig_id, parent.username) == ("90002", "demo_omar")
    assert (reply.ig_id, reply.parent_ig_id, reply.username) == ("91001", "90002", "demo_bakery")
    assert reply.like_count == 5


def test_generic_csv_legacy_aliases():
    # Legacy names that stay on the generic branch (literal id + created_at/postID
    # would detect as comments_csv instead — see test_detect_ordering).
    header = ["commentId", "postId", "user", "text", "createdAt"]
    data = _csv_bytes([{"commentId": "90004", "postId": "DBK002", "user": "demo_karim",
                        "text": "7abibi this is 3ajeeb", "createdAt": "2026-03-02T09:00:00Z"}],
                      header)
    out = parse_file("mine.csv", data)
    assert out.source == "generic_comments_csv"
    assert len(out.comments) == 1
    c = out.comments[0]
    assert (c.ig_id, c.post_code, c.username) == ("90004", "DBK002", "demo_karim")
    assert c.created_at is not None and c.created_at.isoformat() == "2026-03-02T09:00:00+00:00"


def test_generic_csv_missing_id_gets_deterministic_sha1():
    header = ["post_id", "username", "timestamp", "text"]
    row = {"post_id": "DBK001", "username": "demo_noor",
           "timestamp": "2026-03-01T10:12:00Z", "text": "nice bread"}
    out1 = parse_file("a.csv", _csv_bytes([row], header))
    out2 = parse_file("b.csv", _csv_bytes([row], header))
    assert len(out1.comments) == len(out2.comments) == 1
    want = hashlib.sha1(b"DBK001|demo_noor|2026-03-01T10:12:00Z|nice bread").hexdigest()
    assert out1.comments[0].ig_id == want == out2.comments[0].ig_id


def test_generic_missing_text_rejected():
    header = ["post_id", "username", "timestamp", "text"]
    data = _csv_bytes([{"post_id": "DBK001", "username": "demo_x",
                        "timestamp": "2026-03-01T10:00:00Z", "text": ""}], header)
    out = parse_file("a.csv", data)
    assert out.comments == [] and len(out.rejects) == 1


def test_detect_ordering():
    assert detect(["commentUrl", "id", "text"]) == "apify_comments"
    assert detect(["Code", "username", "like_count"]) == "post_metrics_csv"
    assert detect(["id", "text", "created_at"]) == "comments_csv"
    assert detect(["id", "text", "postID"]) == "comments_csv"
    assert detect(["text", "username"]) == "generic_comments_csv"
    assert detect(["Code", "username"]) is None


def test_shared_alias_map_parity():
    raw = (REPO_ROOT / "shared" / "input-aliases.json").read_text(encoding="utf-8")
    aliases = json.loads(raw)
    for logical in ("comment_id", "post_id", "post_url", "username", "author_id",
                    "timestamp", "likes", "parent_id", "account", "text"):
        assert logical in aliases, f"missing alias group: {logical}"
    assert set(parsers.ALIASES) == set(aliases)
    assert "postID" in aliases["post_id"] and "ownerUsername" in aliases["username"]


def _key_tuple(c):
    return (c.ig_id, c.post_code, c.text, c.username, c.owner_id,
            c.created_at.isoformat() if c.created_at else None,
            c.like_count, c.parent_ig_id)


def test_three_file_parity():
    assert SAMPLE.is_dir(), "examples/sample/ fixtures missing"
    by_name = {}
    for name in ("apify.csv", "apify.json", "generic.csv"):
        by_name[name] = parse_file(name, (SAMPLE / name).read_bytes())
    assert {p.source for p in by_name.values()} == {"apify_comments", "generic_comments_csv"}
    keys = {name: sorted(_key_tuple(c) for c in p.comments) for name, p in by_name.items()}
    assert keys["apify.csv"] == keys["apify.json"] == keys["generic.csv"]
    assert len(keys["apify.csv"]) > 6, "replies must be flattened into extra rows"
    assert any(c.parent_ig_id for p in by_name.values() for c in p.comments)
    for p in by_name.values():
        for c in p.comments:
            assert c.username and c.username.startswith("demo_"), c.username
            assert c.ig_id.startswith("900") or c.ig_id.startswith("910")
