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

REM Por default el Funnel NO se apaga (04 sep 2026, zg1IacA): Tailscale
REM puede estar sirviendo otras cosas en esta maquina ademas de este
REM proyecto, no se asume que solo lo usa CFDI-AES.
set /p apagarfunnel="Apagar tambien el Tailscale Funnel? (s/N): "
if /i "%apagarfunnel%"=="s" (
    tailscale funnel 9000 off
    echo Funnel apagado.
) else (
    echo Funnel sin cambios.
)

pause
