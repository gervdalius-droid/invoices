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
Excel), **UBL 2.1 / EN 16931 XML** e-invoice, **JSON** backup.

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
open http://localhost:8741/test.html        # 116 in-browser assertions
python3 tools/e2e/e2e.py                    # headless Chrome, real registry
```

`test.html` drives the app inside an iframe. Top-level `const`/`let` live in the
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
