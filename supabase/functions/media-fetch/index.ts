// media-fetch: copies post thumbnails from the Instagram CDN into Storage ("media" bucket).
// Called by the web app after a post-analytics upload; browsers can't fetch the CDN (CORS),
// and CDN links expire within days, so this has to happen at upload time.
// POST {urls: {code: url}} with the caller's JWT; admins only.

import { createClient } from "jsr:@supabase/supabase-js@2.45.4";

const URL_ = Deno.env.get("SUPABASE_URL")!;
const service = createClient(URL_, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, {
  auth: { persistSession: false },
});

const cors = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "authorization, x-client-info, apikey, content-type",
};
const json = (b: unknown, s = 200) =>
  new Response(JSON.stringify(b), { status: s, headers: { ...cors, "content-type": "application/json" } });

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  const auth = req.headers.get("authorization") ?? "";
  const user = createClient(URL_, Deno.env.get("SUPABASE_ANON_KEY")!, {
    global: { headers: { authorization: auth } }, auth: { persistSession: false },
  });
  const { data: isAdmin } = await user.rpc("is_admin");
  if (!isAdmin) return json({ error: "admins only" }, 403);

  const { urls } = (await req.json()) as { urls: Record<string, string> };
  const done: string[] = [];
  const failed: Record<string, string> = {};
  for (const [code, url] of Object.entries(urls ?? {}).slice(0, 200)) {
    try {
      const r = await fetch(url, {
        headers: { "user-agent": "Mozilla/5.0", referer: "https://www.instagram.com/" },
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const path = `thumbs/${code}.jpg`;
      const { error } = await service.storage.from("media")
        .upload(path, await r.arrayBuffer(), { contentType: "image/jpeg", upsert: true });
      if (error) throw error;
      await service.from("posts").update({ thumbnail_path: path }).eq("code", code);
      done.push(code);
    } catch (e) {
      failed[code] = String((e as Error).message ?? e).slice(0, 200);
    }
  }
  return json({ done: done.length, failed });
});
