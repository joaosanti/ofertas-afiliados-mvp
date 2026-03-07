@echo off
setlocal

cd /d "%~dp0automacao_ofertas"

if not exist ".venv\Scripts\activate.bat" (
  echo Ambiente virtual nao encontrado em automacao_ofertas\.venv
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"

where uvicorn >nul 2>nul
if errorlevel 1 (
  echo Uvicorn nao encontrado no ambiente virtual.
  echo Tente instalar as dependencias do projeto primeiro.
  pause
  exit /b 1
)

start "" "http://127.0.0.1:8010/manager"
uvicorn app.main:app --reload --port 8010

endlocal
