@echo off
REM Deja que los tornos (red 192.168.10.x) entren al FTP del Monitor de planta.
REM Ejecutar con clic derecho > "Ejecutar como administrador".
REM Solo abre los puertos del FTP (21 y 60000-60009) para pythonw.exe y python.exe,
REM y solo desde la red de los tornos 192.168.10.0/24.
net session >nul 2>&1
if errorlevel 1 (
  echo Hay que ejecutarlo como administrador: clic derecho ^> Ejecutar como administrador.
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="Monitor de planta FTP" >nul 2>&1
netsh advfirewall firewall add rule name="Monitor de planta FTP" dir=in action=allow program="C:\Python314\pythonw.exe" protocol=TCP localport=21,60000-60009 remoteip=192.168.10.0/24 profile=any
netsh advfirewall firewall add rule name="Monitor de planta FTP" dir=in action=allow program="C:\Python314\python.exe" protocol=TCP localport=21,60000-60009 remoteip=192.168.10.0/24 profile=any
echo.
echo Listo. Regla "Monitor de planta FTP" creada.
pause
