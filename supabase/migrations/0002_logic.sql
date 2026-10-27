-- Business logic as SQL functions, shared by the web app (RPC), the Colab notebook (via the
-- colab-api Edge Function) and Python workers. JSON appears only as the request/response
-- envelope of these calls — never as a stored column.

-- ---------------------------------------------------------------------------
-- auth helpers
-- ---------------------------------------------------------------------------
create or replace function public.jwt_email() returns text
language sql stable as $$ select lower(coalesce(auth.jwt() ->> 'email', '')) $$;

create or replace function public.current_role_name() returns text
language sql stable security definer set search_path = public as $$
  select role from members where email = jwt_email() and active
$$;
create or replace function public.is_member() returns boolean
language sql stable as $$ select public.current_role_name() is not null $$;
create or replace function public.is_admin() returns boolean
language sql stable as $$ select public.current_role_name() = 'admin' $$;

-- admin in the web app, the service role (Edge Functions), or a direct DB session (workers)
create or replace function public.assert_operator() returns void
language plpgsql stable security definer set search_path = public as $$
begin
  if is_admin() or coalesce(auth.role(), '') = 'service_role'
     or session_user in ('postgres', 'supabase_admin') then
    return;
  end if;
  raise exception 'not allowed: operator role required' using errcode = '42501';
end $$;

create or replace function public.setting(p_key text) returns text
language sql stable security definer set search_path = public as $$
  select value from settings where key = p_key
$$;

-- ---------------------------------------------------------------------------
-- text normalisation (mirrors ops/text.py; parity is tested)
-- ---------------------------------------------------------------------------
create or replace function public.normalize_text(t text) returns text
language plpgsql immutable parallel safe as $$
declare r text;
begin
  if t is null or t = '' then return ''; end if;
  r := normalize(t, NFKC);
  r := regexp_replace(r, '[​-‏‪-‮⁦-⁩﻿]', '', 'g');
  r := regexp_replace(r, '[ؐ-ًؚ-ٰٟۖ-ۭـ]', '', 'g');
  r := translate(r, 'أإآٱىئؤةکی٠١٢٣٤٥٦٧٨٩', 'اااايييوهكي0123456789');
  r := lower(r);
  r := regexp_replace(r, '(https?://\S+|www\.\S+)', '<url>', 'gi');
  r := regexp_replace(r, '(^|\s)@[[:alnum:]_.]+', '\1@user', 'g');
  r := regexp_replace(r, '(.)\1\1+', '\1\1', 'g');
  return btrim(regexp_replace(r, '\s+', ' ', 'g'));
end $$;

create or replace function public.script_of(t text) returns text
language plpgsql immutable parallel safe as $$
declare ar int; la int; share numeric;
begin
  if t is null or btrim(t) = '' then return 'other'; end if;
  ar := length(regexp_replace(t, '[^؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]', '', 'g'));
  la := length(regexp_replace(t, '[^A-Za-zÀ-ɏ]', '', 'g'));
  if ar = 0 and la = 0 then
    return case when t !~ '[[:alpha:]]' and t ~ '[^\u0000-῿]' then 'emoji' else 'other' end;
  end if;
  if ar > 0 and la > 0 then
    share := ar::numeric / (ar + la);
    if share between 0.2 and 0.8 then return 'mixed'; end if;
    return case when share > 0.8 then 'arabic' else 'latin' end;
  end if;
  return case when ar > 0 then 'arabic' else 'latin' end;
end $$;

-- ---------------------------------------------------------------------------
-- post counts
-- ---------------------------------------------------------------------------
create or replace function public.refresh_post_counts(p_posts text[] default null) returns int
language plpgsql security definer set search_path = public as $$
declare n int;
begin
  update posts p set
    n_comments = coalesce(c.n, 0), n_scored = coalesce(c.scored, 0),
    n_negative = coalesce(c.neg, 0), n_flagged = coalesce(c.flagged, 0),
    last_judged_at = c.judged
  from (select po.code, x.n, x.scored, x.neg, x.flagged, x.judged
        from posts po
        left join lateral (
          select count(*) n, count(scored_at) scored,
                 count(*) filter (where sentiment = 'negative') neg,
                 count(*) filter (where verdict in ('hide', 'review')) flagged,
                 max(judged_at) judged
          from comments where post_code = po.code) x on true
        where p_posts is null or po.code = any(p_posts)) c
  where p.code = c.code;
  get diagnostics n = row_count;
  return n;
end $$;

