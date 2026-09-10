# Sąskaitos faktūros

Single-file invoicing app for a Lithuanian company. Zero build, zero backend —
open `index.html` and everything lives in `localStorage`.

**Live: https://gervdalius-droid.github.io/invoices/**

Same shell and design language as the other CraftOS apps (`offer`, `shopflow`):
dark sticky header, sticky tab strip, cards, LT/EN toggle sharing the
`fab_lang` key.

```
python3 serve.py            # http://localhost:8741/
python3 serve.py 9000       # any other port
```

The hosted copy is the same files served from `main` by GitHub Pages — pushing
to `main` redeploys it. `cloud-config.js` is git-ignored, so the hosted app asks
for the cloud connection instead of pre-filling it (its `<script>` tag 404s
harmlessly and is caught by `onerror`).

## What it does

| Tab | |
|---|---|
| **Apžvalga** | outstanding / overdue / month revenue / month VAT, turnover bars, overdue list |
| **Sąskaitos** | all invoices, filter by status + year, free-text search, CSV export |
| **Sąskaita** | the editor — buyer, lines, VAT, totals, payments, PDF, e-invoice XML |
| **Važtaraščiai** | consignment notes, filterable by delivered / not delivered |
| **Važtaraštis** | the waybill editor — three parties, route, vehicle, driver, cargo |
| **Žiniaraščiai** | darbo laiko apskaitos žiniaraščiai, one per month |
| **Žiniaraštis** | the timesheet grid — employees × days, hours and absence codes, filled by hand |
| **Pirkėjai** | customers, manual or straight from the company registry |
| **Prekės ir paslaugos** | catalogue of what you sell, dropped into an invoice with one click |
| **Nustatymai** | seller details, logo, bank accounts, numbering, defaults, import/export, backup |

Document types: **PVM sąskaita faktūra**, **Sąskaita faktūra** (non-VAT payer),
**Išankstinė sąskaita**, **Kreditinė sąskaita**.

The printed document carries everything PVM įstatymas 80 str. asks for: series
and number, issue date, both parties with company and VAT codes and addresses,
per-line quantity / unit / price / VAT rate, the VAT breakdown by rate, the
total, the amount in words, bank details and signature lines.

Exports: **PDF** (browser print), **CSV** (semicolon + BOM, opens straight in
Excel), **UBL 2.1 / EN 16931 XML** e-invoice, **JSON** backup — and
**Export everything**, one ZIP holding the JSON backup, the CSVs (invoice
register, line-level, customers, catalogue, waybill register) and every invoice
as standalone HTML plus UBL XML, and every waybill as standalone HTML. The archive is built in the browser with a hand-rolled ZIP writer
(`CompressionStream('deflate-raw')`, stored fallback); a test reads the central
directory back out of the produced blob.

## Exporting a period

Settings (or the invoice list) → **Eksportuoti laikotarpį**. Pick this/last
month, this/last week, this quarter, this/last year, or custom dates; tick which
document types count; filter by paid / unpaid / draft; optionally fold in the
važtaraščiai for the same dates. A live summary shows the document count, net,
VAT and total before you commit to anything.

Three ways out: **PDF** (one print document, one invoice per page, using your
own template), **ZIP** (a CSV register plus every document as HTML and UBL XML),
or **CSV**.

## Importing from another app

Settings → **Importuoti sąskaitas**. It **merges** — nothing is deleted, and
invoice numbers you already hold are skipped, so re-running the same file is
safe. It accepts **an .xlsx workbook**, a generic CSV, this app's own backup, and
the JSON produced by `tools/import_pdf.py`. Buyers become customers
(deduplicated by company code, then by name), and the preview shows exactly what
will land before you confirm.

A number you already hold is not a dead end. If the file carries **payments** the
invoice here has not seen, they are merged into it — lines untouched — so a fresh
export of the same book brings the paid/unpaid picture up to date instead of
being skipped whole. Payments are matched on date + amount, so importing the same
file twice never double-counts; **"Perkelti mokėjimus į jau turimas sąskaitas"**
turns it off.

Ticking **"Tęsti numeraciją nuo importuotų"** carries the old run forward: the
series, the next number *and the number's shape* are inferred from the file, so
after importing a book ending at `DBSF 0002943` the next invoice you write is
`DBSF 0002944` rather than restarting in this app's default format.

### The accounting export (XLSX)

