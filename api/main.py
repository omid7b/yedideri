from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import json, csv, os
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.parent / "data"
app = FastAPI(title="Yedideri API")

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ── Helpers ──────────────────────────────────────────────────────────────────
def load_json(name):
    p = BASE / name
    if not p.exists(): return []
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except: return []

def save_json(name, data):
    with open(BASE / name, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_settings():
    defaults = {
        "usd_to_tl": 34.0, "leather_price": 2.0, "minute_cost": 10.0,
        "waste": 1.20, "cargo": 80.0, "pack": 20.0, "tax": 20.0, "comm": 21.0,
        "t1_limit": 5, "t1_margin": 2.5, "t2_limit": 50, "t2_margin": 2.2,
        "t3_limit": 200, "t3_margin": 1.9, "t4_margin": 1.6,
    }
    s = load_json("settings.json")
    if isinstance(s, dict): defaults.update(s)
    return defaults

def load_products():
    p = BASE / "products.csv"
    if not p.exists(): return []
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))

def calc_price(product, qty, settings):
    s = settings
    try:
        area = (float(product["len"]) * float(product["wid"])) / 100
        leather = area * float(s["leather_price"]) * float(s["usd_to_tl"]) * float(s["waste"])
        labor   = float(product["time"]) * float(s["minute_cost"])
        mat     = float(product.get("mat", 0))
        base    = leather + mat + labor

        qty = float(qty)
        if   qty <= float(s["t1_limit"]): margin = float(s["t1_margin"])
        elif qty <= float(s["t2_limit"]): margin = float(s["t2_margin"])
        elif qty <= float(s["t3_limit"]): margin = float(s["t3_margin"])
        else:                             margin = float(s["t4_margin"])

        raw = base * margin
        sales = round(raw / 10) * 10 - 1 if raw >= 10 else round(raw, 1)
        denom = max(0.1, 1 - ((float(s["tax"]) + float(s["comm"])) / 100))
        tr_raw = (base * float(s["t1_margin"]) + float(s["cargo"]) + float(s["pack"])) / denom
        trendyol = round(tr_raw / 10) * 10 - 1 if tr_raw >= 10 else round(tr_raw, 1)

        return {"base_cost": round(base, 2), "sales_price": sales,
                "trendyol_price": trendyol, "margin": margin}
    except: return None

def inv_totals(inv):
    items    = inv.get("items", [])
    subtotal = sum(float(i.get("qty",1)) * float(i.get("price",0)) for i in items)
    total    = subtotal - float(inv.get("discount", 0) or 0)
    paid     = float(inv.get("paid", 0) or 0)
    return total, paid, total - paid

# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.get("/api/dashboard")
def get_dashboard():
    from datetime import date
    today = date.today()
    invoices  = load_json("invoices.json")
    giderler  = load_json("gider.json")
    customers = load_json("customers.json")

    ciro_ay = gider_ay = bekleyen = 0.0
    bekleyen_list = []
    monthly_ciro  = {}
    monthly_gider = {}
    ay_labels     = []

    for i in range(5, -1, -1):
        m = today.month - i; y = today.year
        while m <= 0: m += 12; y -= 1
        key = f"{y}-{m:02d}"
        monthly_ciro[key] = 0.0; monthly_gider[key] = 0.0
        ay_labels.append(f"{m:02d}/{str(y)[2:]}")

    cust_map = {c["id"]: c for c in customers}

    for inv in invoices:
        total, paid, kalan = inv_totals(inv)
        status = inv.get("status", "beklemede")
        try:
            d_str = inv.get("date", "")
            # try both formats
            try: d = datetime.strptime(d_str, "%Y-%m-%d %H:%M:%S")
            except: d = datetime.strptime(d_str, "%Y-%m-%d")
            if d.month == today.month and d.year == today.year:
                ciro_ay += total
            key = f"{d.year}-{d.month:02d}"
            if key in monthly_ciro: monthly_ciro[key] += total
        except: pass
        if status in ("beklemede", "kismi") and kalan > 0:
            bekleyen += kalan
            c = cust_map.get(inv.get("customer_id", ""), {})
            bekleyen_list.append({
                "name": c.get("name", "?"), "amt": round(kalan, 2),
                "inv_id": inv.get("id", ""), "status": status
            })

    for g in giderler:
        try:
            d = datetime.strptime(g.get("tarih", ""), "%d.%m.%Y")
            if d.month == today.month and d.year == today.year:
                gider_ay += float(g.get("tutar", 0))
            key = f"{d.year}-{d.month:02d}"
            if key in monthly_gider: monthly_gider[key] += float(g.get("tutar", 0))
        except: pass

    net = ciro_ay - gider_ay
    return {
        "kpis": {
            "ciro_ay": round(ciro_ay, 2), "bekleyen": round(bekleyen, 2),
            "gider_ay": round(gider_ay, 2), "net_kar": round(net, 2),
        },
        "bekleyen_list": sorted(bekleyen_list, key=lambda x: -x["amt"])[:8],
        "chart": {
            "labels": ay_labels,
            "ciro":   list(monthly_ciro.values()),
            "gider":  list(monthly_gider.values()),
        },
        "stats": {
            "total_customers": len(customers),
            "total_invoices": len(invoices),
        }
    }