-- ---------------------------------------------------------------------------
-- scores: one writer for imports, Colab and local workers
-- ---------------------------------------------------------------------------
-- p_rows: [{ig_id, sentiment: [{label,score}..], emotions: [{label,score}..], scored_at?}]
-- Fills the NLP columns of comments that aren't scored yet (first score wins).
create or replace function public.apply_scores(p_rows jsonb, p_by text, p_model text default null)
returns int
language plpgsql security definer set search_path = public as $$
declare n int; mv text := coalesce(p_model, setting('nlp_model'), 'persocial-v1');
begin
  with r as (
    select x.ig_id, x.sentiment s, coalesce(x.emotions, '[]'::jsonb) e, x.scored_at
    from jsonb_to_recordset(p_rows) as x(ig_id text, sentiment jsonb, emotions jsonb,
                                         scored_at timestamptz)
    where jsonb_typeof(x.sentiment) = 'array' and jsonb_array_length(x.sentiment) > 0),
  v as (
    select r.ig_id, r.scored_at,
           (select l ->> 'label' from jsonb_array_elements(r.s) l
             order by (l ->> 'score')::real desc limit 1) as top,
           (select (l ->> 'score')::real from jsonb_array_elements(r.s) l where l ->> 'label' = 'negative') as neg,
           (select (l ->> 'score')::real from jsonb_array_elements(r.s) l where l ->> 'label' = 'neutral') as neu,
           (select (l ->> 'score')::real from jsonb_array_elements(r.s) l where l ->> 'label' = 'positive') as pos,
           (select l ->> 'label' from jsonb_array_elements(r.e) l
             order by (l ->> 'score')::real desc limit 1) as emo,
           (select max((l ->> 'score')::real) from jsonb_array_elements(r.e) l) as emo_s
    from r)
  update comments c set
    sentiment = v.top, sent_negative = v.neg, sent_neutral = v.neu, sent_positive = v.pos,
    emotion = v.emo, emotion_score = v.emo_s, nlp_model = mv,
    scored_at = coalesce(v.scored_at, now()), scored_by = p_by
  from v
  where c.ig_id = v.ig_id and c.scored_at is null;
  get diagnostics n = row_count;
  return n;
end $$;

-- ---------------------------------------------------------------------------
-- review sheets
-- ---------------------------------------------------------------------------
create or replace function public.sheet_counts(p_sheet bigint) returns void
language sql security definer set search_path = public as $$
  update review_sheets s set
    n_flagged = x.flagged, n_decided = x.decided
  from (select count(*) filter (where c.verdict in ('hide', 'review') or c.welfare) flagged,
               count(*) filter (where c.decision is not null) decided
        from review_sheets rs
        join comments c on c.first_upload_id = rs.upload_id and c.post_code = rs.post_code
        where rs.id = p_sheet) x
  where s.id = p_sheet
$$;

create or replace function public.sheet_mark_ready(p_sheet bigint) returns text
language plpgsql security definer set search_path = public as $$
declare was text; s record; who text;
begin
  select status into was from review_sheets where id = p_sheet for update;
  if was is null then return 'missing'; end if;
  perform sheet_counts(p_sheet);
  update review_sheets set status = 'ready', ready_at = coalesce(ready_at, now())
   where id = p_sheet returning post_code, n_new, n_flagged into s;
  if was = 'ready' then return 'ready'; end if;          -- re-judge: no second ping
  select '@' || a.username || ' · ' into who
    from posts p join accounts a on a.id = p.account_id where p.code = s.post_code;
  insert into notifications (kind, title, body, link, post_code, sheet_id)
  values ('sheet_ready', coalesce(who, '') || s.n_new || ' new comments',
          s.n_flagged || ' flagged on post ' || s.post_code, '/sheets/' || p_sheet,
          s.post_code, p_sheet);
  return 'ready';
end $$;

create or replace function public.sheet_advance(p_sheet bigint) returns text
language plpgsql security definer set search_path = public as $$
declare s review_sheets; unscored int;
begin
  select * into s from review_sheets where id = p_sheet;
  if s.id is null or s.status <> 'scoring' then return coalesce(s.status, 'missing'); end if;
  select count(*) into unscored from comments
   where first_upload_id = s.upload_id and post_code = s.post_code and scored_at is null;
  if unscored > 0 then return 'scoring'; end if;
  if coalesce(setting('auto_judge'), 'true') <> 'true' then return sheet_mark_ready(p_sheet); end if;
  update review_sheets set status = 'judging' where id = p_sheet;
  if not exists (select 1 from jobs where kind = 'judge' and sheet_id = p_sheet
                   and status in ('queued', 'running')) then
    insert into jobs (kind, purpose, post_code, sheet_id, model, prompt, seed)
    values ('judge', 'review', s.post_code, p_sheet,
            (select id from models where is_default and enabled),
            (select version from prompts where is_active), (random() * 2e9)::int + 1);
  end if;
  return 'judging';
end $$;

create or replace function public.sheets_advance_for_post(p_post text) returns void
language sql security definer set search_path = public as $$
  select sheet_advance(id) from review_sheets where post_code = p_post and status = 'scoring'
$$;

-- reviewer decisions keep their sheet's counter current
create or replace function public._decision_counts() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  perform sheet_counts(rs.id) from review_sheets rs
   where rs.upload_id = new.first_upload_id and rs.post_code = new.post_code;
  return new;
