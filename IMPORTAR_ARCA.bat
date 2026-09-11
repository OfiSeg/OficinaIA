@echo off
setlocal
cd /d "%~dp0"
set "PADRON="
for %%F in (apellidoNombreDenominacion*.zip) do if not defined PADRON set "PADRON=%%F"
if not defined PADRON (
  echo No encontre apellidoNombreDenominacion*.zip en esta carpeta.
  echo Copia el ZIP del padron dentro de esta carpeta y volve a ejecutar este archivo.
  pause
  exit /b 1
)
echo ========================================
echo IMPORTANDO PADRON ARCA
echo Archivo: %PADRON%
echo ========================================
py importar_padron_arca.py "%PADRON%"
if errorlevel 1 goto error
echo.
echo Importacion ARCA finalizada.
pause
exit /b 0
:error
echo.
echo ERROR: la importacion ARCA fallo.
echo Revisar el mensaje anterior.
pause
exit /b 1
