@echo off
title MetalERP - Servidor del Taller
echo.
echo  ==========================================
echo   MetalERP - Servidor iniciando...
echo  ==========================================
echo.
echo  Mantene esta ventana ABIERTA mientras uses el sistema.
echo  Para detener el servidor, cerra esta ventana.
echo.

REM Opcion 1: Si existe el .exe compilado
if exist "MetalERP.exe" (
    MetalERP.exe
    goto fin
)

REM Opcion 2: Si no hay .exe, usar Python directamente
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: No se encontro Python ni MetalERP.exe
    echo Instala Python desde https://www.python.org/downloads/
    pause
    exit /b 1
)
pip install flask --quiet
python server.py

:fin
pause