end $$;
create trigger comments_decision_counts after update of decision on public.comments
  for each row when (old.decision is distinct from new.decision)
  execute function public._decision_counts();

-- who/when are stamped by the database, never taken from the client
create or replace function public._stamp_review() returns trigger
language plpgsql as $$
begin
  if new.decision is distinct from old.decision then
    new.decided_by := nullif(public.jwt_email(), ''); new.decided_at := now();
    if new.decided_by is null then new.decided_by := coalesce(old.decided_by, 'system'); end if;
  end if;
  if new.ig_action is distinct from old.ig_action then
    new.ig_action_by := coalesce(nullif(public.jwt_email(), ''), 'system'); new.ig_action_at := now();
  end if;
  return new;
end $$;
create trigger comments_stamp_review before update of decision, ig_action on public.comments
  for each row execute function public._stamp_review();

-- ---------------------------------------------------------------------------
-- upload: preview → begin → chunks → finish
-- ---------------------------------------------------------------------------
-- p_rows: [{"p": post_code, "i": ig_id}] — ids only, so a 13k-row file previews cheaply.
create or replace function public.preview_comments(p_rows jsonb) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare out jsonb;
begin
  perform assert_operator();
  with r as (select x ->> 'p' code, x ->> 'i' ig_id from jsonb_array_elements(p_rows) x),
  per as (select r.code, count(*) n_rows, count(distinct r.ig_id) n_unique,
                 count(distinct c.ig_id) n_existing
          from r left join comments c on c.ig_id = r.ig_id group by r.code)
  select coalesce(jsonb_agg(jsonb_build_object(
           'code', per.code, 'known', p.code is not null, 'status', p.status,
           'registered', p.status = 'registered', 'account', a.username,
           'caption', left(p.caption, 160), 'thumbnail_path', p.thumbnail_path,
           'like_count', p.like_count, 'comment_count', p.comment_count,
           'metrics_updated_at', p.metrics_updated_at, 'stored_comments', coalesce(p.n_comments, 0),
           'n_rows', per.n_rows, 'n_existing', per.n_existing,
           'n_new', per.n_unique - per.n_existing) order by per.code), '[]'::jsonb)
    into out
  from per left join posts p on p.code = per.code left join accounts a on a.id = p.account_id;
  return out;
end $$;

create or replace function public.ensure_account(p_username text) returns bigint
language plpgsql security definer set search_path = public as $$
declare u text := lower(ltrim(btrim(p_username), '@')); i bigint;
begin
  insert into accounts (username) values (u) on conflict (username) do nothing;
  select id into i from accounts where username = u;
  return i;
end $$;

-- p_meta: {account, reported_comment_count, rows_total, rows_rejected, reject_note, captured_at}
-- retry rule (was 0005): only a finished upload counts as 'already uploaded'.
create or replace function public.ingest_begin(p_source text, p_filename text, p_sha text,
                                               p_meta jsonb default '{}') returns jsonb
language plpgsql security definer set search_path = public as $$
declare u uploads;
begin
  perform assert_operator();
  select * into u from uploads where sha256 = p_sha;
  if found and u.status = 'done' then
    return jsonb_build_object('upload_id', u.id, 'duplicate', true,
                              'rows_inserted', u.rows_inserted, 'rows_existing', u.rows_existing);
  elsif found then
    delete from uploads where id = u.id;
  end if;
  insert into uploads (source, filename, sha256, account_hint, reported_comment_count,
         rows_total, rows_rejected, reject_note, captured_at, uploaded_by)
  values (p_source, p_filename, p_sha, nullif(p_meta ->> 'account', ''),
          (p_meta ->> 'reported_comment_count')::int, coalesce((p_meta ->> 'rows_total')::int, 0),
          coalesce((p_meta ->> 'rows_rejected')::int, 0), p_meta ->> 'reject_note',
          (p_meta ->> 'captured_at')::timestamptz,
          coalesce(nullif(jwt_email(), ''), nullif(p_meta ->> 'uploaded_by', ''), 'ops'))
  returning * into u;
  return jsonb_build_object('upload_id', u.id, 'duplicate', false);
end $$;

create or replace function public.ingest_comments_chunk(p_upload bigint, p_rows jsonb,
                                                        p_account text default null) returns jsonb
