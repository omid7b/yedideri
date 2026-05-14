from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import json, csv, os
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.parent / "data"
app = FastAPI(title="Yedideri API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Helpers ───────────────────────────────────────────────────────────────────
def load_json(name, default=None):
    p = BASE / name
    if not p.exists(): return default if default is not None else []
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except: return default if default is not None else []

def save_json(name, data):
    with open(BASE / name, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_settings():
    d = {"usd_to_tl":34.0,"leather_price":2.0,"minute_cost":10.0,"waste":1.20,
         "cargo":80.0,"pack":20.0,"tax":20.0,"comm":21.0,
         "t1_limit":5,"t1_margin":2.5,"t2_limit":50,"t2_margin":2.2,
         "t3_limit":200,"t3_margin":1.9,"t4_margin":1.6}
    s = load_json("settings.json", {})
    if isinstance(s, dict): d.update(s)
    return d

def load_products():
    p = BASE / "products.csv"
    if not p.exists(): return []
    with open(p, encoding="utf-8") as f: return list(csv.DictReader(f))

def save_products(rows):
    if not rows: return
    p = BASE / "products.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader(); w.writerows(rows)

def make_psych(v):
    if v < 10: return round(v, 1)
    return round(v / 10) * 10 - 1

def calc_price(product, qty, s):
    try:
        area = (float(product["len"]) * float(product["wid"])) / 100
        leather = area * float(s["leather_price"]) * float(s["usd_to_tl"]) * float(s["waste"])
        labor = float(product["time"]) * float(s["minute_cost"])
        mat = float(product.get("mat", 0))
        base = leather + mat + labor
        qty = float(qty)
        if   qty <= float(s["t1_limit"]): margin = float(s["t1_margin"])
        elif qty <= float(s["t2_limit"]): margin = float(s["t2_margin"])
        elif qty <= float(s["t3_limit"]): margin = float(s["t3_margin"])
        else:                             margin = float(s["t4_margin"])
        sales = make_psych(base * margin)
        denom = max(0.1, 1 - ((float(s["tax"]) + float(s["comm"])) / 100))
        tr_raw = (base * float(s["t1_margin"]) + float(s["cargo"]) + float(s["pack"])) / denom
        trendyol = make_psych(tr_raw)
        return {"base_cost": round(base,2), "sales_price": sales,
                "trendyol_price": trendyol, "margin": margin}
    except: return None

def inv_totals(inv):
    subtotal = sum(float(i.get("qty",1)) * float(i.get("price",0)) for i in inv.get("items",[]))
    total = subtotal - float(inv.get("discount",0) or 0)
    paid = float(inv.get("paid",0) or 0)
    return total, paid, total - paid

def next_inv_id():
    invs = load_json("invoices.json")
    now = datetime.now()
    prefix = f"YD-{now.year}{now.month:02d}-"
    nums = [int(i["id"].split("-")[-1]) for i in invs if i.get("id","").startswith(prefix)]
    n = max(nums, default=0) + 1
    return f"{prefix}{n:04d}"

# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.get("/api/dashboard")
def get_dashboard():
    from datetime import date
    today = date.today()
    invoices  = load_json("invoices.json")
    giderler  = load_json("gider.json")
    customers = {c["id"]: c for c in load_json("customers.json")}
    ciro_ay = gider_ay = bekleyen = 0.0
    bekleyen_list = []
    monthly = {}
    for i in range(5, -1, -1):
        m = today.month - i; y = today.year
        while m <= 0: m += 12; y -= 1
        monthly[f"{y}-{m:02d}"] = {"ciro": 0.0, "gider": 0.0}
    for inv in invoices:
        total, paid, kalan = inv_totals(inv)
        try:
            d_str = inv.get("date","")
            try: d = datetime.strptime(d_str, "%Y-%m-%d %H:%M:%S")
            except: d = datetime.strptime(d_str[:10], "%Y-%m-%d")
            if d.month == today.month and d.year == today.year: ciro_ay += total
            key = f"{d.year}-{d.month:02d}"
            if key in monthly: monthly[key]["ciro"] += total
        except: pass
        if inv.get("status") in ("beklemede","kismi") and kalan > 0:
            bekleyen += kalan
            c = customers.get(inv.get("customer_id",""), {})
            bekleyen_list.append({"name": c.get("name","?"), "amt": round(kalan,2),
                                   "inv_id": inv.get("id",""), "status": inv.get("status")})
    for g in giderler:
        try:
            d = datetime.strptime(g.get("tarih",""), "%d.%m.%Y")
            if d.month == today.month and d.year == today.year: gider_ay += float(g.get("tutar",0))
            key = f"{d.year}-{d.month:02d}"
            if key in monthly: monthly[key]["gider"] += float(g.get("tutar",0))
        except: pass
    keys = sorted(monthly.keys())
    return {
        "kpis": {"ciro_ay": round(ciro_ay,2), "bekleyen": round(bekleyen,2),
                 "gider_ay": round(gider_ay,2), "net_kar": round(ciro_ay - gider_ay,2)},
        "bekleyen_list": sorted(bekleyen_list, key=lambda x: -x["amt"])[:8],
        "chart": {"labels": [k[5:]+"/"+k[2:4] for k in keys],
                  "ciro": [monthly[k]["ciro"] for k in keys],
                  "gider": [monthly[k]["gider"] for k in keys]},
        "stats": {"total_customers": len(customers), "total_invoices": len(invoices)}
    }

# ── Products ──────────────────────────────────────────────────────────────────
@app.get("/api/products")
def get_products(qty: float = 1):
    s = load_settings()
    return [{**p, **(calc_price(p, qty, s) or {})} for p in load_products()]

@app.post("/api/products")
def create_product(data: dict):
    rows = load_products()
    if any(r["code"] == data.get("code") for r in rows):
        raise HTTPException(400, "Bu kod zaten var")
    rows.append(data)
    save_products(rows)
    return data

@app.put("/api/products/{code}")
def update_product(code: str, data: dict):
    rows = load_products()
    for i, r in enumerate(rows):
        if r["code"] == code:
            rows[i] = {**r, **data}
            save_products(rows)
            return rows[i]
    raise HTTPException(404)

@app.delete("/api/products/{code}")
def delete_product(code: str):
    rows = [r for r in load_products() if r["code"] != code]
    save_products(rows)
    return {"ok": True}

# ── Customers ─────────────────────────────────────────────────────────────────
@app.get("/api/customers")
def get_customers():
    customers = load_json("customers.json")
    invoices = load_json("invoices.json")
    result = []
    for c in customers:
        cid = c["id"]
        c_invs = [i for i in invoices if i.get("customer_id") == cid]
        total_paid = sum(float(i.get("paid",0)) for i in c_invs)
        total_debt = sum(max(0, inv_totals(i)[2]) for i in c_invs
                         if i.get("status") in ("beklemede","kismi"))
        result.append({**c, "invoice_count": len(c_invs),
                        "total_paid": round(total_paid,2), "total_debt": round(total_debt,2)})
    return result

class CustomerIn(BaseModel):
    name: str
    phone: Optional[str] = ""
    email: Optional[str] = ""
    city: Optional[str] = ""
    platform: Optional[str] = ""
    address: Optional[str] = ""

@app.post("/api/customers")
def create_customer(body: CustomerIn):
    customers = load_json("customers.json")
    new = {**body.dict(), "id": f"C{int(datetime.now().timestamp()*1000)}",
            "created": datetime.now().strftime("%Y-%m-%d")}
    customers.append(new)
    save_json("customers.json", customers)
    return new

@app.put("/api/customers/{cid}")
def update_customer(cid: str, body: CustomerIn):
    customers = load_json("customers.json")
    for i, c in enumerate(customers):
        if c["id"] == cid:
            customers[i] = {**c, **body.dict()}
            save_json("customers.json", customers)
            return customers[i]
    raise HTTPException(404)

@app.delete("/api/customers/{cid}")
def delete_customer(cid: str):
    customers = [c for c in load_json("customers.json") if c["id"] != cid]
    save_json("customers.json", customers)
    return {"ok": True}

@app.get("/api/customers/{cid}/invoices")
def get_customer_invoices(cid: str):
    return [i for i in load_json("invoices.json") if i.get("customer_id") == cid]

# ── Invoices ──────────────────────────────────────────────────────────────────
@app.get("/api/invoices")
def get_invoices():
    invoices = load_json("invoices.json")
    customers = {c["id"]: c for c in load_json("customers.json")}
    result = []
    for inv in invoices:
        total, paid, kalan = inv_totals(inv)
        c = customers.get(inv.get("customer_id",""), {})
        # Fix status based on actual numbers
        if kalan <= 0.01: status = "odendi"
        elif paid > 0: status = "kismi"
        else: status = "beklemede"
        result.append({**inv, "customer_name": c.get("name","?"),
                        "total": round(total,2), "paid_total": round(paid,2),
                        "kalan": round(max(0, kalan),2), "status": status})
    return sorted(result, key=lambda x: x.get("date",""), reverse=True)

class InvoiceIn(BaseModel):
    customer_id: str
    items: List[dict]
    discount: Optional[float] = 0
    payment: Optional[str] = "Nakit"
    notes: Optional[str] = ""
    date: Optional[str] = ""

@app.post("/api/invoices")
def create_invoice(body: InvoiceIn):
    invoices = load_json("invoices.json")
    d = body.dict()
    d["id"] = next_inv_id()
    d["date"] = d["date"] or datetime.now().strftime("%Y-%m-%d")
    d["paid"] = "0"
    d["status"] = "beklemede"
    d["payments"] = []
    invoices.append(d)
    save_json("invoices.json", invoices)
    return d

@app.put("/api/invoices/{inv_id}")
def update_invoice(inv_id: str, body: InvoiceIn):
    invoices = load_json("invoices.json")
    for i, inv in enumerate(invoices):
        if inv["id"] == inv_id:
            invoices[i] = {**inv, **body.dict()}
            save_json("invoices.json", invoices)
            return invoices[i]
    raise HTTPException(404)

@app.delete("/api/invoices/{inv_id}")
def delete_invoice(inv_id: str):
    invoices = [i for i in load_json("invoices.json") if i["id"] != inv_id]
    save_json("invoices.json", invoices)
    return {"ok": True}

class PaymentIn(BaseModel):
    tutar: float
    note: Optional[str] = ""

@app.post("/api/invoices/{inv_id}/payment")
def add_payment(inv_id: str, body: PaymentIn):
    invoices = load_json("invoices.json")
    inv = next((i for i in invoices if i["id"] == inv_id), None)
    if not inv: raise HTTPException(404)
    pmts = list(inv.get("payments", []))
    pmts.append({"tarih": datetime.now().strftime("%d.%m.%Y %H:%M"),
                  "tutar": body.tutar, "not": body.note})
    inv["payments"] = pmts
    inv["paid"] = str(float(inv.get("paid",0)) + body.tutar)
    total, paid, kalan = inv_totals(inv)
    inv["status"] = "odendi" if kalan <= 0.01 else ("kismi" if paid > 0 else "beklemede")
    save_json("invoices.json", invoices)
    return {"ok": True, "kalan": round(max(0,kalan),2), "status": inv["status"],
            "payments": inv["payments"]}

@app.delete("/api/invoices/{inv_id}/payment/{idx}")
def delete_payment(inv_id: str, idx: int):
    invoices = load_json("invoices.json")
    inv = next((i for i in invoices if i["id"] == inv_id), None)
    if not inv: raise HTTPException(404)
    pmts = inv.get("payments", [])
    if idx >= len(pmts): raise HTTPException(404)
    removed = pmts.pop(idx)
    inv["payments"] = pmts
    inv["paid"] = str(max(0, float(inv.get("paid",0)) - float(removed["tutar"])))
    total, paid, kalan = inv_totals(inv)
    inv["status"] = "odendi" if kalan <= 0.01 else ("kismi" if paid > 0 else "beklemede")
    save_json("invoices.json", invoices)
    return {"ok": True}

# ── Print (HTML templates) ────────────────────────────────────────────────────
@app.get("/api/print/invoice/{inv_id}")
def print_invoice(inv_id: str, currency: str = "TL"):
    invoices = load_json("invoices.json")
    inv = next((i for i in invoices if i["id"] == inv_id), None)
    if not inv: raise HTTPException(404)
    customers = {c["id"]: c for c in load_json("customers.json")}
    c = customers.get(inv.get("customer_id",""), {})
    s = load_settings()
    usd_tl = float(s["usd_to_tl"])
    is_usd = (currency == "USD")
    sym = "$" if is_usd else "₺"
    def fp(v): return f"${float(v):,.2f}" if is_usd else f"{float(v):,.0f} ₺"
    def fa(v): return f"{float(v)*usd_tl:,.0f} ₺" if is_usd else f"${float(v)/usd_tl:,.2f}"
    rows_html = ""
    subtotal = 0.0
    for idx, item in enumerate(inv.get("items",[]), 1):
        qty = float(item.get("qty",1)); price = float(item.get("price",0))
        total = qty * price; subtotal += total
        rows_html += f"""<tr>
          <td>{idx}</td><td>{item.get("code","")}</td>
          <td>{item.get("desc", item.get("name",""))}</td>
          <td class="right">{qty:.0f}</td>
          <td class="right">{fp(price)}</td>
          <td class="right" style="color:#888;font-size:9px">{fa(price)}</td>
          <td class="right">{fp(total)}</td></tr>"""
    discount = float(inv.get("discount",0))
    total_amt = subtotal - discount
    paid = float(inv.get("paid",0))
    remaining = max(0, total_amt - paid)
    status = inv.get("status","beklemede")
    sc = {"odendi":"status-paid","beklemede":"status-pending","kismi":"status-partial"}.get(status,"status-pending")
    st = {"odendi":"Ödendi","beklemede":"Beklemede","kismi":"Kısmi Ödeme"}.get(status, status)
    notes_html = f'<div class="notes-box"><div class="notes-label">Notlar</div>{inv["notes"]}</div>' if inv.get("notes","").strip() else ""
    curr_label = "USD INVOICE" if is_usd else "FATURA"
    HTML_INV = """<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8">
<title>Fatura - {inv_id}</title>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700;900&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Montserrat',sans-serif;background:#fff}}
.page{{width:148mm;min-height:210mm;margin:0 auto;padding:8mm 10mm;background:#fff}}
.header{{display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid #000;padding-bottom:10px;margin-bottom:12px}}
.brand{{font-size:20px;font-weight:900;letter-spacing:3px}}
.brand-sub{{font-size:8px;color:#555;margin-top:3px;line-height:1.5}}
.inv-info{{text-align:right}}
.inv-title{{font-size:18px;font-weight:900;letter-spacing:2px}}
.inv-id{{font-size:12px;font-weight:700;margin-top:4px}}
.inv-date{{font-size:10px;color:#555;margin-top:2px}}
.customer-bar{{background:#f5f5f5;border:1px solid #ddd;border-radius:4px;padding:8px 12px;margin-bottom:10px;font-size:10px}}
.customer-bar strong{{font-size:11px}}
table{{width:100%;border-collapse:collapse;margin-bottom:10px;font-size:10px}}
th{{background:#000;color:#fff;padding:6px 8px;text-align:left;font-size:9px;text-transform:uppercase;letter-spacing:.5px}}
th.right,td.right{{text-align:right}}
td{{padding:6px 8px;border-bottom:1px solid #eee}}
tr:nth-child(even) td{{background:#f9f9f9}}
.totals{{display:flex;justify-content:flex-end;margin-bottom:10px}}
.totals-box{{width:55%}}
.total-row{{display:flex;justify-content:space-between;padding:4px 0;font-size:10px;border-bottom:1px solid #eee}}
.total-final{{font-size:13px;font-weight:900;border-top:2px solid #000;padding-top:6px;margin-top:3px}}
.status-box{{display:inline-block;padding:3px 12px;border-radius:12px;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;margin-top:4px}}
.status-paid{{background:#d4edda;color:#155724}}
.status-pending{{background:#fff3cd;color:#856404}}
.status-partial{{background:#cce5ff;color:#004085}}
.notes-box{{background:#f9f9f9;border:1px solid #eee;border-radius:4px;padding:8px;margin-bottom:10px;font-size:9px;color:#444}}
.notes-label{{font-size:9px;font-weight:700;text-transform:uppercase;color:#888;margin-bottom:4px}}
.payment-box{{display:flex;gap:8px;margin-bottom:10px}}
.pay-card{{flex:1;border-radius:6px;padding:10px 14px;text-align:center}}
.pay-label{{font-size:8px;text-transform:uppercase;letter-spacing:1px;font-weight:700;margin-bottom:4px}}
.pay-amount{{font-size:18px;font-weight:900}}
.pay-sub{{font-size:8px;margin-top:2px}}
.pay-total{{background:#f5f5f5;border:2px solid #000}}
.pay-paid{{background:#d4edda;border:2px solid #28a745;color:#155724}}
.pay-kalan{{background:#fff3cd;border:3px solid #ffc107;color:#856404}}
.pay-kalan .pay-amount{{font-size:22px;color:#856404}}
.footer{{text-align:center;border-top:1px solid #eee;padding-top:8px;font-size:8px;color:#999}}
@media print{{@page{{margin:0;size:A5 portrait}}body{{background:#fff}}.page{{width:100%;padding:8mm 10mm}}}}
</style></head><body><div class="page">
<div class="header">
  <div><div class="brand">YEDİDERİ</div>
  <div class="brand-sub">İKİTELLİ OSB MAH. AYKOSAN 4'LÜ B BLOK No:1 B<br>
  Başakşehir / İSTANBUL | Tel: 0552 626 88 07<br>VKN: 4541621861 | www.yedideri.com</div></div>
  <div class="inv-info">
    <div class="inv-title">{curr_label}</div>
    <div class="inv-id">No: {inv_id}</div>
    <div class="inv-date">Tarih: {inv_date}</div>
    <div><span class="status-box {sc}">{st}</span></div>
  </div>
</div>
<div class="customer-bar">
  <strong>{cname}</strong> &nbsp;|&nbsp; {cphone} &nbsp;|&nbsp; {caddr}
</div>
<table><thead><tr>
  <th>#</th><th>Ürün</th><th>Açıklama</th>
  <th class="right">Adet</th><th class="right">Birim (TL)</th>
  <th class="right">Birim (USD)</th><th class="right">Toplam</th>
</tr></thead><tbody>{rows}</tbody></table>
<div class="totals"><div class="totals-box">
  <div class="total-row"><span>Ara Toplam</span><span>{subtotal}</span></div>
  <div class="total-row"><span>İndirim</span><span>-{discount}</span></div>
  <div class="total-row total-final"><span>TOPLAM</span><span>{total}</span></div>
</div></div>
<div class="payment-box">
  <div class="pay-card pay-total"><div class="pay-label">Genel Toplam</div>
  <div class="pay-amount">{total}</div><div class="pay-sub">Ödeme: {payment}</div></div>
  <div class="pay-card pay-paid"><div class="pay-label">Ödenen</div>
  <div class="pay-amount">{paid_fmt}</div><div class="pay-sub">Tahsil edildi</div></div>
  <div class="pay-card pay-kalan"><div class="pay-label">⚠ Kalan Borç</div>
  <div class="pay-amount">{remaining_fmt}</div><div class="pay-sub">Ödenmesi bekleniyor</div></div>
</div>
{notes}
<div class="footer">Teşekkür ederiz! &nbsp;|&nbsp; www.yedideri.com &nbsp;|&nbsp; YEDİDERİ © {year}
<br><br><button onclick="window.print()" style="margin-top:8px;padding:6px 20px;background:#000;color:#fff;border:none;cursor:pointer;font-family:Montserrat;font-weight:700;letter-spacing:1px">YAZDIR</button>
</div></div></body></html>"""
    from fastapi.responses import HTMLResponse
    html = HTML_INV.format(
        inv_id=inv_id, curr_label=curr_label, inv_date=inv.get("date",""),
        sc=sc, st=st, cname=c.get("name",""), cphone=c.get("phone",""),
        caddr=c.get("address","").replace("\n"," "),
        rows=rows_html, subtotal=fp(subtotal), discount=fp(discount),
        total=fp(total_amt), payment=inv.get("payment",""),
        paid_fmt=fp(paid), remaining_fmt=fp(remaining),
        notes=notes_html, year=datetime.now().year
    )
    return HTMLResponse(html)

@app.get("/api/print/cargo")
def print_cargo(name: str, addr: str = "", city: str = "", phone: str = ""):
    from fastapi.responses import HTMLResponse
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700;900&display=swap" rel="stylesheet">
<style>
body{{margin:0;padding:20px;background:#f0f0f0;display:flex;justify-content:center;font-family:Montserrat,sans-serif}}
.page{{width:148mm;height:210mm;background:#fff;display:flex;justify-content:center;align-items:center;border:1px solid #ddd}}
.card{{width:90%;height:90%;border:2px solid #000;border-radius:8px;display:flex;flex-direction:column}}
.sender{{padding:18px 15px;border-bottom:1px dashed #000;background:#fafafa;text-align:center}}
.s-label{{font-size:10px;font-weight:700;color:#666;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px}}
.s-name{{font-size:18px;font-weight:900;letter-spacing:2px}}
.s-detail{{font-size:10px;color:#333;margin-top:4px;line-height:1.4}}
.receiver{{padding:28px 20px;flex-grow:1;display:flex;flex-direction:column;align-items:center}}
.r-label{{font-size:10px;font-weight:700;color:#666;text-transform:uppercase;letter-spacing:1px}}
.r-name{{font-size:26px;font-weight:900;text-transform:uppercase;margin:8px 0;padding-bottom:6px;border-bottom:2px solid #000}}
.r-addr{{font-size:15px;font-weight:600;line-height:1.6;margin:16px 0;max-width:90%;text-align:center}}
.r-city{{font-size:48px;font-weight:900;border:3px solid #000;padding:8px 36px;letter-spacing:6px;margin-top:auto}}
.r-phone{{margin-top:20px;font-size:22px;font-weight:800;border-top:1px solid #eee;padding-top:12px;width:100%;text-align:center}}
@media print{{body{{background:none;padding:0}}.page{{border:none}}}}
</style></head><body>
<div class="page"><div class="card">
<div class="sender">
  <div class="s-label">GÖNDERİCİ</div>
  <div class="s-name">YEDİDERİ</div>
  <div class="s-detail">İKİTELLİ OSB MAH. AYKOSAN 4'LÜ B BLOK No:1 B, Başakşehir / İSTANBUL<br>
  <strong>Tel:</strong> 0552 626 88 07 | <strong>VKN:</strong> 4541621861</div>
</div>
<div class="receiver">
  <div class="r-label">ALICI</div>
  <div class="r-name">{name}</div>
  <div class="r-addr">{addr.replace(chr(10),"<br>")}</div>
  <div class="r-city">{city.upper()}</div>
  <div class="r-phone">TEL: {phone}</div>
</div>
</div></div>
<script>setTimeout(()=>window.print(),500)</script>
</body></html>"""
    return HTMLResponse(html)

# ── Gider ─────────────────────────────────────────────────────────────────────
@app.get("/api/gider")
def get_gider():
    return sorted(load_json("gider.json"), key=lambda x: x.get("created",""), reverse=True)

class GiderIn(BaseModel):
    tarih: str
    aciklama: str
    kategori: str
    tutar: float
    note: Optional[str] = ""

@app.post("/api/gider")
def add_gider(body: GiderIn):
    giderler = load_json("gider.json")
    new = {"id": int(datetime.now().timestamp()*1000), "tarih": body.tarih,
            "aciklama": body.aciklama, "kategori": body.kategori,
            "tutar": body.tutar, "not": body.note,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    giderler.append(new)
    save_json("gider.json", giderler)
    return new

@app.put("/api/gider/{gid}")
def update_gider(gid: int, body: GiderIn):
    giderler = load_json("gider.json")
    for i, g in enumerate(giderler):
        if g.get("id") == gid:
            giderler[i] = {**g, "tarih": body.tarih, "aciklama": body.aciklama,
                            "kategori": body.kategori, "tutar": body.tutar, "not": body.note}
            save_json("gider.json", giderler)
            return giderler[i]
    raise HTTPException(404)

@app.delete("/api/gider/{gid}")
def delete_gider(gid: int):
    save_json("gider.json", [g for g in load_json("gider.json") if g.get("id") != gid])
    return {"ok": True}

# ── Stok ──────────────────────────────────────────────────────────────────────
@app.get("/api/stok")
def get_stok(): return load_json("stok.json", {})

@app.post("/api/stok/uretim")
def add_uretim(data: dict):
    stok = load_json("stok.json", {})
    key = f"{data['code']}-{data.get('renk','')}" if data.get('renk') else data['code']
    stok[key] = stok.get(key, 0) + int(data.get("qty", 1))
    save_json("stok.json", stok)
    return {"ok": True, "stok": stok.get(key)}

@app.post("/api/stok/satis")
def add_satis(data: dict):
    stok = load_json("stok.json", {})
    key = f"{data['code']}-{data.get('renk','')}" if data.get('renk') else data['code']
    current = stok.get(key, 0)
    if current < int(data.get("qty", 1)):
        raise HTTPException(400, "Yetersiz stok")
    stok[key] = current - int(data.get("qty", 1))
    save_json("stok.json", stok)
    return {"ok": True, "stok": stok.get(key)}

# ── Settings ──────────────────────────────────────────────────────────────────
@app.get("/api/settings")
def get_settings(): return load_settings()

@app.post("/api/settings")
def save_settings_ep(data: dict):
    save_json("settings.json", data)
    return {"ok": True}

# ── Özel Hesap (Teklif) ───────────────────────────────────────────────────────
@app.post("/api/teklif/hesapla")
def teklif_hesapla(data: dict):
    s = load_settings()
    uzunluk = float(data.get("uzunluk", 0))
    genislik = float(data.get("genislik", 0))
    sure = float(data.get("sure", 0))
    mat = float(data.get("mat", 0))
    logo_tl = float(data.get("logo_tl", 0))
    klise_tl = float(data.get("klise_tl", 0))
    tirajlar = data.get("tirajlar", [10, 50, 100, 500, 1000])
    margin = float(data.get("margin", s["t1_margin"]))
    alan = (uzunluk * genislik) / 100.0
    deri_tl = alan * float(s["leather_price"]) * float(s["usd_to_tl"]) * float(s["waste"])
    iscilik = sure * float(s["minute_cost"])
    results = []
    for qty in tirajlar:
        logo = logo_tl + (klise_tl / max(qty, 1))
        maliyet = deri_tl + iscilik + mat + logo
        satis = make_psych(maliyet * margin)
        toplam = satis * qty
        results.append({"qty": qty, "birim": satis, "toplam": round(toplam, 2),
                         "maliyet": round(maliyet, 2)})
    return {"results": results, "deri_tl": round(deri_tl, 2),
            "iscilik": round(iscilik, 2), "alan": round(alan, 2)}

# ── Serve frontend ────────────────────────────────────────────────────────────
from fastapi.staticfiles import StaticFiles
frontend = Path(__file__).parent.parent / "static"
if frontend.exists():
    app.mount("/", StaticFiles(directory=str(frontend), html=True), name="static")
