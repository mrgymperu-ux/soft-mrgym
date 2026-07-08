@echo off
echo ========================================
echo     Soft-MrGym Lite - Version Offline
echo ========================================
echo.
echo Abriendo sistema en tu navegador...
echo.
echo Caracteristicas:
echo  - No requiere instalacion
echo  - 100%% gratuito
echo  - Funciona sin internet
echo  - Datos guardados en tu navegador
echo.
echo ========================================
echo.

REM Abrir el archivo HTML en el navegador predeterminado
start "" "%~dp0frontend-lite\index.html"

echo Sistema abierto correctamente!
echo.
echo Para usar el sistema:
echo 1. El navegador se abrira automaticamente
echo 2. Si no, abre el archivo: frontend-lite/index.html
echo 3. Los datos se guardan automaticamente en tu navegador
echo.
echo NOTA: Para respaldar tus datos, usa la funcion de 
echo        exportar/importar cuando este disponible
echo.
pause