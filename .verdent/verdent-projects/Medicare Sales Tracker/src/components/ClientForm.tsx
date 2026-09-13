import { useState, type FormEvent } from 'react';
import type { Client } from '../lib/types';
import { btnGhost, btnPrimary, Field } from './ui';
import type { TrackerStore } from '../lib/store';

export function emptyClient(): Omit<Client, 'id'> {
  return { first_name: '', last_name: '', phone: '', email: '', dob: null, county: '', notes: '' };
}

export default function ClientForm({
  store,
  initial,
  onDone,
}: {
  store: TrackerStore;
  initial: Omit<Client, 'id'> & { id?: string };
  onDone: () => void;
}) {
  const [c, setC] = useState(initial);
  const [saving, setSaving] = useState(false);
  const set = <K extends keyof Client>(k: K, v: Client[K]) => setC((p) => ({ ...p, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (initial.id) await store.updateClient(initial.id, c);
      else await store.addClient(c);
      onDone();
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="First name">
          <input value={c.first_name} onChange={(e) => set('first_name', e.target.value)} required />
        </Field>
        <Field label="Last name">
          <input value={c.last_name} onChange={(e) => set('last_name', e.target.value)} required />
        </Field>
        <Field label="Phone">
          <input value={c.phone ?? ''} onChange={(e) => set('phone', e.target.value)} placeholder="(555) 555-1234" />
        </Field>
        <Field label="Email">
          <input type="email" value={c.email ?? ''} onChange={(e) => set('email', e.target.value)} />
        </Field>
        <Field label="Date of birth">
          <input type="date" value={c.dob ?? ''} onChange={(e) => set('dob', e.target.value || null)} />
        </Field>
        <Field label="County">
          <input value={c.county ?? ''} onChange={(e) => set('county', e.target.value)} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Notes">
            <textarea rows={2} value={c.notes ?? ''} onChange={(e) => set('notes', e.target.value)} />
          </Field>
        </div>
      </div>
      <div className="flex justify-end gap-2 pt-1">
        <button type="button" className={btnGhost} onClick={onDone}>
          Cancel
        </button>
        <button type="submit" className={btnPrimary} disabled={saving}>
          {saving ? 'Saving…' : initial.id ? 'Save changes' : 'Add client'}
        </button>
      </div>
    </form>
  );
}
