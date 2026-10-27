import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Plus, Star, Trash2 } from "lucide-react";
import { must, rpc, supabase } from "../lib/supabase";
import { ago, n } from "../lib/format";
import { Button, Card, Chip, ErrorBox, PageHeader, Spinner, StatusChip } from "../components/ui";
import { useModelGate } from "../components/ModelGate";

type Tab = "models" | "audit" | "prompts" | "lexicon" | "runs";
const KINDS = ["insult", "public_figure_attack", "threat", "sectarian", "sexual", "scam", "promo", "allow"];

export default function JudgeLab() {
  const [tab, setTab] = useState<Tab>("models");
  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader title="Judge lab" sub="Models, audit policy, prompt versions, lexicon and runs — where the judge gets better." />
      <div className="mb-4 flex gap-1 rounded-lg border border-line bg-panel p-1 text-sm">
        {(["models", "audit", "prompts", "lexicon", "runs"] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={clsx("flex-1 rounded-md px-3 py-1.5 capitalize", tab === t ? "bg-accent-soft font-medium text-accent" : "text-dim")}>{t}</button>
        ))}
      </div>
      {tab === "models" && <Models />}
      {tab === "audit" && <Audit />}
      {tab === "prompts" && <Prompts />}
      {tab === "lexicon" && <Lexicon />}
      {tab === "runs" && <Runs />}
    </div>
  );
}

function Models() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["models"], queryFn: () => must(supabase.from("models").select("*").order("id")) });
  const [form, setForm] = useState({ id: "", label: "", base_url: "", model: "", api_key_env: "", batch_size: 15 });
  const save = useMutation({
    mutationFn: async (row: Record<string, unknown>) => must(supabase.from("models").upsert(row)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });
  const setDefault = useMutation({
    mutationFn: (id: string) => rpc("set_default_model", { p_id: id }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });
  if (q.isLoading) return <Spinner />;
  return (
    <div className="space-y-4">
      <ErrorBox error={q.error ?? save.error ?? setDefault.error} />
      <Card className="divide-y divide-line">
        {((q.data as any[]) ?? []).map((m) => (
          <div key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
            <button onClick={() => setDefault.mutate(m.id)} title="Make default"
              className={m.is_default ? "text-review" : "text-faint hover:text-review"}><Star className="h-4 w-4" fill={m.is_default ? "currentColor" : "none"} /></button>
            <div className="min-w-48">
              <div className="font-medium">{m.label}</div>
              <div className="font-mono text-xs text-dim">{m.model} · {m.base_url || "LM Studio (local)"}</div>
            </div>
            <label className="flex items-center gap-1 text-xs text-dim">batch
              <input type="number" min={1} max={500} defaultValue={m.batch_size} className="w-16 rounded border border-line bg-panel px-1"
                onBlur={(e) => +e.target.value !== m.batch_size && save.mutate({ ...m, batch_size: +e.target.value })} /></label>
            <label className="flex items-center gap-1 text-xs text-dim">
              <input type="checkbox" checked={m.disable_thinking} onChange={(e) => save.mutate({ ...m, disable_thinking: e.target.checked })} /> thinking off</label>
            <label className="ml-auto flex items-center gap-1 text-xs text-dim">
              <input type="checkbox" checked={m.enabled} onChange={(e) => save.mutate({ ...m, enabled: e.target.checked })} /> enabled</label>
          </div>
        ))}
      </Card>
      <Card className="p-4">
        <div className="mb-2 text-sm font-semibold">Add a model (any OpenAI-compatible endpoint — local or cloud)</div>
        <div className="grid gap-2 md:grid-cols-3">
          {([["id", "slug, e.g. local-judge"], ["label", "display name"], ["model", "model name sent in the request"],
            ["base_url", "https://…/v1 (empty = local LM Studio)"], ["api_key_env", "env var holding the key (worker side)"]] as const).map(([k, ph]) => (
            <input key={k} placeholder={ph} value={(form as any)[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })}
              className="rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm" />
          ))}
          <Button variant="primary" disabled={!form.id || !form.model}
            onClick={() => save.mutate({ ...form, api_key_env: form.api_key_env || null, label: form.label || form.id })}>
            <Plus className="h-3.5 w-3.5" /> Add model
          </Button>
        </div>
        <p className="mt-2 text-xs text-faint">API keys never go in the database — set them as environment variables on the machine running the judge worker.</p>
      </Card>
    </div>
  );
}

