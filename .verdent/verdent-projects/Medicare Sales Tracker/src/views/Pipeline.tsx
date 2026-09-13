import { useState } from 'react';
import type { Policy, Status } from '../lib/types';
import type { TrackerStore } from '../lib/store';
import { PIPELINE, PRODUCT_LINES, money } from '../lib/constants';
import { LineBadge } from '../components/ui';

const colColors: Record<Status, string> = {
  lead: 'border-slate-300',
  quote: 'border-sky-300',
  application: 'border-indigo-300',
  pending: 'border-orange-300',
  effective: 'border-emerald-300',
  declined: 'border-rose-300',
  cancelled: 'border-rose-200',
};

export default function Pipeline({ store }: { store: TrackerStore }) {
  const [lineFilter, setLineFilter] = useState<string>('ALL');
  const [dragId, setDragId] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState<Status | null>(null);

  const filtered = store.policies.filter(
    (p) => PIPELINE.includes(p.status) && (lineFilter === 'ALL' || p.product_line === lineFilter),
  );
  const clientName = (id: string) => {
    const c = store.clients.find((x) => x.id === id);
    return c ? `${c.first_name} ${c.last_name}` : 'Unknown';
  };
  const carrierName = (id: string | null) => store.carriers.find((c) => c.id === id)?.name ?? '';

  const move = async (p: Policy, dir: -1 | 1) => {
    const idx = PIPELINE.indexOf(p.status);
    const next = PIPELINE[idx + dir];
    if (next) await store.updatePolicy(p.id, { status: next });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => setLineFilter('ALL')}
          className={`rounded-full px-3 py-1.5 text-xs font-semibold ${
            lineFilter === 'ALL' ? 'bg-slate-800 text-white' : 'bg-white text-slate-600 border border-slate-200'
          }`}
        >
          All
        </button>
        {PRODUCT_LINES.map((pl) => (
          <button
            key={pl.id}
            onClick={() => setLineFilter(pl.id)}
            className={`rounded-full px-3 py-1.5 text-xs font-semibold ${
              lineFilter === pl.id ? 'bg-slate-800 text-white' : 'bg-white text-slate-600 border border-slate-200'
            }`}
          >
            {pl.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {PIPELINE.map((status, colIdx) => {
          const cards = filtered.filter((p) => p.status === status);
          return (
            <div
              key={status}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(status);
              }}
              onDragLeave={() => setDragOver((s) => (s === status ? null : s))}
              onDrop={() => {
                if (dragId) {
                  const p = store.policies.find((x) => x.id === dragId);
                  if (p && p.status !== status) void store.updatePolicy(p.id, { status });
                }
                setDragId(null);
                setDragOver(null);
              }}
              className={`min-h-40 rounded-xl border-t-4 bg-slate-50 p-3 transition ${
                colColors[status]
              } ${dragOver === status ? 'ring-2 ring-indigo-400' : ''}`}
            >
              <div className="mb-3 flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-wide text-slate-500">{status}</span>
                <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-bold text-slate-500">
                  {cards.length}
                </span>
              </div>
              <div className="space-y-2">
                {cards.map((p) => (
                  <div
                    key={p.id}
                    draggable
                    onDragStart={() => setDragId(p.id)}
                    onDragEnd={() => setDragId(null)}
                    className={`cursor-grab rounded-lg border border-slate-200 bg-white p-2.5 shadow-sm active:cursor-grabbing ${
                      dragId === p.id ? 'opacity-40' : ''
                    }`}
                  >
                    <p className="truncate text-sm font-semibold text-slate-700">{clientName(p.client_id)}</p>
                    <p className="truncate text-xs text-slate-400">
                      {carrierName(p.carrier_id)}
                      {p.plan_name ? ` · ${p.plan_name}` : ''}
                    </p>
                    <div className="mt-1.5 flex items-center justify-between gap-1">
                      <LineBadge line={p.product_line} short />
                      {p.monthly_premium > 0 && (
                        <span className="text-[11px] font-medium text-slate-500">{money(Number(p.monthly_premium))}/mo</span>
                      )}
                    </div>
                    <div className="mt-2 flex justify-between">
                      <button
                        onClick={() => void move(p, -1)}
                        disabled={colIdx === 0}
                        className="rounded px-2 py-0.5 text-xs text-slate-400 hover:bg-slate-100 disabled:opacity-0"
                        aria-label="Move back"
                      >
                        ◀
                      </button>
                      <button
                        onClick={() => void move(p, 1)}
                        disabled={colIdx === PIPELINE.length - 1}
                        className="rounded px-2 py-0.5 text-xs text-slate-400 hover:bg-slate-100 disabled:opacity-0"
                        aria-label="Advance"
                      >
                        ▶
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <p className="text-xs text-slate-400">
        Drag cards between columns, or use ◀ ▶ on mobile. Declined and cancelled policies live under the Policies tab.
      </p>
    </div>
  );
}
