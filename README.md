# Yedideri Web — راهنمای نصب

## ساختار پروژه
```
yedideri_web/
├── api/
│   └── main.py          ← FastAPI backend
├── data/
│   ├── invoices.json
│   ├── customers.json
│   ├── gider.json
│   ├── settings.json
│   ├── products.csv
│   └── stok.json
├── static/
│   └── index.html       ← کل frontend در یک فایل
├── requirements.txt
├── Procfile
└── README.md
```

## اجرا در لوکال
```bash
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
# باز کن: http://localhost:8000
```

## دیپلوی رایگان روی Render.com

1. کد رو آپلود کن روی GitHub (repo جدید بساز)
2. برو به https://render.com → New → Web Service
3. GitHub repo رو وصل کن
4. تنظیمات:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
   - **Plan:** Free
5. Deploy کن — آدرس `https://yedideri-xxx.onrender.com` میگیری

> ⚠️ نکته: پلن رایگان Render بعد از ۱۵ دقیقه بی‌کاری sleep میشه.
> اولین بار که باز میکنی ۳۰ ثانیه طول میکشه بیدار بشه — بعدش سریعه.

## دیپلوی رایگان روی Railway.app

1. برو https://railway.app → New Project → Deploy from GitHub
2. همون repo رو انتخاب کن
3. Railway خودش Procfile رو میخونه و deploy میکنه
4. ماهانه ۵ دلار credit رایگان داره — برای استفاده شخصی کافیه

## نکته مهم — دیتا
فعلاً دیتا روی فایل‌های JSON ذخیره میشه.
برای استفاده جدی، دیتابیس SQLite یا PostgreSQL اضافه کن.
