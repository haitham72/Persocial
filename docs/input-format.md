# Input formats

Persocial ingests the comments on your own Instagram posts from two export
shapes. The format is auto-detected on upload (web) and on `persocial run`
(CLI) — you never pick it. Detection order: `commentUrl` → Apify export;
`Code` + like/comment counts → post-metrics snapshot; `id` + `text` +
(`created_at` or `postID`) → scored comments CSV; bare `text` → generic CSV.

## Apify recipe (comments export)

1. In the Apify Store, run an **Instagram Comment Scraper** actor on your own
   post URLs (one run per batch of posts is fine).
2. Export the run dataset as **CSV** (flattened `owner/username` columns) or
   **JSON** (array; nested `owner{}`, `replies[]` array). Both work: JSON keeps
   the nesting, CSV carries replies as a JSON string in the `replies` column.
3. Upload the file on the Upload page or pass it to `persocial run`.

Field mapping (unknown extra keys are ignored):

| Persocial field | CSV column | JSON field |
|---|---|---|
| comment id | `commentUrl` `/c/<id>`, else `id` | `commentUrl` `/c/<id>`, else `id` |
| post code | shortcode in `commentUrl` or `postUrl` (`/p/`, `/reel/`, `/tv/`) | same |
| text | `text` | `text` |
| author | `ownerUsername` or `owner/username` | `owner.username` (else `ownerUsername`) |
| author id | `owner/id` | `owner.id` |
| posted at | `timestamp` (ISO 8601, `Z` honored; naive → `PERSOCIAL_TZ`) | same |
| likes | `likesCount` | `likesCount` |
| replies | `replies` JSON string, flattened with `parent_id` | `replies[]` array, flattened with `parent_id` |

A wrapped object (`{"comments": [...]}`, `{"data": [...]}`, `{"items": [...]}`)
is unwrapped automatically. Comment ids may be any non-empty string.

## Generic CSV contract

For exports from any other tool. Only `text` is required.

| Logical field | Accepted column names | Notes |
|---|---|---|
| `text` | `text` | required; empty rows are rejected |
| comment id | `comment_id`, `id`, `commentId` | missing → `sha1(post\|username\|timestamp\|text)` |
| post | `post_id`, `postID`, `postId`, `post_code`, `code` | required (or `post_url`) |
| post url | `post_url`, `postUrl`, `url` | shortcode extracted from `/p/`, `/reel/`, `/tv/` |
| author | `username`, `ownerUsername`, `user`, `author` | |
| author id | `author_id`, `owner_id`, `ownerId` | |
| posted at | `timestamp`, `created_at`, `createdAt`, `date` | ISO 8601 preferred; naive → `PERSOCIAL_TZ` (default UTC) |
| likes | `likes`, `like_count`, `likesCount`, `likes_count` | |
| parent | `parent_id`, `parentId`, `parent` | set for replies |
| account | `account`, `account_username` | informational only |

The full map lives in `shared/input-aliases.json` and is shared by the
Python parser and the web parser — a parity test fails if they disagree.

## Demo example

The files in `examples/sample/` carry the same synthetic set in all three shapes (300 top-level comments + 24 flattened replies for the fictional `demo_bakery` account, posts DBK001-DBK003; every username starts with `demo_`). Same column contract as a generic CSV, e.g.:

```csv
comment_id,post_id,author_id,username,text,timestamp,likes,parent_id
90001,DBK001,501,demo_layla,Love this new sourdough recipe! Soft inside crusty outside.,2026-03-01T10:00:00Z,12,
90002,DBK001,502,demo_omar,How much is the family box?,2026-03-01T10:05:00Z,3,
91001,DBK001,500,demo_bakery,"The family box is 85, order a day ahead!",2026-03-01T11:00:00Z,5,90002
90003,DBK001,503,demo_noor,أحب مخبوزاتكم، خبز اليوم كان رائعا,2026-03-01T10:12:00Z,8,
90004,DBK002,504,demo_karim,"7abibi this kunafa is 3ajeeb, honestly the best",2026-03-02T09:00:00Z,15,
```

Re-uploading the same file twice adds 0 comments (files are deduplicated by
SHA-256; comments by `(post_code, ig_id)`).
