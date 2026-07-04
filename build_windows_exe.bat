@echo off
setlocal
cd /d "%~dp0"

python -m pip install -r requirements_desktop.txt
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --name StockAgentRev ^
  --add-data "configs;configs" ^
  --add-data "data;data" ^
  --add-data "tickers.csv;." ^
  --add-data "tickers_kr.csv;." ^
  --collect-data matplotlib ^
  --hidden-import ttkbootstrap ^
  desktop_app.py

echo.
echo Build complete: dist\StockAgentRev\StockAgentRev.exe
pause
