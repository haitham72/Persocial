import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, ExternalLink, Gavel } from "lucide-react";
import { mediaUrl, must, rpc, supabase } from "../lib/supabase";
import { useAuth } from "../lib/auth";
import { localTime, delta, igCommentUrl, n } from "../lib/format";
import { Button, Card, Chip, Empty, ErrorBox, Spinner, Stat, StatusChip } from "../components/ui";
import CommentDrawer, { HistoryButton } from "../components/CommentDrawer";
import { useModelGate } from "../components/ModelGate";

type Filter = "flagged" | "negative" | "decided" | "unscored" | "all";

function Spark({ points }: { points: { t: string; v: number | null }[] }) {
  const ps = points.filter((p) => p.v != null) as { t: string; v: number }[];
  if (ps.length < 2) return <div className="text-xs text-faint">one snapshot so far</div>;
  const min = Math.min(...ps.map((p) => p.v)), max = Math.max(...ps.map((p) => p.v));
  const w = 160, h = 36;
  const d = ps.map((p, i) => `${i ? "L" : "M"}${(i / (ps.length - 1)) * w},${h - ((p.v - min) / (max - min || 1)) * (h - 4) - 2}`).join("");
  return <svg width={w} height={h} className="text-accent"><path d={d} fill="none" stroke="currentColor" strokeWidth={1.5} /></svg>;
}

