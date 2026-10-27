import clsx from "clsx";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Loader2 } from "lucide-react";

export function Button({ variant = "default", size = "md", className, ...p }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "primary" | "ghost" | "danger"; size?: "sm" | "md" }) {
  return (
    <button
      {...p}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm",
        variant === "primary" && "bg-accent text-white hover:opacity-90",
        variant === "default" && "border border-line bg-panel hover:bg-bg",
        variant === "ghost" && "hover:bg-bg text-dim",
        variant === "danger" && "bg-hide text-white hover:opacity-90",
        className,
      )}
    />
  );
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("rounded-xl border border-line bg-panel", className)}>{children}</div>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-dim">
      <Loader2 className="h-4 w-4 animate-spin" /> {label ?? "Loading…"}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line p-10 text-center">
      <div className="font-medium">{title}</div>
      {children && <div className="mt-1 text-sm text-dim">{children}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="rounded-lg border border-hide/30 bg-hide-soft px-3 py-2 text-sm text-hide">
      {error instanceof Error ? error.message : String(error)}
    </div>
  );
}

const VERDICT: Record<string, string> = {
  hide: "bg-hide-soft text-hide",
  review: "bg-review-soft text-review",
  keep: "bg-keep-soft text-keep",
  escalate: "bg-review-soft text-review",
};

export function Chip({ kind, children, className }: { kind?: string; children: ReactNode; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-semibold",
      (kind && VERDICT[kind]) || "bg-bg text-dim", className)}>
      {children}
    </span>
  );
}

const STATUS: Record<string, [string, string]> = {
  scoring: ["Scoring", "bg-accent-soft text-accent"],
  judging: ["Judging", "bg-review-soft text-review"],
  ready: ["Ready", "bg-keep-soft text-keep"],
  failed: ["Failed", "bg-hide-soft text-hide"],
  pending: ["Pending", "bg-review-soft text-review"],
  registered: ["Registered", "bg-keep-soft text-keep"],
  open: ["Claimed", "bg-accent-soft text-accent"],
  returned: ["Returned", "bg-keep-soft text-keep"],
  expired: ["Expired", "bg-bg text-faint"],
  cancelled: ["Cancelled", "bg-bg text-faint"],
  queued: ["Queued", "bg-bg text-dim"],
  running: ["Running", "bg-accent-soft text-accent"],
  done: ["Done", "bg-keep-soft text-keep"],
};

export function StatusChip({ status }: { status: string }) {
  const [label, cls] = STATUS[status] ?? [status, "bg-bg text-dim"];
  return <span className={clsx("rounded-md px-1.5 py-0.5 text-[11px] font-semibold", cls)}>{label}</span>;
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {sub && <div className="mt-0.5 text-sm text-dim">{sub}</div>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-medium uppercase tracking-wide text-faint">{label}</div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums">{value}</div>
      {hint && <div className="text-xs text-dim">{hint}</div>}
    </div>
  );
}
