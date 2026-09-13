import type { TrackerStore } from '../lib/store';
import { currentMonth, money, productLineMeta, PRODUCT_LINES, statusMeta } from '../lib/constants';
import { EmptyState, LineBadge, StatusBadge } from '../components/ui';

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className={`mb-2 h-1 w-8 rounded-full ${accent}`} />
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-1 text-2xl font-bold text-slate-800">{value}</p>
      {sub && <p className="text-xs text-slate-400">{sub}</p>}
    </div>
  );
}

export default function Dashboard({ store }: { store: TrackerStore }) {
  const { policies, clients, carriers, goals } = store;
  const month = currentMonth();
  const year = month.slice(0, 4);

  const written = policies.filter(
    (p) => p.app_date?.startsWith(month) && !['lead', 'quote'].includes(p.status),
  );
  const commissions = policies
    .filter((p) => p.effective_date?.startsWith(month) && p.status === 'effective')
    .reduce((s, p) => s + Number(p.commission_amount), 0);
  const inFlight = policies.filter((p) => ['quote', 'application', 'pending'].includes(p.status));
  const effectiveYTD = policies.filter(
    (p) => p.effective_date?.startsWith(year) && p.status === 'effective',
  );

  // Last 14 days production chart
  const days: { date: string; label: string; count: number }[] = [];
  for (let i = 13; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const iso = d.toISOString().slice(0, 10);
    const count = written.filter((p) => p.app_date === iso).length;
    days.push({ date: iso, label: d.toLocaleDateString('en-US', { weekday: 'narrow' }), count });
  }
  const maxDay = Math.max(1, ...days.map((d) => d.count));

  // Carrier mix (apps written YTD)
  const writtenYTD = policies.filter(
    (p) => p.app_date?.startsWith(year) && !['lead', 'quote'].includes(p.status),
  );
  const carrierCounts = carriers
    .map((c) => ({ name: c.name, count: writtenYTD.filter((p) => p.carrier_id === c.id).length }))
    .filter((c) => c.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, 6);
  const maxCarrier = Math.max(1, ...carrierCounts.map((c) => c.count));

  const lineCounts = PRODUCT_LINES.map((pl) => ({
    ...pl,
    count: written.filter((p) => p.product_line === pl.id).length,
  }));
  const maxLine = Math.max(1, ...lineCounts.map((l) => l.count));

  const recent = policies.slice(0, 5);
  const clientName = (id: string) => {
    const c = clients.find((x) => x.id === id);
    return c ? `${c.first_name} ${c.last_name}` : 'Unknown';
  };
  const carrierName = (id: string | null) => carriers.find((c) => c.id === id)?.name ?? '—';

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Apps written" value={written.length} sub="this month" accent="bg-indigo-500" />
        <StatCard label="Commissions" value={money(commissions)} sub="effective this month" accent="bg-emerald-500" />
        <StatCard label="In flight" value={inFlight.length} sub="quote → pending" accent="bg-orange-500" />
        <StatCard label="Effective YTD" value={effectiveYTD.length} sub={`${year}`} accent="bg-blue-500" />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-5 lg:col-span-2">
          <h3 className="font-bold text-slate-800">Daily production — last 14 days</h3>
          <div className="mt-4 flex h-40 items-end gap-1.5">
            {days.map((d) => (
              <div key={d.date} className="flex flex-1 flex-col items-center gap-1">
                <div className="flex w-full flex-1 items-end">
                  <div
                    className="w-full rounded-t bg-indigo-500 transition-all"
                    style={{ height: `${(d.count / maxDay) * 100}%`, minHeight: d.count > 0 ? '6px' : '2px', opacity: d.count > 0 ? 1 : 0.15 }}
                    title={`${d.count} app${d.count === 1 ? '' : 's'} on ${d.date}`}
                  />
                </div>
                <span className="text-[10px] text-slate-400">{d.label}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h3 className="font-bold text-slate-800">
            Goal progress <span className="text-sm font-normal text-slate-400">({month})</span>
          </h3>
          <div className="mt-4 space-y-4">
            {PRODUCT_LINES.map((pl) => {
              const goal = goals.find((g) => g.month === month && g.product_line === pl.id);
              const target = goal?.target_apps ?? 0;
              const actual = written.filter((p) => p.product_line === pl.id).length;
              const pct = target > 0 ? Math.min(100, Math.round((actual / target) * 100)) : 0;
              return (
                <div key={pl.id}>
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span className="font-medium text-slate-600">{pl.label}</span>
                    <span className="text-slate-400">
                      {actual} / {target || '—'}
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                    <div className={`h-full rounded-full ${pl.bar}`} style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h3 className="font-bold text-slate-800">Carrier mix — apps written YTD</h3>
          {carrierCounts.length === 0 ? (
            <p className="mt-3 text-sm text-slate-400">No apps written yet this year.</p>
          ) : (
            <div className="mt-4 space-y-2.5">
              {carrierCounts.map((c) => (
                <div key={c.name} className="flex items-center gap-3">
                  <span className="w-32 truncate text-sm text-slate-600">{c.name}</span>
                  <div className="h-4 flex-1 overflow-hidden rounded bg-slate-100">
                    <div className="h-full rounded bg-slate-400" style={{ width: `${(c.count / maxCarrier) * 100}%` }} />
                  </div>
                  <span className="w-6 text-right text-sm font-semibold text-slate-700">{c.count}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h3 className="font-bold text-slate-800">Product mix — this month</h3>
          {written.length === 0 ? (
            <p className="mt-3 text-sm text-slate-400">No apps written yet this month.</p>
          ) : (
            <div className="mt-4 space-y-2.5">
              {lineCounts.map((l) => (
                <div key={l.id} className="flex items-center gap-3">
                  <span className="w-32 truncate text-sm text-slate-600">{l.label}</span>
                  <div className="h-4 flex-1 overflow-hidden rounded bg-slate-100">
                    <div className={`h-full rounded ${l.bar}`} style={{ width: `${(l.count / maxLine) * 100}%` }} />
                  </div>
                  <span className="w-6 text-right text-sm font-semibold text-slate-700">{l.count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <h3 className="font-bold text-slate-800">Recent activity</h3>
        {recent.length === 0 ? (
          <EmptyState title="No policies yet" hint="Add a client, then log your first policy to see it here." />
        ) : (
          <ul className="mt-3 divide-y divide-slate-100">
            {recent.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-2 py-2.5 text-sm">
                <span className="font-semibold text-slate-700">{clientName(p.client_id)}</span>
                <LineBadge line={p.product_line} short />
                <span className="text-slate-400">{carrierName(p.carrier_id)}</span>
                {p.plan_name && <span className="truncate text-slate-400">· {p.plan_name}</span>}
                <span className="ml-auto flex items-center gap-2">
                  <StatusBadge status={p.status} />
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
