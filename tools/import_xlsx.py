#!/usr/bin/env python3
"""Convert the accounting export workbook into the app's import JSON.

Written for the two-sheet XLSX the previous invoicing app exports:

    Sąskaitos   Serija · Serijos numeris · Data · Pirkėjas · Adresas · Šalis ·
                Įm. kodas · PVM kodas · El. paštas · Nuolaida ·
                Suma be PVM · PVM · Kaina
    Mokėjimai   Mokėjimo data · Sąskaitos serija · Sąskaitos serijos numeris ·
                Sąskaitos data · Mokėtojas · Mokėjimo tipas · Kvito tipas ·
                Kvito serija · Kvito serijos numeris · Sumokėta

    python3 tools/import_xlsx.py BOOK.xlsx -o import.json

Then in the app: Nustatymai → Importuoti sąskaitas. Invoice numbers are built
as "SERIJA NUMERIS" ("DBSF 0002851") — the same shape tools/import_pdf.py
emits — so a book imported from the PDF and this workbook line up and the
payments land on the invoices that are already there.

The workbook carries no line items, only the invoice totals, so each invoice
gets a single line priced at "Suma be PVM". Anything already in the app keeps
its own lines; only the payments are merged.

Columns are found by header name, not position. Every invoice is checked
against its own arithmetic (net + VAT == total) and every payment against the
invoice it claims to pay; failures are reported, never silently imported.

Standard library only — no openpyxl, no node.
"""
import argparse, datetime, json, re, sys, unicodedata, zipfile
import xml.etree.ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def norm(s):
    """Lower-case, strip diacritics and punctuation — for matching headers."""
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# ---------------------------------------------------------------- xlsx reader
def col_of(ref):
    """'AB12' -> 27 (0-based column index)."""
    n = 0
    for ch in ref:
        if ch.isdigit():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def serial_date(n):
    """Excel serial -> ISO. 1900 leap-year bug included, as Excel has it."""
    base = datetime.date(1899, 12, 30)
    return (base + datetime.timedelta(days=int(n))).isoformat()


