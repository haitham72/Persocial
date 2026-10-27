import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { must, supabase } from "../lib/supabase";
import { Button, Card } from "./ui";

type Model = { id: string; label: string; model: string; base_url: string; is_default: boolean };

// Local (LM Studio) models are never loaded by the app: the operator loads them and turns
// thinking off by hand, then confirms here. The worker also refuses to run a job for a local
// model that isn't loaded, so skipping this dialog can't trigger a load either.
export function useModelGate() {
  const models = useQuery({ queryKey: ["models"], queryFn: () => must(supabase.from("models").select("*").eq("enabled", true)) });
  const [pending, setPending] = useState<{ model: Model; run: () => void } | null>(null);

  const gate = (modelId: string | null, run: () => void) => {
    const list = (models.data as Model[] | undefined) ?? [];
    const m = list.find((x) => (modelId ? x.id === modelId : x.is_default));
    if (m && !m.base_url) setPending({ model: m, run });
    else run();
  };

  const dialog = pending && (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setPending(null)}>
      <Card className="w-full max-w-md p-5">
        <div onClick={(e) => e.stopPropagation()}>
          <div className="mb-3 flex items-center gap-2 font-semibold text-review">
            <AlertTriangle className="h-5 w-5" /> Load the model first
          </div>
          <p className="text-sm text-dim">The app never loads a local model for you. Before starting:</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
            <li>In LM Studio, load <b>{pending.model.label}</b> <span className="font-mono text-xs text-faint">({pending.model.model})</span>.</li>
            <li><b>Use thinking tags: turn thinking OFF</b> for this model.</li>
          </ol>
          <p className="mt-3 text-xs text-faint">If the model isn't loaded, the job waits in the queue until it is.</p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setPending(null)}>Cancel</Button>
            <Button variant="primary" onClick={() => { pending.run(); setPending(null); }}>Loaded, thinking off — start</Button>
          </div>
        </div>
      </Card>
    </div>
  );

  return { gate, dialog };
}
