@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo. > jarvis_error.log
venv\Scripts\python.exe -X utf8 main.py --gui 2>> jarvis_error.log
