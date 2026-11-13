@echo off
chcp 65001 >nul
echo Agregando lectura de alarmas a Nexus...
where python >nul 2>nul && (python "%~dp0aplicar_alarmas.py" "%~dp0..") || (C:\Python314\python.exe "%~dp0aplicar_alarmas.py" "%~dp0..")
pause
