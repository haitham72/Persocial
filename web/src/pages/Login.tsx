import { useState } from "react";
import { supabase } from "../lib/supabase";
import { useAuth } from "../lib/auth";
import { Button, Card, ErrorBox } from "../components/ui";

const GUEST_LOGIN = import.meta.env.VITE_GUEST_LOGIN === "true";

export default function Login() {
  const { session, role } = useAuth();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const redirectTo = window.location.origin;

  if (session && !role) {
    return (
      <Center>
        <h1 className="text-lg font-semibold">Not on the list</h1>
        <p className="mt-1 text-sm text-dim">
          {session.user.email} isn't a member of this workspace. Ask the admin to add you.
        </p>
        <Button className="mt-4" onClick={() => supabase.auth.signOut()}>Sign out</Button>
      </Center>
    );
  }

  return (
    <Center>
      <h1 className="text-lg font-semibold">Persocial</h1>
      <p className="mt-1 text-sm text-dim">Sign in with Google, or with an email magic link.</p>
      <Button variant="primary" className="mt-5 w-full justify-center"
        onClick={() => supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo } })}>
        Continue with Google
      </Button>
      <div className="my-5 flex items-center gap-3 text-xs text-faint">
        <div className="h-px flex-1 bg-line" /> or email code <div className="h-px flex-1 bg-line" />
      </div>
      {!sent ? (
        <form className="flex gap-2" onSubmit={async (e) => {
          e.preventDefault(); setErr(null);
          const { error } = await supabase.auth.signInWithOtp({ email, options: { shouldCreateUser: true } });
          if (error) setErr(error); else setSent(true);
        }}>
          <input className="min-w-0 flex-1 rounded-lg border border-line bg-panel px-3 py-2 text-sm"
            placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
          <Button type="submit">Send</Button>
        </form>
      ) : (
        <form className="flex gap-2" onSubmit={async (e) => {
          e.preventDefault(); setErr(null);
          const { error } = await supabase.auth.verifyOtp({ email, token: code, type: "email" });
          if (error) setErr(error);
        }}>
          <input className="min-w-0 flex-1 rounded-lg border border-line bg-panel px-3 py-2 text-sm tracking-widest"
            placeholder="6-digit code" value={code} onChange={(e) => setCode(e.target.value)} />
          <Button type="submit" variant="primary">Verify</Button>
        </form>
      )}
      {GUEST_LOGIN && (
        <>
          <div className="my-5 flex items-center gap-3 text-xs text-faint">
            <div className="h-px flex-1 bg-line" /> or <div className="h-px flex-1 bg-line" />
          </div>
          <Button className="w-full justify-center" onClick={async () => {
            setErr(null);
            const { error } = await supabase.auth.signInAnonymously();
            if (error) setErr(error);
          }}>
            Continue as guest
          </Button>
          <p className="mt-2 text-xs text-faint">Demo access: view and triage sample data. No admin, members or settings.</p>
        </>
      )}
      <div className="mt-3"><ErrorBox error={err} /></div>
    </Center>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <Card className="w-full max-w-sm p-6">{children}</Card>
    </div>
  );
}