**Drop the workbook straight into the dialog** — no converter, no command line.
An .xlsx is a zip of XML, so the app opens it in the browser: `readZip()` walks
the central directory, `DecompressionStream('deflate-raw')` inflates the entries
(the mirror of the ZIP writer that builds "export everything"), and `readXlsx()`
turns the sheets into plain rows. Shared strings, inline strings and numbers are
read; formatting is ignored.

The two-sheet export the previous app produces — `Sąskaitos` and `Mokėjimai` —
is understood as a whole: the payments sheet is matched to the invoice sheet by
`SERIJA NUMERIS` (`DBSF 0002851`), which is also the shape `import_pdf.py` emits,
so payments land on invoices that came in from the PDF.

Sheets are found by what their header row contains, never by name or position, and
one builder handles both shapes a sheet can have: **one row per line** (an item or
quantity column present) or **one row per invoice** — a register, whose money
columns are invoice totals, so `Kaina` there is the gross rather than a unit price.

`tools/import_xlsx.py` does the same conversion offline if you would rather have
the JSON (`python3 tools/import_xlsx.py BOOK.xlsx -o import.json`), standard
library only — no openpyxl.

Two things the workbook forces:

- It has **no line items**, only invoice totals, so each invoice gets a single
  line priced at `Suma be PVM`. Anything already in the app keeps its own lines.
  It carries no payment term either, so the due date is the invoice date plus the
  term in Settings — using the invoice date itself would file every unpaid
  invoice as overdue the moment it landed.
- Some totals were back-computed from a round gross (`19 215,00`), so recomputing
  21% VAT from the stored net lands a cent away from the document that was
  actually sent — and the matching payment would leave the invoice *part paid*
  forever. Those get a visible `Apvalinimas` line of ∓0.01 so the total, and
  therefore the balance, matches the customer's copy.

A second series ending in `IS` (`DBSFIS`) is imported as **išankstinė sąskaita**.

Column names are matched **exact-first, then by prefix, one column to one key**:
`PVM` is a VAT amount and `PVM kodas` a VAT number, and a single pass in table
order let the second swallow the first. `%` survives normalisation for the same
reason — it is the only thing separating `PVM %` (a rate) from `PVM` (a sum). If
a sheet gives net, VAT and total, and the three only add up when the VAT column
is read as a *rate*, the arithmetic wins over the header.

Dates are accepted as `2026-01-15`, `2026.01.15`, `15/01/2026` or an Excel serial;
anything else is passed through untouched rather than guessed at.

### Invoice books that only exist as PDF

`tools/import_pdf.py` converts a printed invoice book into that JSON:

```bash
python3 -m pip install pdfminer.six
python3 tools/import_pdf.py BOOK.pdf -o import.json
```

It reads the PDF as individual glyphs with coordinates and rebuilds the rows and
columns, because the plain text layer runs values together — `…persirengimui4vnt494.00 €`
— and the split between a description ending in digits and the quantity is
genuinely ambiguous there. Column positions are read from **each page's own
header row**, since the generator auto-sizes the table per page. Descriptions
that wrap inside their cell are stitched back together.

Every page is checked against its own arithmetic (qty × price = line net, line
nets = stated net, net + VAT = total) and anything that fails is reported and
left out rather than imported quietly.

## The invoice list

Sorted newest first and **split by month**, each divider carrying that month's
count, total and — when there is one — the amount still outstanding. The year and
month pickers narrow the list; picking a single month drops the dividers, since
there is then only one. The dashboard's compact tables are left ungrouped.

Browser **Back** walks back through the app rather than leaving it: every view
change pushes a history entry, and a back press with a dialog open closes the
dialog and stays put. Opening an invoice and pressing Back returns to the list.

## Invoice appearance

Settings → **Sąskaitos išvaizda** restyles the printed document with a live
preview beside the controls, rendering your most recent real invoice:

- three templates — **modern**, **classic**, **minimal** (they style the
  važtaraštis too)
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

**The table name is configurable**, and that is the cheap way in: point it at a
table you already have with `id text primary key, data jsonb, updated_at, updated_by`
and an RLS policy for `authenticated`, give this app its own `workspace` id, and
there is no SQL to run at all. This install does exactly that — it shares the
ShopFlow project's `workspaces` table under the row id `dedes-baldai-invoices`.
For a fresh project the `CREATE TABLE` is in the app (Settings → *SQL lentelei
sukurti*).

### cloud-config.js

An optional, **git-ignored** `cloud-config.js` pre-fills the connection so a new
device only types the password:

```js
window.CLOUD_CONFIG = {
  url:       "https://YOUR-PROJECT.supabase.co",
  key:       "sb_publishable_… or the anon key",
  email:     "you@example.com",
  workspace: "my-company-invoices",
  table:     "invoice_workspaces",
};
```

