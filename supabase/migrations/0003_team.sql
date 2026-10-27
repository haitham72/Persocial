-- Persocial team layer (squashed WP7: reviewer board, audit log, autohide, queue/SLA,
-- saved-reply seeds). Applies on top of 0001_schema + 0002_logic, from empty.
insert into public.saved_replies (title, body, lang) values
  ('Thanks + DM redirect (EN)', 'Thank you for reaching out — please send us a DM so the team can help you directly.', 'en'),
  ('Thanks + DM redirect (AR)', 'شكراً لتواصلكم — يرجى إرسال رسالة خاصة حتى يتمكن الفريق من مساعدتكم.', 'ar'),
  ('Welfare escalation (EN)', 'We are concerned about you. If you are in danger, please contact local emergency services or a trusted person right away.', 'en');

create table public.auto_actions (
  id          bigint generated always as identity primary key,
  ig_id       text not null references public.comments(ig_id) on delete cascade,
  job_id      bigint references public.jobs(id) on delete set null,
  action      text not null,
  mode        text not null check (mode in ('shadow', 'live')),
  created_at  timestamptz not null default now(),
  unique (ig_id, job_id)
);
alter table public.auto_actions enable row level security;
create policy admin_read on public.auto_actions for select to authenticated
  using (public.is_admin());
create policy admin_write on public.auto_actions for all to authenticated
  using (public.is_admin()) with check (public.is_admin());
alter table public.jobs add column if not exists n_autohide integer;
insert into public.settings (key, value) values
  ('autohide_mode', 'shadow'),
  ('autohide_min_sev', '3'),
  ('autohide_min_conf', '0.9')
on conflict (key) do nothing;

-- Unified reviewer queue (was 0013): flagged, undecided comments across all posts, newest
-- first. Powers the Inbox board. WP7 adds assignee/status/decision so the board can
-- group, assign and stamp without a second query.
create or replace function public.queue_comments(p_limit int default 200,
                                                 p_offset int default 0)
returns jsonb
language sql stable security invoker set search_path = public as $$
  select coalesce(jsonb_agg(to_jsonb(q) order by q.created_at desc nulls last),
                  '[]'::jsonb)
  from (select c.ig_id, c.post_code, c.author, c.text, c.created_at,
               c.sentiment, c.emotion, c.verdict, c.category, c.severity,
               c.confidence, c.welfare, c.judge_reason, c.decision, c.decided_by,
               c.assignee, c.status, c.judged_at, a.username as account,
               p.thumbnail_path
        from comments c
        join posts p on p.code = c.post_code
        left join accounts a on a.id = p.account_id
        where c.verdict in ('hide', 'review') and c.decision is null
        order by c.created_at desc nulls last
        limit p_limit offset p_offset) q
$$;
revoke all on function public.queue_comments(int, int) from public, anon;
grant execute on function public.queue_comments(int, int) to authenticated, service_role;
insert into public.settings (key, value) values ('sla_hours', '24')
on conflict (key) do nothing;

-- Comment audit log (WP7): one row per decision/assignee/status/ig_action change,
-- shown as a timeline in the comment drawer. Actor is the signed-in member; direct
-- DB sessions (tests, workers) fall back to 'system', like the review stamp.
create or replace function public._audit_comment() returns trigger
language plpgsql security definer set search_path = public as $$
declare who text := coalesce(nullif(public.jwt_email(), ''), 'system');
begin
  if new.decision is distinct from old.decision then
    insert into comment_events (comment_id, actor, action, from_value, to_value)
    values (new.ig_id, who, 'decision', old.decision, new.decision);
  end if;
  if new.assignee is distinct from old.assignee then
    insert into comment_events (comment_id, actor, action, from_value, to_value)
    values (new.ig_id, who, 'assignee', old.assignee::text, new.assignee::text);
  end if;
  if new.status is distinct from old.status then
    insert into comment_events (comment_id, actor, action, from_value, to_value)
    values (new.ig_id, who, 'status', old.status, new.status);
  end if;
  if new.ig_action is distinct from old.ig_action then
    insert into comment_events (comment_id, actor, action, from_value, to_value)
    values (new.ig_id, who, 'ig_action', old.ig_action, new.ig_action);
  end if;
  return new;
end $$;
drop trigger if exists comments_audit_log on public.comments;
create trigger comments_audit_log after update of decision, assignee, status, ig_action
  on public.comments for each row execute function public._audit_comment();
