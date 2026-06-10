# Workflow: Arabic Think Tank Monitor

## هدف
بررسی هفتگی وب‌سایت‌های اندیشکده‌های عربی‌زبان و ارسال لینک گزارش‌هایی که حاوی کلیدواژه‌های مشخص (در عنوان یا متن) هستند به بات تلگرام.

---

## ورودی‌ها

| فایل | محتوا |
|------|--------|
| `config.yaml` | لیست اندیشکده‌ها، کلیدواژه‌ها، تنظیمات |
| `.env` | `TELEGRAM_BOT_TOKEN`، `TELEGRAM_CHAT_ID` |
| `.tmp/seen_urls.json` | لینک‌های قبلاً ارسال‌شده (جلوگیری از تکرار) |

---

## مراحل اجرا

```
1. بارگذاری .env و config.yaml
2. بارگذاری seen_urls.json (اگر وجود نداشت، خالی شروع می‌شود)
3. برای هر اندیشکده:
   a. تلاش برای دریافت RSS feed
   b. اگر RSS نداشت یا خالی بود ← scrape HTML
   c. فیلتر لینک‌های قبلاً دیده‌شده
   d. جستجوی کلیدواژه در عنوان/خلاصه
   e. اگر عنوان مطابقت نداشت ← دریافت متن کامل و جستجو
   f. ارسال لینک‌های مطابق به تلگرام
   g. ثبت لینک‌های ارسال‌شده در seen_urls.json
4. نمایش خلاصه نتیجه
```

---

## نحوه اجرا

```bash
# اجرای مستقیم
python tools/main.py

# اجرا با ذخیره لاگ
run_monitor.bat
```

---

## زمان‌بندی هفتگی (Windows Task Scheduler)

1. `taskschd.msc` را باز کن
2. **Create Basic Task** → نام دلخواه
3. **Trigger**: Weekly → روز و ساعت مورد نظر
4. **Action**: Start a Program
   - Program: `C:\Users\javad\Claude\Projects\CSS\run_monitor.bat`
5. **Finish**

لاگ اجرا در `.tmp\run.log` ذخیره می‌شود.

---

## مدیریت خطاها

| خطا | رفتار سیستم |
|------|------------|
| سایت دسترس‌پذیر نیست | ثبت warning، رد شدن سایت، ادامه |
| خطای Telegram API | ثبت error، لینک در seen ثبت **نمی‌شود** (در اجرای بعدی دوباره تلاش می‌شود) |
| خطای encoding | استفاده از `chardet` برای تشخیص کدگذاری |
| تمام سایت‌ها خطا داشتند | خروج با کد 1 |

---

## افزودن اندیشکده جدید

```yaml
# در config.yaml اضافه کن:
think_tanks:
  - name: "نام اندیشکده"
    url: "https://example.com"
    rss: null  # یا آدرس RSS feed
```

---

## تغییر کلیدواژه‌ها

```yaml
# در config.yaml:
keywords:
  - "کلیدواژه جدید"
  - "existing keyword"
```

---

## بازنشانی حافظه (ارسال مجدد همه لینک‌ها)

```bash
# حذف فایل seen_urls برای شروع از صفر
del .tmp\seen_urls.json
```

---

## فایل‌های مرتبط

| فایل | وظیفه |
|------|--------|
| `tools/main.py` | هماهنگ‌کننده اصلی |
| `tools/fetcher.py` | دریافت RSS و scrape HTML |
| `tools/matcher.py` | جستجوی کلیدواژه |
| `tools/notifier.py` | ارسال پیام تلگرام |
| `tools/state.py` | مدیریت seen_urls |
