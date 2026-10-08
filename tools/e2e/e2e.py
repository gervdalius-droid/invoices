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
    # NOT localStorage.clear() + reload: the app saves on beforeunload, so the
    # reload writes the old state straight back. Reset in memory, then persist.
    c.eval("adopt({});saveNow();EDIT=null;WB=null;go('dash')")
    time.sleep(0.5)

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

    print("— važtaraštis from that invoice")
    r = c.eval("""(function(){
      S.settings.wbPlace='Vilnius';
      S.fleet=[{id:'f1',plate:'JAG 470',make:'Mercedes Sprinter',trailer:''}];
      S.drivers=[{id:'d1',name:'Jonas Jonaitis',doc:'AA123456'},
                 {id:'d2',name:'Petras Petraitis',doc:'BB998877'}];
      newWaybill(S.invoices[0]);
      WB.lines[0].packs=6; WB.lines[0].weight=241.5;
      WB.lines[1].packs=2; WB.lines[1].weight=98.4;
      WB.vehicle='JAG 470 Mercedes Sprinter';
      WB.drivers=[{name:'Jonas Jonaitis',doc:'AA123456'},{name:'Petras Petraitis',doc:'BB998877'}];
      WB.unloadDate=addDays(today(),1);
      var okSave=commitWaybill();
      var tt=wbTotals(S.waybills[0]);
      return {okSave:okSave,no:WB.no,linked:WB.invoiceId===S.invoices[0].id,
              consignee:WB.consignee.name,consigneeCode:WB.consignee.code,
              unload:WB.unloadAddr,packs:tt.packs,weight:tt.weight,value:tt.value,
              cargo:WB.lines.length,wbNext:S.settings.wbNext,invNext:S.settings.next,
              crew:wbDrivers(WB).length,crewNames:wbDriverNames(WB)};
    })()""")
    print("   ", json.dumps(r, ensure_ascii=False)[:340])
    expect(r.get("okSave") is True, "waybill saved")
    expect(r.get("linked"), "waybill linked to the invoice")
    expect(r.get("no", "").startswith("V"), "waybill uses its own series", r.get("no"))
    expect(r.get("invNext") == 2 and r.get("wbNext") == 2, "the two counters advance independently", r)
    expect(r.get("consigneeCode"), "consignee carries the registry company code")
    expect(r.get("unload"), "delivery address prefilled from the buyer")
    expect(r.get("cargo") == 2, "both invoice lines became cargo", r.get("cargo"))
    expect(r.get("packs") == 8, "packages summed", r.get("packs"))
    expect(abs(r.get("weight", 0) - 339.9) < 0.01, "gross weight summed", r.get("weight"))
    expect(abs(r.get("value", 0) - 5130) < 0.01, "cargo value equals the invoice net", r.get("value"))
    expect(r.get("crew") == 2, "a two-driver crew is held", r.get("crew"))
    expect(r.get("crewNames") == "Jonas Jonaitis, Petras Petraitis", "both names joined", r.get("crewNames"))

    print("— printed važtaraštis")
    r = c.eval("""(function(){
      var w={document:{open:function(){},close:function(){},write:function(h){window.__wb=h}}};
      var real=window.open; window.open=function(){return w};
      printWaybill(S.waybills[0]); window.open=real;
      var d=window.__wb||'';
      return {len:d.length,
              title:d.indexOf('KROVINIO VAŽTARAŠTIS')>=0,
              consignor:d.indexOf('Mano Įmonė UAB')>=0,
              consignee:d.indexOf('MAXIMA LT, UAB')>=0,
              vehicle:d.indexOf('JAG 470 Mercedes Sprinter')>=0,
              driver:d.indexOf('Jonas Jonaitis')>=0,
              driver2:d.indexOf('Petras Petraitis')>=0,
              licences:d.indexOf('AA123456')>=0 && d.indexOf('BB998877')>=0,
              invoiceRef:d.indexOf(S.invoices[0].no)>=0,
              sigs:(d.match(/class="sig"/g)||[]).length,
              rows:(d.match(/<tr><td class="c">\\d+<\\/td>/g)||[]).length};
    })()""")
    print("   ", json.dumps(r, ensure_ascii=False))
    expect(r.get("title"), "titled KROVINIO VAŽTARAŠTIS")
    expect(r.get("consignor"), "consignor printed")
    expect(r.get("consignee"), "consignee printed")
    expect(r.get("vehicle"), "vehicle printed")
    expect(r.get("driver") and r.get("driver2"), "both drivers printed")
    expect(r.get("licences"), "both licence numbers printed")
    expect(r.get("invoiceRef"), "related invoice number printed")
    expect(r.get("sigs") == 3, "three signature blocks", r.get("sigs"))
    expect(r.get("rows") == 2, "both cargo rows printed", r.get("rows"))

    print("— cloud config")
    r = c.eval("(function(){var d=Cloud.defaults();"
               "return {preset:Cloud.preset(),url:d.url,ws:d.workspace,table:d.table,"
               "hasKey:(d.key||'').length>20,email:d.email,tableFallback:(Cloud.cfg=null,Cloud.table())};})()")
    print("   ", json.dumps(r, ensure_ascii=False))
    expect(r.get("tableFallback") == "invoice_workspaces", "table falls back when unconfigured")
    if r.get("preset"):
        expect(r.get("url", "").startswith("https://"), "preset carries a project URL")
        expect(r.get("hasKey"), "preset carries a key")
        expect(r.get("ws"), "preset names a workspace id")
        print("    (cloud-config.js present: %s / %s)" % (r.get("ws"), r.get("table")))
    else:
        print("    (no cloud-config.js on this machine - preset checks skipped)")

    print("— screens")
    for view, name in [("dash", "1-dashboard"), ("invoices", "2-invoices"),
                       ("editor", "3-editor"), ("waybills", "4-waybills"),
                       ("waybill", "5-waybill"), ("customers", "6-customers"),
                       ("settings", "7-settings")]:
        c.eval("if('%s'==='editor'){openInvoice(S.invoices[0].id)}"
               "else if('%s'==='waybill'){openWaybill(S.waybills[0].id)}else{go('%s')}"
               % (view, view, view))
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
