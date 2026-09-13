create table if not exists public.clients (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  first_name text not null default '',
  last_name text not null default '',
  phone text default '',
  email text default '',
  dob date,
  county text default '',
  notes text default '',
  created_at timestamptz not null default now()
);

create table if not exists public.carriers (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  product_lines text[] not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists public.policies (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  client_id uuid not null references public.clients(id) on delete cascade,
  carrier_id uuid references public.carriers(id) on delete set null,
  product_line text not null check (product_line in ('MA','MEDSUPP','PARTD','ANCILLARY')),
  ancillary_type text,
  plan_name text default '',
  status text not null default 'lead' check (status in ('lead','quote','application','pending','effective','declined','cancelled')),
  monthly_premium numeric(10,2) default 0,
  commission_amount numeric(10,2) default 0,
  app_date date,
  effective_date date,
  renewal_date date,
  notes text default '',
  created_at timestamptz not null default now()
);

create table if not exists public.goals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  month text not null,
  product_line text not null check (product_line in ('MA','MEDSUPP','PARTD','ANCILLARY')),
  target_apps int not null default 0,
  created_at timestamptz not null default now(),
  unique (user_id, month, product_line)
);

create index if not exists idx_policies_user on public.policies(user_id);
create index if not exists idx_policies_client on public.policies(client_id);
create index if not exists idx_clients_user on public.clients(user_id);

alter table public.clients enable row level security;
alter table public.carriers enable row level security;
alter table public.policies enable row level security;
alter table public.goals enable row level security;

drop policy if exists clients_owner_all on public.clients;
create policy clients_owner_all on public.clients for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists carriers_owner_all on public.carriers;
create policy carriers_owner_all on public.carriers for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists policies_owner_all on public.policies;
create policy policies_owner_all on public.policies for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists goals_owner_all on public.goals;
create policy goals_owner_all on public.goals for all using (auth.uid() = user_id) with check (auth.uid() = user_id);