// Public browser config for the Verdent-managed Supabase project.
// These values are publishable-key (anon) credentials — safe for client source.
// Server-only secrets must never be placed here.
export const SUPABASE_URL =
  (import.meta.env.VITE_SUPABASE_URL as string | undefined) ??
  'https://supabase-api-prod.verdent.ai/p/pad90cd2c27c6aa7bd3cf';

export const SUPABASE_PUBLISHABLE_KEY =
  (import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined) ??
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoyMTA0NzQ5MjIzLCJpYXQiOjE3ODkxMzAwMjMsImlzcyI6InN1cGFiYXNlIiwicHJvamVjdF9yZWYiOiJwYWQ5MGNkMmMyN2M2YWE3YmQzY2YiLCJyb2xlIjoiYW5vbiJ9.p-GIHJyiN5hKfgo95WqGUmQBxsJLt-99aVPCm8TxWXA';
