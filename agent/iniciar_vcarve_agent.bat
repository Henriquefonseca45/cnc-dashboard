@echo off
cd /d "%~dp0"
py -3 vcarve_agent.py
if errorlevel 1 (
  python vcarve_agent.py
)
pause
