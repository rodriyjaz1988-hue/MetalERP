@echo off
REM Deja que los tornos (red 192.168.10.x) entren al FTP de Nexus.
REM Ejecutar con clic derecho > "Ejecutar como administrador".
REM Abre solo los puertos del FTP (21 y 60000-60009), y solo desde la red de
REM los tornos 192.168.10.0/24. Vale para cualquier Python o .exe que corra
REM Nexus (antes dependia de que Python estuviera en C:\Python314).
net session >nul 2>&1
if errorlevel 1 (
  echo Hay que ejecutarlo como administrador: clic derecho ^> Ejecutar como administrador.
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="Monitor de planta FTP" >nul 2>&1
netsh advfirewall firewall delete rule name="Nexus FTP tornos" >nul 2>&1
netsh advfirewall firewall add rule name="Nexus FTP tornos" dir=in action=allow protocol=TCP localport=21,60000-60009 remoteip=192.168.10.0/24 profile=any
echo.
echo Listo. Regla "Nexus FTP tornos" creada.
pause
