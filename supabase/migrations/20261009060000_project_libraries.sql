-- A library belongs to one authenticated user. Guest visitors have no table access.
create table public.project_libraries (
    user_id uuid primary key references auth.users(id) on delete cascade,
    projects jsonb not null default '{}'::jsonb,
    revision bigint not null default 1 check (revision > 0),
    updated_at timestamptz not null default now(),
    constraint projects_object check (jsonb_typeof(projects) = 'object'),
    constraint projects_size check (octet_length(projects::text) <= 10000000)
);

alter table public.project_libraries enable row level security;
revoke all on public.project_libraries from anon, authenticated;
grant select on public.project_libraries to authenticated;
grant insert (user_id, projects), update (projects) on public.project_libraries to authenticated;

create policy "Read own library" on public.project_libraries
    for select to authenticated using ((select auth.uid()) = user_id);
create policy "Create own library" on public.project_libraries
    for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "Update own library" on public.project_libraries
    for update to authenticated
    using ((select auth.uid()) = user_id)
    with check ((select auth.uid()) = user_id);

create function public.bump_library_revision()
returns trigger language plpgsql security invoker set search_path = '' as $$
begin
    new.revision = old.revision + 1;
    new.updated_at = now();
    return new;
end;
$$;
revoke all on function public.bump_library_revision() from public, anon, authenticated;
create trigger library_revision before update on public.project_libraries
    for each row execute function public.bump_library_revision();
