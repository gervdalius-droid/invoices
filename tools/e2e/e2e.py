#!/usr/bin/env python3
"""End-to-end check of the invoice app against the REAL 6.4 MB registry.

Drives a headless Chrome over CDP (stdlib only, no node):
  python3 tools/e2e/e2e.py [http://localhost:8741/]
Writes screenshots next to it in shots/.
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Chrome

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8741/"
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
os.makedirs(SHOTS, exist_ok=True)
fails = []


def expect(cond, msg, extra=""):
    print(("  ok    " if cond else "  FAIL  ") + msg + (("   " + str(extra)) if (extra and not cond) else ""))
    if not cond:
        fails.append(msg)


with Chrome(width=1440, height=980, dpr=1, mobile=False, port=9341,
            profile="/tmp/cdp-invoices") as c:
    c.goto(URL, wait=2.0)
    c.eval("localStorage.clear();location.reload()")
    time.sleep(2.0)

    print("— boot")
    expect(c.eval("typeof S==='object' && VIEW==='dash'"), "app booted on the dashboard")
    expect(not c.eval("!!document.querySelector('.bad')"), "no error toast on boot")

    print("— registry: real file, real search")
    t0 = time.time()
    r = c.eval("REG.load(function(){}).then(function(ok){return {ok:ok,state:REG.state,lines:REG.lines,"
               "chars:REG.text.length,sameLen:REG.norm.length===REG.text.length,meta:REG.meta};})",
               await_promise=True)
    print("   ", json.dumps(r, ensure_ascii=False)[:300])
    expect(isinstance(r, dict) and r.get("ok"), "6.4 MB registry loaded + inflated", r)
    expect(r.get("lines", 0) > 200000, "230k+ companies indexed", r.get("lines"))
    expect(r.get("sameLen"), "folded blob keeps byte-for-byte line offsets")
    print("    load wall time: %.1fs" % (time.time() - t0))

    for q, want in [("maxima lt", "MAXIMA"), ("swedbank", "Swedbank"), ("123033512", "MAXIMA")]:
        res = c.eval("(function(){var a=performance.now();var h=REG.search(%s,5);"
                     "return {ms:Math.round(performance.now()-a),n:h.length,top:h[0]||null};})()" % json.dumps(q))
        top = (res or {}).get("top") or {}
        print("    %-12s %2d hits  %3d ms  ->  %s | %s | %s"
              % (q, res.get("n", 0), res.get("ms", -1), top.get("code", "-"),
                 (top.get("name") or "-")[:44], top.get("vat") or "-"))
        expect(res.get("n", 0) > 0, "search finds '%s'" % q)
        expect(res.get("ms", 999) < 400, "search '%s' under 400 ms" % q, res.get("ms"))
        if want:
            expect(want.lower() in (top.get("name") or "").lower(), "'%s' ranks a %s first" % (q, want), top.get("name"))

    print("— a whole invoice, from a registry row to a printable document")
    c.eval("setLang('lt')")
    r = c.eval("""(function(){
      S.seller={...S.seller,name:'Mano Įmonė UAB',code:'302475348',vat:'LT100005781213',
        address:'Vilnius, Gedimino pr. 1',email:'info@manoimone.lt',phone:'+370 600 00000',
        director:'R. Gervinskas',
        banks:[{bank:'Swedbank',iban:'LT12 7300 0100 0000 0001',swift:'HABALT22'}]};
      var hit=REG.search('maxima lt',1)[0];
      newInvoice();
      var cust=customerFromRegistry(hit); S.customers.push(cust); setBuyer(cust);
      EDIT.lines=[{id:'a',name:'Virtuvės baldų komplektas',qty:1,unit:'kompl.',price:4850,disc:0,vat:21},
                  {id:'b',name:'Montavimo darbai',qty:8,unit:'val',price:35,disc:0,vat:21}];
      var okSave=commitInvoice();
      var c=calc(S.invoices[0]);
      return {okSave:okSave,no:S.invoices[0].no,buyer:EDIT.buyer,
              net:c.net,vat:c.vat,total:c.total,words:amountWords(c.total),
              date:EDIT.date,due:EDIT.dueDate,customers:S.customers.length};
    })()""")
    print("   ", json.dumps(r, ensure_ascii=False)[:420])
    expect(r.get("okSave") is True, "invoice saved")
    expect(abs(r.get("net", 0) - 5130) < 0.01, "net 4850 + 280 = 5130", r.get("net"))
    expect(abs(r.get("vat", 0) - 1077.30) < 0.01, "VAT 21% = 1077.30", r.get("vat"))
    expect(abs(r.get("total", 0) - 6207.30) < 0.01, "total 6207.30", r.get("total"))
    expect((r.get("buyer") or {}).get("code"), "buyer carries the registry company code")
    expect((r.get("buyer") or {}).get("vat"), "buyer carries the VMI VAT number")
    expect(r.get("due") != r.get("date"), "due date is later than the issue date")

    print("— screens")
    for view, name in [("dash", "1-dashboard"), ("invoices", "2-invoices"),
                       ("editor", "3-editor"), ("customers", "4-customers"),
                       ("settings", "5-settings")]:
        c.eval("if('%s'==='editor'){openInvoice(S.invoices[0].id)}else{go('%s')}" % (view, view))
        time.sleep(0.45)
        c.shot(os.path.join(SHOTS, name + ".png"))
        h = c.eval("document.querySelector('#p-%s').innerHTML.length" % view)
        expect(isinstance(h, int) and h > 400, "%s renders" % name, h)

    print("— printable document")
    PRINT_PROBE = """(function(){
      var w={document:{open:function(){},close:function(){},write:function(h){window.__doc=h}}};
      var real=window.open; window.open=function(){return w};
      printInvoice(S.invoices[0]);
      window.open=real;
      var d=window.__doc||'';
      var m=d.match(/Suma žodžiais<\\/div><b>([^<]*)/)||d.match(/Amount in words<\\/div><b>([^<]*)/);
      return {len:d.length,
              hasTitle:d.indexOf('PVM SĄSKAITA FAKTŪRA')>=0,
              hasTitleEn:d.indexOf('VAT INVOICE')>=0,
              hasSellerVat:d.indexOf('LT100005781213')>=0,
              hasBuyerCode:d.indexOf(S.invoices[0].buyer.code)>=0,
              hasIban:d.indexOf('LT12 7300 0100 0000 0001')>=0,
              hasWords:d.indexOf('Suma žodžiais')>=0||d.indexOf('Amount in words')>=0,
              hasWordsLt:/eurai|eurų|euras/.test(d),
              hasWordsEn:/euros|euro /.test(d),
              words:m?m[1]:null,
              hasTotal:d.replace(/[\\s\u00a0\u202f,]/g,'').indexOf('620730')>=0,
              lines:(d.match(/<tr><td class="c">/g)||[]).length};
    })()"""
    r = c.eval(PRINT_PROBE)
    print("   ", json.dumps(r, ensure_ascii=False))
    expect(r.get("hasTitle"), "document is titled PVM SĄSKAITA FAKTŪRA")
    expect(r.get("hasSellerVat"), "seller VAT number printed")
    expect(r.get("hasBuyerCode"), "buyer company code printed")
    expect(r.get("hasIban"), "bank account printed")
    expect(r.get("hasTotal"), "total printed")
    expect(r.get("lines") == 2, "both lines printed", r.get("lines"))
    expect(r.get("hasWordsLt"), "amount in words is Lithuanian", r.get("words"))

    print("— the same document in English")
    c.eval("setLang('en')")
    r2 = c.eval(PRINT_PROBE)
    expect(r2.get("hasTitleEn"), "English document is titled VAT INVOICE")
    expect(r2.get("hasWordsEn"), "amount in words is English", r2.get("words"))
    c.eval("setLang('lt')")

    print("— mobile 390px")
    c.resize(390, 844, dpr=2)
    time.sleep(0.4)
    for view, name in [("dash", "6-mobile-dash"), ("editor", "7-mobile-editor")]:
        c.eval("if('%s'==='editor'){openInvoice(S.invoices[0].id)}else{go('%s')}" % (view, view))
        time.sleep(0.45)
        c.shot(os.path.join(SHOTS, name + ".png"))
    r = c.eval("(function(){var d=document.documentElement;"
               "return {sw:d.scrollWidth,cw:d.clientWidth};})()")
    print("   ", r)
    expect(r["sw"] <= r["cw"] + 1, "no horizontal overflow at 390px", r)

    print("— console")
    for e in c.drain_logs():
        txt = str(e)
        if "error" in txt.lower() and "favicon" not in txt.lower():
            print("   ", txt[:200])

print()
print(("FAIL — %d" % len(fails)) if fails else "ALL_PASS")
for f in fails:
    print("   -", f)
sys.exit(1 if fails else 0)
