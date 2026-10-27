import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowLeft, Download, ExternalLink, Check, EyeOff, Flag, ShieldAlert, Copy, Plus, Trash2 } from "lucide-react";
import { mediaUrl, must, rpc, supabase } from "../lib/supabase";
import { useAuth } from "../lib/auth";
import { localTime, downloadCsv, igCommentUrl, n, delta } from "../lib/format";
import { Button, Card, Chip, Empty, ErrorBox, Spinner, Stat, StatusChip } from "../components/ui";
import CommentDrawer, { HistoryButton } from "../components/CommentDrawer";
import { SHEET_SELECT, type SheetRow } from "./Inbox";

interface Row {
  ig_id: string; post_code: string; author: string | null; text: string; script: string;
  created_at: string | null; repeat_commenter: boolean; sentiment: string | null;
  emotion: string | null; verdict: string | null; category: string | null; severity: number | null;
  confidence: number | null; welfare: boolean; judge_reason: string | null;
  judge_selection: string | null; decision: string | null; decided_by: string | null;
  assignee: string | null; status: string | null;
  ig_action: string | null; opened_at: string | null; opened_by: string | null;
}
type Filter = "flagged" | "undecided" | "all" | "decided";
type Decision = "hide" | "keep" | "escalate";

const flaggedRow = (r: Row) => r.verdict === "hide" || r.verdict === "review" || r.welfare;

