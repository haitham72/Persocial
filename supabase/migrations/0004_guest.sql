-- Guest access (demo/local only). A Supabase anonymous session (JWT claim is_anonymous = true)
-- is treated as a member with the reviewer role, minus configuration:
--   can   : read shared data, triage comments (decision/assignee/status), assign sheets
--   cannot: act as admin, manage members, read settings (except sla_hours), models, prompts,
--           lexicon, uploads, jobs or judge ledgers
-- Turn anonymous sign-ins off in Supabase (and VITE_GUEST_LOGIN=false) for any real deployment.
create or replace function public.is_guest() returns boolean
language sql stable as $$
  select coalesce((auth.jwt() ->> 'is_anonymous')::boolean, false)
$$;

-- actor name shown in stamps and the audit trail
create or replace function public.jwt_email() returns text
language sql stable as $$
  select case when public.is_guest() then 'guest@guest.invalid'
              else lower(coalesce(auth.jwt() ->> 'email', '')) end
$$;

-- guests resolve to the lowest role that still lets them use the app; never admin.
-- The members lookup is skipped for guests, so no allowlist row can promote one.
create or replace function public.current_role_name() returns text
language sql stable security definer set search_path = public as $$
  select case when public.is_guest() then 'reviewer'
              else (select role from members where email = jwt_email() and active) end
$$;

-- configuration tables stay closed to guests
drop policy if exists members_read on public.settings;
create policy members_read on public.settings for select to authenticated
  using (public.is_member() and (not public.is_guest() or key = 'sla_hours'));
do $$
declare t text;
begin
  foreach t in array array['models', 'prompts', 'lexicon']
  loop
    execute format('drop policy if exists members_read on public.%I', t);
    execute format('create policy members_read on public.%I for select to authenticated using (public.is_member() and not public.is_guest())', t);
  end loop;
end $$;
