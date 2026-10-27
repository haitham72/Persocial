import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { mediaUrl, must, rpc, supabase } from "../lib/supabase";
import { dayBucket, delta, n } from "../lib/format";
import { ErrorBox, PageHeader, Spinner, StatusChip } from "../components/ui";

interface Post {
  code: string; username: string | null; caption: string | null; posted_at: string | null;
  thumbnail_path: string | null; like_count: number | null; comment_count: number | null;
  play_count: number | null; metrics_updated_at: string | null; updated_at: string;
  n_comments: number; n_unscored: number; n_negative: number; n_flagged: number;
  status: string; like_delta: number | null; comment_delta: number | null;
}

export default function Posts() {
  const [account, setAccount] = useState("");
  const [sort, setSort] = useState<"posted" | "updated">("posted");
  const [cols, setCols] = useState(() => {
    try { return Number(localStorage.getItem("grid_cols")) || 5; } catch { return 5; }
  });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => must(supabase.from("accounts").select("id, username").order("username")) });
  const posts = useQuery({
    queryKey: ["posts", account, sort],
    queryFn: () => rpc<Post[]>("post_grid", { p_account: account || null, p_sort: sort, p_limit: 400 }),
  });
  const groups = useMemo(() => {
    const g: [string, Post[]][] = [];
    for (const p of posts.data ?? []) {
      const b = dayBucket(sort === "posted" ? p.posted_at : p.updated_at);
      if (!g.length || g[g.length - 1][0] !== b) g.push([b, []]);
      g[g.length - 1][1].push(p);
    }
    return g;
  }, [posts.data, sort]);

  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader title="Posts" sub="Thumbnails, latest analytics and moderation status (dates in the configured timezone)." actions={
        <>
          <select value={account} onChange={(e) => setAccount(e.target.value)}
            className="rounded-lg border border-line bg-panel px-2 py-1.5 text-sm">
            <option value="">All accounts</option>
            {((accounts.data as any[]) ?? []).map((a) => <option key={a.id} value={a.username}>@{a.username}</option>)}
          </select>
          <div className="flex rounded-lg border border-line bg-panel p-0.5 text-sm">
            {(["posted", "updated"] as const).map((s) => (
              <button key={s} onClick={() => setSort(s)}
                className={clsx("rounded-md px-2.5 py-1", sort === s ? "bg-accent-soft text-accent" : "text-dim")}>
                {s === "posted" ? "Post date" : "Last updated"}
              </button>
            ))}
          </div>
          <input type="range" min={2} max={8} value={cols} title="Posts per row"
            onChange={(e) => { setCols(+e.target.value); try { localStorage.setItem("grid_cols", e.target.value); } catch { /* */ } }} />
        </>
      } />
      <ErrorBox error={posts.error} />
      {posts.isLoading ? <Spinner /> : groups.map(([bucket, ps]) => (
        <section key={bucket} className="mb-6">
          <div className="mb-2 flex items-center gap-3 text-xs font-semibold uppercase tracking-wide text-faint">
            {bucket} <span className="font-normal">{ps.length}</span><div className="h-px flex-1 bg-line" />
          </div>
          <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
            {ps.map((p) => <PostCard key={p.code} p={p} />)}
          </div>
        </section>
      ))}
    </div>
  );
}

function PostCard({ p }: { p: Post }) {
  const thumb = mediaUrl(p.thumbnail_path);
  const flagged = p.n_flagged;
  return (
    <Link to={`/posts/${p.code}`} className="group overflow-hidden rounded-xl border border-line bg-panel hover:border-accent/40">
      <div className="relative aspect-square bg-bg">
        {thumb ? <img src={thumb} alt="" className="h-full w-full object-cover" loading="lazy" />
          : <div className="grid h-full place-items-center font-mono text-xs text-faint">{p.code}</div>}
        {flagged > 0 && (
          <span className="absolute right-2 top-2 rounded-full bg-hide px-1.5 py-0.5 text-[11px] font-bold text-white">{flagged}</span>
        )}
        {p.n_unscored > 0 && (
          <span className="absolute left-2 top-2 rounded-md bg-panel/90 px-1.5 py-0.5 text-[11px] font-semibold text-accent">
            {n(p.n_unscored)} unscored
          </span>
        )}
      </div>
      <div className="space-y-0.5 p-2.5 text-xs">
        <div className="flex items-center justify-between gap-1">
          <span className="truncate font-medium">@{p.username ?? "?"}</span>
          {p.status === "pending" && <StatusChip status="pending" />}
        </div>
        <div className="flex gap-3 text-dim tabular-nums">
          <span>♥ {n(p.like_count)}{delta(p.like_delta) && <span className="text-keep"> {delta(p.like_delta)}</span>}</span>
          <span>💬 {n(p.comment_count)}{delta(p.comment_delta) && <span className="text-keep"> {delta(p.comment_delta)}</span>}</span>
        </div>
        <div className="text-faint">{n(p.n_comments)} stored · {n(p.n_negative)} negative</div>
      </div>
    </Link>
  );
}
