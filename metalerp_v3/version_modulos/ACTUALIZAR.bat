@echo off
title MetalERP - Actualizar otra instalacion
echo.
echo  Copia el codigo de esta carpeta a otra instalacion de MetalERP.
echo  NO toca la base de datos (database\) ni las claves (*_api_key.txt).
echo.
set /p INSTALL_DIR=Ruta de la otra instalacion: 
if not exist "%INSTALL_DIR%\server.py" (
    echo.
    echo ERROR: No se encontro server.py en "%INSTALL_DIR%"
    echo Verifica la ruta e intenta nuevamente.
    pause
    exit /b 1
)
REM Desde el 29/10/2026 el codigo esta repartido: server.py + metalerp\ + templates\
copy /Y "%~dp0server.py" "%INSTALL_DIR%\server.py"
copy /Y "%~dp0requirements.txt" "%INSTALL_DIR%\requirements.txt"
robocopy "%~dp0metalerp" "%INSTALL_DIR%\metalerp" /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP
robocopy "%~dp0templates" "%INSTALL_DIR%\templates" /E /XF *.bak_* /NFL /NDL /NJH /NJS /NP
echo.
echo  Listo. Reinicia el servidor de esa instalacion.
pause
