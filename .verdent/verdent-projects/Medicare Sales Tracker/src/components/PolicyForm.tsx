import { useState, type FormEvent } from 'react';
import type { ProductLine, Status } from '../lib/types';
import { ANCILLARY_TYPES, PRODUCT_LINES, STATUS_META, todayISO } from '../lib/constants';
import { btnGhost, btnPrimary, Field } from './ui';
import type { TrackerStore } from '../lib/store';

export interface PolicyDraft {
  client_id: string;
  carrier_id: string | null;
  product_line: ProductLine;
  ancillary_type: string | null;
  plan_name: string;
  status: Status;
  monthly_premium: number;
  commission_amount: number;
  app_date: string | null;
  effective_date: string | null;
  renewal_date: string | null;
  notes: string;
}

export function emptyDraft(clientId = ''): PolicyDraft {
  return {
    client_id: clientId,
    carrier_id: null,
    product_line: 'MA',
    ancillary_type: null,
    plan_name: '',
    status: 'lead',
    monthly_premium: 0,
    commission_amount: 0,
    app_date: todayISO(),
    effective_date: null,
    renewal_date: null,
    notes: '',
  };
}

export default function PolicyForm({
  store,
  initial,
  onDone,
}: {
  store: TrackerStore;
  initial: PolicyDraft & { id?: string };
  onDone: () => void;
}) {
  const [d, setD] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [newCarrier, setNewCarrier] = useState('');
  const set = <K extends keyof PolicyDraft>(k: K, v: PolicyDraft[K]) => setD((p) => ({ ...p, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!d.client_id) return;
    setSaving(true);
    const payload = { ...d };
    if (payload.product_line !== 'ANCILLARY') payload.ancillary_type = null;
    try {
      if (initial.id) await store.updatePolicy(initial.id, payload);
      else await store.addPolicy(payload);
      onDone();
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Client">
          <select value={d.client_id} onChange={(e) => set('client_id', e.target.value)} required>
            <option value="">Select client…</option>
            {store.clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.first_name} {c.last_name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Status">
          <select value={d.status} onChange={(e) => set('status', e.target.value as Status)}>
            {Object.entries(STATUS_META).map(([k, v]) => (
              <option key={k} value={k}>
                {v.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Product line">
          <select
            value={d.product_line}
            onChange={(e) => set('product_line', e.target.value as ProductLine)}
          >
            {PRODUCT_LINES.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>
        {d.product_line === 'ANCILLARY' && (
          <Field label="Ancillary type">
            <select
              value={d.ancillary_type ?? ''}
              onChange={(e) => set('ancillary_type', e.target.value || null)}
            >
              <option value="">Select type…</option>
              {ANCILLARY_TYPES.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Carrier">
          <select
            value={d.carrier_id ?? ''}
            onChange={(e) => set('carrier_id', e.target.value || null)}
          >
            <option value="">Select carrier…</option>
            {store.carriers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Plan name">
          <input value={d.plan_name} onChange={(e) => set('plan_name', e.target.value)} placeholder="e.g. Aetna Medicare Eagle PPO" />
        </Field>
        <Field label="Monthly premium ($)">
          <input
            type="number"
            step="0.01"
            min="0"
            value={d.monthly_premium}
            onChange={(e) => set('monthly_premium', Number(e.target.value))}
          />
        </Field>
        <Field label="Commission ($)">
          <input
            type="number"
            step="0.01"
            min="0"
            value={d.commission_amount}
            onChange={(e) => set('commission_amount', Number(e.target.value))}
          />
        </Field>
        <Field label="Application date">
          <input type="date" value={d.app_date ?? ''} onChange={(e) => set('app_date', e.target.value || null)} />
        </Field>
        <Field label="Effective date">
          <input type="date" value={d.effective_date ?? ''} onChange={(e) => set('effective_date', e.target.value || null)} />
        </Field>
        <Field label="Renewal date">
          <input type="date" value={d.renewal_date ?? ''} onChange={(e) => set('renewal_date', e.target.value || null)} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Notes">
            <textarea rows={2} value={d.notes} onChange={(e) => set('notes', e.target.value)} />
          </Field>
        </div>
      </div>

      <details className="rounded-lg border border-slate-200 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-slate-500">Add a new carrier</summary>
        <div className="mt-2 flex gap-2">
          <input
            value={newCarrier}
            onChange={(e) => setNewCarrier(e.target.value)}
            placeholder="Carrier name"
          />
          <button
            type="button"
            className={btnGhost}
            onClick={async () => {
              if (newCarrier.trim()) {
                await store.addCarrier(newCarrier.trim());
                setNewCarrier('');
              }
            }}
          >
            Add
          </button>
        </div>
      </details>

      <div className="flex justify-end gap-2 pt-1">
        <button type="button" className={btnGhost} onClick={onDone}>
          Cancel
        </button>
        <button type="submit" className={btnPrimary} disabled={saving || !d.client_id}>
          {saving ? 'Saving…' : initial.id ? 'Save changes' : 'Add policy'}
        </button>
      </div>
    </form>
  );
}
