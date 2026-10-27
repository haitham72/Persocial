import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, X } from "lucide-react";
import { must, supabase } from "../lib/supabase";
import { useAuth } from "../lib/auth";
import { ago, igCommentUrl, localTime } from "../lib/format";
import { Button, Chip, ErrorBox } from "./ui";

export interface DrawerComment {
  ig_id: string;
  post_code: string;
  author: string | null;
  text: string;
  created_at: string | null;
  verdict: string | null;
  category: string | null;
  severity: number | null;
  decision: string | null;
  decided_by: string | null;
  assignee: string | null;
  status: string | null;
}

export const STATUSES = ["new", "assigned", "in_review", "done"] as const;

export function shortId(id?: string | null) {
  return id ? `${id.slice(0, 8)}…` : "—";
}

export function HistoryButton({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={(e) => { e.stopPropagation(); onClick(); }} title="History & assignment"
      className="rounded-md border border-line px-2 py-0.5 text-xs text-faint hover:bg-bg hover:text-dim">
      <History className="h-3.5 w-3.5" />
    </button>
  );
}

export default function CommentDrawer({ comment, onClose, onChanged }: {
  comment: DrawerComment | null; onClose: () => void; onChanged: () => void;
}) {
  const qc = useQueryClient();
  const { session } = useAuth();
  const uid = session?.user.id ?? null;
  const igId = comment?.ig_id ?? null;

  const events = useQuery({
    queryKey: ["comment-events", igId],
    enabled: !!igId,
    queryFn: () => must<any[]>(supabase.from("comment_events").select("*")
      .eq("comment_id", igId!).order("at", { ascending: true })),
  });

  useEffect(() => {
    if (!igId) return;
    const ch = supabase.channel(`events-${igId}`)
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "comment_events", filter: `comment_id=eq.${igId}` },
        () => qc.invalidateQueries({ queryKey: ["comment-events", igId] }))
      .subscribe();
    return () => { supabase.removeChannel(ch); };
  }, [igId, qc]);

  const mutate = useMutation({
    mutationFn: async (p: Record<string, unknown>) => {
      if (!igId) return;
      await must(supabase.from("comments").update(p).eq("ig_id", igId));
    },
    onSuccess: () => {
      onChanged();
      qc.invalidateQueries({ queryKey: ["comment-events", igId] });
      qc.invalidateQueries({ queryKey: ["board"] });
    },
  });

  if (!comment) return null;
  return (
    <div className="fixed inset-0 z-50" onClick={onClose}>
      <div className="absolute inset-0 bg-black/30" />
      <div className="absolute inset-y-0 right-0 flex w-full max-w-md flex-col overflow-y-auto border-l border-line bg-panel p-5"
        onClick={(e) => e.stopPropagation()}>
        <div className="mb-1 flex items-center justify-between">
          <span className="font-medium">@{comment.author ?? "?"}</span>
          <button onClick={onClose} className="rounded-md p-1 text-dim hover:bg-bg"><X className="h-4 w-4" /></button>
        </div>
        <div className="mb-3 text-xs text-faint">{localTime(comment.created_at)} · {comment.post_code}</div>
        <p className="mb-3 whitespace-pre-wrap break-words text-[15px]" dir="auto">{comment.text}</p>
        <div className="mb-4 flex flex-wrap items-center gap-1.5 text-xs">
          {comment.verdict && <Chip kind={comment.verdict}>judge: {comment.verdict}</Chip>}
          {comment.category && <span className="text-dim">{comment.category.replace(/_/g, " ")} · S{comment.severity}</span>}
          {comment.decision && <Chip kind={comment.decision}>decided: {comment.decision} · {comment.decided_by?.split("@")[0]}</Chip>}
          <a href={igCommentUrl(comment.post_code, comment.ig_id)} target="_blank" rel="noreferrer"
            className="text-dim hover:text-accent">open on Instagram</a>
        </div>

        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">Workflow</div>
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <select value={comment.status ?? "new"}
            onChange={(e) => mutate.mutate({ status: e.target.value })}
            className="rounded-lg border border-line bg-panel px-2 py-1.5 text-sm">
            {STATUSES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
          </select>
          {comment.assignee === uid
            ? <Button size="sm" variant="ghost" onClick={() => mutate.mutate({ assignee: null })}>Unassign me</Button>
            : <Button size="sm" onClick={() => mutate.mutate({ assignee: uid, ...(comment.status === "new" ? { status: "assigned" } : {}) })}>
              {comment.assignee ? `Reassign to me (${shortId(comment.assignee)})` : "Assign to me"}
            </Button>}
          {comment.assignee && comment.assignee !== uid && (
            <span className="text-xs text-faint" title={comment.assignee}>→ {shortId(comment.assignee)}</span>
          )}
        </div>
        <ErrorBox error={mutate.error} />

        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">Timeline</div>
        {(events.data ?? []).length === 0 ? (
          <div className="text-sm text-faint">No changes yet — decisions, assignments and status moves appear here.</div>
        ) : (
          <ol className="space-y-2">
            {(events.data ?? []).map((e) => (
              <li key={e.id} className="flex items-baseline gap-2 text-sm">
                <span className="shrink-0 rounded bg-bg px-1.5 py-0.5 text-[11px] font-semibold text-dim">{e.action}</span>
                <span className="min-w-0 flex-1 truncate" title={`${e.from_value ?? "—"} → ${e.to_value ?? "—"}`}>
                  {e.from_value ?? "—"} → <span className="font-medium">{e.to_value ?? "—"}</span>
                </span>
                <span className="shrink-0 text-[11px] text-faint" title={e.actor}>{e.actor?.split("@")[0] ?? e.actor} · {ago(e.at)}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
