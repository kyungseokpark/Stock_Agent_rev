@echo off
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
  python desktop_app.py
  pause
  exit /b %errorlevel%
)

py -3 desktop_app.py
if not %errorlevel%==0 (
  echo.
  echo Python is not installed or the existing virtual environment is broken.
  echo Install Python 3.11+ first, then run:
  echo   python -m pip install -r requirements_desktop.txt
)
pause
