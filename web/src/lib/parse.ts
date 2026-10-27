// In-browser CSV/JSON parsing for the laptop upload flow — a port of
// persocial/ingest/parsers.py that produces exactly the JSON rows the SQL
// ingest functions take. Keep the two in step. Both are driven by
// shared/input-aliases.json for the generic CSV contract; a parity test
// (tests/test_adapters.py) fails when the two disagree on the samples.
import Papa from "papaparse";
import aliases from "../../../shared/input-aliases.json";

export type Source = "comments_csv" | "apify_comments" | "generic_comments_csv" | "post_metrics_csv";

export interface CommentRow {
  ig_id: string; post_code: string; text: string;
  author_id: string | null; author: string | null; created_at: string | null;
  like_count: number | null; parent_ig_id: string | null; repeat_commenter: boolean;
  sentiment: { label: string; score: number }[] | null;
  emotions: { label: string; score: number }[] | null;
  scored_at: string | null; model_version: string | null;
}
export interface MetricRow {
  code: string; username: string; caption: string | null; posted_at: string | null;
  media_type: string | null; video_url: string | null; image_url: string | null;
  like_count: number | null; comment_count: number | null; play_count: number | null;
  engagement_rate: number | null; follower_count: number | null;
  following_count: number | null; media_count: number | null;
}
export interface Parsed {
  source: Source; filename: string; sha256: string; rowsTotal: number;
  comments: CommentRow[]; metrics: MetricRow[];
  rejects: { line: number; reason: string }[];
  hadScores: boolean; reportedCommentCount: number | null;
  capturedAt: string | null;
}

const FILE_POST = /^(.+?)-comment--(\d+)/i;
const URL_POST = /\/(?:p|reel|tv)\/([A-Za-z0-9_-]+)/;
const URL_COMMENT = /\/c\/(\d+)/;
const FILE_TS = /(\d{8})-(\d{6})/;

/** Display/ingest timezone; keep in step with PERSOCIAL_TZ (default UTC). */
const TZ = (import.meta.env.VITE_PERSOCIAL_TZ as string | undefined) || "UTC";

/** Offset (ms) of TZ from UTC at the given instant. */
function tzOffsetMs(utcMs: number): number {
  if (TZ === "UTC") return 0;
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: TZ, hour12: false,
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).formatToParts(new Date(utcMs)).map((x) => [x.type, x.value]),
  );
  return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second) - utcMs;
}

/** Naive wall time in TZ -> ISO string (Z form; same instant, explicit offset). */
function isoFromNaive(y: string, mo: string, d: string, h: string, mi: string, se: string): string {
  const wall = Date.UTC(+y, +mo - 1, +d, +h, +mi, +se);
  return new Date(wall - tzOffsetMs(wall)).toISOString();
}

/** Naive timestamps are in PERSOCIAL_TZ (default UTC). Day-first, never guessed. */
export function parseLocal(v?: string | null): string | null {
  if (!v) return null;
  const s = v.trim();
  if (!s) return null;
  if (s.endsWith(" UTC")) return s.slice(0, -4).replace(" ", "T") + "Z";
  if (/(Z|[+-]\d{2}:?\d{2})$/.test(s) && !Number.isNaN(Date.parse(s))) return new Date(s).toISOString();
  let m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4}),?\s*(?:(\d{1,2}):(\d{2})(?::(\d{2}))?)?$/);
  if (m) {
    const [, d, mo, y, h = "0", mi = "0", se = "0"] = m;
    return isoFromNaive(y, mo, d, h, mi, se);
  }
  m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}):(\d{2}))?$/);
  if (m) {
    const [, y, mo, d, h = "00", mi = "00", se = "00"] = m;
    return isoFromNaive(y, mo, d, h, mi, se);
  }
  return null;
}

const int = (v?: string) => (v == null || v.trim() === "" || Number.isNaN(Number(v)) ? null : Math.trunc(Number(v)));
const float = (v?: string) => (v == null || v.trim() === "" || Number.isNaN(Number(v)) ? null : Number(v));

