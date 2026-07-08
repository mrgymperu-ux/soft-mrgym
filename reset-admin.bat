@echo off
cd /d "%~dp0"
echo ========================================
echo   Restablecer contrasena del ADMIN
echo ========================================
py -3.12 -m backend.reset_admin
if errorlevel 1 (
    echo.
    echo Hubo un error. Probando con "python"...
    python -m backend.reset_admin
)
echo.
pause