language plpgsql security definer set search_path = public as $$
declare missing text[]; acc bigint; ins int; ex int; sc int; fname text;
begin
  perform assert_operator();
  create temp table if not exists stg_c (
    ig_id text, post_code text, parent_ig_id text, author_id text, author text, text text,
    created_at timestamptz, like_count int, repeat_commenter boolean) on commit drop;
  truncate stg_c;
  insert into stg_c
  select distinct on (x.ig_id) x.ig_id, x.post_code, x.parent_ig_id, x.author_id, x.author,
         coalesce(x.text, ''), x.created_at, x.like_count, coalesce(x.repeat_commenter, false)
  from jsonb_to_recordset(p_rows) as x(ig_id text, post_code text, parent_ig_id text,
       author_id text, author text, text text, created_at timestamptz, like_count int,
       repeat_commenter boolean)
  where x.ig_id ~ '^\d+$' and coalesce(x.post_code, '') <> ''
  order by x.ig_id;

  select array_agg(distinct s.post_code) into missing
  from stg_c s where not exists (select 1 from posts p where p.code = s.post_code);
  if missing is not null then
    if coalesce(btrim(p_account), '') = '' then
      raise exception 'unknown_posts:%', array_to_string(missing, ',') using errcode = 'P0002';
    end if;
    acc := ensure_account(p_account);
    insert into posts (code, account_id, status) select unnest(missing), acc, 'pending'
    on conflict do nothing;
  end if;

  with up as (
    insert into comments as c (ig_id, post_code, parent_ig_id, author_id, author, text,
           text_norm, script, created_at, like_count, repeat_commenter, first_upload_id,
           last_upload_id)
    select ig_id, post_code, parent_ig_id, author_id, author, text, normalize_text(text),
           script_of(text), created_at, like_count, repeat_commenter, p_upload, p_upload
    from stg_c
    on conflict (ig_id) do update set
      last_upload_id   = excluded.last_upload_id,
      last_seen_at     = now(),
      like_count       = coalesce(excluded.like_count, c.like_count),
      parent_ig_id     = coalesce(c.parent_ig_id, excluded.parent_ig_id),
      author_id        = coalesce(c.author_id, excluded.author_id),
      author           = coalesce(c.author, excluded.author),
      created_at       = coalesce(c.created_at, excluded.created_at),
      repeat_commenter = c.repeat_commenter or excluded.repeat_commenter,
      text      = case when c.text = '' then excluded.text else c.text end,
      text_norm = case when c.text = '' then excluded.text_norm else c.text_norm end,
      script    = case when c.text = '' then excluded.script else c.script end
    returning (xmax = 0) as inserted)
  select count(*) filter (where inserted), count(*) filter (where not inserted) into ins, ex from up;

  select filename into fname from uploads where id = p_upload;
  sc := apply_scores(p_rows, 'csv:' || coalesce(fname, '?'),
                     (select max(x.model_version) from jsonb_to_recordset(p_rows) x(model_version text)));

  update uploads set rows_inserted = rows_inserted + ins, rows_existing = rows_existing + ex,
         rows_scored = rows_scored + sc, post_code = coalesce(post_code, (select min(post_code) from stg_c))
   where id = p_upload;
  return jsonb_build_object('inserted', ins, 'existing', ex, 'scored', sc);
end $$;

-- p_rows: [{code, username, caption, posted_at, media_type, video_url, image_url, like_count,
--          comment_count, play_count, engagement_rate, follower_count, following_count, media_count}]
create or replace function public.ingest_metrics_chunk(p_upload bigint, p_rows jsonb,
                                                       p_captured_at timestamptz) returns jsonb
language plpgsql security definer set search_path = public as $$
declare r record; acc bigint; ins int := 0; upd int := 0; was_new boolean; thumb text;
        need jsonb := '{}'::jsonb;
begin
  perform assert_operator();
  for r in select * from jsonb_to_recordset(p_rows) as x(code text, username text, caption text,
      posted_at timestamptz, media_type text, video_url text, image_url text, like_count int,
      comment_count int, play_count int, engagement_rate numeric, follower_count int,
      following_count int, media_count int) loop
    acc := ensure_account(r.username);
    update accounts set follower_count = coalesce(r.follower_count, follower_count),
           following_count = coalesce(r.following_count, following_count),
           media_count = coalesce(r.media_count, media_count) where id = acc;
    insert into posts as p (code, account_id, status, caption, posted_at, media_type, video_url,
           like_count, comment_count, play_count, engagement_rate, metrics_updated_at)
    values (r.code, acc, 'registered', r.caption, r.posted_at, r.media_type, r.video_url,
            r.like_count, r.comment_count, r.play_count, r.engagement_rate, p_captured_at)
    on conflict (code) do update set
      status = 'registered',
      account_id = coalesce(p.account_id, excluded.account_id),
      caption    = coalesce(excluded.caption, p.caption),
      posted_at  = coalesce(p.posted_at, excluded.posted_at),
      media_type = coalesce(excluded.media_type, p.media_type),
      video_url  = coalesce(excluded.video_url, p.video_url),
      like_count      = case when p.metrics_updated_at is null or excluded.metrics_updated_at >= p.metrics_updated_at then excluded.like_count      else p.like_count end,
      comment_count   = case when p.metrics_updated_at is null or excluded.metrics_updated_at >= p.metrics_updated_at then excluded.comment_count   else p.comment_count end,
      play_count      = case when p.metrics_updated_at is null or excluded.metrics_updated_at >= p.metrics_updated_at then excluded.play_count      else p.play_count end,
      engagement_rate = case when p.metrics_updated_at is null or excluded.metrics_updated_at >= p.metrics_updated_at then excluded.engagement_rate else p.engagement_rate end,
      metrics_updated_at = greatest(p.metrics_updated_at, excluded.metrics_updated_at)
    returning (xmax = 0), thumbnail_path into was_new, thumb;
    if was_new then ins := ins + 1; else upd := upd + 1; end if;
    if thumb is null and r.image_url is not null then
      need := need || jsonb_build_object(r.code, r.image_url);
    end if;
    insert into post_snapshots (post_code, captured_at, like_count, comment_count, play_count,
           engagement_rate, follower_count, upload_id)
    values (r.code, p_captured_at, r.like_count, r.comment_count, r.play_count,
            r.engagement_rate, r.follower_count, p_upload)
    on conflict (post_code, captured_at) do nothing;
  end loop;
  update uploads set rows_inserted = rows_inserted + ins, rows_existing = rows_existing + upd
   where id = p_upload;
  return jsonb_build_object('inserted', ins, 'updated', upd, 'image_urls', need);
