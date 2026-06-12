@echo off
chcp 65001 >nul
title Monitor Think Tanks - Run Now
echo.
echo در حال اجرای پایش...
echo.
python "%~dp0tools\main.py"
echo.
pause