# ── Products ──────────────────────────────────────────────────────────────────
@app.get("/api/products")
def get_products():
    products  = load_products()
    settings  = load_settings()
    result = []
    for p in products:
        r = calc_price(p, 1, settings)
        result.append({**p, **(r or {})})
    return result

# ── Customers ─────────────────────────────────────────────────────────────────
@app.get("/api/customers")
def get_customers():
    customers = load_json("customers.json")
    invoices  = load_json("invoices.json")
    result = []
    for c in customers:
        cid = c["id"]
        c_invs = [i for i in invoices if i.get("customer_id") == cid]
        total_paid = sum(float(i.get("paid", 0)) for i in c_invs)
        total_debt = sum(max(0, inv_totals(i)[2]) for i in c_invs
                         if i.get("status") in ("beklemede", "kismi"))
        result.append({**c, "invoice_count": len(c_invs),
                        "total_paid": round(total_paid, 2),
                        "total_debt": round(total_debt, 2)})
    return result

@app.get("/api/customers/{cid}/invoices")
def get_customer_invoices(cid: str):
    invoices = load_json("invoices.json")
    return [i for i in invoices if i.get("customer_id") == cid]

# ── Invoices ──────────────────────────────────────────────────────────────────
@app.get("/api/invoices")
def get_invoices():
    invoices  = load_json("invoices.json")
    customers = {c["id"]: c for c in load_json("customers.json")}
    result = []
    for inv in invoices:
        total, paid, kalan = inv_totals(inv)
        c = customers.get(inv.get("customer_id", ""), {})
        result.append({**inv, "customer_name": c.get("name", "?"),
                        "total": round(total, 2), "paid_total": round(paid, 2),
                        "kalan": round(kalan, 2)})
    return sorted(result, key=lambda x: x.get("date", ""), reverse=True)

class PaymentIn(BaseModel):
    tutar: float
    note: Optional[str] = ""

@app.post("/api/invoices/{inv_id}/payment")
def add_payment(inv_id: str, body: PaymentIn):
    invoices = load_json("invoices.json")
    inv = next((i for i in invoices if i["id"] == inv_id), None)
    if not inv: raise HTTPException(404, "Fatura bulunamadı")

    pmts = list(inv.get("payments", []))
    pmts.append({"tarih": datetime.now().strftime("%d.%m.%Y %H:%M"),
                  "tutar": body.tutar, "not": body.note})
    inv["payments"] = pmts
    inv["paid"] = str(float(inv.get("paid", 0)) + body.tutar)

    total, paid, kalan = inv_totals(inv)
    inv["status"] = "odendi" if kalan <= 0.01 else ("kismi" if paid > 0 else "beklemede")

    save_json("invoices.json", invoices)
    return {"ok": True, "kalan": round(kalan, 2), "status": inv["status"],
            "payments": inv["payments"]}

# ── Gider ─────────────────────────────────────────────────────────────────────
@app.get("/api/gider")
def get_gider():
    return sorted(load_json("gider.json"),
                  key=lambda x: x.get("created", ""), reverse=True)

class GiderIn(BaseModel):
    tarih: str
    aciklama: str
    kategori: str
    tutar: float
    note: Optional[str] = ""

@app.post("/api/gider")
def add_gider(body: GiderIn):
    giderler = load_json("gider.json")
    new = {"id": int(datetime.now().timestamp() * 1000),
            "tarih": body.tarih, "aciklama": body.aciklama,
            "kategori": body.kategori, "tutar": body.tutar,
            "not": body.note, "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    giderler.append(new)
    save_json("gider.json", giderler)
    return new

@app.delete("/api/gider/{gid}")
def delete_gider(gid: int):
    giderler = [g for g in load_json("gider.json") if g.get("id") != gid]
    save_json("gider.json", giderler)
    return {"ok": True}

# ── Settings ──────────────────────────────────────────────────────────────────
@app.get("/api/settings")
def get_settings():
    return load_settings()

@app.post("/api/settings")
def save_settings_endpoint(data: dict):
    save_json("settings.json", data)
    return {"ok": True}

# ── Stok ──────────────────────────────────────────────────────────────────────
@app.get("/api/stok")
def get_stok():
    return load_json("stok.json")

# ── Serve frontend ────────────────────────────────────────────────────────────
frontend = Path(__file__).parent.parent / "static"
if frontend.exists():
    app.mount("/", StaticFiles(directory=str(frontend), html=True), name="static")
