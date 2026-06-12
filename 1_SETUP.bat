@echo off
chcp 65001 >nul
title Setup - Monitor Think Tanks
echo.
echo =========================================
echo   نصب و راه‌اندازی پایش اندیشکده‌ها
echo =========================================
echo.

:: بررسی وجود Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [خطا] Python نصب نیست.
    echo لطفاً از https://www.python.org/downloads/ نصب کنید
    echo و گزینه "Add Python to PATH" را تیک بزنید.
    pause
    exit /b 1
)

echo [OK] Python پیدا شد.
echo.

:: نصب کتابخانه‌ها
echo در حال نصب کتابخانه‌ها...
pip install -r "%~dp0requirements.txt" -q
if %errorlevel% neq 0 (
    echo [خطا] نصب کتابخانه‌ها ناموفق بود.
    pause
    exit /b 1
)
echo [OK] کتابخانه‌ها نصب شدند.
echo.

:: تست ارسال به تلگرام
echo در حال تست ارسال پیام به تلگرام...
python -c "from dotenv import load_dotenv; import os, sys, requests; load_dotenv(); token=os.getenv('TELEGRAM_BOT_TOKEN','').strip(); chat=os.getenv('TELEGRAM_CHAT_ID','').strip(); missing=not token or not chat; print('[خطا] TELEGRAM_BOT_TOKEN یا TELEGRAM_CHAT_ID در .env تنظیم نشده است.' if missing else '', end=''); sys.exit(1) if missing else None; r=requests.post(f'https://api.telegram.org/bot{token}/sendMessage', json={'chat_id':chat,'text':'✅ سیستم پایش اندیشکده‌ها با موفقیت نصب شد!'}, timeout=10); print('[OK] تلگرام کار می‌کند.' if r.ok else '[خطا] ' + r.text); sys.exit(0 if r.ok else 1)"
if %errorlevel% neq 0 (
    echo [!] تست تلگرام ناموفق بود. فایل .env را بررسی کنید.
)
echo.

:: ایجاد تسک زمان‌بندی‌شده (نیاز به Admin)
echo در حال تنظیم زمان‌بندی خودکار...
set SCRIPT=%~dp0tools\main.py
for /f "tokens=*" %%p in ('where python') do set PY=%%p

schtasks /create /tn "Monitor Think Tanks" /tr "\"%PY%\" \"%SCRIPT%\"" /sc daily /st 09:00 /f >nul 2>&1
if %errorlevel%==0 (echo [OK] تسک ساعت 9 صبح ایجاد شد.) else (echo [!] برای تسک، این فایل را راست‌کلیک کرده و "Run as administrator" بزنید.)

echo.
echo =========================================
echo   تمام! هر روز ساعت 9 صبح
echo   نتایج به تلگرام شما ارسال می‌شود.
echo =========================================
echo.
pause
