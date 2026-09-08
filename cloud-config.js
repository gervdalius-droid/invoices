/* Cloud connection for this deployment — Dėdės Baldai.

   Committed on purpose so the hosted app pre-fills the connection and a phone
   only has to type the password. Nothing here is a secret in the Supabase
   sense: the publishable/anon key on its own reads NOTHING, because the table
   is RLS-locked to authenticated sessions. The password is never stored here,
   or anywhere else in the repo.

   It points at the SAME Supabase project ShopFlow uses, and at ShopFlow's
   existing `workspaces` table under its own row id — so no extra table and no
   SQL were ever needed. Sign in with the ShopFlow shop password. */
window.CLOUD_CONFIG = {
  url:       "https://niveinyzkkwtreeeaziv.supabase.co",
  key:       "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5pdmVpbnl6a2t3dHJlZWVheml2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU4Mzc2ODgsImV4cCI6MjEwMTQxMzY4OH0.E2LnA_ClFpE1pe_pVPp28M1zOCkzi1RoAIU3bo9PNxk",
  email:     "shopflow@dedesbaldai.lt",
  workspace: "dedes-baldai-invoices",
  table:     "workspaces",
};