end $$;

create or replace function public.ingest_finish(p_upload bigint, p_create_sheets boolean default true)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare u uploads; sheet_ids bigint[] := '{}'; p record; sid bigint; touched text[];
begin
  perform assert_operator();
  select * into u from uploads where id = p_upload for update;
  select array_agg(distinct post_code) into touched from comments where last_upload_id = p_upload;
  if u.source = 'post_metrics_csv' then
    select array_agg(post_code) into touched from post_snapshots where upload_id = p_upload;
  end if;
  perform refresh_post_counts(coalesce(touched, '{}'));
  -- a post scored to the end (e.g. a scored CSV back from offline Colab) frees its lease
  update posts set claimed_by = null, claimed_at = null, claim_expires_at = null
   where code = any(coalesce(touched, '{}')) and n_scored >= n_comments and claimed_by is not null;
   if p_create_sheets and u.source in ('comments_csv', 'apify_comments', 'generic_comments_csv') then
    for p in select post_code, count(*) n from comments where first_upload_id = p_upload
             group by post_code loop
      insert into review_sheets (post_code, upload_id, n_new) values (p.post_code, p_upload, p.n)
        returning id into sid;
      sheet_ids := sheet_ids || sid;
      perform sheet_advance(sid);
    end loop;
  end if;
  perform sheets_advance_for_post(t) from unnest(coalesce(touched, '{}')) t;
  update uploads set status = 'done', finished_at = now() where id = p_upload returning * into u;
  return jsonb_build_object('upload_id', u.id, 'rows_inserted', u.rows_inserted,
    'rows_existing', u.rows_existing, 'rows_scored', u.rows_scored,
    'rows_rejected', u.rows_rejected, 'sheet_ids', to_jsonb(sheet_ids));
end $$;

-- ---------------------------------------------------------------------------
-- scoring leases (Colab / any GPU): the lease is three columns on posts
-- ---------------------------------------------------------------------------
create or replace function public.pending_scoring(p_search text default null) returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(jsonb_build_object(
           'code', p.code, 'username', a.username, 'caption', left(p.caption, 120),
           'posted_at', p.posted_at, 'n_unscored', p.n_comments - p.n_scored,
           'claimed', p.claim_expires_at > now(), 'claimed_by', p.claimed_by)
         order by p.posted_at desc nulls last, p.code), '[]'::jsonb)
  from posts p left join accounts a on a.id = p.account_id
  where p.n_comments > p.n_scored
    and (p_search is null or p.code ilike '%' || p_search || '%' or a.username ilike '%' || p_search || '%')
$$;

-- Lease the next n unscored posts (or the given ones) to a runner.
create or replace function public.claim_posts(p_post_codes text[] default null, p_n int default 1,
                                              p_runner text default 'colab') returns jsonb
language plpgsql security definer set search_path = public as $$
declare ttl int := coalesce(setting('claim_ttl_minutes')::int, 120); out jsonb;
begin
  perform assert_operator();
  with picked as (
    select code from posts
    where n_comments > n_scored
      and (claim_expires_at is null or claim_expires_at < now())
      and (p_post_codes is null or code = any(p_post_codes))
    order by posted_at desc nulls last, code
    for update skip locked
    limit p_n),
  upd as (
    update posts p set claimed_by = p_runner, claimed_at = now(),
           claim_expires_at = now() + make_interval(mins => ttl)
    from picked where p.code = picked.code
    returning p.code, p.n_comments - p.n_scored as n_unscored, p.claim_expires_at)
  select coalesce(jsonb_agg(jsonb_build_object('post_code', code, 'n_unscored', n_unscored,
                                               'expires_at', claim_expires_at)), '[]'::jsonb)
    into out from upd;
  return out;
end $$;

create or replace function public.claim_comments(p_post text, p_limit int default 5000) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare out jsonb;
begin
  perform assert_operator();
  select coalesce(jsonb_agg(jsonb_build_object('ig_id', ig_id, 'text', text)), '[]'::jsonb) into out
  from (select ig_id, text from comments where post_code = p_post and scored_at is null
        order by created_at nulls last, ig_id limit p_limit) x;
  return out;
