import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { FileUp, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";
import { mediaUrl, must, rpc, supabase } from "../lib/supabase";
import { parseFile, type Parsed } from "../lib/parse";
import { localTime, n } from "../lib/format";
import { Button, Card, Chip, ErrorBox, PageHeader, StatusChip } from "../components/ui";

const CHUNK = 2000;

interface PreviewPost {
  code: string; known: boolean; registered: boolean; status: string | null; account: string | null;
  caption: string | null; thumbnail_path: string | null; like_count: number | null;
  comment_count: number | null; metrics_updated_at: string | null; stored_comments: number;
  n_rows: number; n_existing: number; n_new: number;
}
interface Item {
  key: string; file: File; parsed?: Parsed; preview?: PreviewPost[]; metricsKnown?: number;
  account: string; state: "parsing" | "ready" | "uploading" | "done" | "error";
  progress?: number; result?: Record<string, any>; error?: unknown;
}

export default function Upload() {
  const qc = useQueryClient();
  const [items, setItems] = useState<Item[]>([]);
  const [drag, setDrag] = useState(false);
  const accounts = useQuery({
    queryKey: ["accounts"],
    queryFn: () => must(supabase.from("accounts").select("username").order("username")),
  });
  const update = (key: string, p: Partial<Item>) =>
    setItems((xs) => xs.map((x) => (x.key === key ? { ...x, ...p } : x)));

  const addFiles = useCallback(async (files: FileList | File[]) => {
    const fresh: Item[] = [...files].map((f) => ({ key: `${f.name}-${f.size}-${Math.random()}`, file: f, account: "", state: "parsing" }));
    setItems((xs) => [...fresh, ...xs]);
    for (const it of fresh) {
      try {
        const parsed = await parseFile(it.file);
        if (parsed.source === "post_metrics_csv") {
          const codes = parsed.metrics.map((m) => m.code);
          const known = await must(supabase.from("posts").select("code", { count: "exact" }).in("code", codes.slice(0, 500)));
          update(it.key, { parsed, metricsKnown: (known as unknown[]).length, state: "ready" });
        } else {
          const preview = await rpc<PreviewPost[]>("preview_comments", {
            p_rows: parsed.comments.map((c) => ({ p: c.post_code, i: c.ig_id })),
          });
          update(it.key, { parsed, preview, state: "ready" });
        }
      } catch (e) {
        update(it.key, { state: "error", error: e });
      }
    }
  }, []);

  const commit = async (it: Item) => {
    const p = it.parsed!;
    update(it.key, { state: "uploading", progress: 0 });
    try {
      const begin = await rpc<{ upload_id: number; duplicate: boolean }>("ingest_begin", {
        p_source: p.source, p_filename: p.filename, p_sha: p.sha256,
        p_meta: { account: it.account || null, reported_comment_count: p.reportedCommentCount,
          rows_total: p.rowsTotal, rows_rejected: p.rejects.length,
          reject_note: p.rejects.slice(0, 20).map((r) => `line ${r.line}: ${r.reason}`).join("; ") || null,
          captured_at: p.capturedAt },
      });
      if (begin.duplicate) {
        update(it.key, { state: "done", result: { duplicate: true } });
        return;
      }
      const rows = p.source === "post_metrics_csv" ? p.metrics : p.comments;
      let images: Record<string, string> = {};
      for (let i = 0; i < rows.length; i += CHUNK) {
        const chunk = rows.slice(i, i + CHUNK);
        if (p.source === "post_metrics_csv") {
          const out = await rpc<{ image_urls: Record<string, string> }>("ingest_metrics_chunk", {
            p_upload: begin.upload_id, p_rows: chunk, p_captured_at: p.capturedAt ?? new Date().toISOString() });
          images = { ...images, ...out.image_urls };
        } else {
          await rpc("ingest_comments_chunk", { p_upload: begin.upload_id, p_rows: chunk, p_account: it.account || null });
        }
        update(it.key, { progress: Math.min(1, (i + CHUNK) / rows.length) });
      }
      const fin = await rpc<Record<string, any>>("ingest_finish", { p_upload: begin.upload_id, p_create_sheets: true });
      if (Object.keys(images).length) {
        // thumbnails: the Instagram CDN blocks browsers, so the server side fetches them
        supabase.functions.invoke("media-fetch", { body: { urls: images } }).catch(() => {});
      }
      update(it.key, { state: "done", result: { ...fin, thumbnails: Object.keys(images).length } });
      qc.invalidateQueries();
    } catch (e) {
      update(it.key, { state: "error", error: e });
    }
  };

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Upload" sub="Apify comments export (CSV or JSON), a generic comments CSV, a scored comments CSV, or a post-analytics CSV. Format is detected automatically." />
      <label
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}
        className={clsx("flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-10 text-center transition-colors",
          drag ? "border-accent bg-accent-soft" : "border-line bg-panel hover:border-accent/50")}>
        <FileUp className="h-8 w-8 text-faint" />
        <div className="mt-2 font-medium">Drop CSV or JSON files here or click to choose</div>
        <div className="text-sm text-dim">Nothing is saved until you confirm each file.</div>
        <input type="file" accept=".csv,.json,application/json,text/csv" multiple className="hidden"
          onChange={(e) => e.target.files && addFiles(e.target.files)} />
      </label>

      <div className="mt-6 space-y-4">
        {items.map((it) => (
          <Card key={it.key} className="p-4">
            <div className="flex items-center gap-2">
              <span className="truncate font-medium">{it.file.name}</span>
              {it.parsed && <Chip>{it.parsed.source.replace(/_/g, " ")}</Chip>}
              {it.parsed && <span className="text-xs text-dim">{n(it.parsed.rowsTotal)} rows{it.parsed.hadScores ? " · already scored" : ""}</span>}
              <span className="ml-auto">
                {it.state === "parsing" && <Loader2 className="h-4 w-4 animate-spin text-dim" />}
                {it.state === "done" && <CheckCircle2 className="h-5 w-5 text-keep" />}
                {it.state === "error" && <AlertTriangle className="h-5 w-5 text-hide" />}
              </span>
            </div>
            <ErrorBox error={it.error} />
            {it.parsed && it.parsed.rejects.length > 0 && (
              <div className="mt-2 text-xs text-review">
                {it.parsed.rejects.length} rows will be skipped (e.g. line {it.parsed.rejects[0].line}: {it.parsed.rejects[0].reason})
              </div>
            )}

            {it.preview?.map((p) => (
              <div key={p.code} className="mt-3 flex gap-3 rounded-lg border border-line p-3">
                <div className="h-16 w-16 shrink-0 overflow-hidden rounded-md bg-bg">
                  {mediaUrl(p.thumbnail_path) && <img src={mediaUrl(p.thumbnail_path)!} alt="" className="h-full w-full object-cover" />}
                </div>
                <div className="min-w-0 flex-1 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs">{p.code}</span>
                    {p.known ? <StatusChip status={p.registered ? "registered" : "pending"} /> : <Chip kind="review">not registered</Chip>}
                    {p.account && <span className="text-dim">@{p.account}</span>}
                  </div>
                  {p.known ? (
                    <div className="mt-1 text-xs text-dim">
                      {p.registered
                        ? <>Likes {n(p.like_count)} · comments on IG {n(p.comment_count)} · as of {localTime(p.metrics_updated_at)}</>
                        : "Known only from a previous comments upload — waiting for a post-analytics export."}
                      {" · "}{n(p.stored_comments)} comments already stored
                    </div>
                  ) : (
                    <div className="mt-1 text-xs text-dim">
                      This post isn't in the system yet. It will be created as <b>pending</b> under the account you pick.
                    </div>
                  )}
                  <div className="mt-2 flex gap-4 text-xs">
                    <span><b className="tabular-nums">{n(p.n_rows)}</b> in file</span>
                    <span className="text-dim"><b className="tabular-nums">{n(p.n_existing)}</b> already stored (skipped)</span>
                    <span className="text-keep"><b className="tabular-nums">{n(p.n_new)}</b> new</span>
                  </div>
                  {!p.known && it.state === "ready" && (
                    <div className="mt-2 flex items-center gap-2">
                      <span className="text-xs text-dim">Account</span>
                      <input list="accounts" value={it.account} onChange={(e) => update(it.key, { account: e.target.value })}
                        placeholder="username" className="rounded-md border border-line bg-panel px-2 py-1 text-sm" />
                      <datalist id="accounts">
                        {((accounts.data as { username: string }[]) ?? []).map((a) => <option key={a.username} value={a.username} />)}
                      </datalist>
                    </div>
                  )}
                </div>
              </div>
            ))}

            {it.parsed?.source === "post_metrics_csv" && it.state !== "done" && (
              <div className="mt-2 text-sm text-dim">
                {n(it.parsed.metrics.length)} posts · {n(it.metricsKnown)} already known (metrics will update) ·{" "}
                {n(it.parsed.metrics.length - (it.metricsKnown ?? 0))} new
              </div>
            )}

            {it.state === "ready" && (
              <div className="mt-3 flex items-center gap-2">
                <Button variant="primary"
                  disabled={!!it.preview?.some((p) => !p.known) && !it.account}
                  onClick={() => commit(it)}>
                  Confirm upload
                </Button>
                <Button variant="ghost" onClick={() => setItems((xs) => xs.filter((x) => x.key !== it.key))}>Discard</Button>
                {it.preview?.every((p) => p.n_new === 0) && <span className="text-xs text-dim">Nothing new — every comment is already stored.</span>}
              </div>
            )}
            {it.state === "uploading" && (
              <div className="mt-3 h-1.5 overflow-hidden rounded bg-bg">
                <div className="h-full bg-accent transition-all" style={{ width: `${Math.round((it.progress ?? 0) * 100)}%` }} />
              </div>
            )}
            {it.state === "done" && it.result && (
              <div className="mt-2 text-sm">
                {it.result.duplicate ? <span className="text-dim">This exact file was uploaded before — nothing written.</span> : (
                  <div className="flex flex-wrap gap-4">
                    <span><b>{n(it.result.rows_inserted)}</b> new</span>
                    <span className="text-dim"><b>{n(it.result.rows_existing)}</b> already stored</span>
                    {it.result.rows_scored > 0 && <span><b>{n(it.result.rows_scored)}</b> with scores</span>}
                    {it.result.rows_rejected > 0 && <span className="text-review"><b>{n(it.result.rows_rejected)}</b> skipped</span>}
                    {it.result.sheet_ids?.length > 0 && (
                      <span>{it.result.sheet_ids.map((s: number) => <Link key={s} className="text-accent" to={`/sheets/${s}`}>review sheet #{s} </Link>)}</span>
                    )}
                    {!it.result.rows_scored && it.result.rows_inserted > 0 && (
                      <Link to="/scoring" className="text-accent">→ score them (Colab or local)</Link>
                    )}
                  </div>
                )}
              </div>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}
