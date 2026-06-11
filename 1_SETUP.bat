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
pip install ddgs requests python-dotenv -q
if %errorlevel% neq 0 (
    pip install duckduckgo-search requests python-dotenv -q
)
echo [OK] کتابخانه‌ها نصب شدند.
echo.

:: تست ارسال به تلگرام
echo در حال تست ارسال پیام به تلگرام...
python -c "from dotenv import load_dotenv; import os, requests; load_dotenv(); r=requests.post(f'https://api.telegram.org/bot{os.environ[\"BOT_TOKEN\"]}/sendMessage', json={'chat_id':os.environ['CHAT_ID'],'text':'✅ سیستم پایش اندیشکده‌ها با موفقیت نصب شد!'}); print('[OK] تلگرام کار می‌کند.' if r.ok else '[خطا] ' + r.text)"
echo.

:: ایجاد تسک زمان‌بندی‌شده (نیاز به Admin)
echo در حال تنظیم زمان‌بندی خودکار...
set SCRIPT=%~dp0monitor_think_tanks.py
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
