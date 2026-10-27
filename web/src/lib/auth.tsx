import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "./supabase";

type Role = "admin" | "reviewer" | null;
interface AuthState {
  session: Session | null;
  email: string | null;
  role: Role;
  loading: boolean;
  isGuest: boolean;
}

const Ctx = createContext<AuthState>({ session: null, email: null, role: null, loading: true, isGuest: false });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ session: null, email: null, role: null, loading: true, isGuest: false });

  useEffect(() => {
    const load = async (session: Session | null) => {
      if (!session) return setState({ session: null, email: null, role: null, loading: false, isGuest: false });
      if (session.user.is_anonymous) {
        // Guest: server maps anonymous JWTs to a restricted reviewer (migration 0004).
        return setState({ session, email: "guest@guest.invalid", role: "reviewer", loading: false, isGuest: true });
      }
      const email = session.user.email?.toLowerCase() ?? null;
      // RLS lets a member read only their own row (admins read all); no row = not allowed in.
      const { data } = await supabase.from("members").select("role,active").eq("email", email ?? "").maybeSingle();
      setState({ session, email, role: data?.active ? (data.role as Role) : null, loading: false, isGuest: false });
    };
    supabase.auth.getSession().then(({ data }) => load(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => { load(s); });
    return () => sub.subscription.unsubscribe();
  }, []);

  return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
