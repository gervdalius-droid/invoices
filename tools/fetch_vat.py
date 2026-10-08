#!/usr/bin/env python3
"""Download active LT VAT numbers (PVM kodai) from data.gov.lt (VMI MM registras).

Keyset-paginates the Spinta CSV export by ja_kodas and writes a deduped
`ja_kodas,pvm` CSV. Roughly 410k source rows -> ~140k distinct companies.
"""
import csv, io, sys, time, urllib.parse, urllib.request

BASE = "https://get.data.gov.lt/datasets/gov/vmi/mm_registras/MokesciuMoketojas/:format/csv"
PAGE = 20000
OUT = sys.argv[1] if len(sys.argv) > 1 else "data/vat.csv"


def fetch(after):
    q = ["select(ja_kodas,pvm_kodas_pref,pvm_kodas)", "pvm_isregistruota=null",
         "pvm_kodas!=null", "sort(ja_kodas)", f"limit({PAGE})"]
    if after is not None:
        q.append(f"ja_kodas>{after}")
    url = BASE + "?" + "&".join(urllib.parse.quote(p, safe="()=><!,*") for p in q)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                return r.read().decode("utf-8")
        except Exception as e:                       # transient 5xx / timeouts
            print(f"  retry {attempt+1}: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise SystemExit("failed after 5 attempts: " + url)


seen, after, rows = {}, None, 0
while True:
    text = fetch(after)
    part = list(csv.DictReader(io.StringIO(text)))
    if not part:
        break
    for row in part:
        code = row["ja_kodas"]
        if code and row["pvm_kodas"]:
            seen.setdefault(code, (row["pvm_kodas_pref"] or "LT") + row["pvm_kodas"])
    rows += len(part)
    after = part[-1]["ja_kodas"]
    print(f"  {rows} rows, {len(seen)} companies, at ja_kodas {after}", file=sys.stderr)
    if len(part) < PAGE:
        break

with open(OUT, "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["ja_kodas", "pvm"])
    for code in sorted(seen, key=int):
        w.writerow([code, seen[code]])
print(f"wrote {len(seen)} companies -> {OUT}")
