import { createClient } from '@supabase/supabase-js';
import { createVerdentAuth } from '@verdent/auth-js';
import { SUPABASE_PUBLISHABLE_KEY, SUPABASE_URL } from './config';

export const supabase = createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
});

export const auth = createVerdentAuth({ supabase });
