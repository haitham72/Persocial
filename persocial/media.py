"""Thumbnails and avatars → Supabase Storage bucket "media" (thumbs/{code}.jpg,
avatars/{username}.jpg). Instagram CDN links expire within days, so images are copied in
at ingest time; the web app reads them from storage, never from the CDN."""

from __future__ import annotations

from pathlib import Path

import httpx

from persocial import db
from persocial.config import settings

BUCKET = "media"


def _upload(path: str, data: bytes, base_url: str, key: str) -> None:
    """Plain insert first, upsert only if the object already exists. Some local storage
    server versions fail every upsert against a newer storage schema (42P10: no unique
    index on (name, bucket_id)), while a plain insert works on both."""
    h = {"Authorization": f"Bearer {key}", "apikey": key, "Content-Type": "image/jpeg"}
    url = f"{base_url}/storage/v1/object/{BUCKET}/{path}"
    r = httpx.post(url, content=data, timeout=30, headers=h)
    if r.status_code in (400, 409) and "exists" in r.text.lower():
        r = httpx.put(url, content=data, timeout=30, headers=h)
    r.raise_for_status()


def put(path: str, data: bytes) -> None:
    s = settings()
    _upload(path, data, s.supabase_url, s.supabase_service_key)


def store_thumbnail(code: str, data: bytes) -> str:
    path = f"thumbs/{code}.jpg"
    put(path, data)
    db.execute("update posts set thumbnail_path=%s where code=%s", (path, code))
    return path


def store_avatar(username: str, data: bytes) -> str:
    path = f"avatars/{username}.jpg"
    put(path, data)
    db.execute("update accounts set avatar_path=%s where username=%s", (path, username))
    return path


def fetch_thumbnails(urls: dict[str, str]) -> dict[str, str]:
    """Best effort: a dead CDN link must never fail an ingest. Returns {code: error}."""
    errors = {}
    with httpx.Client(timeout=15, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0",
                               "Referer": "https://www.instagram.com/"}) as client:
        for code, url in urls.items():
            try:
                r = client.get(url)
                r.raise_for_status()
                store_thumbnail(code, r.content)
            except Exception as e:  # noqa: BLE001
                errors[code] = str(e)[:200]
    return errors


def import_folder(thumbs_dir: Path | None = None, avatars_dir: Path | None = None) -> dict:
    """Backfill: img_small/{username}/{code}.jpg and profiles/{username}.jpg. Only posts we
    hold get a thumbnail; existing ones are skipped."""
    done = {"thumbs": 0, "avatars": 0, "failed": 0}
    if thumbs_dir:
        have = {r["code"] for r in db.fetch_all(
            "select code from posts where thumbnail_path is null")}
        for f in thumbs_dir.rglob("*.jpg"):
            if f.stem in have:
                try:
                    store_thumbnail(f.stem, f.read_bytes())
                    done["thumbs"] += 1
                except httpx.HTTPError:
                    done["failed"] += 1
    if avatars_dir:
        users = {r["username"] for r in db.fetch_all("select username from accounts")}
        for f in avatars_dir.glob("*.jpg"):
            if f.stem.lower() in users:
                try:
                    store_avatar(f.stem.lower(), f.read_bytes())
                    done["avatars"] += 1
                except httpx.HTTPError:
                    done["failed"] += 1
    return done