function Audit() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["settings"], queryFn: () => must(supabase.from("settings").select("*")) });
  const models = useQuery({ queryKey: ["models"], queryFn: () => must(supabase.from("models").select("id,label").eq("enabled", true)) });
  const save = useMutation({
    mutationFn: async ({ key, value }: { key: string; value: unknown }) => must(supabase.from("settings").upsert({ key, value: String(value) })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });
  const s = Object.fromEntries(((q.data as any[]) ?? []).map((r) => [r.key, r.value]));
  const Field = ({ k, label, hint, pct }: { k: string; label: string; hint: string; pct?: boolean }) => (
    <div className="flex flex-wrap items-center gap-3 border-t border-line px-4 py-3 first:border-0">
      <div className="min-w-64"><div className="text-sm font-medium">{label}</div><div className="text-xs text-dim">{hint}</div></div>
      <input type="number" step={pct ? 5 : 1} defaultValue={pct ? Math.round(Number(s[k] ?? 0) * 100) : Number(s[k] ?? 0)} key={String(s[k])}
        onBlur={(e) => save.mutate({ key: k, value: pct ? Number(e.target.value) / 100 : Number(e.target.value) })}
        className="w-24 rounded-lg border border-line bg-panel px-2 py-1 text-sm" />
      {pct && <span className="text-sm text-dim">%</span>}
    </div>
  );
  if (q.isLoading) return <Spinner />;
  return (
    <Card>
      <div className="border-b border-line px-4 py-3 text-sm text-dim">
        The NLP finds <b>X</b> candidates per post; the judge also sees <b>X</b> random other comments. If it flags at least the
        threshold below in that random draw, the NLP is missing things on this post, so it draws X more — until a draw comes back clean or the cap is hit.
      </div>
      <Field k="audit_expand_at" label="Expand when audit flags ≥" hint="share of the latest random draw the judge flagged" pct />
      <Field k="audit_max_share" label="Never audit more than" hint="of a post's eligible comments" pct />
      <Field k="audit_min" label="Minimum audit draw" hint="comments, for posts where the NLP found almost nothing" />
      <div className="flex items-center gap-3 border-t border-line px-4 py-3">
        <div className="min-w-64"><div className="text-sm font-medium">Auto-judge new sheets</div><div className="text-xs text-dim">as soon as an upload is fully scored</div></div>
        <input type="checkbox" checked={s.auto_judge === "true"} onChange={(e) => save.mutate({ key: "auto_judge", value: e.target.checked })} />
      </div>
      <div className="flex items-center gap-3 border-t border-line px-4 py-3">
        <div className="min-w-64"><div className="text-sm font-medium">Tiebreak model</div><div className="text-xs text-dim">second opinion on hides below the confidence bar (off = primary decides alone)</div></div>
        <select value={s.tiebreak_model ?? ""} onChange={(e) => save.mutate({ key: "tiebreak_model", value: e.target.value })}
          className="rounded-lg border border-line bg-panel px-2 py-1 text-sm">
          <option value="">off</option>
          {((models.data as any[]) ?? []).map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select>
      </div>
      <Field k="tiebreak_below_conf" label="Tiebreak hides under" hint="primary confidence below this gets a second opinion; a split verdict goes to review" pct />
      <div className="flex items-center gap-3 border-t border-line px-4 py-3">
        <div className="min-w-64"><div className="text-sm font-medium">Auto-hide mode</div><div className="text-xs text-dim">shadow records what would hide · live stamps the decision (never over a human)</div></div>
        <select value={s.autohide_mode ?? "shadow"} onChange={(e) => save.mutate({ key: "autohide_mode", value: e.target.value })}
          className="rounded-lg border border-line bg-panel px-2 py-1 text-sm">
          {(["off", "shadow", "live"] as const).map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
      <Field k="autohide_min_sev" label="Auto-hide from severity" hint="minimum severity S0–S3" />
      <Field k="autohide_min_conf" label="Auto-hide from confidence" hint="minimum primary confidence on the final verdict" pct />
      <ErrorBox error={save.error} />
    </Card>
  );
}

function Prompts() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["prompts"], queryFn: () => must(supabase.from("prompts").select("*").order("created_at", { ascending: false })) });
  const [draft, setDraft] = useState<{ version: string; notes: string; system_prompt: string } | null>(null);
  const save = useMutation({
    mutationFn: async () => {
      await must(supabase.from("prompts").insert(draft));
    },
    onSuccess: () => { setDraft(null); qc.invalidateQueries({ queryKey: ["prompts"] }); },
  });
  const activate = useMutation({
    mutationFn: (v: string) => rpc("activate_prompt", { p_version: v }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prompts"] }),
  });
  if (q.isLoading) return <Spinner />;
  const list = (q.data as any[]) ?? [];
  return (
    <div className="space-y-4">
      <ErrorBox error={save.error ?? activate.error} />
      {draft ? (
        <Card className="space-y-2 p-4">
          <div className="flex gap-2">
            <input value={draft.version} onChange={(e) => setDraft({ ...draft, version: e.target.value })} placeholder="version, e.g. v2"
              className="w-32 rounded-lg border border-line bg-panel px-2 py-1.5 text-sm" />
            <input value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} placeholder="what changed and why"
              className="flex-1 rounded-lg border border-line bg-panel px-2 py-1.5 text-sm" />
          </div>
          <textarea value={draft.system_prompt} onChange={(e) => setDraft({ ...draft, system_prompt: e.target.value })}
            rows={22} className="w-full rounded-lg border border-line bg-panel p-3 font-mono text-xs" />
          <div className="flex gap-2">
            <Button variant="primary" disabled={!draft.version || list.some((p) => p.version === draft.version)} onClick={() => save.mutate()}>Save version</Button>
            <Button variant="ghost" onClick={() => setDraft(null)}>Cancel</Button>
          </div>
          <p className="text-xs text-faint">Saving doesn't activate it. Activate, then re-run the judge on a few posts and compare in Runs.</p>
        </Card>
      ) : (
        <Button onClick={() => {
          const a = list.find((p) => p.is_active);
          setDraft({ version: `v${list.length + 1}`, notes: "", system_prompt: a?.system_prompt ?? "" });
        }}><Plus className="h-3.5 w-3.5" /> New version from active</Button>
      )}
      <Card className="divide-y divide-line">
        {list.map((p) => (
          <div key={p.version} className="flex items-center gap-3 px-4 py-3 text-sm">
            <span className="font-mono font-semibold">{p.version}</span>
            {p.is_active && <Chip kind="keep">active</Chip>}
            <span className="truncate text-dim">{p.notes}</span>
            <span className="ml-auto text-xs text-faint">{ago(p.created_at)}</span>
            {!p.is_active && <Button size="sm" onClick={() => activate.mutate(p.version)}>Activate</Button>}
          </div>
        ))}
      </Card>
    </div>
  );
}