export default function SheetPage() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const { email } = useAuth();
  const [filter, setFilter] = useState<Filter>("flagged");
  const [cursor, setCursor] = useState(0);
  const [macrosOpen, setMacrosOpen] = useState(false);
  const [copied, setCopied] = useState<number | null>(null);
  const [drawer, setDrawer] = useState<Row | null>(null);
  const [macroDraft, setMacroDraft] = useState({ title: "", body: "", lang: "en" });

  const sheet = useQuery({
    queryKey: ["sheet", id],
    queryFn: async () => {
      const s = await must<SheetRow>(supabase.from("review_sheets").select(SHEET_SELECT).eq("id", id).single());
      const [post] = await rpc<any[]>("post_grid", { p_code: s.post_code, p_limit: 1 });
      return { s, post };
    },
  });
  const rows = useQuery({ queryKey: ["sheet-rows", id], queryFn: () => rpc<Row[]>("sheet_comments", { p_sheet: id }) });
  const macros = useQuery({ queryKey: ["macros"], queryFn: () => must(supabase.from("saved_replies").select("*").order("id")) });
  const copyMacro = async (m: { id: number; body: string }) => {
    await navigator.clipboard.writeText(m.body);
    setCopied(m.id);
    setTimeout(() => setCopied((c) => (c === m.id ? null : c)), 1500);
  };
  const macroSave = useMutation({
    mutationFn: async () => must(supabase.from("saved_replies").insert({ ...macroDraft, created_by: email })),
    onSuccess: () => { setMacroDraft({ title: "", body: "", lang: "en" }); qc.invalidateQueries({ queryKey: ["macros"] }); },
  });
  const macroDel = useMutation({
    mutationFn: async (mid: number) => must(supabase.from("saved_replies").delete().eq("id", mid)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["macros"] }),
  });

  const shown = useMemo(() => (rows.data ?? []).filter((r) =>
    filter === "all" ? true
      : filter === "flagged" ? flaggedRow(r)
      : filter === "decided" ? !!r.decision
      : !r.decision && flaggedRow(r)), [rows.data, filter]);

  const patch = (ids: string[], p: Partial<Row>) =>
    qc.setQueryData<Row[]>(["sheet-rows", id], (old) => old?.map((r) => (ids.includes(r.ig_id) ? { ...r, ...p } : r)));

  // decided_by / decided_at are stamped by the database from the signed-in account
  const decide = useMutation({
    mutationFn: async ({ ids, decision }: { ids: string[]; decision: Decision }) => {
      for (let i = 0; i < ids.length; i += 200) {
        await must(supabase.from("comments").update({ decision }).in("ig_id", ids.slice(i, i + 200)));
      }
    },
    onMutate: ({ ids, decision }) => patch(ids, { decision, decided_by: email }),
    onError: () => qc.invalidateQueries({ queryKey: ["sheet-rows", id] }),
    onSettled: () => { qc.invalidateQueries({ queryKey: ["sheets"] }); qc.invalidateQueries({ queryKey: ["sheet", id] }); },
  });
  // Removed = hide + removed on IG; Neutral = keep. One update, stamped by the database.
  const settle = useMutation({
    mutationFn: async ({ cid, removed }: { cid: string; removed: boolean }) =>
      must(supabase.from("comments").update(removed ? { decision: "hide", ig_action: "removed_on_ig" }
        : { decision: "keep", ig_action: null }).eq("ig_id", cid)),
    onMutate: ({ cid, removed }) => patch([cid], removed ? { decision: "hide", ig_action: "removed_on_ig", decided_by: email }
      : { decision: "keep", ig_action: null, decided_by: email }),
    onError: () => qc.invalidateQueries({ queryKey: ["sheet-rows", id] }),
    onSettled: () => { qc.invalidateQueries({ queryKey: ["sheets"] }); qc.invalidateQueries({ queryKey: ["sheet", id] }); },
  });
  // Opening a comment on Instagram marks it "opened" (yellow) until Removed / Neutral is clicked.
  const markOpened = (r: Row) => {
    if (r.opened_at) return;
    patch([r.ig_id], { opened_at: new Date().toISOString(), opened_by: email });
    supabase.from("comments").update({ opened_at: new Date().toISOString() }).eq("ig_id", r.ig_id).then(() => {});
  };
  const openOnIg = (r: Row) => { window.open(igCommentUrl(r.post_code, r.ig_id), "_blank", "noreferrer"); markOpened(r); };
  const assign = useMutation({
    mutationFn: async (p: Record<string, unknown>) => must(supabase.from("review_sheets").update(p).eq("id", id)),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["sheet", id] }); qc.invalidateQueries({ queryKey: ["sheets"] }); },
  });

  const current = shown[cursor];
  const onKey = useCallback((e: KeyboardEvent) => {
    if ((e.target as HTMLElement)?.tagName === "INPUT") return;
    const k = e.key.toLowerCase();
    if (k === "arrowdown" || k === "j") { e.preventDefault(); setCursor((c) => Math.min(c + 1, shown.length - 1)); }
    else if (k === "arrowup") { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
    else if (current && k === "o") openOnIg(current);
    else if (current && (k === "r" || k === "n")) {
      settle.mutate({ cid: current.ig_id, removed: k === "r" });
      setCursor((c) => Math.min(c + 1, shown.length - 1));
    } else if (current && k === "e") {
      decide.mutate({ ids: [current.ig_id], decision: "escalate" });
      setCursor((c) => Math.min(c + 1, shown.length - 1));
    }
  }, [shown.length, current, decide, settle]);
  useEffect(() => { window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey); }, [onKey]);
  useEffect(() => { document.getElementById(`row-${current?.ig_id}`)?.scrollIntoView({ block: "nearest" }); }, [current]);

  if (sheet.isLoading || rows.isLoading) return <Spinner />;
  if (sheet.error || rows.error) return <ErrorBox error={sheet.error ?? rows.error} />;
  const { s, post } = sheet.data!;
  const all = rows.data ?? [];
  const undecidedHides = all.filter((r) => r.verdict === "hide" && !r.decision).map((r) => r.ig_id);
  const counts = {
    flagged: all.filter(flaggedRow).length,
    undecided: all.filter((r) => !r.decision && flaggedRow(r)).length,
    all: all.length, decided: all.filter((r) => r.decision).length,
  };
  const exportCsv = () => downloadCsv(`${s.post_code}-sheet-${id}.csv`,
    ["comment_id", "author", "created_at_local", "text", "sentiment", "emotion", "verdict", "category",
     "severity", "reason", "opened_by", "decision", "decided_by", "ig_action", "link"],
    all.map((r) => [r.ig_id, r.author, localTime(r.created_at), r.text, r.sentiment, r.emotion, r.verdict,
      r.category, r.severity, r.judge_reason, r.opened_by, r.decision, r.decided_by, r.ig_action, igCommentUrl(r.post_code, r.ig_id)]));

  return (
    <div className="mx-auto max-w-6xl">
      <Link to="/" className="mb-3 inline-flex items-center gap-1 text-sm text-dim hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> Inbox
      </Link>
      <Card className="mb-4 flex flex-wrap gap-5 p-4">
        <div className="h-24 w-24 shrink-0 overflow-hidden rounded-lg bg-bg">
          {mediaUrl(s.posts?.thumbnail_path) && <img src={mediaUrl(s.posts?.thumbnail_path)!} alt="" className="h-full w-full object-cover" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-semibold">@{s.posts?.accounts?.username}</span>
            <a href={`https://www.instagram.com/p/${s.post_code}/`} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1 font-mono text-xs text-dim hover:text-accent">
              {s.post_code} <ExternalLink className="h-3 w-3" /></a>
            <StatusChip status={s.status} />
            {post?.status === "pending" && <StatusChip status="pending" />}
          </div>
          <p className="mt-1 line-clamp-2 text-sm text-dim" dir="auto">{s.posts?.caption}</p>
          <div className="mt-3 flex flex-wrap gap-6">
            <Stat label="New comments" value={n(s.n_new)} hint={`uploaded ${localTime(s.created_at)}`} />
            <Stat label="Flagged" value={n(counts.flagged)} />
            <Stat label="Decided" value={n(counts.decided)} />
            <Stat label="Likes" value={n(post?.like_count)} hint={delta(post?.like_delta) ?? undefined} />
            <Stat label="Comments on IG" value={n(post?.comment_count)} hint={delta(post?.comment_delta) ?? undefined} />
          </div>
        </div>
        <div className="flex flex-col items-end gap-2 text-sm">
          <div className="text-xs text-dim">{s.assigned_to ? `Assigned to ${s.assigned_to}` : "Unassigned"}</div>
          <div className="flex gap-2">
            {s.assigned_to !== email && <Button size="sm" onClick={() => assign.mutate({ assigned_to: email })}>Assign to me</Button>}
            <Button size="sm" variant={s.resolved_at ? "default" : "primary"}
              onClick={() => assign.mutate(s.resolved_at ? { resolved_at: null, resolved_by: null }
                : { resolved_at: new Date().toISOString(), resolved_by: email })}>
              <Check className="h-3.5 w-3.5" /> {s.resolved_at ? "Reopen" : "Mark done"}
            </Button>
          </div>
          <Button size="sm" variant="ghost" onClick={exportCsv}><Download className="h-3.5 w-3.5" /> Export sheet</Button>
        </div>
      </Card>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex gap-1 rounded-lg border border-line bg-panel p-1 text-sm">
          {(["flagged", "undecided", "all", "decided"] as Filter[]).map((f) => (
            <button key={f} onClick={() => { setFilter(f); setCursor(0); }}
              className={clsx("rounded-md px-3 py-1 capitalize", filter === f ? "bg-accent-soft font-medium text-accent" : "text-dim")}>
              {f} <span className="text-faint">{counts[f]}</span>
            </button>
          ))}
        </div>
        {undecidedHides.length > 0 && (
          <Button size="sm" variant="danger" onClick={() => decide.mutate({ ids: undecidedHides, decision: "hide" })}>
            <EyeOff className="h-3.5 w-3.5" /> Accept {undecidedHides.length} judge hides
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => setMacrosOpen((o) => !o)}><Copy className="h-3.5 w-3.5" /> Macros</Button>
        <div className="ml-auto text-xs text-faint">↑↓ move · O open on IG · R removed · N neutral · E escalate</div>
      </div>
      <ErrorBox error={decide.error ?? settle.error ?? assign.error ?? macroSave.error ?? macroDel.error} />
      {macrosOpen && (
        <Card className="mb-3 divide-y divide-line">
          {((macros.data as any[]) ?? []).map((m) => (
            <div key={m.id} className="flex items-center gap-3 px-4 py-2 text-sm">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2"><span className="font-medium">{m.title}</span><Chip>{m.lang}</Chip></div>
                <div className="truncate text-xs text-dim" dir="auto">{m.body}</div>
              </div>
              <Button size="sm" variant="ghost" onClick={() => copyMacro(m)}>{copied === m.id ? "Copied" : "Copy"}</Button>
              <button onClick={() => macroDel.mutate(m.id)} className="text-faint hover:text-hide"><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-2 px-4 py-3">
            <input value={macroDraft.title} onChange={(e) => setMacroDraft({ ...macroDraft, title: e.target.value })} placeholder="Title"
              className="w-48 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm" />
            <input value={macroDraft.body} onChange={(e) => setMacroDraft({ ...macroDraft, body: e.target.value })} placeholder="Reply text (Arabic auto-detects)" dir="auto"
              className="min-w-64 flex-1 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm" />
            <select value={macroDraft.lang} onChange={(e) => setMacroDraft({ ...macroDraft, lang: e.target.value })}
              className="rounded-lg border border-line bg-panel px-2 py-1.5 text-sm">
              {(["en", "ar", "mixed"] as const).map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
            <Button size="sm" variant="primary" disabled={!macroDraft.title.trim() || !macroDraft.body.trim()} onClick={() => macroSave.mutate()}>
              <Plus className="h-3.5 w-3.5" /> Add
            </Button>
          </div>
        </Card>
      )}

      <CommentDrawer comment={drawer} onClose={() => setDrawer(null)}
        onChanged={() => { qc.invalidateQueries({ queryKey: ["sheet-rows", id] }); qc.invalidateQueries({ queryKey: ["sheets"] }); }} />
      {shown.length === 0 ? <Empty title="Nothing in this view" /> : (
        <Card className="divide-y divide-line overflow-hidden">
          {shown.map((r, i) => (
            <div key={r.ig_id} id={`row-${r.ig_id}`} onClick={() => setCursor(i)}
              className={clsx("grid grid-cols-[1fr_auto] gap-4 px-4 py-3",
                r.opened_at && !r.decision && "bg-review-soft",
                i === cursor && "ring-1 ring-inset ring-accent/40", i === cursor && !(r.opened_at && !r.decision) && "bg-accent-soft/40")}>
              <div className="min-w-0">
                <div className="mb-1 flex flex-wrap items-center gap-1.5 text-xs text-dim">
                  <span className="font-medium text-ink">@{r.author ?? "?"}</span>
                  {r.repeat_commenter && <Chip>repeat commenter</Chip>}
                  <span>{localTime(r.created_at)}</span>
                  {r.sentiment && <Chip kind={r.sentiment === "negative" ? "review" : undefined}>{r.sentiment}</Chip>}
                  {r.emotion && <Chip>{r.emotion}</Chip>}
                  {r.judge_selection === "audit" && <Chip>audit sample</Chip>}
                  <a href={igCommentUrl(r.post_code, r.ig_id)} target="_blank" rel="noreferrer"
                    className="inline-flex items-center gap-0.5 hover:text-accent" onClick={(e) => { e.stopPropagation(); markOpened(r); }}>
                    open <ExternalLink className="h-3 w-3" /></a>
                  {r.opened_at && !r.decision && <Chip kind="review">opened{r.opened_by ? ` · ${r.opened_by.split("@")[0]}` : ""}</Chip>}
                </div>
                <div className="comment-text cursor-pointer whitespace-pre-wrap break-words text-[15px] hover:underline" dir="auto"
                  title="Open on Instagram" onClick={(e) => { e.stopPropagation(); setCursor(i); openOnIg(r); }}>{r.text}</div>
                {r.verdict && (
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
                    <Chip kind={r.verdict}>judge: {r.verdict}</Chip>
                    <span className="text-dim">{r.category?.replace(/_/g, " ")} · S{r.severity}</span>
                    {r.welfare && <Chip kind="hide"><ShieldAlert className="mr-0.5 h-3 w-3" /> welfare</Chip>}
                    {r.judge_reason && <span className="text-faint">— {r.judge_reason}</span>}
                  </div>
                )}
              </div>
              <div className="flex flex-col items-end gap-1.5">
                <div className="flex gap-1">
                  <button onClick={(e) => { e.stopPropagation(); settle.mutate({ cid: r.ig_id, removed: true }); }}
                    className={clsx("rounded-md border px-2 py-1 text-xs font-medium",
                      r.ig_action === "removed_on_ig" ? "border-hide bg-hide text-white" : "border-line text-dim hover:bg-bg")}>Removed</button>
                  <button onClick={(e) => { e.stopPropagation(); settle.mutate({ cid: r.ig_id, removed: false }); }}
                    className={clsx("rounded-md border px-2 py-1 text-xs font-medium",
                      r.decision === "keep" ? "border-keep bg-keep text-white" : "border-line text-dim hover:bg-bg")}>Neutral</button>
                  <button onClick={(e) => { e.stopPropagation(); decide.mutate({ ids: [r.ig_id], decision: "escalate" }); }}
                    className={clsx("rounded-md border px-2 py-1 text-xs",
                      r.decision === "escalate" ? "border-review bg-review text-white" : "border-line text-faint hover:bg-bg")}>escalate</button>
                </div>
                {r.decision === "hide" && r.ig_action !== "removed_on_ig" && (
                  <span className="text-[11px] text-hide">to remove on IG</span>
                )}
                {r.decided_by && <div className="text-[11px] text-faint"><Flag className="mr-0.5 inline h-3 w-3" />{r.decided_by}</div>}
                <div className="flex items-center gap-1"><HistoryButton onClick={() => setDrawer(r)} />
                  {r.status && r.status !== "new" && <span className="text-[11px] text-faint">{r.status.replace("_", " ")}</span>}</div>
              </div>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}
