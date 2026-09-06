@echo off
REM Inicia todos los servicios del proyecto CFDI-AES usando Docker Compose.
REM Ejecútalo desde cualquier ubicación; el script cambia automáticamente al directorio del proyecto.

REM Expansion retardada (04 sep 2026, zg1IacA) - necesaria para leer
REM !ERRORLEVEL! DENTRO de bloques if(...) anidados mas abajo. Sin esto,
REM %ERRORLEVEL% dentro de un bloque ya abierto queda congelado con el
REM valor de cuando ese bloque empezo, no se actualiza tras cada comando
REM nuevo que corre adentro - los checks de Tailscale/Funnel de abajo
REM siempre habrian leido el resultado equivocado sin esto.
setlocal enabledelayedexpansion

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

REM Verificar/levantar Tailscale y su Funnel (04 sep 2026, zg1IacA) - NO
REM bloquea el arranque del stack si falla, solo afecta los links
REM publicos de PDF (todo lo demas sigue funcionando en localhost, ver
REM el fallback de storage_client.py). Se checa el codigo de salida real
REM (!ERRORLEVEL!, no texto de error - el mensaje de Windows depende del
REM idioma del sistema).
echo Verificando Tailscale...
tailscale status >nul 2>&1
if !ERRORLEVEL! neq 0 (
    echo Tailscale no esta corriendo. Intentando iniciar el servicio...
    REM Nombre real del servicio confirmado con "sc query state=all" en
    REM esta maquina (04 sep 2026) - si esto falla en otra maquina,
    REM confirmar de nuevo con ese comando antes de asumir el nombre.
    net start Tailscale >nul 2>&1
    if !ERRORLEVEL! neq 0 (
        echo.
        echo AVISO: Tailscale no esta corriendo y no se pudo iniciar automaticamente.
        echo Abre la app de Tailscale manualmente si necesitas acceso publico a PDFs.
        echo Continuando sin Tailscale...
        echo.
    )
)

tailscale status >nul 2>&1
if !ERRORLEVEL! equ 0 (
    tailscale funnel status 2>nul | findstr /c:"127.0.0.1:9000" >nul
    if !ERRORLEVEL! neq 0 (
        echo Levantando Tailscale Funnel en el puerto 9000...
        tailscale funnel --bg 9000 >nul 2>&1
        if !ERRORLEVEL! neq 0 (
            echo AVISO: no se pudo levantar el Tailscale Funnel en el puerto 9000.
            echo Continuando sin Funnel...
        )
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