function Lexicon() {
  const qc = useQueryClient();
  const [term, setTerm] = useState("");
  const [kind, setKind] = useState("insult");
  const [filter, setFilter] = useState("");
  const q = useQuery({ queryKey: ["lexicon"], queryFn: () => must(supabase.from("lexicon").select("*").order("created_at", { ascending: false })) });
  const add = useMutation({
    mutationFn: async () => must(supabase.from("lexicon").insert({ term: term.trim(), kind, note: "added in Judge lab" })),
    onSuccess: () => { setTerm(""); qc.invalidateQueries({ queryKey: ["lexicon"] }); },
  });
  const toggle = useMutation({
    mutationFn: async (r: any) => must(supabase.from("lexicon").update({ enabled: !r.enabled }).eq("id", r.id)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lexicon"] }),
  });
  const del = useMutation({
    mutationFn: async (id: number) => must(supabase.from("lexicon").delete().eq("id", id)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["lexicon"] }),
  });
  const rows = ((q.data as any[]) ?? []).filter((r) => !filter || r.kind === filter);
  return (
    <div className="space-y-4">
      <Card className="flex flex-wrap items-center gap-2 p-4">
        <input value={term} onChange={(e) => setTerm(e.target.value)} placeholder="word or phrase (Arabic is normalised automatically)" dir="auto"
          className="min-w-64 flex-1 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm" />
        <select value={kind} onChange={(e) => setKind(e.target.value)} className="rounded-lg border border-line bg-panel px-2 py-1.5 text-sm">
          {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <Button variant="primary" disabled={!term.trim()} onClick={() => add.mutate()}><Plus className="h-3.5 w-3.5" /> Add</Button>
        <p className="w-full text-xs text-faint">Any term pulls matching comments into the judge even when sentiment says neutral. "allow" does the opposite: it stops weak-negative misreads (e.g. MashAllah) from being sent.</p>
      </Card>
      <ErrorBox error={add.error ?? toggle.error ?? del.error} />
      <div className="flex flex-wrap gap-1">
        <button onClick={() => setFilter("")} className={clsx("rounded-md px-2 py-1 text-xs", !filter ? "bg-accent-soft text-accent" : "text-dim")}>all</button>
        {KINDS.map((k) => <button key={k} onClick={() => setFilter(k)} className={clsx("rounded-md px-2 py-1 text-xs", filter === k ? "bg-accent-soft text-accent" : "text-dim")}>{k}</button>)}
      </div>
      <Card className="divide-y divide-line">
        {rows.map((r) => (
          <div key={r.id} className={clsx("flex items-center gap-3 px-4 py-2 text-sm", !r.enabled && "opacity-50")}>
            <span dir="auto" className="font-medium">{r.term}</span>
            <Chip kind={r.kind === "allow" ? "keep" : "review"}>{r.kind}</Chip>
            <span className="truncate text-xs text-faint">{r.note}</span>
            <label className="ml-auto flex items-center gap-1 text-xs text-dim"><input type="checkbox" checked={r.enabled} onChange={() => toggle.mutate(r)} /> on</label>
            <button onClick={() => del.mutate(r.id)} className="text-faint hover:text-hide"><Trash2 className="h-3.5 w-3.5" /></button>
          </div>
        ))}
      </Card>
    </div>
  );
}

function Runs() {
  const qc = useQueryClient();
  const [sample, setSample] = useState(500);
  const [model, setModel] = useState("");
  const models = useQuery({ queryKey: ["models"], queryFn: () => must(supabase.from("models").select("*").eq("enabled", true)) });
  const runs = useQuery({
    queryKey: ["runs"], refetchInterval: 5000,
    queryFn: () => must(supabase.from("jobs").select("*").eq("kind", "judge").order("id", { ascending: false }).limit(50)),
  });
  const start = useMutation({
    mutationFn: (all: boolean) => rpc<number>("create_judge_run", {
      p_model: model || null, p_purpose: "teacher", p_sample: sample, p_judge_all: all }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });
  const { gate, dialog } = useModelGate();
  return (
    <div className="space-y-4">
      {dialog}
      <Card className="flex flex-wrap items-center gap-2 p-4 text-sm">
        <span className="font-medium">Teacher run</span>
        <span className="text-dim">label a random sample of</span>
        <input type="number" value={sample} onChange={(e) => setSample(+e.target.value)} className="w-24 rounded-lg border border-line bg-panel px-2 py-1" />
        <span className="text-dim">comments with</span>
        <select value={model} onChange={(e) => setModel(e.target.value)} className="rounded-lg border border-line bg-panel px-2 py-1">
          <option value="">default model</option>
          {((models.data as any[]) ?? []).map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select>
        <Button onClick={() => gate(model || null, () => start.mutate(false))}>NLP candidates + audit</Button>
        <Button onClick={() => gate(model || null, () => start.mutate(true))} title="For distillation data: judge every comment in the sample">Judge every comment</Button>
        <ErrorBox error={start.error} />
      </Card>
      {runs.isLoading ? <Spinner /> : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-faint">
              <tr>{["job", "purpose", "model · prompt", "status", "scope", "candidates", "audit (rounds · last rate)", "tiebreak (agree/n)", "auto", "judged", ""].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-line">
              {((runs.data as any[]) ?? []).map((r) => {
                return (
                  <tr key={r.id}>
                    <td className="px-3 py-2 font-mono">#{r.id}</td>
                    <td className="px-3 py-2">{r.purpose}</td>
                    <td className="px-3 py-2 text-dim">{r.model} · {r.prompt}</td>
                    <td className="px-3 py-2"><StatusChip status={r.status} />
                      {r.status === "queued" && r.error && <div className="mt-1 text-xs text-review">{r.error}</div>}</td>
                    <td className="px-3 py-2 tabular-nums">{n(r.n_scope)}</td>
                    <td className="px-3 py-2 tabular-nums">{n(r.n_candidates)}</td>
                    <td className="px-3 py-2 tabular-nums">{n(r.n_audit)}{r.audit_rounds ? ` (${r.audit_rounds} · ${Math.round((r.audit_last_rate ?? 0) * 100)}%)` : ""}</td>
                    <td className="px-3 py-2 tabular-nums">{r.n_tiebreak == null ? "—" : `${n(r.tiebreak_agree)}/${n(r.n_tiebreak)}`}</td>
                    <td className="px-3 py-2 tabular-nums">{r.n_autohide == null ? "—" : n(r.n_autohide)}</td>
                    <td className="px-3 py-2 tabular-nums">{n(r.n_done)}</td>
                    <td className="px-3 py-2 text-xs text-faint">{ago(r.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
