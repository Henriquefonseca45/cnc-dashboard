@echo off
cd /d "%~dp0"
if exist "venv\Scripts\activate.bat" call "venv\Scripts\activate.bat"
python -m backend.init_db
if errorlevel 1 exit /b %errorlevel%
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
