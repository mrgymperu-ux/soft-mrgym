@echo off
chcp 65001 >nul
echo.
echo ========================================
echo     Soft-MrGym - Sistema de Gestion
echo ========================================
echo.

:: Verificar Python
py -3.12 --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python 3.12 no encontrado
    pause
    exit /b 1
)

:: Ir a la carpeta del proyecto
cd /d D:\Soft-MrGym

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
start "Soft-MrGym Backend" cmd /k "cd /d D:\Soft-MrGym && py -3.12 -m uvicorn backend.main:app --reload"

:: Esperar 3 segundos para que el backend arranque
echo [3/4] Esperando que el backend inicie...
timeout /t 3 /nobreak >nul

:: Iniciar frontend-staff en ventana separada
echo [4/4] Iniciando frontends...
start "Soft-MrGym Staff" cmd /k "cd /d D:\Soft-MrGym\frontend-staff && py -3.12 -m http.server 3000"
start "Soft-MrGym Alumno" cmd /k "cd /d D:\Soft-MrGym\frontend-alumno && py -3.12 -m http.server 3001"
start "Soft-MrGym Profesores" cmd /k "cd /d D:\Soft-MrGym\frontend-profesor && py -3.12 -m http.server 3002"

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
