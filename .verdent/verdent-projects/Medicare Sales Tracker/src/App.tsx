import { useEffect, useState } from 'react';
import type { Session } from '@supabase/supabase-js';
import { auth, supabase } from './lib/supabase';
import { useTracker } from './lib/store';
import Dashboard from './views/Dashboard';
import Pipeline from './views/Pipeline';
import Clients from './views/Clients';
import Policies from './views/Policies';
import Goals from './views/Goals';
import { btnPrimary } from './components/ui';

type Tab = 'dashboard' | 'pipeline' | 'clients' | 'policies' | 'goals';

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: 'M3 13h4v8H3zM10 3h4v18h-4zM17 9h4v12h-4z' },
  { id: 'pipeline', label: 'Pipeline', icon: 'M4 5h4M4 12h6M4 19h5M14 5h6M15 12h5M16 19h4' },
  { id: 'clients', label: 'Clients', icon: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75' },
  { id: 'policies', label: 'Policies', icon: 'M12 2 3 6v6c0 5 3.8 9.3 9 10 5.2-.7 9-5 9-10V6l-9-4z' },
  { id: 'goals', label: 'Goals', icon: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01' },
];

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [tab, setTab] = useState<Tab>('dashboard');
  const store = useTracker(session?.user?.id ?? null);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setAuthReady(true);
    });
    const { data } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);

  if (!authReady) {
    return <div className="grid min-h-screen place-items-center text-slate-400">Loading…</div>;
  }

  if (!session) {
    return (
      <div className="grid min-h-screen place-items-center bg-slate-100 px-6">
        <div className="w-full max-w-sm rounded-2xl bg-white p-8 text-center shadow-lg">
          <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-xl bg-indigo-600 text-xl font-black text-white">
            M
          </div>
          <h1 className="text-xl font-bold text-slate-800">Medicare Sales Tracker</h1>
          <p className="mt-2 text-sm text-slate-500">
            Track your Advantage, Supplement, Part D, and Ancillary production in one place.
          </p>
          <button className={`${btnPrimary} mt-6 w-full`} onClick={() => auth.openSignInModal()}>
            Sign in
          </button>
        </div>
      </div>
    );
  }

  const tabProps = { store };
  const icons: Record<Tab, string> = Object.fromEntries(TABS.map((t) => [t.id, t.icon])) as Record<Tab, string>;

  return (
    <div className="min-h-screen bg-slate-100 pb-20 md:pb-0">
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="grid h-8 w-8 place-items-center rounded-lg bg-indigo-600 text-sm font-black text-white">
              M
            </div>
            <span className="hidden font-bold text-slate-800 sm:block">Medicare Sales Tracker</span>
          </div>
          <nav className="hidden gap-1 md:flex">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`rounded-lg px-3.5 py-2 text-sm font-semibold transition ${
                  tab === t.id ? 'bg-indigo-50 text-indigo-700' : 'text-slate-500 hover:bg-slate-100'
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
          <button
            onClick={() => void supabase.auth.signOut()}
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-slate-500 hover:bg-slate-100"
          >
            Sign out
          </button>
        </div>
      </header>

      {store.error && (
        <div className="mx-auto mt-3 max-w-7xl px-4">
          <div className="rounded-lg bg-rose-50 px-4 py-2 text-sm text-rose-700">{store.error}</div>
        </div>
      )}

      <main className="mx-auto max-w-7xl px-4 py-6">
        {store.loading && store.clients.length === 0 ? (
          <div className="grid place-items-center py-24 text-slate-400">Loading your data…</div>
        ) : (
          <>
            {tab === 'dashboard' && <Dashboard {...tabProps} />}
            {tab === 'pipeline' && <Pipeline {...tabProps} />}
            {tab === 'clients' && <Clients {...tabProps} />}
            {tab === 'policies' && <Policies {...tabProps} />}
            {tab === 'goals' && <Goals {...tabProps} />}
          </>
        )}
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-slate-200 bg-white md:hidden">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex flex-col items-center gap-0.5 py-2 text-[10px] font-semibold ${
              tab === t.id ? 'text-indigo-600' : 'text-slate-400'
            }`}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d={icons[t.id]} />
            </svg>
            {t.label}
          </button>
        ))}
      </nav>
    </div>
  );
}
