@echo off
title Crear acceso directo Nexus
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0CREAR_ACCESO_NEXUS.ps1"
pause
