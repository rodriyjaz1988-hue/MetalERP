@echo off
rem Corre el diagnostico de la conexion con el torno (solo mira, no cambia nada).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0DIAGNOSTICO_TORNO.ps1"
echo.
pause
