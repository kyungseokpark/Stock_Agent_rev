@echo off
setlocal
cd /d "%~dp0"

cd ..
python -m PyInstaller --noconfirm --clean --distpath DAD\dist --workpath DAD\build DAD\StockAgentDAD.spec
if errorlevel 1 (
  echo.
  echo Build failed.
  pause
  exit /b 1
)

copy /y "DAD\dist\StockAgentDAD\StockAgentDAD.exe" "DAD\StockAgentDAD.exe" >nul
if exist "DAD\_internal" rmdir /s /q "DAD\_internal"
xcopy "DAD\dist\StockAgentDAD\_internal" "DAD\_internal" /E /I /Y >nul
if errorlevel 1 (
  echo.
  echo Copy failed.
  pause
  exit /b 1
)
for %%F in (*.html) do copy /y "%%F" "DAD\%%~nxF" >nul 2>nul

rmdir /s /q "DAD\build" 2>nul
rmdir /s /q "DAD\dist" 2>nul

echo.
echo Dad app ready: DAD\StockAgentDAD.exe
pause
