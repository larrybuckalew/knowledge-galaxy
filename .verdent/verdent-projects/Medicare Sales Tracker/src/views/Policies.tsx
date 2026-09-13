import { useMemo, useState } from 'react';
import type { Policy, ProductLine, Status } from '../lib/types';
import type { TrackerStore } from '../lib/store';
import { PRODUCT_LINES, STATUS_META, money } from '../lib/constants';
import { btnDanger, btnPrimary, EmptyState, LineBadge, Modal, StatusBadge } from '../components/ui';
import PolicyForm, { emptyDraft } from '../components/PolicyForm';

export default function Policies({ store }: { store: TrackerStore }) {
  const [line, setLine] = useState('ALL');
  const [status, setStatus] = useState('ALL');
  const [carrier, setCarrier] = useState('ALL');
  const [query, setQuery] = useState('');
  const [draft, setDraft] = useState<(ReturnType<typeof emptyDraft> & { id?: string }) | null>(null);

  const clientName = (id: string) => {
    const c = store.clients.find((x) => x.id === id);
    return c ? `${c.first_name} ${c.last_name}` : 'Unknown';
  };
  const carrierName = (id: string | null) => store.carriers.find((c) => c.id === id)?.name ?? '—';

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return store.policies.filter(
      (p) =>
        (line === 'ALL' || p.product_line === line) &&
        (status === 'ALL' || p.status === status) &&
        (carrier === 'ALL' || p.carrier_id === carrier) &&
        (!q || clientName(p.client_id).toLowerCase().includes(q) || (p.plan_name ?? '').toLowerCase().includes(q)),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.policies, store.clients, line, status, carrier, query]);

  const totals = filtered.reduce(
    (acc, p) => ({
      premium: acc.premium + Number(p.monthly_premium),
      commission: acc.commission + Number(p.commission_amount),
    }),
    { premium: 0, commission: 0 },
  );

  const selectCls = 'w-auto';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select className={selectCls} value={line} onChange={(e) => setLine(e.target.value)}>
          <option value="ALL">All product lines</option>
          {PRODUCT_LINES.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
        <select className={selectCls} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="ALL">All statuses</option>
          {Object.entries(STATUS_META).map(([k, v]) => (
            <option key={k} value={k}>
              {v.label}
            </option>
          ))}
        </select>
        <select className={selectCls} value={carrier} onChange={(e) => setCarrier(e.target.value)}>
          <option value="ALL">All carriers</option>
          {store.carriers.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <input
          className="max-w-xs"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search client or plan…"
        />
        <button
          className={`${btnPrimary} ml-auto`}
          onClick={() => setDraft(emptyDraft())}
        >
          + Add policy
        </button>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          title={store.policies.length === 0 ? 'No policies yet' : 'No matches for these filters'}
          hint={store.policies.length === 0 ? 'Add a client first, then log a policy.' : undefined}
        />
      ) : (
        <>
          {/* Mobile cards */}
          <div className="space-y-2 md:hidden">
            {filtered.map((p) => (
              <div key={p.id} className="rounded-xl border border-slate-200 bg-white p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-slate-700">{clientName(p.client_id)}</span>
                  <StatusBadge status={p.status} />
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                  <LineBadge line={p.product_line} short />
                  <span>{carrierName(p.carrier_id)}</span>
                  {p.plan_name && <span className="truncate">{p.plan_name}</span>}
                </div>
                <div className="mt-2 flex items-center justify-between">
                  <span className="text-xs text-slate-500">
                    {money(Number(p.monthly_premium))}/mo · {money(Number(p.commission_amount))} comm
                  </span>
                  <span className="flex gap-1">
                    <button className="rounded p-1 text-slate-400 hover:bg-slate-100" onClick={() => setDraft({ ...emptyDraft(), ...p, notes: p.notes ?? '' } as typeof draft)}>
                      ✎
                    </button>
                    <button
                      className="rounded p-1 text-slate-400 hover:bg-rose-50"
                      onClick={() => confirm('Delete this policy?') && void store.deletePolicy(p.id)}
                    >
                      🗑
                    </button>
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* Desktop table */}
          <div className="hidden overflow-x-auto rounded-xl border border-slate-200 bg-white md:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-400">
                  <th className="px-4 py-3">Client</th>
                  <th className="px-4 py-3">Product</th>
                  <th className="px-4 py-3">Carrier</th>
                  <th className="px-4 py-3">Plan</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Premium</th>
                  <th className="px-4 py-3 text-right">Commission</th>
                  <th className="px-4 py-3">App date</th>
                  <th className="px-4 py-3">Effective</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5 font-semibold text-slate-700">{clientName(p.client_id)}</td>
                    <td className="px-4 py-2.5"><LineBadge line={p.product_line} short /></td>
                    <td className="px-4 py-2.5 text-slate-600">{carrierName(p.carrier_id)}</td>
                    <td className="max-w-40 truncate px-4 py-2.5 text-slate-500">{p.plan_name || '—'}</td>
                    <td className="px-4 py-2.5"><StatusBadge status={p.status} /></td>
                    <td className="px-4 py-2.5 text-right text-slate-600">{money(Number(p.monthly_premium))}</td>
                    <td className="px-4 py-2.5 text-right font-medium text-emerald-700">{money(Number(p.commission_amount))}</td>
                    <td className="px-4 py-2.5 text-slate-500">{p.app_date || '—'}</td>
                    <td className="px-4 py-2.5 text-slate-500">{p.effective_date || '—'}</td>
                    <td className="px-4 py-2.5">
                      <span className="flex gap-1">
                        <button className="rounded p-1 text-slate-400 hover:bg-slate-100" onClick={() => setDraft({ ...emptyDraft(), ...p, notes: p.notes ?? '' } as typeof draft)} aria-label="Edit">
                          ✎
                        </button>
                        <button
                          className="rounded p-1 text-slate-400 hover:bg-rose-50"
                          onClick={() => confirm('Delete this policy?') && void store.deletePolicy(p.id)}
                          aria-label="Delete"
                        >
                          🗑
                        </button>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-slate-200 bg-slate-50 text-sm font-semibold text-slate-600">
                  <td className="px-4 py-2.5" colSpan={5}>
                    {filtered.length} {filtered.length === 1 ? 'policy' : 'policies'}
                  </td>
                  <td className="px-4 py-2.5 text-right">{money(totals.premium)}</td>
                  <td className="px-4 py-2.5 text-right text-emerald-700">{money(totals.commission)}</td>
                  <td colSpan={3}></td>
                </tr>
              </tfoot>
            </table>
          </div>
        </>
      )}

      {draft && (
        <Modal title={draft.id ? 'Edit policy' : 'Add policy'} onClose={() => setDraft(null)} wide>
          <PolicyForm store={store} initial={draft} onDone={() => setDraft(null)} />
        </Modal>
      )}
    </div>
  );
}
