# Sąskaitos faktūros

Single-file invoicing app for a Lithuanian company. Zero build, zero backend —
open `index.html` and everything lives in `localStorage`.

Same shell and design language as the other CraftOS apps (`offer`, `shopflow`):
dark sticky header, sticky tab strip, cards, LT/EN toggle sharing the
`fab_lang` key.

```
python3 serve.py            # http://localhost:8741/
python3 serve.py 9000       # any other port
```

## What it does

| Tab | |
|---|---|
| **Apžvalga** | outstanding / overdue / month revenue / month VAT, turnover bars, overdue list |
| **Sąskaitos** | all invoices, filter by status + year, free-text search, CSV export |
| **Sąskaita** | the editor — buyer, lines, VAT, totals, payments, PDF, e-invoice XML |
| **Pirkėjai** | customers, manual or straight from the company registry |
| **Prekės ir paslaugos** | catalogue of what you sell, dropped into an invoice with one click |
| **Nustatymai** | seller details, logo, bank accounts, numbering, defaults, backup |

Document types: **PVM sąskaita faktūra**, **Sąskaita faktūra** (non-VAT payer),
**Išankstinė sąskaita**, **Kreditinė sąskaita**.

The printed document carries everything PVM įstatymas 80 str. asks for: series
and number, issue date, both parties with company and VAT codes and addresses,
per-line quantity / unit / price / VAT rate, the VAT breakdown by rate, the
total, the amount in words, bank details and signature lines.

Exports: **PDF** (browser print), **CSV** (semicolon + BOM, opens straight in
Excel), **UBL 2.1 / EN 16931 XML** e-invoice, **JSON** backup — and
**Export everything**, one ZIP holding the JSON backup, four CSVs (register,
line-level, customers, catalogue) and every invoice as both standalone HTML and
UBL XML. The archive is built in the browser with a hand-rolled ZIP writer
(`CompressionStream('deflate-raw')`, stored fallback); a test reads the central
directory back out of the produced blob.

## Invoice appearance

Settings → **Sąskaitos išvaizda** restyles the printed document with a live
preview beside the controls, rendering your most recent real invoice:

- three templates — **modern**, **classic**, **minimal**
- accent colour (eight presets plus a picker), typeface, logo height
- a free line under the company name
- toggles for logo, line numbers, unit column, VAT column, amount in words,
  bank block, notes, signature lines, footer and a "PAID" stamp
- a signature/stamp image dropped onto the "Issued by" line
- custom titles per document type

All three templates carry the same fields — only colours, borders and weights
differ — so nothing legally required can be styled away.

## Cloud sync

Settings → **Duomenys debesyje** connects your own Supabase project so the same
data follows you between computer and phone. Unlike the offer app this **signs
in** first: invoices hold customer and financial data, so `invoice_workspaces`
is locked to `authenticated` and the publishable key alone grants nothing. The
app talks plain REST — no SDK, no CDN.

The whole state is one jsonb document per workspace. Saves push after a 1.8 s
debounce; other devices are picked up by a 60 s poll. **Conflicts are never
resolved silently** — if the row moved under us while we also had local edits,
the app stops and asks which side wins. Same on first connect to a workspace
that already holds data.

The SQL to create the table is in the app (Settings → *SQL lentelei sukurti*).

## The buyer picker

One box. Type three characters and it searches your saved customers first, then
**all 233 971 legal entities registered in Lithuania** underneath. Picking one
fills in name, company code, VAT number and registered address, and saves it as
a customer. Companies in bankruptcy or liquidation are flagged.

The registry is a 6.4 MB file fetched once on first use, kept in the Cache API
and searched entirely offline afterwards — typical query is 10–25 ms.

## Rebuilding the registry

`data/lt-registry.txt.gz` is generated, not hand-written. Refresh it when the
registers change (a few times a year is plenty):

```bash
curl -o data/jar.csv "https://www.registrucentras.lt/aduomenys/?byla=JAR_IREGISTRUOTI.csv"
python3 tools/fetch_vat.py data/vat.csv     # ~10 min, pages data.gov.lt
python3 tools/build_registry.py
```

Sources: Registrų centras JAR (names, codes, addresses, legal form, status) and
the VMI taxpayer register via data.gov.lt (VAT numbers). Both are open data.
Neither sends CORS headers, which is why the app ships a prebuilt file instead
of querying them live from the browser.

`data/jar.csv` and `data/vat.csv` are intermediates and stay out of git.

## Tests

```bash
python3 serve.py &
open http://localhost:8741/test.html        # 197 in-browser assertions
python3 tools/e2e/e2e.py                    # headless Chrome, real registry
```

`test.html` drives the app inside an iframe; the cloud and ZIP groups are async,
so the suite returns a promise the harness awaits. Top-level `const`/`let` live in the
global lexical scope where a parent window cannot see them, so `index.html` ends
with an explicit test bridge that exposes `S`, `EDIT`, `VIEW`, `I18N` and `REG`.

`tools/e2e/e2e.py` drives headless Chrome over CDP (stdlib only, no node): it
loads the real 6.4 MB registry, builds an invoice from a real company, renders
the printable document in both languages, and checks 390 px layout. Screenshots
land in `tools/e2e/shots/`.

## Notes for later

- Dates are handled in **UTC** end to end. `new Date(iso+'T00:00:00')` plus
  `toISOString()` rolls back a day in every UTC+ zone — that bug put every due
  date one day early before it was caught.
- The registry search keeps a diacritic-folded copy of the whole 20 MB blob plus
  newline offsets for **both** copies, so a match position maps back to its line
  without building 234 k objects. `deacc` must stay length-preserving.
- Amount in words is real Lithuanian declension (`ltForm` picks singular /
  plural / genitive from the last two digits); 1000 is "tūkstantis", not "vienas
  tūkstantis".
- Every state document — localStorage, an imported backup, a cloud pull — goes
  through **`adopt()`**, which is also where the v1→v2 migration runs. Read the
  defaults out of `blankState()` *before* the top-level `Object.assign`: merging
  into `base.settings` after `Object.assign(base, p)` is a no-op, because `base`
  already points at the stored object.
- Cloud sync stores only tokens, never the password. Signing out clears them.
