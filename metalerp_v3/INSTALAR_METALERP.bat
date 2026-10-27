@echo off
setlocal EnableExtensions
title MetalERP - Instalador
REM ==========================================================
REM  Instala MetalERP en esta PC:
REM   1. Python (si falta)
REM   2. Codigo de MetalERP bajado de GitHub
REM   3. Librerias (flask, groq)
REM   4. Acceso directo en el escritorio + permiso en el firewall
REM  Si MetalERP ya estaba instalado, solo actualiza el codigo:
REM  la base de datos y las claves NO se tocan.
REM ==========================================================

set "CARPETA=C:\MetalERP\metalerp_v3"
set "RAMA=main"
set "ZIP_URL=https://github.com/rodriyjaz1988-hue/MetalERP/archive/refs/heads/%RAMA%.zip"
set "PY_URL=https://www.python.org/ftp/python/3.13.1/python-3.13.1-amd64.exe"
set "TEMPO=%TEMP%\metalerp_instalador"
set "ORIGEN=%~dp0"

echo.
echo  ==========================================
echo   MetalERP - Instalador
echo  ==========================================
echo.
echo  Se va a instalar en: %CARPETA%
set /p "OTRA=Enter para seguir, o escribi otra carpeta: "
if not "%OTRA%"=="" set "CARPETA=%OTRA%"

if exist "%TEMPO%" rmdir /S /Q "%TEMPO%"
mkdir "%TEMPO%"

REM ---------- 1. Python ----------
echo.
echo [1/4] Buscando Python...
set "PY="
python --version >nul 2>&1 && set "PY=python"
if not defined PY (
    py -3 --version >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
    echo       No esta instalado. Descargando Python 3.13...
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing '%PY_URL%' -OutFile '%TEMPO%\python.exe'"
    if not exist "%TEMPO%\python.exe" goto error_red
    echo       Instalando Python, puede tardar unos minutos...
    start "" /wait "%TEMPO%\python.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
    if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
        set "PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe""
    ) else (
        echo  ERROR: Python no se pudo instalar.
        echo  Instalalo a mano desde https://www.python.org/downloads/
        echo  marcando "Add python.exe to PATH", y volve a correr este archivo.
        goto fin_error
    )
)
echo       OK

REM ---------- 2. Codigo de MetalERP ----------
echo.
echo [2/4] Descargando MetalERP de GitHub...
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing '%ZIP_URL%' -OutFile '%TEMPO%\metalerp.zip'"
if not exist "%TEMPO%\metalerp.zip" goto error_red
powershell -NoProfile -Command "Expand-Archive -Force '%TEMPO%\metalerp.zip' '%TEMPO%\zip'"
set "NUEVO=%TEMPO%\zip\MetalERP-%RAMA%\metalerp_v3"
if not exist "%NUEVO%\server.py" (
    echo  ERROR: el archivo bajado no tiene metalerp_v3\server.py
    goto fin_error
)
if not exist "%CARPETA%" mkdir "%CARPETA%"
REM Copia el codigo pero NO la carpeta database ni __pycache__
robocopy "%NUEVO%" "%CARPETA%" /E /XD database __pycache__ /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
    echo  ERROR: no se pudieron copiar los archivos a %CARPETA%
    goto fin_error
)
if not exist "%CARPETA%\database" mkdir "%CARPETA%\database"

REM Base de datos: nunca se pisa una existente.
if exist "%CARPETA%\database\metalerp.db" (
    echo       Base de datos existente: se conserva.
) else if exist "%ORIGEN%metalerp.db" (
    copy /Y "%ORIGEN%metalerp.db" "%CARPETA%\database\metalerp.db" >nul
    echo       Base de datos copiada desde la carpeta del instalador.
) else (
    echo       Sin base de datos: se crea una vacia al arrancar.
    echo       Usuario: admin  Clave: admin123  ^(cambiala despues^)
)

REM Claves del asistente (opcionales): se copian si estan junto al instalador
for %%K in (groq_api_key.txt fish_api_key.txt) do (
    if exist "%ORIGEN%%%K" if not exist "%CARPETA%\%%K" copy /Y "%ORIGEN%%%K" "%CARPETA%\%%K" >nul
)
echo       OK

REM ---------- 3. Librerias ----------
echo.
echo [3/4] Instalando librerias de Python...
%PY% -m pip install --upgrade pip --quiet --disable-pip-version-check
%PY% -m pip install -r "%CARPETA%\requirements.txt" --quiet --disable-pip-version-check
if errorlevel 1 (
    echo  ERROR: fallo la instalacion de librerias. Revisa la conexion a internet.
    goto fin_error
)
echo       OK

REM ---------- 4. Acceso directo y firewall ----------
echo.
echo [4/4] Creando acceso directo en el escritorio...
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\MetalERP.lnk'); $s.TargetPath='%CARPETA%\INICIAR_SERVIDOR.bat'; $s.WorkingDirectory='%CARPETA%'; $s.Save()"
netsh advfirewall firewall show rule name="MetalERP" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="MetalERP" dir=in action=allow protocol=TCP localport=5000 >nul 2>&1
    if errorlevel 1 (
        echo       Aviso: para que otras PCs entren por la red, corre este
        echo       instalador con clic derecho ^> "Ejecutar como administrador".
    )
)
echo       OK

rmdir /S /Q "%TEMPO%" >nul 2>&1
echo.
echo  ==========================================
echo   Listo. MetalERP quedo instalado en:
echo   %CARPETA%
echo.
echo   Para usarlo: doble clic en "MetalERP" del escritorio
echo   y abri http://localhost:5000 en el navegador.
echo  ==========================================
echo.
set /p "ABRIR=Queres arrancarlo ahora? (S/N): "
if /I "%ABRIR%"=="S" (
    start "" "http://localhost:5000"
    cd /d "%CARPETA%"
    %PY% server.py
)
exit /b 0

:error_red
echo  ERROR: no se pudo descargar. Revisa la conexion a internet.
:fin_error
echo.
pause
exit /b 1