export default function PostPage() {
  const code = useParams().code!;
  const { role } = useAuth();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>("flagged");
  const [page, setPage] = useState(0);
  const [drawer, setDrawer] = useState<any>(null);
  const PAGE = 100;

  const post = useQuery({
    queryKey: ["post", code],
    queryFn: async () => {
      const [grid, snaps, sheets, runs] = await Promise.all([
        rpc<any[]>("post_grid", { p_code: code, p_limit: 1 }),
        must(supabase.from("post_snapshots").select("*").eq("post_code", code).order("captured_at")),
        must(supabase.from("review_sheets").select("*").eq("post_code", code).order("created_at", { ascending: false })),
        role === "admin"
          ? must(supabase.from("jobs").select("*").eq("post_code", code).eq("kind", "judge").order("id", { ascending: false }).limit(10))
          : Promise.resolve([]),
      ]);
      if (!grid[0]) throw new Error(`post ${code} not found`);
      return { p: grid[0], snaps: snaps as any[], sheets: sheets as any[], runs: runs as any[] };
    },
  });
  const comments = useQuery({
    queryKey: ["post-comments", code, filter, page],
    queryFn: () => rpc<{ total: number; rows: any[] }>("post_comments", { p_post: code, p_filter: filter, p_limit: PAGE, p_offset: page * PAGE }),
  });
  const judge = useMutation({
    mutationFn: () => rpc<number>("create_judge_run", { p_post: code }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["post", code] }),
  });
  const { gate, dialog } = useModelGate();
  // same review flow as a sheet: open on IG → yellow "opened" → Removed / Neutral
  const setRow = (id: string, p: Record<string, unknown>) =>
    qc.setQueryData<{ total: number; rows: any[] }>(["post-comments", code, filter, page],
      (old) => old && { ...old, rows: old.rows.map((r) => (r.ig_id === id ? { ...r, ...p } : r)) });
  const markOpened = (c: any) => {
    if (c.opened_at) return;
    setRow(c.ig_id, { opened_at: new Date().toISOString() });
    supabase.from("comments").update({ opened_at: new Date().toISOString() }).eq("ig_id", c.ig_id).then(() => {});
  };
  const settle = useMutation({
    mutationFn: ({ id, removed }: { id: string; removed: boolean }) =>
      must(supabase.from("comments").update(removed ? { decision: "hide", ig_action: "removed_on_ig" }
        : { decision: "keep", ig_action: null }).eq("ig_id", id)),
    onMutate: ({ id, removed }) => setRow(id, removed ? { decision: "hide", ig_action: "removed_on_ig" } : { decision: "keep", ig_action: null }),
  });

  if (post.isLoading) return <Spinner />;
  if (post.error) return <ErrorBox error={post.error} />;
  const { p, snaps, sheets, runs } = post.data!;
  const total = comments.data?.total ?? 0;

  return (
    <div className="mx-auto max-w-6xl">
      {dialog}
      <Link to="/posts" className="mb-3 inline-flex items-center gap-1 text-sm text-dim hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> Posts
      </Link>
      <Card className="mb-4 flex flex-wrap gap-5 p-4">
        <div className="h-36 w-36 shrink-0 overflow-hidden rounded-lg bg-bg">
          {mediaUrl(p.thumbnail_path) && <img src={mediaUrl(p.thumbnail_path)!} alt="" className="h-full w-full object-cover" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">@{p.username}</span>
            <a href={`https://www.instagram.com/p/${code}/`} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1 font-mono text-xs text-dim hover:text-accent">{code} <ExternalLink className="h-3 w-3" /></a>
            {p.status === "pending" && <StatusChip status="pending" />}
            <span className="text-xs text-faint">posted {localTime(p.posted_at, false)}</span>
          </div>
          <p className="mt-1 line-clamp-3 whitespace-pre-wrap text-sm text-dim" dir="auto">{p.caption}</p>
          <div className="mt-3 flex flex-wrap gap-6">
            <Stat label="Likes" value={n(p.like_count)} hint={delta(p.like_delta) ? `${delta(p.like_delta)} since last snapshot` : undefined} />
            <Stat label="Comments (IG)" value={n(p.comment_count)} hint={delta(p.comment_delta) ? `${delta(p.comment_delta)} since last snapshot` : undefined} />
            <Stat label="Plays" value={n(p.play_count)} />
            <Stat label="Stored" value={n(p.n_comments)} hint={p.n_unscored ? `${n(p.n_unscored)} unscored` : "all scored"} />
            <Stat label="Negative" value={n(p.n_negative)} />
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wide text-faint">Likes over time</div>
              <Spark points={snaps.map((s) => ({ t: s.captured_at, v: s.like_count }))} />
            </div>
          </div>
        </div>
        {role === "admin" && (
          <div className="flex flex-col items-end gap-2">
            <Button size="sm" variant="primary" disabled={judge.isPending || p.n_unscored > 0} onClick={() => gate(null, () => judge.mutate())}
              title={p.n_unscored > 0 ? "Score all comments first" : ""}>
              <Gavel className="h-3.5 w-3.5" /> Run judge
            </Button>
            {judge.data && <span className="text-xs text-keep">run #{judge.data} queued</span>}
            <ErrorBox error={judge.error} />
          </div>
        )}
      </Card>

      <div className="mb-4 grid gap-4 md:grid-cols-2">
        <Card className="p-4">
          <div className="mb-2 text-sm font-semibold">Review sheets</div>
          {sheets.length === 0 ? <div className="text-sm text-dim">No uploads with new comments yet.</div> :
            sheets.map((s) => (
              <Link key={s.id} to={`/sheets/${s.id}`} className="flex items-center justify-between border-t border-line py-1.5 text-sm first:border-0 hover:text-accent">
                <span>#{s.id} · {n(s.n_new)} new · {n(s.n_flagged)} flagged</span>
                <span className="flex items-center gap-2"><StatusChip status={s.status} /><span className="text-xs text-faint">{localTime(s.created_at)}</span></span>
              </Link>
            ))}
        </Card>
        <Card className="p-4">
          <div className="mb-2 text-sm font-semibold">Judge runs</div>
          {runs.length === 0 ? <div className="text-sm text-dim">Not judged yet.</div> :
            runs.map((r) => (
              <div key={r.id} className="flex items-center justify-between border-t border-line py-1.5 text-sm first:border-0">
                <span>#{r.id} · {r.model} · {r.prompt} · {n(r.n_done)} judged</span>
                <span className="flex items-center gap-2"><StatusChip status={r.status} /><span className="text-xs text-faint">{r.purpose}</span></span>
              </div>
            ))}
        </Card>
      </div>

      <div className="mb-3 flex items-center gap-2">
        <div className="flex gap-1 rounded-lg border border-line bg-panel p-1 text-sm">
          {(["flagged", "negative", "decided", "unscored", "all"] as Filter[]).map((f) => (
            <button key={f} onClick={() => { setFilter(f); setPage(0); }}
              className={clsx("rounded-md px-3 py-1 capitalize", filter === f ? "bg-accent-soft font-medium text-accent" : "text-dim")}>{f}</button>
          ))}
        </div>
        <span className="text-sm text-dim">{n(total)} comments</span>
        <div className="ml-auto flex gap-1">
          <Button size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Prev</Button>
          <Button size="sm" disabled={(page + 1) * PAGE >= total} onClick={() => setPage(page + 1)}>Next</Button>
      <CommentDrawer comment={drawer} onClose={() => setDrawer(null)}
        onChanged={() => qc.invalidateQueries({ queryKey: ["post-comments"] })} />
        </div>
      </div>
      {comments.isLoading ? <Spinner /> : !comments.data?.rows.length ? <Empty title="Nothing in this view" /> : (
        <Card className="divide-y divide-line">
          {comments.data.rows.map((c) => (
            <div key={c.ig_id} className={clsx("flex gap-3 px-4 py-2.5", c.opened_at && !c.decision && "bg-review-soft")}>
             <div className="min-w-0 flex-1">
              <div className="mb-0.5 flex flex-wrap items-center gap-1.5 text-xs text-dim">
                <span className="font-medium text-ink">@{c.author}</span>
                <span>{localTime(c.created_at)}</span>
                {c.sentiment && <Chip kind={c.sentiment === "negative" ? "review" : undefined}>{c.sentiment}</Chip>}
                {c.emotion && <Chip>{c.emotion}</Chip>}
                {c.verdict && <Chip kind={c.verdict}>judge: {c.verdict}</Chip>}
                {c.category && c.category !== "none" && <span>{c.category.replace(/_/g, " ")} · S{c.severity}</span>}
                {c.decision && <Chip kind={c.decision}>decided: {c.decision}</Chip>}
                <a href={igCommentUrl(code, c.ig_id)} target="_blank" rel="noreferrer" className="hover:text-accent"
                  onClick={() => markOpened(c)}><ExternalLink className="h-3 w-3" /></a>
                {c.opened_at && !c.decision && <Chip kind="review">opened</Chip>}
              </div>
              <a href={igCommentUrl(code, c.ig_id)} target="_blank" rel="noreferrer" onClick={() => markOpened(c)}
                className="comment-text block whitespace-pre-wrap break-words text-sm hover:underline" dir="auto">{c.text}</a>
             </div>
             <div className="flex shrink-0 items-start gap-1">
              <HistoryButton onClick={() => setDrawer(c)} />
              <button onClick={() => settle.mutate({ id: c.ig_id, removed: true })}
                className={clsx("rounded-md border px-2 py-0.5 text-xs", c.ig_action === "removed_on_ig" ? "border-hide bg-hide text-white" : "border-line text-dim hover:bg-bg")}>Removed</button>
              <button onClick={() => settle.mutate({ id: c.ig_id, removed: false })}
                className={clsx("rounded-md border px-2 py-0.5 text-xs", c.decision === "keep" ? "border-keep bg-keep text-white" : "border-line text-dim hover:bg-bg")}>Neutral</button>
             </div>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}
