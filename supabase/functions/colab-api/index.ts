// colab-api: the only door the Colab notebook uses. Token-guarded (x-colab-token, set with
// `supabase secrets set COLAB_TOKEN=...`), calls the same SQL functions the web app and the
// ops service use, with the service role — so the notebook never holds a database password
// or the service key.
//
// POST {action, ...}
//   pending   {search?}                   -> [{code, username, caption, n_unscored, claimed}]
//   claim     {post_codes?: string[], n?, runner} -> [{post_code, n_unscored, expires_at}]
//             (post_codes null = next unscored posts, newest first)
//   comments  {post_code, limit?}         -> [{ig_id, text}]  still-unscored only
//   submit    {post_code, rows, runner}   -> {written, remaining}   (a save point)
//   release   {post_code}                 -> {ok}

import { createClient } from "jsr:@supabase/supabase-js@2.45.4";

const db = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  { auth: { persistSession: false } },
);

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return json({ error: "POST only" }, 405);
  const expected = Deno.env.get("COLAB_TOKEN") ?? "";
  const got = req.headers.get("x-colab-token") ?? "";
  if (!expected || !timingSafeEqual(got, expected)) return json({ error: "unauthorized" }, 401);

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return json({ error: "body must be JSON" }, 400);
  }

  const rpc = async (fn: string, args: Record<string, unknown>) => {
    const { data, error } = await db.rpc(fn, args);
    if (error) throw new Error(`${fn}: ${error.message}`);
    return data;
  };

  try {
    switch (body.action) {
      case "pending":
        return json(await rpc("pending_scoring", { p_search: body.search ?? null }));
      case "claim":
        return json(await rpc("claim_posts", {
          p_post_codes: body.post_codes ?? null,
          p_n: Number(body.n ?? 1),
          p_runner: String(body.runner ?? "colab"),
        }));
      case "comments":
        return json(await rpc("claim_comments", {
          p_post: body.post_code,
          p_limit: Math.min(Number(body.limit ?? 5000), 20000),
        }));
      case "submit":
        return json(await rpc("submit_scores", {
          p_post: body.post_code,
          p_rows: body.rows,
          p_runner: String(body.runner ?? "colab"),
        }));
      case "release":
        return json({ ok: await rpc("release_claim", { p_post: body.post_code }) });
      default:
        return json({ error: `unknown action ${body.action}` }, 400);
    }
  } catch (e) {
    return json({ error: String((e as Error).message ?? e) }, 500);
  }
});
