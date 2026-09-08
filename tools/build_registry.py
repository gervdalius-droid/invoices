#!/usr/bin/env python3
"""Build the offline Lithuanian company registry the invoice app searches.

Inputs
  data/jar.csv  Registru centras JAR_IREGISTRUOTI export (pipe-delimited)
  data/vat.csv  ja_kodas,pvm  produced by tools/fetch_vat.py  (optional)

Output
  data/lt-registry.txt.gz   one company per line, TAB separated:
      code \t name \t address \t vat \t form \t status
  data/lt-registry.json     metadata the app shows in Settings

The app fetches the .gz, inflates it with DecompressionStream("gzip") and
searches the raw text, so the line format must stay stable.
"""
import csv, gzip, json, os, sys, datetime

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JAR = os.path.join(HERE, "data", "jar.csv")
VAT = os.path.join(HERE, "data", "vat.csv")
OUT = os.path.join(HERE, "data", "lt-registry.txt.gz")
META = os.path.join(HERE, "data", "lt-registry.json")

# Legal form -> the abbreviation Lithuanians actually write on an invoice.
FORMS = {
    "Uždaroji akcinė bendrovė": "UAB",
    "Mažoji bendrija": "MB",
    "Akcinė bendrovė": "AB",
    "Individuali įmonė": "IĮ",
    "Viešoji įstaiga": "VšĮ",
    "Asociacija": "Asociacija",
    "Labdaros ir paramos fondas": "Fondas",
    "Biudžetinė įstaiga": "BĮ",
    "Žemės ūkio bendrovė": "ŽŪB",
    "Kooperatinė bendrovė (kooperatyvas)": "KB",
    "Tikroji ūkinė bendrija": "TŪB",
    "Komanditinė ūkinė bendrija": "KŪB",
    "Sodininkų bendrija": "SB",
    "Daugiabučių namų savininkų bendrija": "DNSB",
    "Europos bendrovė": "SE",
    "Užsienio juridinio asmens filialas": "Filialas",
    "Užsienio juridinio asmens atstovybė": "Atstovybė",
}


def load_vat():
    if not os.path.exists(VAT):
        print("! no data/vat.csv - VAT numbers will be blank", file=sys.stderr)
        return {}
    out = {}
    with open(VAT, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["ja_kodas"]] = row["pvm"]
    return out


def main():
    vat = load_vat()
    rows, flagged = [], 0
    with open(JAR, encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter="|"):
            code = (r["ja_kodas"] or "").strip()
            name = " ".join((r["ja_pavadinimas"] or "").split())
            if not code or not name:
                continue
            form = FORMS.get(r["form_pavadinimas"], "")
            # stat_kodas 0 = nothing noted; anything else is bankruptcy /
            # liquidation / restructuring and the app warns about it.
            status = "" if r["stat_kodas"] == "0" else " ".join((r["stat_pavadinimas"] or "").split())
            if status:
                flagged += 1
            addr = " ".join((r["adresas"] or "").split())
            rows.append((code, name, addr, vat.get(code, ""), form, status))

    rows.sort(key=lambda x: x[1].lower())
    body = "\n".join("\t".join(c.replace("\t", " ") for c in r) for r in rows)
    blob = body.encode("utf-8")
    with gzip.open(OUT, "wb", compresslevel=9) as fh:
        fh.write(blob)

    meta = {
        "built": datetime.date.today().isoformat(),
        "companies": len(rows),
        "withVat": sum(1 for r in rows if r[3]),
        "flagged": flagged,
        "bytes": len(blob),
        "gzBytes": os.path.getsize(OUT),
        "source": "Registru centras JAR + VMI mokesciu moketoju registras (data.gov.lt)",
    }
    with open(META, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    print(json.dumps(meta, ensure_ascii=False, indent=2))


main()
