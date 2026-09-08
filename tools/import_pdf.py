#!/usr/bin/env python3
"""Convert a printed invoice-book PDF into the app's import JSON.

Written for the mPDF-generated "PVM SĄSKAITA FAKTŪRA" books produced by the
b1/sąskaita-style app Dėdės Baldai used before this one: one invoice per page,
a fixed column grid. Text is read as individual glyphs with coordinates and
re-assembled into rows and columns, which is what makes the line-item table
recoverable at all — the plain text layer runs "…persirengimui4vnt494.00 €"
together, and the split between a name ending in digits and the quantity is
genuinely ambiguous there.

    python3 tools/import_pdf.py BOOK.pdf -o import.json

Then in the app: Nustatymai → Duomenys → Importuoti sąskaitas.

Every parsed line is checked against the invoice's own arithmetic
(qty x price == line net, sum of nets == stated net, net + VAT == total);
anything that fails is reported and left out rather than silently imported.
"""
import argparse, json, re, sys, unicodedata

try:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTChar
except ImportError:
    sys.exit("needs pdfminer.six:  python3 -m pip install pdfminer.six")

# The generator auto-sizes the line-item table per page, so the column
# x-positions are NOT fixed — they are read from each page's own header row.
# Order of the eight header cells:
NAME, QTY, UNIT, PRICE, NET, VATSUM, RATE, TOTAL = range(8)

MONEY = re.compile(r"^-?[\d\s]*[\d](?:[.,]\d{1,2})?\s*€?$")


def money(s):
    s = (s or "").replace("€", "").replace("\xa0", " ").replace(" ", "").replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def glyphs(page):
    stack, out = [page], []
    while stack:
        for el in stack.pop():
            if isinstance(el, LTChar):
                out.append(el)
            elif hasattr(el, "__iter__"):
                stack.append(el)
    return out


def rows_of(page, ygap=3.0, xgap=3.0):
    """Glyphs -> [(y, [(x, text), ...])], rows top-down, cells left-to-right."""
    cs = sorted(glyphs(page), key=lambda c: (-c.y0, c.x0))
    if not cs:
        return []
    bands, cur, y = [], [cs[0]], cs[0].y0
    for c in cs[1:]:
        if abs(c.y0 - y) > ygap:
            bands.append(cur)
            cur, y = [c], c.y0
        else:
            cur.append(c)
    bands.append(cur)

    out = []
    for band in bands:
        line = sorted(band, key=lambda c: c.x0)
        cells, buf, x0, prev = [], [line[0].get_text()], line[0].x0, line[0]
        for c in line[1:]:
            if c.x0 - prev.x1 > xgap:
                cells.append((round(x0, 1), "".join(buf).strip()))
                buf, x0 = [c.get_text()], c.x0
            else:
                buf.append(c.get_text())
            prev = c
        cells.append((round(x0, 1), "".join(buf).strip()))
        out.append((round(band[0].y0, 1), [c for c in cells if c[1]]))
    return out


def near(x, target, tol=8.0):
    return abs(x - target) <= tol


