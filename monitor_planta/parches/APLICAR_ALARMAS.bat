@echo off
chcp 65001 >nul
echo Agregando lectura de alarmas a Nexus...
set PY=python
where python >nul 2>nul || set PY=C:\Python314\python.exe
"%PY%" "%~dp0aplicar_alarmas.py" "%~dp0.."
pause
