@echo off
chcp 65001 >nul
echo.
echo ========================================
echo     Soft-Gym - Sistema de Gestion
echo ========================================
echo.

:: Verificar Python
py -3.12 --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python 3.12 no encontrado
    pause
    exit /b 1
)

:: Usar siempre la carpeta donde se encuentra este archivo.
:: Esto permite ejecutar copias del proyecto sin apuntar al original.
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

:: Instalar/actualizar dependencias siempre (rapido si ya estan instaladas)
echo [0/4] Verificando dependencias del backend...
py -3.12 -m pip install -r requirements.txt --quiet --disable-pip-version-check
if %errorlevel% neq 0 (
    echo ERROR al instalar dependencias. Revisa tu conexion a internet.
    pause
    exit /b 1
)

:: Inicializar BD si no existe
if not exist "sql_app.db" (
    echo [1/4] Inicializando base de datos...
    py -3.12 -m backend.init_db
    if %errorlevel% neq 0 (
        echo ERROR al inicializar la base de datos
        pause
        exit /b 1
    )
) else (
    echo [1/4] Base de datos existente, omitiendo init...
)

:: Iniciar backend en ventana separada
echo [2/4] Iniciando backend en http://localhost:8000 ...
start "Soft-Gym Backend" /D "%PROJECT_DIR%" cmd /k "py -3.12 -m uvicorn backend.main:app --reload"

:: Esperar 3 segundos para que el backend arranque
echo [3/4] Esperando que el backend inicie...
timeout /t 3 /nobreak >nul

:: Iniciar frontend-staff en ventana separada
echo [4/4] Iniciando frontends...
start "Soft-Gym Staff" /D "%PROJECT_DIR%frontend-staff" cmd /k "py -3.12 -m http.server 3000"
start "Soft-Gym Alumno" /D "%PROJECT_DIR%frontend-alumno" cmd /k "py -3.12 -m http.server 3001"
start "Soft-Gym Profesores" /D "%PROJECT_DIR%frontend-profesor" cmd /k "py -3.12 -m http.server 3002"

:: Esperar 2 segundos y abrir navegador
timeout /t 2 /nobreak >nul

echo.
echo ========================================
echo  Backend:        http://localhost:8000
echo  API Docs:       http://localhost:8000/docs
echo  Panel Staff:    http://localhost:3000/login.html
echo  Portal Alumno:  http://localhost:3001/login.html
echo  Zona Profesores: http://localhost:3002/login.html
echo ========================================
echo.

:: Abrir el panel staff en el navegador
start http://localhost:3000/login.html

echo Presiona cualquier tecla para cerrar esta ventana...
echo (Los servidores seguiran corriendo en sus propias ventanas)
pause >nul
