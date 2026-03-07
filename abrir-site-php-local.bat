@echo off
setlocal

cd /d "%~dp0"

where php >nul 2>nul
if errorlevel 1 (
  echo PHP nao encontrado no PATH.
  echo Instale o PHP ou ajuste a variavel PATH antes de usar este atalho.
  pause
  exit /b 1
)

start "" "http://127.0.0.1:8080"
php -S 127.0.0.1:8080 router.php

endlocal
