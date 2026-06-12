@echo off
cd /d "%~dp0"
if not exist ".tmp" mkdir ".tmp"
python tools\main.py --config config_en.yaml >> .tmp\run_en.log 2>&1
