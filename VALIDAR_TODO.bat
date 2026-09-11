@echo off
setlocal
cd /d "%~dp0"
echo ========================================
echo VALIDANDO OFICINAIA
echo ========================================
py VALIDAR_TODO.py
pause