end $$;

-- Write a chunk of scores (a save point), keep the lease alive, release it when done.
create or replace function public.submit_scores(p_post text, p_rows jsonb, p_runner text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare n int; remaining int; ttl int := coalesce(setting('claim_ttl_minutes')::int, 120);
begin
  perform assert_operator();
  n := apply_scores(p_rows, p_runner);
  select count(*) into remaining from comments where post_code = p_post and scored_at is null;
  perform refresh_post_counts(array[p_post]);
  if remaining = 0 then
    update posts set claimed_by = null, claimed_at = null, claim_expires_at = null where code = p_post;
    perform sheets_advance_for_post(p_post);
  else
    update posts set claim_expires_at = greatest(claim_expires_at, now() + make_interval(mins => ttl))
     where code = p_post;
  end if;
  return jsonb_build_object('written', n, 'remaining', remaining);
end $$;

create or replace function public.release_claim(p_post text) returns boolean
language plpgsql security definer set search_path = public as $$
begin
  perform assert_operator();
  update posts set claimed_by = null, claimed_at = null, claim_expires_at = null
   where code = p_post and claimed_by is not null;
  return found;
end $$;

-- Rows for an offline CSV export (same columns as the comments CSV).
create or replace function public.claim_export(p_post text) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare out jsonb;
begin
  perform assert_operator();
  select coalesce(jsonb_agg(jsonb_build_object(
           'id', ig_id, 'owner_id', author_id, 'username', author, 'text', text,
           'created_at', to_char(created_at at time zone 'UTC', 'DD/MM/YYYY, HH24:MI:SS'),
           'postID', post_code, 'Spam', case when repeat_commenter then 1 else 0 end)
         order by created_at nulls last, ig_id), '[]'::jsonb) into out
  from comments where post_code = p_post and scored_at is null;
  return out;
end $$;

-- ---------------------------------------------------------------------------
-- judge jobs + admin
-- ---------------------------------------------------------------------------
create or replace function public.create_judge_run(p_post text default null, p_sheet bigint default null,
    p_model text default null, p_purpose text default 'review', p_sample int default null,
    p_account text default null, p_judge_all boolean default false) returns bigint
language plpgsql security definer set search_path = public as $$
declare m text; pv text; jid bigint; post text := p_post;
begin
  perform assert_operator();
  if p_sheet is not null and post is null then select post_code into post from review_sheets where id = p_sheet; end if;
  select id into m from models where enabled and (id = p_model or (p_model is null and is_default));
  if m is null then raise exception 'no enabled judge model %', coalesce(p_model, '(default)'); end if;
  select version into pv from prompts where is_active;
  if pv is null then raise exception 'no active prompt'; end if;
  insert into jobs (kind, purpose, post_code, sheet_id, model, prompt, sample_size, sample_account,
                    judge_all, seed)
  values ('judge', p_purpose, post, p_sheet, m, pv, p_sample, p_account, coalesce(p_judge_all, false),
          (random() * 2e9)::int + 1)
  returning id into jid;
  if p_sheet is not null then
    update review_sheets set status = 'judging' where id = p_sheet and status <> 'ready';
  end if;
  return jid;
end $$;

create or replace function public.activate_prompt(p_version text) returns void
language plpgsql security definer set search_path = public as $$
begin
  perform assert_operator();
  update prompts set is_active = false where is_active and version <> p_version;
  update prompts set is_active = true where version = p_version;
end $$;

create or replace function public.set_default_model(p_id text) returns void
language plpgsql security definer set search_path = public as $$
begin
  perform assert_operator();
  update models set is_default = false where is_default and id <> p_id;
  update models set is_default = true where id = p_id;
end $$;

-- ---------------------------------------------------------------------------
-- reads (return one jsonb value: PostgREST caps row sets at 1000)
-- ---------------------------------------------------------------------------
create or replace function public.sheet_comments(p_sheet bigint) returns jsonb
language sql stable security invoker set search_path = public as $$
  select coalesce(jsonb_agg(to_jsonb(c) - 'text_norm' order by
           case c.verdict when 'hide' then 0 when 'review' then 1 else 2 end,
           c.severity desc nulls last, c.created_at desc nulls last), '[]'::jsonb)
  from review_sheets s
  join comments c on c.first_upload_id = s.upload_id and c.post_code = s.post_code
  where s.id = p_sheet
$$;

create or replace function public.post_comments(p_post text, p_filter text default 'flagged',
                                                p_limit int default 200, p_offset int default 0)
returns jsonb
language sql stable security invoker set search_path = public as $$
  with f as (
    select * from comments c where c.post_code = p_post and case p_filter
      when 'flagged' then c.verdict in ('hide', 'review')
      when 'negative' then c.sentiment = 'negative'
      when 'decided' then c.decision is not null
      when 'unscored' then c.scored_at is null
      else true end)
  select jsonb_build_object('total', (select count(*) from f), 'rows', coalesce((
    select jsonb_agg(to_jsonb(x) - 'text_norm') from (
      select * from f order by case verdict when 'hide' then 0 when 'review' then 1 else 2 end,
             created_at desc nulls last limit p_limit offset p_offset) x), '[]'::jsonb))
$$;

-- fast author_stats (was 0006, lateral per-author lookups from 0007).
create or replace function public.author_stats(p_limit int default 200) returns jsonb
language sql stable security invoker set search_path = public as $$
  with shortlist as (
    select author,
           count(*) filter (where decision = 'hide') as decided_hide,
           count(*) filter (where verdict = 'hide')  as judged_hide,
           count(*) filter (where sentiment = 'negative') as negative
    from comments
    where author is not null
      and (sentiment = 'negative' or verdict = 'hide' or decision = 'hide')
    group by author
    having count(*) filter (where verdict = 'hide' or decision = 'hide') > 0
        or count(*) filter (where sentiment = 'negative') > 4
    order by 2 desc, 3 desc, 4 desc
    limit p_limit),
  totals as (           -- per-author index lookups, never a full scan
    select s.author, t.n_comments, t.n_posts, t.last_comment_at
    from shortlist s
    cross join lateral (select count(*) as n_comments, count(distinct c.post_code) as n_posts,
                               max(c.created_at) as last_comment_at
                        from comments c where c.author = s.author) t)
  select coalesce(jsonb_agg(jsonb_build_object(
           'author', s.author, 'n_comments', t.n_comments, 'n_posts', t.n_posts,
           'negative', s.negative, 'judged_hide', s.judged_hide, 'decided_hide', s.decided_hide,
           'last_comment_at', t.last_comment_at)
         order by s.decided_hide desc, s.judged_hide desc, s.negative desc), '[]'::jsonb)
  from shortlist s join totals t on t.author = s.author
$$;

create index if not exists comments_negative_idx on public.comments(author)
  where sentiment = 'negative' or verdict = 'hide' or decision = 'hide';



-- ---------------------------------------------------------------------------
-- row-level security
-- ---------------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array['accounts', 'posts', 'post_snapshots', 'uploads', 'comments',
    'judge_labels', 'judge_calls', 'jobs', 'review_sheets', 'notifications', 'members', 'models',
    'prompts', 'lexicon', 'settings', 'saved_replies', 'comment_events']
  loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
  -- members read the shared data
  foreach t in array array['accounts', 'posts', 'post_snapshots', 'comments', 'judge_labels',
    'review_sheets', 'notifications', 'models', 'prompts', 'lexicon', 'settings',
    'saved_replies', 'comment_events']
  loop
    execute format('create policy members_read on public.%I for select to authenticated using (public.is_member())', t);
  end loop;
  -- admins read the operational ledgers and manage configuration
  foreach t in array array['uploads', 'jobs', 'judge_calls']
  loop
    execute format('create policy admin_read on public.%I for select to authenticated using (public.is_admin())', t);
  end loop;
  foreach t in array array['models', 'prompts', 'lexicon', 'settings']
  loop
    execute format('create policy admin_write on public.%I for all to authenticated using (public.is_admin()) with check (public.is_admin())', t);
  end loop;
end $$;

-- reviewers may change only the review columns of a comment; who/when are stamped by trigger
revoke update on public.comments from authenticated;
grant update (decision, decision_note, ig_action, opened_at, assignee, status) on public.comments to authenticated;
create policy members_review on public.comments for update to authenticated
  using (public.is_member()) with check (public.is_member());

revoke update on public.review_sheets from authenticated;
grant update (assigned_to, resolved_by, resolved_at) on public.review_sheets to authenticated;
create policy members_assign on public.review_sheets for update to authenticated
  using (public.is_member()) with check (public.is_member());

create policy members_self_read on public.members for select to authenticated
  using (public.is_admin() or email = public.jwt_email());
create policy members_admin_write on public.members for all to authenticated
  using (public.is_admin()) with check (public.is_admin());
revoke update on public.members from authenticated;
grant update (role, full_name, active, notifications_seen_at) on public.members to authenticated;
create policy members_seen on public.members for update to authenticated
  using (email = public.jwt_email() or public.is_admin())
  with check (email = public.jwt_email() or public.is_admin());

-- operator functions: not callable anonymously
do $$
declare f text;
begin
  foreach f in array array['preview_comments(jsonb)', 'ingest_begin(text,text,text,jsonb)',
    'ingest_comments_chunk(bigint,jsonb,text)', 'ingest_metrics_chunk(bigint,jsonb,timestamptz)',
    'ingest_finish(bigint,boolean)', 'claim_posts(text[],integer,text)',
    'claim_comments(text,integer)', 'submit_scores(text,jsonb,text)', 'release_claim(text)',
    'claim_export(text)', 'pending_scoring(text)', 'apply_scores(jsonb,text,text)',
    'refresh_post_counts(text[])', 'ensure_account(text)', 'sheet_counts(bigint)',
    'sheet_mark_ready(bigint)', 'sheet_advance(bigint)', 'sheets_advance_for_post(text)',
    'create_judge_run(text,bigint,text,text,integer,text,boolean)', 'activate_prompt(text)',
    'set_default_model(text)']
  loop
    execute format('revoke all on function public.%s from public, anon', f);
    execute format('grant execute on function public.%s to authenticated, service_role', f);
  end loop;
end $$;
grant execute on function public.sheet_comments(bigint) to authenticated;
grant execute on function public.post_comments(text, text, int, int) to authenticated;
grant execute on function public.author_stats(int) to authenticated;

alter publication supabase_realtime add table public.notifications, public.review_sheets,
  public.jobs, public.posts, public.comment_events;

-- ---------------------------------------------------------------------------
-- squashed appendices (were separate migrations; kept verbatim below)
-- ---------------------------------------------------------------------------
-- Post grid read: posts + account + change since the previous analytics snapshot
-- ("+100 likes"). One jsonb value so it isn't capped at 1000 rows.
create or replace function public.post_grid(p_account text default null, p_sort text default 'posted',
                                            p_limit int default 400, p_code text default null)
returns jsonb
language sql stable security invoker set search_path = public as $$
  select coalesce(jsonb_agg(to_jsonb(x) order by
           case when p_sort = 'updated' then x.updated_at else x.posted_at end desc nulls last), '[]'::jsonb)
  from (
    select p.code, p.status, a.username, a.avatar_path, p.caption, p.posted_at, p.thumbnail_path,
           p.like_count, p.comment_count, p.play_count, p.engagement_rate, p.metrics_updated_at,
           p.n_comments, p.n_scored, p.n_comments - p.n_scored as n_unscored, p.n_negative,
           p.n_flagged, p.last_judged_at, p.claimed_by, p.claim_expires_at, p.updated_at,
           p.like_count - s.like_count as like_delta, p.comment_count - s.comment_count as comment_delta,
           p.play_count - s.play_count as play_delta, s.captured_at as prev_captured_at
    from posts p
    left join accounts a on a.id = p.account_id
    left join lateral (select * from post_snapshots ps where ps.post_code = p.code
                         and ps.captured_at < p.metrics_updated_at
                       order by ps.captured_at desc limit 1) s on true
    where (p_account is null or a.username = p_account) and (p_code is null or p.code = p_code)
    order by case when p_sort = 'updated' then p.updated_at else p.posted_at end desc nulls last
    limit p_limit) x
$$;
grant execute on function public.post_grid(text, text, int, text) to authenticated;

-- Workers heartbeat every 30 s into settings `worker:<id>` = '<device>;<loaded LM Studio models, comma-separated>'.
-- The dashboard shows who is live; judge routing prefers a live worker that has a local model loaded.
create or replace function public.workers_live(p_max_age_s int default 90) returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(jsonb_build_object(
           'worker', substr(key, 8), 'device', split_part(value, ';', 1),
           'models', nullif(split_part(value, ';', 2), ''), 'seen_at', updated_at) order by key), '[]'::jsonb)
  from settings
  where key like 'worker:%' and updated_at > now() - make_interval(secs => p_max_age_s)
    and (is_member() or coalesce(auth.role(), '') = 'service_role' or session_user in ('postgres', 'supabase_admin'))
