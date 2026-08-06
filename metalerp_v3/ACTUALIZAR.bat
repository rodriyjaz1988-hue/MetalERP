@echo off
echo ====================================================
echo   MetalERP v3 - Actualizador (version React)
echo ====================================================
echo.
echo Este ZIP contiene: server.py, app.html, login.html
echo y los archivos compilados de React (static\dist\)
echo Tu base de datos NO sera modificada.
echo.
echo Ingresa la ruta completa a tu carpeta metalerp_v3
echo (la que contiene server.py e INICIAR_SERVIDOR.bat)
echo.
echo Ejemplo: C:\MetalERP\metalerp_v3
echo.
set /p INSTALL_DIR=Ruta: 

if not exist "%INSTALL_DIR%\server.py" (
    echo.
    echo ERROR: No se encontro server.py en "%INSTALL_DIR%"
    echo Verifica la ruta e intenta nuevamente.
    pause
    exit /b 1
)

echo.
echo Actualizando archivos en: %INSTALL_DIR%
echo.

REM Copy main files
copy /Y "%~dp0server.py" "%INSTALL_DIR%\server.py"
copy /Y "%~dp0templates\app.html" "%INSTALL_DIR%\templates\app.html"
copy /Y "%~dp0templates\login.html" "%INSTALL_DIR%\templates\login.html"

REM Copy React dist folder (with /Y to overwrite, /E for recursive, /I for create dir, /H for hidden)
if not exist "%INSTALL_DIR%\static" mkdir "%INSTALL_DIR%\static"
xcopy /E /I /Y /Q "%~dp0static\dist" "%INSTALL_DIR%\static\dist"

echo.
echo ====================================================
echo   Listo. Reinicia INICIAR_SERVIDOR.bat
echo   Accede a la version React en:
echo     http://localhost:5000/app
echo   Version anterior en:
echo     http://localhost:5000
echo ====================================================
pause
