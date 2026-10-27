import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cpu, Download, X, FileDown } from "lucide-react";
import { must, rpc, supabase } from "../lib/supabase";
import { ago, localTime, downloadCsv, n } from "../lib/format";
import { Button, Card, Empty, ErrorBox, PageHeader, Spinner, Stat } from "../components/ui";

interface Pending { code: string; username: string | null; caption: string | null; n_unscored: number; claimed: boolean; claimed_by: string | null }

export default function Scoring() {
  const qc = useQueryClient();
  const pending = useQuery({ queryKey: ["pending-scoring"], queryFn: () => rpc<Pending[]>("pending_scoring", { p_search: null }) });
  const leases = useQuery({
    queryKey: ["leases"],
    queryFn: () => must<any[]>(supabase.from("posts").select("code, claimed_by, claimed_at, claim_expires_at, n_comments, n_scored")
      .not("claimed_by", "is", null).order("claimed_at", { ascending: false })),
  });
  const workers = useQuery({
    queryKey: ["workers"], refetchInterval: 15000,
    queryFn: () => must<any[]>(supabase.from("settings").select("key, value, updated_at").like("key", "worker:%")),
  });
  useEffect(() => {
    const ch = supabase.channel("leases")
      .on("postgres_changes", { event: "UPDATE", schema: "public", table: "posts" }, () => {
        qc.invalidateQueries({ queryKey: ["leases"] }); qc.invalidateQueries({ queryKey: ["pending-scoring"] });
      }).subscribe();
    return () => { supabase.removeChannel(ch); };
  }, [qc]);

  const exportPost = useMutation({
    mutationFn: async (code?: string) => {
      const [lease] = await rpc<any[]>("claim_posts", { p_post_codes: code ? [code] : null, p_n: 1, p_runner: "csv-export" });
      if (!lease) throw new Error("Nothing left to score (or the post is leased to another machine).");
      const rows = await rpc<Record<string, string | number | null>[]>("claim_export", { p_post: lease.post_code });
      const header = ["id", "owner_id", "username", "text", "created_at", "postID", "Spam"];
      downloadCsv(`${lease.post_code}-comment--${rows.length}.csv`, header, rows.map((r) => header.map((h) => r[h] ?? "")));
      return lease;
    },
    onSettled: () => { qc.invalidateQueries({ queryKey: ["leases"] }); qc.invalidateQueries({ queryKey: ["pending-scoring"] }); },
  });
  const release = useMutation({
    mutationFn: (code: string) => rpc("release_claim", { p_post: code }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["leases"] }),
  });

  const live = (workers.data ?? []).filter((w) => Date.now() - new Date(w.updated_at).getTime() < 90_000);
  const totalLeft = (pending.data ?? []).reduce((s, p) => s + Number(p.n_unscored), 0);

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Scoring" sub="Sentiment + emotion for every comment, on whatever GPU is available." />
      <div className="mb-4 grid gap-4 md:grid-cols-3">
        <Card className="p-4"><Stat label="Unscored comments" value={n(totalLeft)} hint={`${n(pending.data?.length)} posts`} /></Card>
        <Card className="p-4">
          <div className="text-[11px] font-medium uppercase tracking-wide text-faint">Google Colab</div>
          <p className="mt-1 text-sm text-dim">Open the saved notebook → Run all → <b>Start</b>. It leases posts and saves scores every 1k / 5k / 10k.</p>
          <a href="https://colab.research.google.com/" target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-sm text-accent">
            <Download className="h-3.5 w-3.5" /> open Colab (colab/score_csv.ipynb)
          </a>
        </Card>
        <Card className="p-4">
          <div className="text-[11px] font-medium uppercase tracking-wide text-faint">GPU workers online</div>
          {live.length === 0 ? <p className="mt-1 text-sm text-dim">None. On a GPU box: <code className="text-xs">persocial --target cloud worker --score</code></p> :
            live.map((w) => <div key={w.key} className="mt-1 flex items-center gap-2 text-sm"><Cpu className="h-3.5 w-3.5 text-keep" />{w.key.slice(7)} · {w.value}</div>)}
        </Card>
      </div>
      <ErrorBox error={exportPost.error ?? release.error} />
      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <Card>
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <div className="text-sm font-semibold">Waiting to be scored</div>
            <Button size="sm" onClick={() => exportPost.mutate(undefined)} disabled={exportPost.isPending}>
              <FileDown className="h-3.5 w-3.5" /> Export next post as CSV
            </Button>
          </div>
          {pending.isLoading ? <Spinner /> : !pending.data?.length ? <div className="p-4"><Empty title="Everything is scored" /></div> : (
            <div className="max-h-[520px] divide-y divide-line overflow-auto">
              {pending.data.map((p) => (
                <div key={p.code} className="flex items-center gap-3 px-4 py-2 text-sm">
                  <span className="font-mono text-xs">{p.code}</span>
                  <span className="text-dim">@{p.username ?? "?"}</span>
                  <span className="truncate text-faint" dir="auto">{p.caption}</span>
                  <span className="ml-auto tabular-nums">{n(p.n_unscored)}</span>
                  {p.claimed ? <span className="text-xs text-accent">{p.claimed_by}</span> :
                    <Button size="sm" variant="ghost" onClick={() => exportPost.mutate(p.code)}>CSV</Button>}
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card>
          <div className="border-b border-line px-4 py-3 text-sm font-semibold">Leased right now</div>
          <div className="max-h-[520px] divide-y divide-line overflow-auto">
            {(leases.data ?? []).length === 0 && <div className="p-4 text-sm text-dim">No post is being scored.</div>}
            {(leases.data ?? []).map((l) => (
              <div key={l.code} className="px-4 py-2 text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs">{l.code}</span>
                  <span className="text-xs text-dim">{l.claimed_by}</span>
                  <button onClick={() => release.mutate(l.code)} className="ml-auto text-faint hover:text-hide" title="Release"><X className="h-3.5 w-3.5" /></button>
                </div>
                <div className="text-xs text-faint">
                  {n(l.n_scored)}/{n(l.n_comments)} scored · since {ago(l.claimed_at)} · expires {localTime(l.claim_expires_at)}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
