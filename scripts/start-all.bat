@echo off
REM Inicia todos los servicios del proyecto CFDI-AES usando Docker Compose.
REM Ejecútalo desde cualquier ubicación; el script cambia automáticamente al directorio del proyecto.

cd /d "%~dp0\.."

REM Verificar que exista el .env
if not exist ".env" (
    echo.
    echo AVISO: No se encontro el archivo .env
    echo Copiando .env.example como .env ...
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo Archivo .env creado. Edita las variables antes de continuar.
    ) else (
        echo ERROR: Tampoco existe .env.example. Crea el archivo .env manualmente.
        pause
        exit /b 1
    )
)

echo Iniciando todo el stack CFDI-AES...
docker compose up --build -d
if %ERRORLEVEL% neq 0 (
    echo.
    echo Error: Fallo el arranque del stack.
    echo Verifica que Docker Desktop este en ejecucion y que docker compose este disponible.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo El stack se ha iniciado correctamente.
echo.
echo   Frontend:        http://localhost:3000
echo   Gateway:         http://localhost:8000
echo   WhatsApp Bot:    http://localhost:8006
echo   MinIO Console:   http://localhost:9001
echo.
echo Documentacion del bot: http://localhost:8006/docs
pause
