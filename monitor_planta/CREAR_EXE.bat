@echo off
chcp 65001 >nul
rem Arma MonitorPlanta.exe (con ventana propia) a partir de monitor.py.
rem Hay que correrlo en la carpeta del Monitor (C:\MetalERP\monitor_planta).
cd /d "%~dp0"
echo Instalando lo necesario para armar el programa...
python -m pip install --upgrade flask pywebview pyinstaller || goto error
echo Armando MonitorPlanta.exe...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name MonitorPlanta ^
  --add-data "templates;templates" --hidden-import monitor --hidden-import fanuc_focas monitor_ventana.py || goto error
copy /y "dist\MonitorPlanta.exe" "%~dp0MonitorPlanta.exe" >nul || goto error
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del /q MonitorPlanta.spec 2>nul
echo Creando accesos directos (escritorio e inicio de Windows)...
powershell -NoProfile -Command "$s=New-Object -ComObject WScript.Shell; foreach($d in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Startup'))){ $l=$s.CreateShortcut((Join-Path $d 'Monitor de planta.lnk')); $l.TargetPath='%~dp0MonitorPlanta.exe'; $l.WorkingDirectory='%~dp0'; $l.Save() }"
echo.
echo Listo: MonitorPlanta.exe. Tiene acceso directo en el escritorio y arranca solo al prender la PC.
pause
exit /b 0
:error
echo.
echo No se pudo armar el programa. Revisa los mensajes de arriba.
pause
exit /b 1