def parse_page(rows, problems, page_no):
    """One page -> one invoice dict in the app's shape (no ids)."""
    def cell_after(label, xmin=300.0):
        for _y, cells in rows:
            if any(label in t for _x, t in cells):
                for x, t in cells:
                    if x >= xmin and label not in t:
                        return t
        return ""

    series, number = "", ""
    for _y, cells in rows:
        for x, t in cells:
            m = re.match(r"^Serija\s+(\S+)\s+Nr\.?$", t)
            if m:
                series = m.group(1)
                for x2, t2 in cells:
                    if x2 > x:
                        number = t2.strip()
    if not number:                                   # "Serija DBSF Nr0002943"
        for _y, cells in rows:
            for _x, t in cells:
                m = re.match(r"^Serija\s+(\S+)\s+Nr\.?\s*(\d+)$", t)
                if m:
                    series, number = m.group(1), m.group(2)

    date = cell_after("Sąskaitos data")
    due = cell_after("Apmokėti iki")
    date = (re.search(r"\d{4}-\d{2}-\d{2}", date) or [None])[0] if date else None
    due = (re.search(r"\d{4}-\d{2}-\d{2}", due) or [None])[0] if due else None

    # ---- buyer: the middle column between "Pirkėjas" and the table header ----
    buyer_x, started, buyer_lines = None, False, []
    for _y, cells in rows:
        for x, t in cells:
            if t.startswith("Pirkėjas"):
                buyer_x, started = x, True
        if not started:
            continue
        if any(t.startswith("Pavadinimas") for _x, t in cells):
            break
        for x, t in cells:
            if buyer_x is not None and near(x, buyer_x, 6) and not t.startswith("Pirkėjas"):
                buyer_lines.append(t)

    name_parts, code, vat, addr, phone = [], "", "", [], ""
    skip = False
    for i, t in enumerate(buyer_lines):
        if skip:
            skip = False
            continue
        m = re.match(r"^Įm\.?\s*kodas:?\s*(\d+)$", t)
        if m:
            code = m.group(1); continue
        m = re.match(r"^PVM\s+mokėtojo\s+kodas:?\s*([A-Z]{0,2}\d+)$", t)
        if m:
            vat = m.group(1); continue
        # the label and its value are often on two separate lines
        if re.match(r"^PVM\s+mokėtojo\s+kodas:?$", t):
            nxt = buyer_lines[i + 1] if i + 1 < len(buyer_lines) else ""
            if re.match(r"^[A-Z]{0,2}\d+$", nxt):
                vat, skip = nxt, True
            continue
        if re.match(r"^Įm\.?\s*kodas:?$", t):
            nxt = buyer_lines[i + 1] if i + 1 < len(buyer_lines) else ""
            if re.match(r"^\d+$", nxt):
                code, skip = nxt, True
            continue
        if re.match(r"^\+?\d[\d\s]{6,}$", t):
            phone = t.strip(); continue
        (addr if code else name_parts).append(t)
    buyer = {
        "name": " ".join(name_parts).strip(),
        "code": code, "vat": vat,
        "address": ", ".join(a.strip().rstrip(",") for a in addr if a.strip()),
        "phone": phone, "email": "", "contact": "", "kind": "company",
    }

    # ---- line items ----
    lines, in_table, anchors = [], False, None
    stated_net = stated_vat = stated_total = None
    for _y, cells in rows:
        texts = [t for _x, t in cells]
        joined = " ".join(texts)
        if any(t.startswith("Pavadinimas") for t in texts) and len(cells) >= 6:
            # this page's own column grid
            anchors = [x for x, _t in cells]
            in_table = True
            continue
        if not in_table:
            continue
        if "Suma be PVM" in joined and "(" in joined:
            stated_net = money(next((t for x, t in cells if x > 460), ""))
            continue
        if re.search(r"^PVM \(", joined) or joined.startswith("PVM ("):
            stated_vat = money(next((t for x, t in cells if x > 460), ""))
            continue
        if "Bendra suma" in joined:
            stated_total = money(next((t for x, t in cells if x > 460), ""))
            in_table = False
            continue
        if "Sąskaitą išrašė" in joined:
            in_table = False
            continue

        if not anchors or len(anchors) < 8:
            continue
        # A long description wraps inside its table cell: the numbers sit on the
        # cell's first row, and the rest of the name follows on its own.
        if len(cells) == 1 and lines:
            x, t = cells[0]
            if min(range(len(anchors)), key=lambda k: abs(anchors[k] - x)) == NAME:
                lines[-1]["name"] = (lines[-1]["name"] + " " + t).strip()
                continue
        # assign each cell to the nearest header column (data cells are often
        # right-aligned under a left-aligned header, so nearest beats equal)
        col = {}
        for x, t in cells:
            i = min(range(len(anchors)), key=lambda k: abs(anchors[k] - x))
            col.setdefault(i, t)
        name = col.get(NAME, "")
        price = money(col.get(PRICE, ""))
        net = money(col.get(NET, ""))
        if not name or price is None or net is None:
            continue
        q = money(col.get(QTY, ""))
        if q is None:
            continue
        unit = col.get(UNIT, "")
        r = money((col.get(RATE, "") or "").replace("%", "")) or 0
        lines.append({"name": name, "qty": q, "unit": unit or "vnt",
                      "price": price, "disc": 0, "vat": r or 0, "_net": net})

    # ---- arithmetic must agree, or we do not import the page ----
    bad = []
    for l in lines:
        if abs(round(l["qty"] * l["price"], 2) - l["_net"]) > 0.02:
            bad.append("%s: %s x %s != %s" % (l["name"], l["qty"], l["price"], l["_net"]))
    net_sum = round(sum(l["_net"] for l in lines), 2)
    if stated_net is not None and abs(net_sum - stated_net) > 0.02:
        bad.append("line nets %.2f != stated %.2f" % (net_sum, stated_net))
    if stated_net is not None and stated_vat is not None and stated_total is not None:
        if abs(round(stated_net + stated_vat, 2) - stated_total) > 0.02:
            bad.append("net+vat != total on the page itself")
    if not lines and not number and not buyer["name"]:
        return "blank"                      # spacer page, not a failure
    if not lines:
        bad.append("no line items found")
    if not number:
        bad.append("no invoice number")
    if not buyer["name"]:
        bad.append("no buyer name")

    for l in lines:
        del l["_net"]

    if bad:
        problems.append({"page": page_no, "no": number, "why": bad})
        return None

    no = "%s %s" % (series, number) if series else number
    return {
        "no": no.strip(), "series": series, "seq": int(re.sub(r"\D", "", number) or 0),
        "type": "invoice", "date": date, "dueDate": due,
        "buyer": buyer, "lines": lines,
        "notes": "", "currency": "EUR", "status": "sent", "payments": [],
        "issuer": "", "receiver": "",
        "_stated": {"net": stated_net, "vat": stated_vat, "total": stated_total},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", default="import.json")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    invoices, problems, blanks = [], [], 0
    for i, page in enumerate(extract_pages(a.pdf), 1):
        if a.limit and i > a.limit:
            break
        inv = parse_page(rows_of(page), problems, i)
        if inv == "blank":
            blanks += 1
        elif inv:
            invoices.append(inv)
        if i % 25 == 0:
            print("  …%d pages" % i, file=sys.stderr)

    # de-duplicate by number, newest wins
    seen, uniq = set(), []
    for inv in invoices:
        if inv["no"] in seen:
            continue
        seen.add(inv["no"])
        uniq.append(inv)

    total = round(sum(i["_stated"]["total"] or 0 for i in uniq), 2)
    for inv in uniq:
        del inv["_stated"]

    doc = {"format": "saskaitos-import", "version": 1,
           "source": a.pdf.split("/")[-1], "invoices": uniq}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)

    print("pages parsed   : %d (%d blank)" % (i, blanks))
    print("invoices       : %d (%d unique)" % (len(invoices), len(uniq)))
    print("buyers         : %d distinct" % len({x["buyer"]["name"] for x in uniq}))
    print("total incl VAT : %.2f EUR" % total)
    print("wrote          : %s" % a.out)
    if problems:
        print("\nNOT imported (%d):" % len(problems))
        for p in problems[:20]:
            print("  page %s %s -> %s" % (p["page"], p["no"], "; ".join(p["why"])))


main()