$$;

-- Admin's local database only: how it syncs with the cloud (main) database.
--   manual  push / pull when the admin says (like a git commit)
--   auto    the local worker pulls then pushes every few minutes
--   never   sandbox: new models, fine-tuning; nothing leaves or arrives
-- Stored under `sync:` so sync itself never copies it.
create or replace function public.sync_mode() returns text
language sql stable security definer set search_path = public as $$
  select coalesce((select value from settings where key = 'sync:mode'), 'manual')
$$;

create or replace function public.set_sync_mode(p_mode text) returns void
language plpgsql security definer set search_path = public as $$
begin
  perform assert_operator();
  if p_mode not in ('manual', 'auto', 'never') then raise exception 'sync mode must be manual, auto or never'; end if;
  insert into settings (key, value) values ('sync:mode', p_mode)
  on conflict (key) do update set value = excluded.value, updated_at = now();
end $$;

-- who/when come from the database, never the client (same rule as decisions)
create or replace function public._stamp_opened() returns trigger
language plpgsql as $$
begin
  new.opened_at := now();
  new.opened_by := coalesce(nullif(public.jwt_email(), ''), 'system');
  return new;
end $$;
drop trigger if exists comments_stamp_opened on public.comments;
create trigger comments_stamp_opened before update of opened_at on public.comments
  for each row when (new.opened_at is not null and old.opened_at is null)
  execute function public._stamp_opened();


insert into public.settings (key, value) values
  ('tiebreak_model', ''),
  ('tiebreak_below_conf', '0.7')
on conflict (key) do nothing;
