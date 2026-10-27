import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { must, supabase } from "../lib/supabase";
import { ago } from "../lib/format";
import { Button, Card, Chip, ErrorBox, PageHeader, Spinner } from "../components/ui";

export default function Members() {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("reviewer");
  const [invited, setInvited] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["members"], queryFn: () => must(supabase.from("members").select("*").order("created_at")) });
  const save = useMutation({
    mutationFn: async (row: Record<string, unknown>) => must(supabase.from("members").upsert(row)),
    onSuccess: () => { setEmail(""); qc.invalidateQueries({ queryKey: ["members"] }); },
  });
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Members" sub="Only these emails can see anything. Anyone else who signs in sees an empty app." />
      <Card className="mb-4 flex flex-wrap gap-2 p-4">
        <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@gmail.com"
          className="min-w-64 flex-1 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-sm" />
        <select value={role} onChange={(e) => setRole(e.target.value)} className="rounded-lg border border-line bg-panel px-2 text-sm">
          <option value="reviewer">reviewer</option><option value="admin">admin</option>
        </select>
        <Button variant="primary" disabled={!email.includes("@")} onClick={async () => {
            const addr = email.trim().toLowerCase();
            save.mutate({ email: addr, role, active: true });
            const { error } = await supabase.auth.signInWithOtp({ email: addr });
            setInvited(error ? `invite failed: ${error.message}` : `invite sent to ${addr}`);
          }}>Add & invite</Button>
      </Card>
      {invited && <div className="mb-3 text-sm text-keep">{invited}</div>}
      <ErrorBox error={q.error ?? save.error} />
      {q.isLoading ? <Spinner /> : (
        <Card className="divide-y divide-line">
          {((q.data as any[]) ?? []).map((m) => (
            <div key={m.email} className="flex items-center gap-3 px-4 py-2.5 text-sm">
              <span className={m.active ? "" : "text-faint line-through"}>{m.email}</span>
              <Chip kind={m.role === "admin" ? "review" : undefined}>{m.role}</Chip>
              <span className="text-xs text-faint">added {ago(m.created_at)}</span>
              <Button size="sm" variant="ghost" className="ml-auto" onClick={() => save.mutate({ ...m, active: !m.active })}>
                {m.active ? "Disable" : "Enable"}
              </Button>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}
