import { useCallback, useEffect, useState } from 'react';
import type { Carrier, Client, Goal, Policy } from './types';
import { DEFAULT_CARRIERS } from './constants';
import { supabase } from './supabase';

export interface TrackerStore {
  loading: boolean;
  error: string | null;
  clients: Client[];
  carriers: Carrier[];
  policies: Policy[];
  goals: Goal[];
  addClient: (c: Omit<Client, 'id'>) => Promise<Client | null>;
  updateClient: (id: string, c: Partial<Client>) => Promise<void>;
  deleteClient: (id: string) => Promise<void>;
  addPolicy: (p: Omit<Policy, 'id'>) => Promise<void>;
  updatePolicy: (id: string, p: Partial<Policy>) => Promise<void>;
  deletePolicy: (id: string) => Promise<void>;
  setGoal: (month: string, productLine: string, target: number) => Promise<void>;
  addCarrier: (name: string) => Promise<void>;
  refresh: () => Promise<void>;
}

export function useTracker(userId: string | null): TrackerStore {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [carriers, setCarriers] = useState<Carrier[]>([]);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);

  const refresh = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError(null);
    const [c, cr, p, g] = await Promise.all([
      supabase.from('clients').select('*').order('last_name'),
      supabase.from('carriers').select('*').order('name'),
      supabase.from('policies').select('*').order('created_at', { ascending: false }),
      supabase.from('goals').select('*'),
    ]);
    if (c.error || cr.error || p.error || g.error) {
      setError(c.error?.message ?? cr.error?.message ?? p.error?.message ?? g.error?.message ?? 'Failed to load data');
    } else {
      setClients(c.data ?? []);
      setCarriers(cr.data ?? []);
      setPolicies(p.data ?? []);
      setGoals(g.data ?? []);
    }
    setLoading(false);

    // Seed default carriers once, on first login
    if (!cr.error && (cr.data ?? []).length === 0) {
      await supabase.from('carriers').insert(
        DEFAULT_CARRIERS.map((name) => ({ user_id: userId, name, product_lines: [] })),
      );
      const seeded = await supabase.from('carriers').select('*').order('name');
      if (!seeded.error) setCarriers(seeded.data ?? []);
    }
  }, [userId]);

  useEffect(() => {
    if (userId) void refresh();
  }, [userId, refresh]);

  const guard = async (res: { error: { message: string } | null }) => {
    if (res.error) {
      setError(res.error.message);
      throw res.error;
    }
  };

  const addClient = useCallback(async (c: Omit<Client, 'id'>) => {
    const res = await supabase
      .from('clients')
      .insert({ ...c, user_id: userId })
      .select()
      .single();
    await guard(res);
    setClients((prev) => [...prev, res.data].sort((a, b) => a.last_name.localeCompare(b.last_name)));
    return res.data as Client;
  }, [userId]);

  const updateClient = useCallback(async (id: string, c: Partial<Client>) => {
    await guard(await supabase.from('clients').update(c).eq('id', id));
    setClients((prev) => prev.map((x) => (x.id === id ? { ...x, ...c } : x)));
  }, []);

  const deleteClient = useCallback(async (id: string) => {
    await guard(await supabase.from('clients').delete().eq('id', id));
    setClients((prev) => prev.filter((x) => x.id !== id));
    setPolicies((prev) => prev.filter((p) => p.client_id !== id));
  }, []);

  const addPolicy = useCallback(async (p: Omit<Policy, 'id'>) => {
    const res = await supabase
      .from('policies')
      .insert({ ...p, user_id: userId })
      .select()
      .single();
    await guard(res);
    setPolicies((prev) => [res.data as Policy, ...prev]);
  }, [userId]);

  const updatePolicy = useCallback(async (id: string, p: Partial<Policy>) => {
    await guard(await supabase.from('policies').update(p).eq('id', id));
    setPolicies((prev) => prev.map((x) => (x.id === id ? { ...x, ...p } : x)));
  }, []);

  const deletePolicy = useCallback(async (id: string) => {
    await guard(await supabase.from('policies').delete().eq('id', id));
    setPolicies((prev) => prev.filter((x) => x.id !== id));
  }, []);

  const setGoal = useCallback(async (month: string, productLine: string, target: number) => {
    const existing = goals.find((g) => g.month === month && g.product_line === productLine);
    if (existing) {
      await guard(await supabase.from('goals').update({ target_apps: target }).eq('id', existing.id));
      setGoals((prev) => prev.map((g) => (g.id === existing.id ? { ...g, target_apps: target } : g)));
    } else {
      const res = await supabase
        .from('goals')
        .insert({ month, product_line: productLine, target_apps: target, user_id: userId })
        .select()
        .single();
      await guard(res);
      setGoals((prev) => [...prev, res.data as Goal]);
    }
  }, [goals, userId]);

  const addCarrier = useCallback(async (name: string) => {
    const res = await supabase
      .from('carriers')
      .insert({ user_id: userId, name, product_lines: [] })
      .select()
      .single();
    await guard(res);
    setCarriers((prev) => [...prev, res.data as Carrier].sort((a, b) => a.name.localeCompare(b.name)));
  }, [userId]);

  return {
    loading,
    error,
    clients,
    carriers,
    policies,
    goals,
    addClient,
    updateClient,
    deleteClient,
    addPolicy,
    updatePolicy,
    deletePolicy,
    setGoal,
    addCarrier,
    refresh,
  };
}