Copy `cloud-config.example.js` and fill it in. It never holds a password. It is
git-ignored on purpose: the anon key reads nothing on its own (RLS), but there is
no reason to advertise the account in a public repo — copy the file onto each
device, or add it to a Pages deploy if you want the hosted app to auto-connect.

## Darbo laiko apskaitos žiniaraštis

A month per sheet: employees down the side, the days of the month across the
top, filled in by hand. **Žiniaraščiai** lists them, **Žiniaraštis** is the grid.

A cell holds what the paper form holds — hours (`8`), a code (`A`), or both
(`DP 8`, `8 VD`) — and is stored as the string that was typed, parsed on the fly.
A code this app has never heard of is kept and counted under its own name rather
than dropped, so the eighteen listed codes are a convenience, not a limit.

The grid is built for typing: arrow keys and Enter step between cells the way a
spreadsheet does, the name column is frozen on the left and the two totals on the
right, and only the totals repaint as you type — the inputs are never re-rendered
underneath you. **Užpildyti darbo dienas** fills every working day at each
employee's own daily hours and touches nothing already written; the ⋯ menu on a
row can overwrite it, clear it, or drop the employee from the sheet.

Weekends and public holidays are shaded and left out of the fill. The holidays
are computed, not tabulated — four of them move with Easter (Meeus/Jones/Butcher),
and Mother's and Father's day are the first Sundays of May and June. **A working
day before a holiday is an hour shorter** (DK 112 str. 6 d.), which is why
December 2026 is 21 days but 166 hours rather than 168.

The month norm is shown against what has actually been booked, and the difference
is per employee: someone on four hours a day is measured against their own norm,
not the full-time one. Printing gives A4 landscape — 31 day columns never fit
portrait — with the totals, a summary of the codes used, the legend and signature
lines. There is a CSV too.

Employees are their own small catalogue (name, position, staff number, hours a
day, whether they still work here), kept in `S.employees` and edited from
**Tvarkyti darbuotojus**. A new sheet carries last month's line-up forward, or
falls back to everyone marked as working.

## Važtaraštis (consignment note)

The shipping document that travels with the goods, carrying what the Kelių
transporto kodeksas 29 str. and the vidaus vežimo taisyklės ask for: three
parties (**siuntėjas / vežėjas / gavėjas**), the route with loading and delivery
dates, vehicle, trailer, **one or more drivers** with their licence numbers, the cargo
with packages, gross weight and value, instructions, and **three signature
blocks** — handed over, taken for carriage, received.

A two-up crew is normal on a long haul, so drivers are a list: add a row per
driver, or pick them from the driver list in Settings. The printed note joins the
names, joins the licence numbers, switches its label to *Vairuotojai*, and names
the whole crew on the carrier signature line.

The fast path is one click. Open an invoice, hit **Sukurti važtaraštį**: the
seller becomes the consignor, the buyer the consignee, the delivery address is
prefilled and the invoice lines become cargo (weight is left blank, because an
invoice never knows it). It also runs the other way — **Sukurti sąskaitą** on a
waybill for the deliver-first, bill-later order of work, deriving unit prices
from cargo value ÷ quantity.

Waybills have their **own series and counter** (`VŽ-2026-0001` by default) so
the two numbering runs can never collide, and their own status (draft → issued →
delivered). Settings holds a small fleet and driver list that fill the vehicle
and driver fields from a dropdown. The printed note shares the invoice branding —
same logo, accent, typeface and template.

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
open http://localhost:8741/test.html        # 500 in-browser assertions
python3 tools/e2e/e2e.py                    # headless Chrome, real registry
```

The .xlsx reader is tested against a workbook **built in the browser by the
app's own ZIP writer**, so a real deflated archive goes through the real reader
with no fixture file in the repo.

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
- Do **not** reset test state with `localStorage.clear()` + reload: the app saves
  on `beforeunload`, so the reload writes the old state straight back. Use
  `adopt({}); saveNow()` instead — `tools/e2e/e2e.py` does.
- `formatNo()` expands any `{N…}` run, so `{NNNNNNN}` works; `inferFormat()`
  derives that shape from an imported number.
- Waybill drivers are a list (`w.drivers[]`). `wbDrivers()` also reads a legacy
  single `driver`/`driverDoc` document, so never touch those fields directly.
- Invoices and važtaraščiai keep **separate counters** (`next` / `wbNext`) and
  separate formats. `formatNo()` is the shared formatter.
