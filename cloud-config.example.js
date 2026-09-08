/* Copy to cloud-config.js (git-ignored) to pre-fill Settings → Duomenys debesyje
   on this device. Everything here is optional; the password is never stored.

   `table` may point at an EXISTING table — reusing one that already has
   `id text primary key, data jsonb, updated_at timestamptz, updated_by text`
   and an RLS policy for `authenticated` means no SQL to run. Just give this app
   its own `workspace` id so it cannot collide with the other app's row. */
window.CLOUD_CONFIG = {
  url:       "https://YOUR-PROJECT.supabase.co",
  key:       "sb_publishable_… or the anon key",
  email:     "you@example.com",
  workspace: "my-company-invoices",
  table:     "invoice_workspaces",
};
