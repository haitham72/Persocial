import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { must, rpc, supabase } from "../lib/supabase";
import { useAuth } from "../lib/auth";
import { ago } from "../lib/format";
import { Chip, ErrorBox, Spinner } from "../components/ui";
import CommentDrawer, { shortId, type DrawerComment } from "../components/CommentDrawer";

const COLS = ["new", "assigned", "in_review", "done"] as const;
type Col = (typeof COLS)[number];

interface Card {
  ig_id: string; post_code: string; author: string | null; text: string;
  created_at: string | null; verdict: string | null; category: string | null;
  severity: number | null; decision: string | null; decided_by: string | null;
  assignee: string | null; status: string | null;
}

export default function Board() {
  const qc = useQueryClient();
  const { session } = useAuth();
  const uid = session?.user.id ?? null;
  const [drawer, setDrawer] = useState<DrawerComment | null>(null);
  const [dragId, setDragId] = useState<string | null>(null);

  const queue = useQuery({
    queryKey: ["board"],
    queryFn: () => rpc<Card[]>("queue_comments", { p_limit: 200, p_offset: 0 }),
  });
  const sla = useQuery({
    queryKey: ["sla-hours"],
    queryFn: async () => {
      const r = await must<{ value: string }>(supabase.from("settings").select("value").eq("key", "sla_hours").single());
      return Number(r.value) || 24;
    },
  });
  // Recently finished work: decided comments with workflow status done.
  const doneCol = useQuery({
    queryKey: ["board-done"],
    queryFn: () => must<Card[]>(supabase.from("comments")
      .select("ig_id,post_code,author,text,created_at,verdict,category,severity,decision,decided_by,assignee,status")
      .eq("status", "done").order("updated_at", { ascending: false }).limit(30)),
  });

  const move = useMutation({
    mutationFn: async ({ ig_id, status }: { ig_id: string; status: Col }) =>
      must(supabase.from("comments").update({ status }).eq("ig_id", ig_id)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["board"] }); qc.invalidateQueries({ queryKey: ["board-done"] }); },
  });
  const assignMe = useMutation({
    mutationFn: async (c: Card) =>
      must(supabase.from("comments").update({ assignee: uid, ...(c.status === "new" ? { status: "assigned" } : {}) }).eq("ig_id", c.ig_id)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["board"] }); qc.invalidateQueries({ queryKey: ["board-done"] }); },
  });

  if (queue.isLoading) return <Spinner />;
  if (queue.error) return <ErrorBox error={queue.error} />;
  const slaH = sla.data ?? 24;
  const open = queue.data ?? [];
  const groups: Record<Col, Card[]> = {
    new: [], assigned: [], in_review: [], done: (doneCol.data ?? []).filter((c) => c.decision == null),
  };
  for (const c of open) {
    const s = (COLS as readonly string[]).includes(c.status ?? "") ? (c.status as Col) : "new";
    if (s !== "done") groups[s].push(c);
    else groups.done.push(c);
  }
  // Decided + done rows live in the done column too.
  for (const c of (doneCol.data ?? []).filter((c) => c.decision != null)) groups.done.push(c);

  const breached = (c: Card) => {
    if (!c.created_at) return null;
    const h = Math.floor((Date.now() - new Date(c.created_at).getTime()) / 3600000);
    return h > slaH ? `${h}h/${slaH}h` : null;
  };

  return (
    <div>
      <div className="mb-3 text-sm text-dim">
        Drag a card to change its workflow status. {n0(open.length)} undecided in the queue · SLA {slaH}h.
      </div>
      <ErrorBox error={move.error ?? assignMe.error} />
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        {COLS.map((col) => (
          <div key={col}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => { if (dragId && dragId !== col) { move.mutate({ ig_id: dragId, status: col }); setDragId(null); } }}
            className="min-h-40 rounded-xl border border-line bg-bg/50 p-2">
            <div className="mb-2 flex items-center justify-between px-1 text-xs font-semibold uppercase tracking-wide text-dim">
              <span>{col.replace("_", " ")}</span>
              <span className="text-faint">{groups[col].length}</span>
            </div>
            <div className="space-y-2">
              {groups[col].map((c) => {
                const slaBadge = breached(c);
                return (
                  <div key={c.ig_id} draggable
                    onDragStart={() => setDragId(c.ig_id)}
                    onClick={() => setDrawer({ ...c, created_at: c.created_at })}
                    className={clsx("cursor-grab rounded-lg border border-line bg-panel p-2.5 text-sm active:cursor-grabbing",
                      dragId === c.ig_id && "opacity-50")}>
                    <div className="mb-1 flex flex-wrap items-center gap-1 text-[11px]">
                      <span className="font-medium text-ink">@{c.author ?? "?"}</span>
                      <span className="font-mono text-faint">{c.post_code}</span>
                      {c.verdict && <Chip kind={c.verdict}>{c.verdict}</Chip>}
                      {slaBadge && <Chip kind="hide">SLA {slaBadge}</Chip>}
                    </div>
                    <div className="line-clamp-3 break-words text-[13px]" dir="auto">{c.text}</div>
                    <div className="mt-1.5 flex items-center gap-2 text-[11px] text-faint">
                      <span>{ago(c.created_at)}</span>
                      {c.decision
                        ? <span>decided: {c.decision}</span>
                        : c.assignee === uid
                          ? <span className="font-medium text-accent">assigned to you</span>
                          : <button className="hover:text-accent"
                            onClick={(e) => { e.stopPropagation(); assignMe.mutate(c); }}>
                            {c.assignee ? `→ ${shortId(c.assignee)} · take over` : "assign to me"}
                          </button>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <CommentDrawer comment={drawer} onClose={() => setDrawer(null)}
        onChanged={() => { qc.invalidateQueries({ queryKey: ["board"] }); qc.invalidateQueries({ queryKey: ["board-done"] }); }} />
    </div>
  );
}

const n0 = (v: number) => v.toLocaleString("en-US");
