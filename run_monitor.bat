@echo off
cd /d "%~dp0"
if not exist ".tmp" mkdir ".tmp"
python tools\main.py >> .tmp\run.log 2>&1
