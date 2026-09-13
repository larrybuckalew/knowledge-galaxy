import { useEffect, type ReactNode } from 'react';
import type { ProductLine, Status } from '../lib/types';
import { productLineMeta, statusMeta } from '../lib/constants';

export const btn =
  'inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-semibold transition disabled:opacity-50';
export const btnPrimary = `${btn} bg-indigo-600 text-white hover:bg-indigo-700`;
export const btnGhost = `${btn} border border-slate-300 bg-white text-slate-700 hover:bg-slate-50`;
export const btnDanger = `${btn} text-rose-600 hover:bg-rose-50`;

export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/40 p-0 sm:items-center sm:p-6">
      <div
        className={`max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-white p-5 shadow-xl sm:rounded-2xl sm:p-6 ${
          wide ? 'sm:max-w-3xl' : 'sm:max-w-lg'
        }`}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-bold text-slate-800">{title}</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600" aria-label="Close">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function StatusBadge({ status }: { status: Status }) {
  const m = statusMeta(status);
  return <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${m.badge}`}>{m.label}</span>;
}

export function LineBadge({ line, short }: { line: ProductLine; short?: boolean }) {
  const m = productLineMeta(line);
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${m.badge}`}>
      {short ? m.short : m.label}
    </span>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <label>{label}</label>
      {children}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white/60 p-8 text-center">
      <p className="font-semibold text-slate-600">{title}</p>
      {hint && <p className="mt-1 text-sm text-slate-400">{hint}</p>}
    </div>
  );
}
