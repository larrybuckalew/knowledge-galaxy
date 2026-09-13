import type { ProductLine, Status } from './types';

export const PRODUCT_LINES: {
  id: ProductLine;
  label: string;
  short: string;
  badge: string;
  bar: string;
}[] = [
  {
    id: 'MA',
    label: 'Medicare Advantage',
    short: 'MA',
    badge: 'bg-blue-100 text-blue-700',
    bar: 'bg-blue-500',
  },
  {
    id: 'MEDSUPP',
    label: 'Medicare Supplement',
    short: 'Med Supp',
    badge: 'bg-emerald-100 text-emerald-700',
    bar: 'bg-emerald-500',
  },
  {
    id: 'PARTD',
    label: 'Part D',
    short: 'Part D',
    badge: 'bg-violet-100 text-violet-700',
    bar: 'bg-violet-500',
  },
  {
    id: 'ANCILLARY',
    label: 'Ancillary',
    short: 'Ancillary',
    badge: 'bg-amber-100 text-amber-700',
    bar: 'bg-amber-500',
  },
];

export const PIPELINE: Status[] = ['lead', 'quote', 'application', 'pending', 'effective'];

export const STATUS_META: Record<Status, { label: string; badge: string }> = {
  lead: { label: 'Lead', badge: 'bg-slate-100 text-slate-600' },
  quote: { label: 'Quote', badge: 'bg-sky-100 text-sky-700' },
  application: { label: 'Application', badge: 'bg-indigo-100 text-indigo-700' },
  pending: { label: 'Pending', badge: 'bg-orange-100 text-orange-700' },
  effective: { label: 'Effective', badge: 'bg-emerald-100 text-emerald-700' },
  declined: { label: 'Declined', badge: 'bg-rose-100 text-rose-700' },
  cancelled: { label: 'Cancelled', badge: 'bg-rose-50 text-rose-500' },
};

export const ANCILLARY_TYPES = [
  'Dental',
  'Vision',
  'Dental & Vision',
  'Hospital Indemnity',
  'Cancer',
  'Heart & Stroke',
  'Life',
  'Final Expense',
  'Other',
];

export const DEFAULT_CARRIERS = [
  'Aetna',
  'Humana',
  'UnitedHealthcare',
  'Cigna',
  'Devoted Health',
  'Wellcare',
  'Anthem',
  'Blue Cross Blue Shield',
  'Mutual of Omaha',
  'Aflac',
  'Other',
];

export function productLineMeta(id: ProductLine) {
  return PRODUCT_LINES.find((p) => p.id === id) ?? PRODUCT_LINES[0];
}

export function statusMeta(id: Status) {
  return STATUS_META[id] ?? STATUS_META.lead;
}

export function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

export function monthLabel(month: string): string {
  const [y, m] = month.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleString('en-US', { month: 'long', year: 'numeric' });
}

export function money(n: number): string {
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
}

export function fullName(c: { first_name: string; last_name: string }): string {
  return [c.first_name, c.last_name].filter(Boolean).join(' ') || 'Unnamed client';
}
