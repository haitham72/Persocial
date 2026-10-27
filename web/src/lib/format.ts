/** Display timezone; keep in step with PERSOCIAL_TZ (default UTC). */
export const TZ = (import.meta.env.VITE_PERSOCIAL_TZ as string | undefined) || "UTC";

export function localTime(iso?: string | null, withTime = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-GB", {
    timeZone: TZ, day: "numeric", month: "short", year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

export function ago(iso?: string | null): string {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d ago`;
  return localTime(iso, false);
}

/** Date bucket label in the display timezone: Today / Yesterday / 12 Oct 2026. */
export function dayBucket(iso?: string | null): string {
  if (!iso) return "No date";
  const fmt = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: TZ });
  const day = fmt(new Date(iso));
  const today = fmt(new Date());
  const y = new Date(); y.setDate(y.getDate() - 1);
  if (day === today) return "Today";
  if (day === fmt(y)) return "Yesterday";
  return localTime(iso, false);
}

export const n = (v?: number | null) => (v == null ? "—" : v.toLocaleString("en-US"));

export function delta(v?: number | null): string | null {
  if (v == null || v === 0) return null;
  const abs = Math.abs(v);
  const s = abs >= 1e6 ? `${(abs / 1e6).toFixed(1)}M` : abs >= 1e3 ? `${(abs / 1e3).toFixed(1)}k` : `${abs}`;
  return `${v > 0 ? "+" : "−"}${s}`;
}

export function igCommentUrl(postCode: string, igId: string) {
  return `https://www.instagram.com/p/${postCode}/c/${igId}/`;
}

/** CSV with a UTF-8 BOM so Excel opens Arabic correctly. */
export function downloadCsv(filename: string, header: string[], rows: (string | number | null | undefined)[][]) {
  const esc = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const body = [header, ...rows].map((r) => r.map(esc).join(",")).join("\r\n");
  const blob = new Blob(["﻿" + body], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
