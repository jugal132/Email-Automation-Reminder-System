@echo off
cd /d "%~dp0"

call .venv\Scripts\activate.bat

python main.py

echo.
echo ====================================
echo Project execution completed.
echo ====================================
pause