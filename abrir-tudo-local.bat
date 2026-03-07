@echo off
setlocal

cd /d "%~dp0"

start "Gerenciador Python" cmd /k "\"%~dp0abrir-manager-python.bat\""
start "Site PHP Local" cmd /k "\"%~dp0abrir-site-php-local.bat\""

endlocal
