import { useMemo, useState } from 'react';
import type { Client } from '../lib/types';
import type { TrackerStore } from '../lib/store';
import { fullName } from '../lib/constants';
import { btnDanger, btnGhost, btnPrimary, EmptyState, LineBadge, Modal, StatusBadge } from '../components/ui';
import ClientForm, { emptyClient } from '../components/ClientForm';
import PolicyForm, { emptyDraft } from '../components/PolicyForm';

export default function Clients({ store }: { store: TrackerStore }) {
  const [query, setQuery] = useState('');
  const [editClient, setEditClient] = useState<(Omit<Client, 'id'> & { id?: string }) | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [policyDraft, setPolicyDraft] = useState<(ReturnType<typeof emptyDraft> & { id?: string }) | null>(null);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    return store.clients.filter(
      (c) =>
        !q ||
        `${c.first_name} ${c.last_name}`.toLowerCase().includes(q) ||
        (c.county ?? '').toLowerCase().includes(q) ||
        (c.phone ?? '').includes(q),
    );
  }, [store.clients, query]);

  const detail = store.clients.find((c) => c.id === detailId) ?? null;
  const detailPolicies = store.policies.filter((p) => p.client_id === detailId);
  const carrierName = (id: string | null) => store.carriers.find((c) => c.id === id)?.name ?? '';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name, county, or phone…"
          className="max-w-sm"
        />
        <button className={btnPrimary} onClick={() => setEditClient(emptyClient())}>
          + Add client
        </button>
      </div>

      {results.length === 0 ? (
        <EmptyState
          title={store.clients.length === 0 ? 'No clients yet' : 'No matches'}
          hint={store.clients.length === 0 ? 'Add your first client to start tracking policies.' : undefined}
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <ul className="divide-y divide-slate-100">
            {results.map((c) => {
              const count = store.policies.filter((p) => p.client_id === c.id).length;
              return (
                <li key={c.id}>
                  <button
                    onClick={() => setDetailId(c.id)}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-50"
                  >
                    <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-indigo-100 text-sm font-bold text-indigo-700">
                      {(c.first_name[0] ?? '?') + (c.last_name[0] ?? '')}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-semibold text-slate-700">{fullName(c)}</p>
                      <p className="truncate text-xs text-slate-400">
                        {[c.phone, c.county].filter(Boolean).join(' · ') || 'No contact info'}
                      </p>
                    </div>
                    <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-500">
                      {count} {count === 1 ? 'policy' : 'policies'}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {editClient && (
        <Modal title={editClient.id ? 'Edit client' : 'Add client'} onClose={() => setEditClient(null)}>
          <ClientForm store={store} initial={editClient} onDone={() => setEditClient(null)} />
        </Modal>
      )}

      {policyDraft && (
        <Modal title={policyDraft.id ? 'Edit policy' : 'Add policy'} onClose={() => setPolicyDraft(null)} wide>
          <PolicyForm store={store} initial={policyDraft} onDone={() => setPolicyDraft(null)} />
        </Modal>
      )}

      {detail && (
        <Modal title={fullName(detail)} onClose={() => setDetailId(null)} wide>
          <div className="space-y-5">
            <div className="grid grid-cols-1 gap-3 rounded-xl bg-slate-50 p-4 text-sm sm:grid-cols-2">
              <p><span className="font-semibold text-slate-500">Phone:</span> {detail.phone || '—'}</p>
              <p><span className="font-semibold text-slate-500">Email:</span> {detail.email || '—'}</p>
              <p><span className="font-semibold text-slate-500">DOB:</span> {detail.dob || '—'}</p>
              <p><span className="font-semibold text-slate-500">County:</span> {detail.county || '—'}</p>
              {detail.notes && <p className="sm:col-span-2"><span className="font-semibold text-slate-500">Notes:</span> {detail.notes}</p>}
            </div>

            <div>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="font-bold text-slate-700">Policies</h3>
                <button
                  className={`${btnPrimary} !py-1.5 !text-xs`}
                  onClick={() => {
                    setPolicyDraft(emptyDraft(detail.id));
                    setDetailId(null);
                  }}
                >
                  + Add policy
                </button>
              </div>
              {detailPolicies.length === 0 ? (
                <p className="text-sm text-slate-400">No policies for this client yet.</p>
              ) : (
                <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200">
                  {detailPolicies.map((p) => (
                    <li key={p.id} className="flex flex-wrap items-center gap-2 px-3 py-2.5 text-sm">
                      <LineBadge line={p.product_line} short />
                      <span className="text-slate-600">{carrierName(p.carrier_id) || 'No carrier'}</span>
                      {p.plan_name && <span className="truncate text-slate-400">{p.plan_name}</span>}
                      <span className="ml-auto flex items-center gap-2">
                        <span className="text-xs text-slate-400">
                          {p.effective_date ? `Eff ${p.effective_date}` : p.renewal_date ? `Renew ${p.renewal_date}` : ''}
                        </span>
                        <StatusBadge status={p.status} />
                        <button
                          className="rounded p-1 text-slate-400 hover:bg-slate-100"
                          onClick={() => {
                            setPolicyDraft({ ...emptyDraft(), ...p, notes: p.notes ?? '' } as typeof policyDraft);
                            setDetailId(null);
                          }}
                          aria-label="Edit policy"
                        >
                          ✎
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="flex justify-between border-t border-slate-100 pt-3">
              <button
                className={`${btnDanger}`}
                onClick={async () => {
                  if (confirm(`Delete ${fullName(detail)} and all their policies? This cannot be undone.`)) {
                    await store.deleteClient(detail.id);
                    setDetailId(null);
                  }
                }}
              >
                Delete client
              </button>
              <button
                className={btnGhost}
                onClick={() => {
                  setEditClient({ ...emptyClient(), ...detail });
                  setDetailId(null);
                }}
              >
                Edit details
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
