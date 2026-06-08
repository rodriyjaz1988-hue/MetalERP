@echo off
echo ============================================
echo  MetalERP - Generando ejecutable Windows
echo ============================================
echo.

REM Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no esta instalado.
    echo Descargalo de https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/4] Instalando dependencias...
pip install flask pyinstaller --quiet

echo [2/4] Compilando ejecutable...
pyinstaller --onefile --noconsole ^
  --name "MetalERP" ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --hidden-import=flask ^
  --hidden-import=werkzeug ^
  --hidden-import=jinja2 ^
  --hidden-import=click ^
  --hidden-import=itsdangerous ^
  server.py

echo [3/4] Copiando archivos...
if not exist "dist\database" mkdir "dist\database"
copy INSTRUCCIONES.txt dist\ >nul 2>&1

echo [4/4] Listo.
echo.
echo  El ejecutable esta en la carpeta: dist\MetalERP.exe
echo  Copialo junto con la carpeta dist\ completa al servidor.
echo.
pause
