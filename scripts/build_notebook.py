"""Generates solution.ipynb (kept so the notebook can be regenerated; outputs come from executing it)."""

import nbformat as nbf

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = []

cells.append(md("""# کارخانه داده ۳۱۱ نیویورک — چالش ۱
این نوتبوک فقط **روایت** می‌کند؛ منطق اصلی (دریافت، اعتبارسنجی، قرنطینه، پاک‌سازی، اتصال، خروجی‌ها) در پکیج `src/nyc311_factory` است.
ترتیب: ۱) اجرای کارخانه ۲) گزارش کیفیت و قرنطینه ۳) تحلیل اکتشافی (EDA) ۴) یافته‌ها."""))
cells.append(code("""import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

SEED = 42  # تنها جای تعریف seed در نوتبوک
rng = np.random.default_rng(SEED)

from nyc311_factory.config import load_config
from nyc311_factory.pipeline import run_all
from nyc311_factory import analysis

CONFIG_PATH = os.environ.get("NYC311_CONFIG", "config/default.json")
cfg = load_config(CONFIG_PATH)
print("config:", CONFIG_PATH, "| window:", cfg.window.start, "->", cfg.window.end, "| agencies:", cfg.agencies)"""))

cells.append(md("""## ۱) اجرای کارخانه
چرا اینجا اجرا می‌کنیم؟ تا نوتبوک از «پوشه خالی» قابل تکرار باشد. اگر داده خام قبلاً کامل دانلود شده باشد، هیچ درخواست شبکه‌ای زده نمی‌شود (idempotent)؛
در غیر این صورت دریافت دسته‌ای از همان نقطه‌ای که مانده ادامه می‌یابد."""))
cells.append(code("""summary, result, manifest = run_all(cfg)
manifest = analysis.load_manifest(cfg.paths.curated)
pd.Series(manifest["records"]["quarantine_by_reason"], name="count").to_frame()"""))
cells.append(code("""rec = manifest["records"]
print({k: rec[k] for k in ("raw", "valid", "quarantined")})
print("join:", {k: v for k, v in manifest["join"].items() if k != "note"})
print("http:", manifest["http"]["total_http_requests"], "requests; minimum possible:", manifest["http"]["minimum_possible_requests"])
print(manifest["http"]["rationale"])"""))

cells.append(md("""## ۲) کیفیت داده
گزارش زیر توسط کارخانه تولید شده (دست‌نویس نیست): درصد خالی، تعداد یکتا و دامنه هر ستون. ستون‌هایی با درصد خالی بالا (مثلاً `closed_date`) معنای کسب‌وکاری دارند: پرونده هنوز باز است."""))
cells.append(code("""quality = pd.read_csv(os.path.join(cfg.paths.curated, "data_quality_report.csv"))
quality"""))
cells.append(code("""pd.Series(manifest["cleaning_stats"], name="count").to_frame()"""))

cells.append(md("""## ۳) آمار توصیفی و توزیع مدت‌زمان رسیدگی
فقط پرونده‌های بسته‌شده مدت رسیدگی دارند. پرونده‌های باز **سانسور راست‌گرا (right-censored)** هستند؛ آن‌ها را حذف نمی‌کنیم بلکه جدا گزارش می‌کنیم."""))
cells.append(code("""df = analysis.load_cases(cfg.paths.curated)
print(df.shape, "| open share: %.2f%%" % (100 * (1 - df["is_closed"].mean())))
df[["resolution_hours", "resolution_days", "population_zip", "created_hour"]].describe().round(2)"""))
cells.append(code("""closed = df[df["is_closed"] == 1]
fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
axes[0].hist(closed["resolution_hours"].clip(upper=closed["resolution_hours"].quantile(0.99)), bins=60)
axes[0].set(title="Raw scale (clipped at p99)", xlabel="hours", ylabel="cases")
axes[1].hist(np.log10(closed["resolution_hours"] + 1), bins=60)
axes[1].set(title="log10(hours + 1)", xlabel="log10 hours")
plt.tight_layout(); plt.show()"""))
cells.append(md("""**نتیجه نمودار ۱:** توزیع به‌شدت راست‌چوله است؛ مقیاس خام دم بلند را پنهان می‌کند و مقیاس لگاریتمی شکل واقعی را نشان می‌دهد.
بنابراین برای مقایسه‌ها از **میانه** و مقیاس لگاریتمی استفاده می‌کنیم، نه میانگین."""))

cells.append(md("""## ۴) داده‌های پرت: بررسی و تعیین تکلیف
حصار Tukey روی `log1p(hours)` محاسبه می‌شود (روی مقیاس خام برای توزیع چوله بی‌معناست). تصمیم: **نگه می‌داریم، حذف نمی‌کنیم** — این‌ها پرونده‌های واقعی‌اند (رسیدگی بسیار کند)
و دقیقاً همان چیزی‌اند که تیم تحلیل می‌خواهد ببیند. فقط اثرشان روی میانگین را گزارش می‌کنیم."""))
cells.append(code("""analysis.outlier_summary(df).round(2)"""))

