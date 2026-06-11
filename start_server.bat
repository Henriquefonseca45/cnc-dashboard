@echo off
cd /d C:\Users\servi\cnc-dashboard
call venv\Scripts\activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000