/** Resolve a logical generic field through the shared alias map. */
function alias(r: Record<string, string>, field: string): string {
  for (const name of ((aliases as Record<string, string[]>)[field] ?? [])) {
    const v = r[name];
    if (v != null && v.trim() !== "") return v.trim();
  }
  return "";
}

async function sha1hex(s: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function scores(v?: string): { label: string; score: number }[] | null {
  if (!v || !v.trim()) return null;
  try {
    const p = JSON.parse(v);
    if (!Array.isArray(p)) return null;
    return p.filter((x) => x && "label" in x && "score" in x)
      .map((x) => ({ label: String(x.label), score: Number(x.score) }))
      .sort((a, b) => b.score - a.score);
  } catch {
    return null;
  }
}

/** Same order as parsers.py detect(): commentUrl beats everything, text-only is generic. */
export function detect(header: string[]): Source | null {
  const h = new Set(header);
  if (h.has("commentUrl")) return "apify_comments";
  if (h.has("Code") && (h.has("like_count") || h.has("comment_count"))) return "post_metrics_csv";
  if (h.has("id") && h.has("text") && (h.has("created_at") || h.has("postID"))) return "comments_csv";
  if (h.has("text")) return "generic_comments_csv";
  return null;
}

function flagRepeaters(rows: CommentRow[]) {
  const counts = new Map<string, number>();
  for (const r of rows) if (r.author) counts.set(`${r.post_code}|${r.author}`, (counts.get(`${r.post_code}|${r.author}`) ?? 0) + 1);
  for (const r of rows) if (r.author && (counts.get(`${r.post_code}|${r.author}`) ?? 0) > 3) r.repeat_commenter = true;
}

async function sha256(buf: ArrayBuffer): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

const urlPost = (u: string | undefined) => u?.match(URL_POST)?.[1] ?? null;

/** Flatten one JSON reply object (nested owner{}, like the CSV-string form). */
function flatReply(rep: unknown, post: string, parentId: string, into: CommentRow[]) {
  if (typeof rep !== "object" || rep === null) return;
  const o = rep as Record<string, unknown>;
  const rid = String(o.id ?? "").trim();
  if (!rid) return;
  const owner = (typeof o.owner === "object" && o.owner !== null ? o.owner : {}) as Record<string, unknown>;
  into.push({
    ig_id: rid, post_code: post, text: String(o.text ?? ""),
    author_id: String(owner.id ?? "") || null,
    author: String(owner.username ?? o.ownerUsername ?? "") || null,
    created_at: parseLocal(String(o.timestamp ?? "") || null),
    like_count: int(String(o.likesCount ?? "")), parent_ig_id: parentId,
    repeat_commenter: false, sentiment: null, emotions: null, scored_at: null, model_version: null,
  });
}

/** Apify JSON export: array, or an object wrapping one under comments/data/items. */
function parseApifyJson(filename: string, digest: string, payload: unknown): Parsed {
  let list = payload as unknown;
  if (list !== null && typeof list === "object" && !Array.isArray(list)) {
    const o = list as Record<string, unknown>;
    const wrap = ["comments", "data", "items"].find((k) => Array.isArray(o[k]));
    if (!wrap) throw new Error("JSON is not an array of comments (or wrapped in comments/data/items)");
    list = o[wrap];
  }
  if (!Array.isArray(list)) throw new Error("JSON is not an array of comments");
  const out: Parsed = {
    source: "apify_comments", filename, sha256: digest, rowsTotal: list.length,
    comments: [], metrics: [], rejects: [], hadScores: false, reportedCommentCount: null,
    capturedAt: null,
  };
  list.forEach((raw, idx) => {
    const line = idx + 1;
    if (typeof raw !== "object" || raw === null) {
      out.rejects.push({ line, reason: "not an object" });
      return;
    }
    const r = raw as Record<string, unknown>;
    const url = String(r.commentUrl ?? "");
    const post = urlPost(url) ?? urlPost(String(r.postUrl ?? "")) ?? "";
    const igId = String(r.id ?? "").trim() || url.match(URL_COMMENT)?.[1] || "";
    if (!igId || !post) {
      out.rejects.push({ line, reason: "no comment id / post code" });
      return;
    }
    const owner = (typeof r.owner === "object" && r.owner !== null ? r.owner : {}) as Record<string, unknown>;
    out.comments.push({
      ig_id: igId, post_code: post, text: String(r.text ?? ""),
      author_id: String(owner.id ?? "") || null,
      author: String(owner.username ?? r.ownerUsername ?? "") || null,
      created_at: parseLocal(String(r.timestamp ?? "") || null),
      like_count: int(String(r.likesCount ?? "")), parent_ig_id: null,
      repeat_commenter: false, sentiment: null, emotions: null, scored_at: null, model_version: null,
    });
    let replies = r.replies as unknown;
    if (typeof replies === "string" && replies.trim().startsWith("[")) {
      try { replies = JSON.parse(replies); } catch { replies = null; }
    }
    if (Array.isArray(replies)) {
      for (const rep of replies) flatReply(rep, post, igId, out.comments);
    } else if (replies != null) {
      out.rejects.push({ line, reason: "unreadable replies (parent kept)" });
    }
  });
  flagRepeaters(out.comments);
  return out;
}

export async function parseFile(file: File): Promise<Parsed> {
  const buf = await file.arrayBuffer();
  const digest = await sha256(buf);
  const text = new TextDecoder("utf-8").decode(buf).replace(/^﻿/, "");
  if (file.name.toLowerCase().endsWith(".json") || text.trimStart().startsWith("[")) {
    return parseApifyJson(file.name, digest, JSON.parse(text));
  }
  const res = Papa.parse<Record<string, string>>(text, { header: true, skipEmptyLines: true });
  const header = (res.meta.fields ?? []).map((f) => f.trim().replace(/^"|"$/g, ""));
  const rawRows = res.data as Record<string, string>[];
  // Normalise keys the way parsers.read_csv does (strip whitespace/quotes).
  const rows = rawRows.map((r) => {
    const o: Record<string, string> = {};
    for (const [k, v] of Object.entries(r)) o[k.trim().replace(/^"|"$/g, "")] = v;
    return o;
  });
  const source = detect(header);
  if (!source) throw new Error(`Unrecognised CSV header: ${header.slice(0, 10).join(", ")}`);
  const out: Parsed = {
    source, filename: file.name, sha256: digest, rowsTotal: rows.length,
    comments: [], metrics: [], rejects: [], hadScores: false, reportedCommentCount: null,
    capturedAt: null,
  };

  if (source === "comments_csv") {
    const fm = file.name.match(FILE_POST);
    const filePost = fm?.[1] ?? null;
    if (fm) out.reportedCommentCount = Number(fm[2]);
    const hasSpam = header.includes("Spam");
    rows.forEach((r, i) => {
      const igId = (r.id ?? "").trim();
      const post = (r.postID ?? "").trim() || filePost;
      if (!igId) return out.rejects.push({ line: i + 2, reason: "missing id or post code" });
      if (!post) return out.rejects.push({ line: i + 2, reason: "no postID and filename has no post code" });
      const sent = scores(r.sentiment_fast);
      if (out.reportedCommentCount == null) out.reportedCommentCount = int(r.comment_number);
      out.comments.push({
        ig_id: igId, post_code: post, text: r.text ?? "",
        author_id: (r.owner_id ?? "").trim() || null, author: (r.username ?? "").trim() || null,
        created_at: parseLocal(r.created_at), like_count: null, parent_ig_id: null,
        repeat_commenter: hasSpam && ["1", "1.0", "True"].includes((r.Spam ?? "").trim()),
        sentiment: sent, emotions: sent ? scores(r.emotions_fast) ?? [] : null,
        scored_at: sent ? parseLocal(r.updated_at) : null,
        model_version: (r.model_version ?? "").trim() || null,
      });
    });
    if (!hasSpam) flagRepeaters(out.comments);
    out.hadScores = out.comments.some((c) => c.sentiment);
  } else if (source === "apify_comments") {
    rows.forEach((r, i) => {
      const url = r.commentUrl ?? "";
      const post = urlPost(url) ?? urlPost(r.postUrl) ?? "";
      const igId = url.match(URL_COMMENT)?.[1] ?? (r.id ?? "").trim();
      if (!igId || !post) return out.rejects.push({ line: i + 2, reason: "no comment id / post code in commentUrl" });
      out.comments.push({
        ig_id: igId, post_code: post, text: r.text ?? "",
        author_id: (r["owner/id"] ?? "").trim() || null,
        author: (r.ownerUsername ?? r["owner/username"] ?? "").trim() || null,
        created_at: parseLocal(r.timestamp), like_count: int(r.likesCount), parent_ig_id: null,
        repeat_commenter: false, sentiment: null, emotions: null, scored_at: null, model_version: null,
      });
      const raw = r.replies ?? "";
      if (raw.trim().startsWith("[")) {
        try {
          for (const rep of JSON.parse(raw) as unknown[]) {
            if (typeof rep !== "object" || rep === null) continue;
            const o = rep as Record<string, unknown>;
            const rid = String(o.id ?? "").trim();
            if (!rid) continue;
            const owner = (typeof o.owner === "object" && o.owner !== null ? o.owner : {}) as Record<string, unknown>;
            out.comments.push({
              ig_id: rid, post_code: post, text: String(o.text ?? ""),
              author_id: String(owner.id ?? "") || null,
              author: String(owner.username ?? o.ownerUsername ?? "") || null,
              created_at: parseLocal(String(o.timestamp ?? "") || null),
              like_count: int(String(o.likesCount ?? "")), parent_ig_id: igId,
              repeat_commenter: false, sentiment: null, emotions: null, scored_at: null, model_version: null,
            });
          }
        } catch {
          out.rejects.push({ line: i + 2, reason: "unreadable replies column (parent kept)" });
        }
      }
    });
    flagRepeaters(out.comments);
  } else if (source === "generic_comments_csv") {
    // Resolved sequentially (sha1 needs await); generic uploads are small.
    return (async () => {
      for (let i = 0; i < rows.length; i++) {
        const r = rows[i];
        const line = i + 2;
        const t = (r.text ?? "").trim();
        if (!t) {
          out.rejects.push({ line, reason: "missing text" });
          continue;
        }
        const post = alias(r, "post_id") || urlPost(alias(r, "post_url")) || "";
        if (!post) {
          out.rejects.push({ line, reason: "no post_id or post_url" });
          continue;
        }
        const username = alias(r, "username") || null;
        const tsRaw = alias(r, "timestamp");
        let igId = alias(r, "comment_id");
        if (!igId) igId = await sha1hex(`${post}|${username ?? ""}|${tsRaw}|${t}`);
        out.comments.push({
          ig_id: igId, post_code: post, text: t,
          author_id: alias(r, "author_id") || null, author: username,
          created_at: parseLocal(tsRaw || null),
          like_count: int(alias(r, "likes") || undefined),
          parent_ig_id: alias(r, "parent_id") || null,
          repeat_commenter: false, sentiment: null, emotions: null, scored_at: null, model_version: null,
        });
      }
      flagRepeaters(out.comments);
      return out;
    })();
  } else {
    const m = file.name.match(FILE_TS);
    if (m) out.capturedAt = isoFromNaive(m[1].slice(0, 4), m[1].slice(4, 6), m[1].slice(6), m[2].slice(0, 2), m[2].slice(2, 4), m[2].slice(4));
    rows.forEach((r, i) => {
      const code = (r.Code ?? "").trim();
      const user = (r.username ?? "").trim();
      if (!code || !user) return out.rejects.push({ line: i + 2, reason: "missing Code or username" });
      const video = (r.video_url ?? "").trim() || null;
      out.metrics.push({
        code, username: user, caption: r.caption_text || null, posted_at: parseLocal(r.created_at),
        media_type: (r.carousel_media ?? "").trim() ? "carousel" : video ? "video" : "image",
        video_url: video, image_url: (r.img_small || r.img_origin || "").trim() || null,
        like_count: int(r.like_count), comment_count: int(r.comment_count), play_count: int(r.play_count),
        engagement_rate: float(r.engagement_rate), follower_count: int(r.user_follower_count),
        following_count: int(r.user_following_count), media_count: int(r.user_media_count),
      });
    });
  }
  return out;
}
