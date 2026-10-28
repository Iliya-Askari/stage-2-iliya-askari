# راهنمای اجرای پروژه

این پروژه شامل pipeline مربوط به داده‌های NYC 311 و لایهٔ تحلیلی PostgreSQL برای داده‌های Olist است. برای اجرای کامل روی Windows به Python 3.11 یا جدیدتر، PostgreSQL محلی، اتصال اینترنت، و ۹ فایل CSV منبع Olist نیاز دارید.

## مرحلهٔ اول: دریافت داده‌های Olist

1. مجموعه‌دادهٔ Olist را از [صفحهٔ Kaggle: Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce?resource=download) دانلود کنید. برای دانلود ممکن است لازم باشد وارد حساب Kaggle شوید.
2. فایل ZIP دانلودشده را استخراج کنید.
3. این ۹ فایل CSV را مستقیماً داخل پوشهٔ `data/olist/` پروژه کپی کنید؛ آن‌ها را داخل یک زیرپوشهٔ اضافه قرار ندهید:

```text
data/olist/olist_customers_dataset.csv
data/olist/olist_sellers_dataset.csv
data/olist/olist_products_dataset.csv
data/olist/product_category_name_translation.csv
data/olist/olist_orders_dataset.csv
data/olist/olist_order_items_dataset.csv
data/olist/olist_order_payments_dataset.csv
data/olist/olist_order_reviews_dataset.csv
data/olist/olist_geolocation_dataset.csv
```

پس از کپی، مسیر هر فایل باید دقیقاً مانند بالا باشد. فایل ZIP را داخل `data/olist/` نگه ندارید؛ loader به خود فایل‌های CSV نیاز دارد.

## پیش‌نیازها

1. Python 3.11+ را نصب کنید و مطمئن شوید دستور `python` در PowerShell در دسترس است.
2. PostgreSQL 18 را نصب و سرویس آن را اجرا کنید. اگر PostgreSQL در مسیر پیش‌فرض نصب شده، پوشهٔ `bin` را به `PATH` اضافه کنید:

```powershell
$env:Path += ";C:\Program Files\PostgreSQL\18\bin"
```

3. در ریشهٔ پروژه دیتابیس خالی `stage1` را بسازید. دستور `createdb` در صورت نیاز رمز کاربر postgres را می‌پرسد:

```powershell
createdb -h localhost -U postgres stage1
```

4. آدرس اتصال دیتابیس را برای همین نشست PowerShell تنظیم کنید. `YOUR_PASSWORD` را با رمز PostgreSQL جایگزین کنید:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/stage1"
```

اگر رمز شما نویسه‌هایی مثل `@`, `:`, `/` یا `#` دارد، آن‌ها را در URL به‌شکل percent-encoded بنویسید.

## اجرای مراحل بعد

PostgreSQL باید فعال باشد، دیتابیس خالی `stage1` ساخته شده باشد و `DATABASE_URL` در همان نشست PowerShell تنظیم شده باشد. سپس اجرای کامل را شروع کنید.

## اجرای کامل با یک فایل

از ریشهٔ مخزن این دستور را اجرا کنید:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_project.ps1
```

اسکریپت محیط مجازی `.venv` را می‌سازد، وابستگی‌ها را نصب می‌کند، pipeline دادهٔ NYC 311 را اجرا می‌کند، schema و داده‌های PostgreSQL را بارگذاری می‌کند، تست‌ها را اجرا می‌کند و notebook بنچمارک را اجرا می‌کند. بارگیری مرحلهٔ NYC 311 به اینترنت دسترسی می‌خواهد. اسکریپت، دیتابیس PostgreSQL را خودش نصب یا راه‌اندازی نمی‌کند؛ سرویس باید از قبل فعال باشد.

برای اجرای pipeline و تست‌ها بدون notebook بنچمارک:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_project.ps1 -SkipBenchmark
```

بنچمارک با همین `DATABASE_URL` روی دیتابیس شما اجرا می‌شود و بعضی تنظیمات و indexهای تحلیلی آن را تغییر می‌دهد. برای دیتابیسی اجرا کنید که برای کار این پروژه در نظر گرفته‌اید.

## اجرای تست‌ها به‌تنهایی

پس از نصب وابستگی‌ها و تنظیم `DATABASE_URL`, تست‌ها را از ریشهٔ پروژه اجرا کنید:

```powershell
python -m pytest -q
```

بدون `DATABASE_URL` تست‌های PostgreSQL رد می‌شوند و فقط تست‌های مستقل از دیتابیس اجرا می‌شوند. تست بازبارگذاری کامل Olist اختیاری است و به دیتابیس جداگانهٔ آزمایشی نیاز دارد که نامش به `_test` ختم شود. دیتابیس تست باید جدا از `stage1` باشد، چون این تست داده‌های Olist را پاک و دوباره بارگذاری می‌کند:

```powershell
createdb -h localhost -U postgres stage1_test
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/stage1_test"
python -m pytest -q
```

## اجرای مرحله‌های جداگانه

برای اجرای فقط مرحلهٔ NYC 311 (دریافت و پاک‌سازی داده‌ها):

```powershell
python -m nyc311_factory --config config/default.json -v run
```

برای ساخت schema و بارگذاری دادهٔ مرحلهٔ اول و Olist در PostgreSQL، پس از آماده بودن خروجی مرحلهٔ اول و فایل‌های CSV:

```powershell
python -m nyc311_factory --config config/default.json db-load
```

گزارش طراحی، دلیل انتخاب ساختار و وضعیت اعتبارسنجی در [report.md](report.md) و جزئیات پیاده‌سازی DBA در [docs/challenge2.md](docs/challenge2.md) قرار دارد.
