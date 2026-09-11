@echo off
setlocal
cd /d "%~dp0"
echo ========================================
echo INSTALACION LOCAL OFICINAIA
echo ========================================
py -m pip install --upgrade pip
if errorlevel 1 goto error
py -m pip install -r requirements.txt
if errorlevel 1 goto error
py DIAGNOSTICO_OFICINAIA.py
if errorlevel 1 goto error
echo.
echo Instalacion local finalizada.
echo Para iniciar: INICIAR_LOCAL.bat
pause
exit /b 0
:error
echo.
echo ERROR: la instalacion no pudo completarse.
echo Revisar el mensaje anterior.
pause
exit /b 1
