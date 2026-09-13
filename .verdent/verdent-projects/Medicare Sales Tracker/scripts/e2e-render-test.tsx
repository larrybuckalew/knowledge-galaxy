import { JSDOM } from 'jsdom';
import { createElement, act } from 'react';
import { createRoot } from 'react-dom/client';
import Clients from '../src/views/Clients';

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'http://localhost/',
  pretendToBeVisual: true,
});

const w = dom.window as unknown as Record<string, unknown>;
for (const k of ['window', 'document', 'Event', 'CustomEvent', 'HTMLElement', 'HTMLInputElement', 'HTMLSelectElement', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'localStorage']) {
  try {
    (globalThis as Record<string, unknown>)[k] = w[k] ?? (dom as unknown as Record<string, unknown>)[k];
  } catch {
    Object.defineProperty(globalThis, k, { value: w[k], configurable: true });
  }
}
Object.defineProperty(globalThis, 'navigator', { value: w.navigator, configurable: true });
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

async function main() {
  const client = {
    id: 'c1',
    first_name: 'Larry',
    last_name: 'Testclient',
    phone: '',
    email: '',
    dob: null,
    county: '',
    notes: '',
  };

  const store = {
    loading: false,
    error: null,
    clients: [client],
    carriers: [{ id: 'cr1', name: 'Aetna', product_lines: [] }],
    policies: [],
    goals: [],
    addClient: async () => null,
    updateClient: async () => {},
    deleteClient: async () => {},
    addPolicy: async () => {},
    updatePolicy: async () => {},
    deletePolicy: async () => {},
    setGoal: async () => {},
    addCarrier: async () => {},
    refresh: async () => {},
  };

  const root = createRoot(document.getElementById('root')!);
  console.log('rendering Clients...');
  await act(async () => {
    root.render(createElement(Clients, { store: store as never }));
  });
  console.log('initial render done. Buttons:', document.querySelectorAll('button').length);

  const row = [...document.querySelectorAll('button')].find((b) => b.textContent!.includes('Larry Testclient'));
  if (!row) {
    console.error('FAIL: row not found');
    process.exit(1);
  }
  console.log('clicking row...');
  const t0 = Date.now();
  await act(async () => {
    (row as HTMLElement).click();
  });
  console.log(`click done in ${Date.now() - t0}ms`);

  const hasDetail = document.body.textContent!.includes('Policies') && Boolean(document.querySelector('.fixed h2'));
  console.log('detail modal visible:', hasDetail);
  console.log(hasDetail ? 'PASS' : 'FAIL: no detail');
  process.exit(hasDetail ? 0 : 1);
}

void main();
