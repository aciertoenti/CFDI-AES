@echo off
REM Detiene todos los servicios del proyecto CFDI-AES y elimina los contenedores de Docker Compose.
REM Ejecútalo desde cualquier ubicación; el script cambia automáticamente al directorio del proyecto.

cd /d "%~dp0\.."
echo Deteniendo todo el stack CFDI-AES...
docker compose down
if %ERRORLEVEL% neq 0 (
    echo.
    echo Error: Falló la detención del stack. Verifica que Docker Desktop esté en ejecución y que docker compose esté disponible.
    pause
    exit /b %ERRORLEVEL%
)
echo.
echo El stack se ha detenido correctamente.
pause
