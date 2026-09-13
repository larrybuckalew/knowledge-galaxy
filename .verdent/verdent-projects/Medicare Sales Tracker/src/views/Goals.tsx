import { useState } from 'react';
import type { TrackerStore } from '../lib/store';
import { currentMonth, monthLabel, PRODUCT_LINES } from '../lib/constants';

export default function Goals({ store }: { store: TrackerStore }) {
  const [month, setMonth] = useState(currentMonth());
  const year = month.slice(0, 4);

  const written = (line: string) =>
    store.policies.filter(
      (p) =>
        p.product_line === line &&
        p.app_date?.startsWith(month) &&
        !['lead', 'quote'].includes(p.status),
    ).length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-slate-800">Monthly goals</h2>
          <p className="text-sm text-slate-400">Set app targets per product line — progress counts apps written in the month.</p>
        </div>
        <input
          type="month"
          value={month}
          min={`${Number(year) - 2}-01`}
          max={`${Number(year) + 2}-12`}
          onChange={(e) => setMonth(e.target.value)}
          className="w-auto"
        />
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <h3 className="mb-4 font-bold text-slate-800">{monthLabel(month)}</h3>
        <div className="space-y-5">
          {PRODUCT_LINES.map((pl) => {
            const goal = store.goals.find((g) => g.month === month && g.product_line === pl.id);
            const target = goal?.target_apps ?? 0;
            const actual = written(pl.id);
            const pct = target > 0 ? Math.min(100, Math.round((actual / target) * 100)) : 0;
            return (
              <div key={pl.id} className="grid grid-cols-1 items-center gap-3 sm:grid-cols-[1fr_auto_1fr]">
                <div className="flex items-center gap-2">
                  <span className={`h-2.5 w-2.5 rounded-full ${pl.bar}`} />
                  <span className="font-medium text-slate-700">{pl.label}</span>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min="0"
                    value={target || ''}
                    placeholder="Set target"
                    onChange={(e) =>
                      void store.setGoal(month, pl.id, Math.max(0, Number(e.target.value) || 0))
                    }
                    className="w-28"
                  />
                  <span className="whitespace-nowrap text-sm text-slate-400">
                    apps · <span className="font-semibold text-slate-600">{actual}</span> written
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                    <div className={`h-full rounded-full ${pl.bar}`} style={{ width: `${pct}%` }} />
                  </div>
                  <span className="w-10 text-right text-sm font-semibold text-slate-600">{target > 0 ? `${pct}%` : '—'}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