cells.append(md("""## ۵) رابطه متغیرهای عددی (همبستگی اسپیرمن)
اسپیرمن چون رابطه‌ها لزوماً خطی نیستند و توزیع چوله است."""))
cells.append(code("""corr = analysis.correlation_frame(df)
fig, ax = plt.subplots(figsize=(5.2, 4.2))
im = ax.imshow(corr.values, vmin=-1, vmax=1, cmap="coolwarm")
ax.set_xticks(range(len(corr))); ax.set_xticklabels(corr.columns, rotation=45, ha="right")
ax.set_yticks(range(len(corr))); ax.set_yticklabels(corr.columns)
for i in range(len(corr)):
    for j in range(len(corr)):
        ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center", fontsize=8)
fig.colorbar(im); ax.set_title("Spearman correlation (closed cases)"); plt.tight_layout(); plt.show()"""))
cells.append(md("""**نتیجه نمودار ۲:** اگر همبستگی‌ها نزدیک صفر باشند، ساعت/روز ثبت و جمعیت ZIP به‌تنهایی مدت رسیدگی را توضیح نمی‌دهند؛ عامل اصلی باید نوع شکایت و منطقه باشد (بخش بعد)."""))

cells.append(md("""## ۶) مقایسه متغیرهای دسته‌ای
مدت رسیدگی بر اساس منطقه (borough؛ پرونده‌های با منطقه نامشخص حذف می‌شوند چون جمعیت و مقایسه‌ای ندارند) و بر اساس نوع شکایت."""))
cells.append(code("""known = closed[closed["borough"] != "UNSPECIFIED"]
order = known.groupby("borough")["resolution_hours"].median().sort_values().index
data = [np.log10(known.loc[known["borough"] == b, "resolution_hours"] + 1) for b in order]
fig, ax = plt.subplots(figsize=(8, 3.8))
ax.boxplot(data, tick_labels=list(order), showfliers=False)
ax.set(title="log10(hours + 1) by borough (sorted by median)", ylabel="log10 hours"); plt.xticks(rotation=20); plt.tight_layout(); plt.show()"""))
cells.append(md("""**نتیجه نمودار ۳:** مناطق از نظر میانه مدت رسیدگی تفاوت دارند؛ ترتیب جعبه‌ها همان ترتیب میانه است. این تفاوت را در بخش یافته‌ها عددی می‌کنیم."""))
cells.append(code("""top = closed["complaint_type"].value_counts().head(8).index
med = closed[closed["complaint_type"].isin(top)].groupby("complaint_type")["resolution_hours"].median().sort_values()
fig, ax = plt.subplots(figsize=(8, 3.8))
ax.barh(med.index, med.values); ax.set(title="Median resolution hours, 8 most frequent complaint types", xlabel="hours")
plt.tight_layout(); plt.show()"""))
cells.append(md("""**نتیجه نمودار ۴:** نوع شکایت مدت رسیدگی را قوی‌تر از ساعت ثبت تغییر می‌دهد — با همبستگی‌های بخش ۵ سازگار است."""))

cells.append(md("""## ۷) روند در زمان: «بهتر می‌شود یا بدتر؟»
پاسخ ساده‌لوحانه (میانه ماهانه) گمراه‌کننده است: ماه‌های اخیر هنوز پرونده‌های بسته‌نشده دارند. دو سری را کنار هم می‌گذاریم."""))
cells.append(code("""trend = analysis.monthly_trend(df)
fig, ax1 = plt.subplots(figsize=(9, 3.8))
ax1.plot(trend.index, trend["median_hours_closed"], marker="o", label="median hours (closed cases)")
ax1.set_ylabel("median hours"); ax1.tick_params(axis="x", rotation=60)
ax2 = ax1.twinx(); ax2.plot(trend.index, trend["open_share_pct"], color="tab:red", marker="s", label="% still open")
ax2.set_ylabel("% still open"); ax1.set_title("Resolution time and open share by creation month")
plt.tight_layout(); plt.show()"""))
cells.append(md("""**نتیجه نمودار ۵:** اگر میانه در ماه‌های آخر پایین می‌آید ولی سهم پرونده‌های باز بالا می‌رود، بهبود واقعی نیست؛ اثر سانسور است."""))

cells.append(md("""## ۸) یافته‌های غیربدیهی (جمله‌ها از روی داده ساخته می‌شوند، نه دست‌نویس)
بعد از اجرا با داده واقعی، هر یافته را در `report.md` با همین عددها بنویسید و بررسی کنید که واقعاً «غیربدیهی» است."""))
cells.append(code("""for i, sentence in enumerate(analysis.findings(df), 1):
    print(f"{i}. {sentence}")"""))

cells.append(md("""## ۹) جدول تجمیعی عریض
منطقه × نوع شکایت × ماه؛ شمار و نرخ به‌ازای هر ۱۰٬۰۰۰ نفر جمعیت (جمعیت منطقه = مجموع جمعیت ZIPهای نگاشت‌شده به آن)."""))
cells.append(code("""wide = analysis.load_wide(cfg.paths.curated)
print(wide.shape)
wide.iloc[:5, :8]"""))
cells.append(code("""print(manifest["output_hashes_sha256"])"""))

nb = nbf.v4.new_notebook(cells=cells)
nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
nbf.write(nb, "solution.ipynb")
print("notebook written with", len(cells), "cells")
