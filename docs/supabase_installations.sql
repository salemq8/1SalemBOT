-- 1SalemBOT v1.8 Supabase telemetry table setup
--
-- Run this in the Supabase SQL editor for the project that backs:
-- https://yvuqeulhbrjjpolcnvso.supabase.co
--
-- The app uses only the publishable key. It does not include a service role
-- key, Twitch tokens, OpenAI keys, passwords, chat logs, or private runtime data.

create table if not exists public.installations (
    install_id text primary key,
    channel_name text,
    bot_name text,
    app_version text,
    os_version text,
    first_seen timestamptz,
    last_seen timestamptz
);

-- Required for duplicate-safe upsert through:
-- /rest/v1/installations?on_conflict=install_id
-- If this block fails, remove duplicate install_id rows first, then run again.
do $$
declare
    install_id_attnum smallint;
begin
    select attnum
    into install_id_attnum
    from pg_attribute
    where attrelid = 'public.installations'::regclass
      and attname = 'install_id'
      and not attisdropped;

    if not exists (
        select 1
        from pg_constraint
        where conrelid = 'public.installations'::regclass
          and contype in ('p', 'u')
          and conkey = array[install_id_attnum]
    ) then
        alter table public.installations
            add constraint installations_install_id_unique unique (install_id);
    end if;
end $$;

-- Required table privileges for the publishable/anon key.
grant insert, update on public.installations to anon;

-- If Row Level Security is enabled, enable only the app's insert/update flow.
alter table public.installations enable row level security;

drop policy if exists "1salembot_installations_insert" on public.installations;
create policy "1salembot_installations_insert"
on public.installations
for insert
to anon
with check (install_id is not null);

drop policy if exists "1salembot_installations_update" on public.installations;
create policy "1salembot_installations_update"
on public.installations
for update
to anon
using (install_id is not null)
with check (install_id is not null);

-- Some Supabase/PostgREST configurations require SELECT on the conflict/filter
-- column for upsert/update filtering. Grant the narrowest useful column access.
grant select (install_id) on public.installations to anon;

drop policy if exists "1salembot_installations_select_id" on public.installations;
create policy "1salembot_installations_select_id"
on public.installations
for select
to anon
using (install_id is not null);
