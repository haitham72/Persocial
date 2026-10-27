import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { mediaUrl, must, supabase } from "../lib/supabase";
import { ago, n } from "../lib/format";
import { Empty, ErrorBox, PageHeader, Spinner, StatusChip } from "../components/ui";
import Board from "./Board";

type Tab = "todo" | "processing" | "done" | "board";

export interface SheetRow {
  id: number; post_code: string; status: string; n_new: number; n_flagged: number; n_decided: number;
  assigned_to: string | null; resolved_at: string | null; created_at: string; ready_at: string | null;
  posts: { caption: string | null; thumbnail_path: string | null; accounts: { username: string } | null } | null;
}

export const SHEET_SELECT = "*, posts(caption, thumbnail_path, accounts(username))";

export default function Inbox() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("todo");
  const { data, isLoading, error } = useQuery({
    queryKey: ["sheets"],
    queryFn: () => must<SheetRow[]>(supabase.from("review_sheets").select(SHEET_SELECT)
      .order("created_at", { ascending: false }).limit(300)),
  });
  useEffect(() => {
    const ch = supabase.channel("sheets")
      .on("postgres_changes", { event: "*", schema: "public", table: "review_sheets" },
        () => qc.invalidateQueries({ queryKey: ["sheets"] }))
      .subscribe();
    return () => { supabase.removeChannel(ch); };
  }, [qc]);

  const all = data ?? [];
  const done = (s: SheetRow) => !!s.resolved_at || (s.n_flagged > 0 && s.n_decided >= s.n_flagged);
  const lists: Record<Exclude<Tab, "board">, SheetRow[]> = {
    todo: all.filter((s) => s.status === "ready" && !done(s)),
    processing: all.filter((s) => s.status !== "ready"),
    done: all.filter((s) => s.status === "ready" && done(s)),
  };

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Inbox" sub="New comments per upload, judged and waiting for a decision." />
      <div className="mb-4 flex gap-1 rounded-lg border border-line bg-panel p-1 text-sm">
        {([["todo", "To review"], ["processing", "Processing"], ["done", "Done"], ["board", "Board"]] as const).map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={clsx("flex-1 rounded-md px-3 py-1.5", tab === k ? "bg-accent-soft font-medium text-accent" : "text-dim")}>
            {label} <span className="text-faint">{k === "board" ? "" : lists[k].length}</span>
          </button>
        ))}
      </div>
      <ErrorBox error={error} />
      {tab === "board" ? <Board /> : isLoading ? <Spinner /> : lists[tab].length === 0 ? (
        <Empty title={tab === "todo" ? "All caught up" : "Nothing here"}>
          {tab === "todo" && "New sheets appear here when an upload has been scored and judged."}
        </Empty>
      ) : (
        <div className="space-y-2">{lists[tab].map((s) => <Row key={s.id} s={s} />)}</div>
      )}
    </div>
  );
}

function Row({ s }: { s: SheetRow }) {
  const thumb = mediaUrl(s.posts?.thumbnail_path);
  const pct = s.n_flagged ? Math.min(100, Math.round((s.n_decided / s.n_flagged) * 100)) : 0;
  return (
    <Link to={`/sheets/${s.id}`}
      className="flex items-center gap-4 rounded-xl border border-line bg-panel p-3 transition-colors hover:border-accent/40">
      <div className="h-14 w-14 shrink-0 overflow-hidden rounded-lg bg-bg">
        {thumb && <img src={thumb} alt="" className="h-full w-full object-cover" loading="lazy" />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-medium">@{s.posts?.accounts?.username ?? "?"}</span>
          <span className="font-mono text-xs text-dim">{s.post_code}</span>
          <StatusChip status={s.status} />
          {s.assigned_to && <span className="text-xs text-faint">→ {s.assigned_to}</span>}
        </div>
        <div className="mt-0.5 truncate text-sm text-dim" dir="auto">{s.posts?.caption || "—"}</div>
        {s.status === "ready" && s.n_flagged > 0 && (
          <div className="mt-1.5 h-1 w-48 overflow-hidden rounded bg-bg">
            <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
          </div>
        )}
      </div>
      <div className="text-right text-sm">
        <div><span className="font-semibold tabular-nums">{n(s.n_new)}</span> <span className="text-dim">new</span></div>
        {s.status === "ready" && (
          <div className={clsx("text-xs", s.n_flagged ? "text-hide" : "text-keep")}>
            {s.n_flagged ? `${n(s.n_flagged)} flagged · ${n(s.n_decided)} decided` : "nothing flagged"}
          </div>
        )}
        <div className="text-xs text-faint">{ago(s.created_at)}</div>
      </div>
    </Link>
  );
}
