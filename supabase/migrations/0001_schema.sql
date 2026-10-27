-- persocial schema (squashed WP7 from 13 migrations: 0001 = tables/indexes).
--
--
-- One wide row per comment carries its whole life: upload → NLP scores (+ who/when/which
-- machine) → judge verdict (+ model/prompt/when) → reviewer decision (+ who/when) → the
-- manual Instagram action (+ who/when). Cloud is the source of truth; GPU workers and Colab
-- write into it directly.

create extension if not exists pgcrypto;

create or replace function public.touch_updated_at() returns trigger
language plpgsql as $$ begin new.updated_at := now(); return new; end $$;

-- 1 -------------------------------------------------------------------------
create table public.accounts (
  id               bigint generated always as identity primary key,
  username         text not null unique,
  display_name     text,
  avatar_path      text,
  follower_count   integer,
  following_count  integer,
  media_count      integer,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

-- 2 -------------------------------------------------------------------------
create table public.posts (
  code                text primary key,               -- Instagram shortcode
  account_id          bigint references public.accounts(id),
  status              text not null default 'registered'
                        check (status in ('pending', 'registered')),
  -- pending = known only from a comments upload; registered = seen in an analytics export
  caption             text,
  posted_at           timestamptz,
  media_type          text,
  video_url           text,
  thumbnail_path      text,                           -- storage path in bucket "media"
  -- latest analytics
  like_count          integer,
  comment_count       integer,
  play_count          integer,
  engagement_rate     numeric,
  metrics_updated_at  timestamptz,
  -- counts over stored comments (refresh_post_counts)
  n_comments          integer not null default 0,
  n_scored            integer not null default 0,
  n_negative          integer not null default 0,
  n_flagged           integer not null default 0,
  last_judged_at      timestamptz,
  -- scoring lease: one machine scores a post at a time (Colab / any GPU)
  claimed_by          text,
  claimed_at          timestamptz,
  claim_expires_at    timestamptz,
  -- vendor crawl watermark: stop paging at the first already-known comment
  crawl_newest_ig_id  text,
  crawl_newest_at     timestamptz,
  crawled_at          timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create index posts_account_idx on public.posts(account_id, posted_at desc);
create index posts_unscored_idx on public.posts(posted_at desc) where n_comments > n_scored;

-- 3 -------------------------------------------------------------------------
create table public.post_snapshots (
  post_code        text not null references public.posts(code) on delete cascade,
  captured_at      timestamptz not null,
  like_count       integer,
  comment_count    integer,
  play_count       integer,
  engagement_rate  numeric,
  follower_count   integer,
  upload_id        bigint,
  primary key (post_code, captured_at)
);

-- 4 -------------------------------------------------------------------------
create table public.uploads (
  id                      bigint generated always as identity primary key,
  source                  text not null check (source in
                            ('comments_csv', 'apify_comments', 'generic_comments_csv', 'post_metrics_csv')),
  filename                text not null,
  sha256                  text not null unique,       -- same file twice = no-op
  post_code               text,
  account_hint            text,
  reported_comment_count  integer,
  captured_at             timestamptz,                -- analytics snapshot time
  rows_total              integer not null default 0,
  rows_inserted           integer not null default 0,
  rows_existing           integer not null default 0,
  rows_scored             integer not null default 0,
  rows_rejected           integer not null default 0,
  reject_note             text,
  status                  text not null default 'running'
                            check (status in ('running', 'done', 'failed')),
  error                   text,
  uploaded_by             text,
  created_at              timestamptz not null default now(),
  finished_at             timestamptz
);

-- 5 -------------------------------------------------------------------------
create table public.comments (
  ig_id             text primary key,                 -- Instagram comment id: THE dedup key
  post_code         text not null references public.posts(code) on delete cascade,
  parent_ig_id      text,
  author_id         text,
  author            text,
  text              text not null default '',
  text_norm         text not null default '',          -- normalised: judge dedup key
  script            text not null default 'other'
                      check (script in ('arabic', 'latin', 'mixed', 'emoji', 'other')),
  created_at        timestamptz,
  like_count        integer,
  repeat_commenter  boolean not null default false,    -- >3 comments by the author on the post
  first_upload_id   bigint,                            -- the upload that brought it in
  last_upload_id    bigint,
  first_seen_at     timestamptz not null default now(),
  last_seen_at      timestamptz not null default now(),
  -- NLP (sentiment + emotion)
  sentiment         text check (sentiment in ('negative', 'neutral', 'positive')),
  sent_negative     real,
  sent_neutral      real,
  sent_positive     real,
  emotion           text,                              -- null = nothing above threshold
  emotion_score     real,
  nlp_model         text,
  scored_at         timestamptz,
  scored_by         text,                              -- e.g. colab:Tesla T4, local:cuda:RTX 4080
  -- LLM judge (latest verdict that counts for review)
  judge_selection   text check (judge_selection in ('candidate', 'audit')),
  judge_signals     text,                              -- why it was selected, comma-separated
  verdict           text check (verdict in ('hide', 'keep', 'review')),
  category          text,
  severity          smallint check (severity between 0 and 3),
  confidence        real,
  welfare           boolean not null default false,
  judge_reason      text,
  judge_model       text,
  judge_prompt      text,
  judged_at         timestamptz,
  judge_job_id      bigint,
  judged_as_copy_of text,                              -- ig_id whose identical text was judged
  -- reviewer
  decision          text check (decision in ('hide', 'keep', 'escalate')),
  decision_note     text,
  decided_by        text,
  decided_at        timestamptz,
  -- team board: reviewer workflow state per comment (WP7)
  assignee          uuid,
  status            text not null default 'new'
                      check (status in ('new', 'assigned', 'in_review', 'done')),
  -- what was actually done on Instagram (by hand — no Graph API)
  ig_action         text check (ig_action in ('removed_on_ig', 'hidden_on_ig', 'unhidden_on_ig', 'reported',
                                              'blocked_author', 'replied')),
  ig_action_by      text,
  ig_action_at      timestamptz,
  opened_at         timestamptz,                       -- first open on Instagram (review flow)
  opened_by         text,
  updated_at        timestamptz not null default now()
);
create index comments_post_idx on public.comments(post_code, created_at desc);
create index comments_norm_md5_idx on public.comments (md5(text_norm));
create index comments_negative_idx on public.comments(author)
  where sentiment = 'negative' or verdict = 'hide' or decision = 'hide';
create index comments_board_idx on public.comments(status, created_at desc)
  where verdict in ('hide', 'review') and decision is null;
create index comments_upload_idx on public.comments(first_upload_id, post_code);
create index comments_unscored_idx on public.comments(post_code) where scored_at is null;
create index comments_flagged_idx on public.comments(post_code) where verdict in ('hide', 'review');
create index comments_author_idx on public.comments(author);

-- 6 -------------------------------------------------------------------------
-- Every model's verdict per comment (production judge + extra teacher models). The
-- fine-tuning label table: agreement across models = trust.
create table public.judge_labels (
  ig_id       text not null references public.comments(ig_id) on delete cascade,
  model       text not null,
  prompt      text not null,
  verdict     text not null check (verdict in ('hide', 'keep', 'review')),
  category    text,
  severity    smallint,
  confidence  real,
  reason      text,
  job_id      bigint,
  call_id     bigint,
  labeled_at  timestamptz not null default now(),
  primary key (ig_id, model, prompt)
);

-- 7 -------------------------------------------------------------------------
-- Raw model calls, kept whole: the distillation corpus.
create table public.judge_calls (
  id             bigint generated always as identity primary key,
  job_id         bigint,
  model          text not null,
  prompt         text not null,
  post_code      text,
  user_payload   text not null,                     -- exactly what was sent as the user turn
  response_text  text,
  parse_status   text not null check (parse_status in ('ok', 'salvaged', 'failed')),
  item_ids       text[] not null,                   -- ig_ids in local-id order "1","2",…
  latency_ms     integer,
  prompt_tokens  integer,
  output_tokens  integer,
  error          text,
  created_at     timestamptz not null default now()
);
create index judge_calls_job_idx on public.judge_calls(job_id);

-- 8 -------------------------------------------------------------------------
create table public.jobs (
  id               bigint generated always as identity primary key,
  kind             text not null check (kind in ('judge', 'score')),
  purpose          text not null default 'review' check (purpose in ('review', 'teacher')),
  status           text not null default 'queued'
                     check (status in ('queued', 'running', 'done', 'failed', 'cancelled')),
  post_code        text,
  sheet_id         bigint,
  model            text,
  prompt           text,
  -- teacher-run scope
  sample_size      integer,
  sample_account   text,
  judge_all        boolean not null default false,
  batch_size       integer,
  no_cache         boolean not null default false,
  seed             integer not null default 1,
  -- results
  n_scope          integer,
  n_candidates     integer,
  n_audit          integer,
  audit_rounds     integer,
  audit_last_rate  real,
  n_tiebreak       integer,
  tiebreak_agree   integer,
  n_autohide       integer,
  n_unique         integer,
  n_done           integer not null default 0,
  n_total          integer,
  worker           text,
  attempts         integer not null default 0,
  error            text,
  created_at       timestamptz not null default now(),
  started_at       timestamptz,
  finished_at      timestamptz,
  updated_at       timestamptz not null default now()
);
create index jobs_queue_idx on public.jobs(created_at) where status = 'queued';

-- 9 -------------------------------------------------------------------------
-- A sheet = the new comments one upload brought for one post
-- (comments where first_upload_id = upload_id and post_code = post_code).
create table public.review_sheets (
  id           bigint generated always as identity primary key,
  post_code    text not null references public.posts(code) on delete cascade,
  upload_id    bigint not null,
  n_new        integer not null,
  n_flagged    integer not null default 0,
  n_decided    integer not null default 0,
  status       text not null default 'scoring'
                 check (status in ('scoring', 'judging', 'ready', 'failed')),
  assigned_to  text,
  resolved_by  text,
  resolved_at  timestamptz,
  created_at   timestamptz not null default now(),
  ready_at     timestamptz,
  updated_at   timestamptz not null default now(),
  unique (upload_id, post_code)
);

-- 10 ------------------------------------------------------------------------
create table public.notifications (
  id          bigint generated always as identity primary key,
  kind        text not null,
  title       text not null,
  body        text,
  link        text,
  post_code   text,
  sheet_id    bigint,
  created_at  timestamptz not null default now()
);

-- 11 ------------------------------------------------------------------------
create table public.members (
  email                  text primary key check (email = lower(email)),
  role                   text not null default 'reviewer' check (role in ('admin', 'reviewer')),
  full_name              text,
  active                 boolean not null default true,
  notifications_seen_at  timestamptz not null default 'epoch',
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);

-- 12 ------------------------------------------------------------------------
create table public.models (
  id                text primary key,
  label             text not null,
  base_url          text not null default '',          -- '' = local LM Studio
  model             text not null,
  api_key_env       text,                              -- env var name on the worker
  batch_size        integer not null default 15,
  disable_thinking  boolean not null default true,
  enabled           boolean not null default true,
  is_default        boolean not null default false,
  updated_at        timestamptz not null default now()
);
create unique index models_one_default on public.models(is_default) where is_default;

-- 13 ------------------------------------------------------------------------
create table public.prompts (
  version        text primary key,
  notes          text,
  system_prompt  text not null,
  is_active      boolean not null default false,
  created_at     timestamptz not null default now()
);
create unique index prompts_one_active on public.prompts(is_active) where is_active;

-- 14 ------------------------------------------------------------------------
create table public.lexicon (
  id          bigint generated always as identity primary key,
  term        text not null,
  kind        text not null check (kind in ('insult', 'public_figure_attack', 'threat', 'sectarian',
                                            'sexual', 'scam', 'promo', 'allow')),
  is_regex    boolean not null default false,
  note        text,
  enabled     boolean not null default true,
  created_at  timestamptz not null default now(),
  unique (term, kind)
);

-- 15 ------------------------------------------------------------------------
-- key/value settings; also worker heartbeats ('worker:<host>' = device, updated_at = seen).
create table public.settings (
  key         text primary key,
  value       text not null,
  updated_at  timestamptz not null default now()
);
insert into public.settings (key, value) values
  ('auto_judge', 'true'), ('claim_ttl_minutes', '120'), ('nlp_model', 'persocial-v1'),
  ('audit_expand_at', '0.2'), ('audit_max_share', '0.5'), ('audit_min', '5');

-- touch triggers
do $$
declare t text;
begin
  foreach t in array array['accounts', 'posts', 'comments', 'jobs', 'review_sheets', 'members',
                           'models', 'settings']
  loop
    execute format('create trigger %I_touch before update on public.%I
                    for each row execute function public.touch_updated_at()', t, t);
  end loop;
end $$;

-- storage bucket for thumbnails/avatars
insert into storage.buckets (id, name, public) values ('media', 'media', true)
on conflict (id) do nothing;

-- 16 ------------------------------------------------------------------------
-- Saved replies (reviewer macros). Neutral template seeds live in 0003_team.sql.
create table public.saved_replies (
  id          bigint generated always as identity primary key,
  title       text not null,
  body        text not null,
  lang        text not null default 'en' check (lang in ('ar', 'en', 'mixed')),
  created_by  text,
  created_at  timestamptz not null default now()
);

-- 17 ------------------------------------------------------------------------
-- Team audit log: every decision/assignee/status/ig_action change on a comment
-- (WP7). Rows are written only by the comments_audit_log trigger; reviewers
-- read them as a timeline in the comment drawer.
create table public.comment_events (
  id          bigint generated always as identity primary key,
  comment_id  text not null references public.comments(ig_id) on delete cascade,
  actor       text not null,
  action      text not null check (action in ('decision', 'assignee', 'status', 'ig_action')),
  from_value  text,
  to_value    text,
  at          timestamptz not null default now()
);
create index comment_events_comment_idx on public.comment_events(comment_id, at desc);