def sheets(path):
    """-> {sheet name: [[cell, ...], ...]} with every value as a string."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")):
                shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
        rels = {r.get("Id"): r.get("Target")
                for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        out = {}
        for sh in ET.fromstring(z.read("xl/workbook.xml")).iter(NS + "sheet"):
            target = rels[sh.get(RNS + "id")].lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            rows = []
            for row in ET.fromstring(z.read(target)).iter(NS + "row"):
                cells = []
                for c in row.iter(NS + "c"):
                    i = col_of(c.get("r") or "A1")
                    while len(cells) <= i:
                        cells.append("")
                    t, v = c.get("t"), c.find(NS + "v")
                    if t == "s":
                        val = shared[int(v.text)] if v is not None else ""
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(NS + "t"))
                    elif v is None:
                        val = ""
                    else:
                        val = v.text or ""
                    cells[i] = val.strip()
                rows.append(cells)
            out[sh.get("name")] = rows
        return out


def headers(row, wanted):
    """{key: column index} for the aliases in `wanted`, matched by name."""
    idx = {}
    seen = [norm(h) for h in row]
    for key, aliases in wanted.items():
        for a in aliases:
            a = norm(a)
            hit = [i for i, h in enumerate(seen) if h == a]
            if not hit:
                hit = [i for i, h in enumerate(seen) if h.startswith(a)]
            if hit:
                idx[key] = hit[0]
                break
    return idx


def cell(row, idx, key):
    i = idx.get(key)
    return row[i].strip() if i is not None and i < len(row) else ""


def r2(n):
    """Round half up, the way the app's r2() does — not Python's half-even."""
    return (1 if n >= 0 else -1) * int(abs(n) * 100 + 0.5) / 100.0


def app_total(net, rate, extra=0.0):
    """What the app will show: VAT recomputed from the net, then added."""
    return r2(r2(net) + r2(r2(net) * rate / 100.0) + extra)


def money(s):
    s = str(s or "").replace("\xa0", " ").replace(" ", "").replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


def iso(s):
    """The export writes ISO text; a real date cell arrives as a serial."""
    s = str(s or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    if re.fullmatch(r"\d{4}[./]\d{1,2}[./]\d{1,2}", s):
        y, m, d = re.split(r"[./]", s)
        return "%04d-%02d-%02d" % (int(y), int(m), int(d))
    if re.fullmatch(r"\d{1,2}[./]\d{1,2}[./]\d{4}", s):
        d, m, y = re.split(r"[./]", s)
        return "%04d-%02d-%02d" % (int(y), int(m), int(d))
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return serial_date(float(s))
    return ""


def plus_days(date, days):
    y, m, d = (int(x) for x in date.split("-"))
    return (datetime.date(y, m, d) + datetime.timedelta(days=days)).isoformat()


INV_COLS = {
    "series": ["serija"], "number": ["serijos numeris", "numeris", "nr"],
    "date": ["data", "saskaitos data"], "buyer": ["pirkejas", "klientas"],
    "address": ["adresas"], "country": ["salis"],
    "code": ["im kodas identifikavimo numeris", "im kodas", "imones kodas", "kodas"],
    "vat": ["pvm kodas"], "email": ["el pastas", "elektroninis pastas"],
    "disc": ["nuolaida"], "net": ["suma be pvm"], "vatsum": ["pvm"],
    "total": ["kaina", "viso", "suma su pvm"],
}
PAY_COLS = {
    "date": ["mokejimo data"], "series": ["saskaitos serija"],
    "number": ["saskaitos serijos numeris"], "payer": ["moketojas"],
    "kind": ["mokejimo tipas"], "amount": ["sumoketa", "suma"],
}


def pick(book, cols, must):
    """Find the sheet whose header row carries the required columns."""
    for name, rows in book.items():
        for n, row in enumerate(rows[:5]):
            idx = headers(row, cols)
            if all(k in idx for k in must):
                return name, rows[n + 1:], idx
    return None, [], {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("-o", "--out", default="import.json")
    ap.add_argument("--term", type=int, default=14,
                    help="payment term in days, used when the workbook has no "
                         "due date column (default 14)")
    ap.add_argument("--vat", type=float, default=21.0,
                    help="fallback VAT rate when an invoice has no VAT (21)")
    ap.add_argument("--proforma-series", default="auto",
                    help="series to import as išankstinė sąskaita / proforma. "
                         "'auto' (default) takes any series ending in IS that is "
                         "not the main one; '' turns the detection off")
    a = ap.parse_args()

    book = sheets(a.xlsx)
    isheet, irows, iidx = pick(book, INV_COLS, ("number", "date", "buyer", "net"))
    if not isheet:
        sys.exit("no invoice sheet found (needs Serijos numeris / Data / Pirkėjas / Suma be PVM)")
    psheet, prows, pidx = pick(book, PAY_COLS, ("date", "number", "amount"))

    # "Išankstinė sąskaita" is its own document type in the app, and the old
    # book marks it with its own series (DBSF -> DBSFIS). Only the printed
    # title differs, so getting it wrong is cheap to undo — but getting it
    # right means the proformas do not read as VAT invoices.
    counts = {}
    for row in irows:
        if cell(row, iidx, "number"):
            se = cell(row, iidx, "series")
            counts[se] = counts.get(se, 0) + 1
    main = max(counts, key=lambda k: counts[k]) if counts else ""
    if a.proforma_series == "auto":
        proforma = {k for k in counts if k != main and k.upper().endswith("IS")}
    else:
        proforma = {x.strip() for x in a.proforma_series.split(",") if x.strip()}

    problems, invoices, by_no, rounded = [], [], {}, []
    for row in irows:
        number = cell(row, iidx, "number")
        if not number:
            continue
        series = cell(row, iidx, "series")
        no = ("%s %s" % (series, number)).strip()
        date = iso(cell(row, iidx, "date"))
        net = money(cell(row, iidx, "net"))
        vatsum = money(cell(row, iidx, "vatsum"))
        total = money(cell(row, iidx, "total"))
        why = []
        if not date:
            why.append("no date")
        if total and abs(round(net + vatsum, 2) - total) > 0.01:
            why.append("net %.2f + VAT %.2f != total %.2f" % (net, vatsum, total))
        if no in by_no:
            why.append("duplicate number")
        if why:
            problems.append({"no": no, "why": why})
            continue
        rate = round(vatsum / net * 100, 2) if net else a.vat
        # 21.0 rather than 20.999999 when the export rounds the VAT sum
        if abs(rate - round(rate)) < 0.02:
            rate = float(round(rate))
        code = cell(row, iidx, "code")
        inv = {
            "no": no, "series": series, "seq": int(re.sub(r"\D", "", number) or 0),
            "type": "proforma" if series in proforma else "invoice",
            "date": date, "dueDate": plus_days(date, a.term),
            "buyer": {"name": cell(row, iidx, "buyer"), "code": code,
                      "vat": cell(row, iidx, "vat"),
                      "address": cell(row, iidx, "address"),
                      "email": cell(row, iidx, "email"), "phone": "", "contact": "",
                      "kind": "company" if code else "person"},
            "lines": [{"name": "Prekės ir paslaugos", "qty": 1, "unit": "vnt",
                       "price": net, "disc": money(cell(row, iidx, "disc")),
                       "vat": rate}],
            "notes": "", "currency": "EUR", "status": "sent", "payments": [],
            "issuer": "", "receiver": "",
        }
        # The old app stored a net back-computed from a round gross, so a plain
        # 21% recompute can land a cent away from the total on the customer's
        # copy — and then the matching payment leaves the invoice "part paid"
        # forever. Carry the difference as a visible rounding line so the total,
        # and therefore the balance, matches the document that was actually sent.
        if total:
            drift = r2(total - app_total(net, rate))
            if drift:
                inv["lines"].append({"name": "Apvalinimas", "qty": 1, "unit": "vnt",
                                     "price": drift, "disc": 0, "vat": 0})
                rounded.append((no, drift))
        inv["_total"] = total or app_total(net, rate)
        by_no[no] = inv
        invoices.append(inv)

    paid_total, orphans = 0.0, []
    for row in prows:
        number = cell(row, pidx, "number")
        if not number:
            continue
        no = ("%s %s" % (cell(row, pidx, "series"), number)).strip()
        amount = money(cell(row, pidx, "amount"))
        date = iso(cell(row, pidx, "date"))
        if no not in by_no:
            orphans.append(no)
            continue
        if not amount:
            continue
        by_no[no]["payments"].append(
            {"date": date or by_no[no]["date"], "amount": amount,
             "note": cell(row, pidx, "kind")})
        paid_total += amount


    gross = r2(sum(i["_total"] for i in invoices))
    settled, part, open_ = [], [], []
    for i in invoices:
        got = r2(sum(p["amount"] for p in i["payments"]))
        if not got:
            open_.append(i)
        elif got >= i["_total"] - 0.005:
            settled.append(i)
        else:
            part.append(i)
    print("sheets         : %s / %s" % (isheet, psheet or "—"))
    print("invoices       : %d%s" % (len(invoices), "".join(
        "\n  %s x%d%s" % (se, n, "   -> išankstinė sąskaita / proforma"
                          if se in proforma else "")
        for se, n in sorted(counts.items(), key=lambda kv: -kv[1])) if len(counts) > 1 else ""))
    print("buyers         : %d distinct" % len({i["buyer"]["name"] for i in invoices}))
    print("payments       : %d, %.2f EUR" % (
        sum(len(i["payments"]) for i in invoices), paid_total))
    print("paid in full   : %d" % len(settled))
    print("part paid      : %d%s" % (len(part), ("  " + ", ".join(
        "%s (%.2f of %.2f)" % (i["no"], r2(sum(p["amount"] for p in i["payments"])), i["_total"])
        for i in part)) if part else ""))
    print("unpaid         : %d%s" % (len(open_), ("  " + ", ".join(
        i["no"] for i in open_)) if open_ else ""))
    print("total incl VAT : %.2f EUR   outstanding %.2f EUR" % (gross, r2(gross - paid_total)))
    if rounded:
        print("\nrounding line added (%d) — workbook total kept, VAT recomputed:" % len(rounded))
        for no, d in rounded:
            print("  %s  %+.2f" % (no, d))
    if orphans:
        print("\npayments with no invoice (%d): %s" % (len(orphans), ", ".join(orphans[:10])))
    if problems:
        print("\nNOT imported (%d):" % len(problems))
        for p in problems[:20]:
            print("  %s -> %s" % (p["no"], "; ".join(p["why"])))

    for i in invoices:
        del i["_total"]
    doc = {"format": "saskaitos-import", "version": 1,
           "source": a.xlsx.split("/")[-1], "invoices": invoices}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    print("\nwrote          : %s" % a.out)


main()
