// Smoke test of the web app's data layer: signs in as a member (real session via the admin
// API) and runs exactly the queries the pages run, under row-level security.
//   node web/scripts/smoke.mjs <supabase-url> <anon-key> <service-key> <email>
import { createClient } from "@supabase/supabase-js";

const [url, anon, service, email] = process.argv.slice(2);
const admin = createClient(url, service, { auth: { persistSession: false } });
const { data: link, error: le } = await admin.auth.admin.generateLink({ type: "magiclink", email });
if (le) throw le;
const sb = createClient(url, anon, { auth: { persistSession: false } });
const { error: ve } = await sb.auth.verifyOtp({ token_hash: link.properties.hashed_token, type: "email" });
if (ve) throw ve;

let failures = 0;
async function check(name, fn) {
  try {
    const out = await fn();
    console.log(`ok   ${name}${out !== undefined ? ` — ${out}` : ""}`);
  } catch (e) {
    failures++;
    console.log(`FAIL ${name} — ${e.message ?? e}`);
  }
}
const must = async (p) => { const { data, error } = await p; if (error) throw new Error(error.message); return data; };

await check("auth: member row (role)", async () => (await must(sb.from("members").select("role").eq("email", email).single())).role);
let sheetId, postCode, igId;
await check("Inbox: review_sheets + post + account", async () => {
  const d = await must(sb.from("review_sheets").select("*, posts(caption, thumbnail_path, accounts(username))").limit(5));
  sheetId = d[0]?.id;
  return `${d.length} sheets`;
});
await check("Posts: accounts list", async () => `${(await must(sb.from("accounts").select("id, username"))).length} accounts`);
await check("Posts: post_grid", async () => {
  const d = await must(sb.rpc("post_grid", { p_account: null, p_sort: "posted", p_limit: 400 }));
  postCode = d.find((p) => p.n_flagged > 0)?.code ?? d[0]?.code;
  return `${d.length} posts, first delta ${JSON.stringify(d.find((p) => p.like_delta != null)?.like_delta ?? null)}`;
});
await check("Post: snapshots", async () => `${(await must(sb.from("post_snapshots").select("*").eq("post_code", postCode))).length}`);
await check("Post: post_comments flagged", async () => {
  const d = await must(sb.rpc("post_comments", { p_post: postCode, p_filter: "flagged", p_limit: 100, p_offset: 0 }));
  igId = d.rows[0]?.ig_id;
  return `${d.total} flagged on ${postCode}`;
});
if (sheetId) await check("Sheet: sheet_comments", async () => `${(await must(sb.rpc("sheet_comments", { p_sheet: sheetId }))).length} rows`);
await check("Scoring: pending_scoring", async () => `${(await must(sb.rpc("pending_scoring", { p_search: null }))).length} posts`);
await check("Scoring: leases", async () => `${(await must(sb.from("posts").select("code").not("claimed_by", "is", null))).length}`);
await check("Scoring: worker heartbeats", async () => `${(await must(sb.from("settings").select("key").like("key", "worker:%"))).length}`);
await check("Judge lab: models/prompts/lexicon/settings", async () => {
  const [m, p, l, s] = await Promise.all(["models", "prompts", "lexicon", "settings"].map((t) => must(sb.from(t).select("*"))));
  return `${m.length}/${p.length}/${l.length}/${s.length}`;
});
await check("Judge lab: jobs (admin read)", async () => `${(await must(sb.from("jobs").select("id").eq("kind", "judge"))).length} judge jobs`);
await check("Offenders: author_stats", async () => `${(await must(sb.rpc("author_stats", { p_limit: 200 }))).length} authors`);
await check("Upload: preview_comments", async () => `${(await must(sb.rpc("preview_comments", { p_rows: [{ p: postCode, i: igId ?? "1" }] })))[0]?.n_existing} existing`);
await check("Bell: notifications", async () => `${(await must(sb.from("notifications").select("*").limit(30))).length}`);
await check("Team: sla_hours + saved replies readable", async () => {
  const s = await must(sb.from("settings").select("value").eq("key", "sla_hours").single());
  const r = await must(sb.from("saved_replies").select("id").limit(5));
  return `sla ${s.value}h, ${r.length} replies`;
});
await check("Team: queue_comments (assignee/status fields)", async () => {
  const q = await must(sb.rpc("queue_comments", { p_limit: 50, p_offset: 0 }));
  if (q.length && !("assignee" in q[0] && "status" in q[0])) throw new Error("missing board fields");
  return `${q.length} queued`;
});
if (igId) {
  await check("Review: decide (DB stamps who/when), then undo", async () => {
    await must(sb.from("comments").update({ decision: "keep" }).eq("ig_id", igId));
    const row = await must(sb.from("comments").select("decision, decided_by, decided_at").eq("ig_id", igId).single());
    if (row.decided_by !== email) throw new Error(`decided_by=${row.decided_by}`);
    await must(sb.from("comments").update({ decision: null }).eq("ig_id", igId));
    return `${row.decision} by ${row.decided_by}`;
  });
  await check("Review: reviewers cannot edit verdicts (column grant)", async () => {
    const { error } = await sb.from("comments").update({ verdict: "keep" }).eq("ig_id", igId);
    if (!error) throw new Error("verdict update was allowed");
    return "blocked";
  });
}
if (igId) {
  await check("Team: board move + assign, audit timeline", async () => {
    const { data: { user } } = await sb.auth.getUser();
    await must(sb.from("comments").update({ status: "in_review", assignee: user.id }).eq("ig_id", igId));
    const row = await must(sb.from("comments").select("status, assignee").eq("ig_id", igId).single());
    if (row.status !== "in_review" || row.assignee !== user.id) throw new Error(`status=${row.status} assignee=${row.assignee}`);
    const evs = await must(sb.from("comment_events").select("action, actor").eq("comment_id", igId));
    const acts = evs.map((e) => e.action);
    if (!acts.includes("status") || !acts.includes("assignee")) throw new Error(`missing events: ${JSON.stringify(acts)}`);
    if (!evs.every((e) => e.actor === email)) throw new Error(`actor not stamped: ${JSON.stringify(evs.map((e) => e.actor))}`);
    await must(sb.from("comments").update({ status: "new", assignee: null }).eq("ig_id", igId));
    return `${evs.length} events`;
  });
}
const anonC = createClient(url, anon, { auth: { persistSession: false } });
await check("Security: signed-out sees no comments", async () => {
  const { data } = await anonC.from("comments").select("ig_id").limit(1);
  if (data?.length) throw new Error("anon read comments");
  return "0 rows";
});
console.log(failures ? `\n${failures} FAILED` : "\nALL OK");
process.exit(failures ? 1 : 0);
