import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  Bell, Inbox, LayoutGrid, Upload, Cpu, FlaskConical, Users, UserX, LogOut, Moon, Sun,
} from "lucide-react";
import { rpc, supabase } from "../lib/supabase";
import { useAuth } from "../lib/auth";
import { ago } from "../lib/format";

const NAV = [
  { to: "/", label: "Inbox", icon: Inbox, admin: false },
  { to: "/posts", label: "Posts", icon: LayoutGrid, admin: false },
  { to: "/offenders", label: "Repeat offenders", icon: UserX, admin: false },
  { to: "/upload", label: "Upload", icon: Upload, admin: true },
  { to: "/scoring", label: "Scoring", icon: Cpu, admin: true },
  { to: "/judge", label: "Judge lab", icon: FlaskConical, admin: true },
  { to: "/members", label: "Members", icon: Users, admin: true },
];

type Worker = { worker: string; device: string; models: string | null; seen_at: string };

// Workers are the GPU/LM Studio PCs (4080, Mac). None live → scoring needs Colab and the
// judge goes to the cloud API.
function Workers() {
  const q = useQuery({ queryKey: ["workers-live"], refetchInterval: 30_000, queryFn: () => rpc<Worker[]>("workers_live") });
  const ws = q.data ?? [];
  const title = ws.length
    ? ws.map((w) => `${w.worker} · ${w.device}${w.models ? ` · ${w.models}` : " · no LLM loaded"}`).join("\n")
    : "No worker PC online: score with Colab; the judge uses the cloud model";
  return (
    <span title={title} className={clsx("mr-1 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs",
      ws.length ? "bg-keep-soft text-keep" : "bg-bg text-dim")}>
      <span className={clsx("h-1.5 w-1.5 rounded-full", ws.length ? "bg-keep" : "bg-faint")} />
      {ws.length ? `${ws.length} worker${ws.length > 1 ? "s" : ""} live` : "no workers"}
    </span>
  );
}

const IS_LOCAL_DB = /127\.0\.0\.1|localhost/.test(import.meta.env.VITE_SUPABASE_URL ?? "");

// Admin's local database only: manual / auto / never (sandbox) sync with the cloud.
function SyncMode() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["sync-mode"], queryFn: () => rpc<string>("sync_mode") });
  const set = async (m: string) => { await rpc("set_sync_mode", { p_mode: m }); qc.invalidateQueries({ queryKey: ["sync-mode"] }); };
  return (
    <label className="mr-1 inline-flex items-center gap-1 text-xs text-dim" title="manual: push/pull on demand · auto: the local worker syncs every 5 min · never: sandbox">
      sync
      <select value={q.data ?? "manual"} onChange={(e) => set(e.target.value)} className="rounded-md border border-line bg-panel px-1.5 py-0.5">
        <option value="manual">manual</option><option value="auto">auto</option><option value="never">never (sandbox)</option>
      </select>
    </label>
  );
}

function useDark() {
  const [dark, setDark] = useState(() => {
    try { return localStorage.getItem("theme") === "dark"; } catch { return false; }
  });
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch { /* private mode */ }
  }, [dark]);
  return [dark, setDark] as const;
}

function Bell_() {
  const { email } = useAuth();
  const qc = useQueryClient();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const { data } = useQuery({
    queryKey: ["notifications"],
    queryFn: async () => {
      const [{ data: items }, { data: me }] = await Promise.all([
        supabase.from("notifications").select("*").order("created_at", { ascending: false }).limit(30),
        supabase.from("members").select("notifications_seen_at").eq("email", email ?? "").maybeSingle(),
      ]);
      const seen = new Date(me?.notifications_seen_at ?? 0).getTime();
      return (items ?? []).map((n) => ({ ...n, read: new Date(n.created_at).getTime() <= seen }));
    },
  });
  useEffect(() => {
    const ch = supabase.channel("notif")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "notifications" },
        () => qc.invalidateQueries({ queryKey: ["notifications"] }))
      .subscribe();
    return () => { supabase.removeChannel(ch); };
  }, [qc]);
  const unread = (data ?? []).filter((n) => !n.read);
  const markAll = async () => {
    if (!unread.length || !email) return;
    await supabase.from("members").update({ notifications_seen_at: new Date().toISOString() }).eq("email", email);
    qc.invalidateQueries({ queryKey: ["notifications"] });
  };
  return (
    <div className="relative">
      <button onClick={() => { setOpen(!open); if (!open) markAll(); }}
        className="relative rounded-lg p-2 text-dim hover:bg-bg" aria-label="Notifications">
        <Bell className="h-4 w-4" />
        {unread.length > 0 && (
          <span className="absolute -right-0.5 -top-0.5 rounded-full bg-hide px-1 text-[10px] font-bold text-white">
            {unread.length}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-80 overflow-hidden rounded-xl border border-line bg-panel shadow-lg">
          <div className="border-b border-line px-3 py-2 text-xs font-semibold text-dim">Notifications</div>
          <div className="max-h-96 overflow-auto">
            {(data ?? []).length === 0 && <div className="p-4 text-sm text-dim">Nothing yet.</div>}
            {(data ?? []).map((n) => (
              <button key={n.id} onClick={() => { setOpen(false); if (n.link) nav(n.link); }}
                className={clsx("block w-full border-b border-line px-3 py-2 text-left hover:bg-bg", !n.read && "bg-accent-soft/40")}>
                <div className="text-sm font-medium">{n.title}</div>
                <div className="text-xs text-dim">{n.body} · {ago(n.created_at)}</div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Layout() {
  const { email, role, isGuest } = useAuth();
  const [dark, setDark] = useDark();
  return (
    <div className="flex h-full">
      <aside className="hidden w-56 shrink-0 flex-col border-r border-line bg-panel md:flex">
        <div className="px-4 py-4">
          <div className="text-[15px] font-semibold tracking-tight">Persocial</div>
          <div className="text-xs text-faint">comment intelligence</div>
        </div>
        <nav className="flex-1 space-y-0.5 px-2">
          {NAV.filter((i) => !i.admin || role === "admin").map((i) => (
            <NavLink key={i.to} to={i.to} end={i.to === "/"}
              className={({ isActive }) => clsx(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm",
                isActive ? "bg-accent-soft font-medium text-accent" : "text-dim hover:bg-bg hover:text-ink")}>
              <i.icon className="h-4 w-4" /> {i.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-line p-3 text-xs text-dim">
          <div className="truncate">{isGuest ? "Guest" : email}</div>
          <div className="mt-0.5 capitalize text-faint">{role}</div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-end gap-1 border-b border-line bg-panel px-4 py-2">
          <div className="mr-auto flex gap-1 overflow-x-auto md:hidden">
            {NAV.filter((i) => !i.admin || role === "admin").map((i) => (
              <NavLink key={i.to} to={i.to} end={i.to === "/"} className={({ isActive }) =>
                clsx("rounded-md p-2", isActive ? "bg-accent-soft text-accent" : "text-dim")}>
                <i.icon className="h-4 w-4" />
              </NavLink>
            ))}
          </div>
          <Workers />
          {role === "admin" && IS_LOCAL_DB && <SyncMode />}
          <Bell_ />
          <button onClick={() => setDark(!dark)} className="rounded-lg p-2 text-dim hover:bg-bg" aria-label="Theme">
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <button onClick={() => supabase.auth.signOut()} className="rounded-lg p-2 text-dim hover:bg-bg" aria-label="Sign out">
            <LogOut className="h-4 w-4" />
          </button>
        </header>
        <main className="min-h-0 flex-1 overflow-auto px-4 py-6 md:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
