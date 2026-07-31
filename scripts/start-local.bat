@echo off
REM Levanta api_gateway y auth_usuarios sin Docker (uvicorn directo).
REM Lee las variables del .env de la raiz y las exporta en esta sesion
REM antes de arrancar los servicios (ej. JWT_SECRET), para no tener que
REM hacerlo manualmente cada vez.
REM Requiere que ya hayas hecho "pip install -r requirements.txt" en
REM backend/api_gateway y backend/microservices/auth_usuarios.

cd /d "%~dp0\.."
set "ROOT=%cd%"

if not exist ".env" (
    echo.
    echo ERROR: No se encontro el archivo .env en la raiz del proyecto.
    echo Copia .env.example como .env y rellena los valores antes de continuar.
    pause
    exit /b 1
)

echo Cargando variables de entorno desde .env ...
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" set "%%A=%%B"
)

if "%JWT_SECRET%"=="" (
    echo.
    echo ERROR: JWT_SECRET no esta definido en .env
    pause
    exit /b 1
)

echo JWT_SECRET cargado desde .env.
echo.
echo Iniciando API Gateway en el puerto 8000...
start "CFDI - API Gateway (8000)" /D "%ROOT%\backend\api_gateway" cmd /k uvicorn main:app --reload --port 8000

echo Iniciando Auth / Usuarios en el puerto 8005...
start "CFDI - Auth Usuarios (8005)" /D "%ROOT%\backend\microservices\auth_usuarios" cmd /k uvicorn main:app --reload --port 8005

echo.
echo Ambos servicios se iniciaron en ventanas de cmd separadas y heredaron
echo las variables de .env (incluido JWT_SECRET).
echo.
echo   API Gateway:      http://localhost:8000/health
echo   Auth / Usuarios:  http://localhost:8005/health
echo.
echo NOTA: el Gateway enruta a los demas microservicios (facturacion,
echo administracion, addenda_aes, reportes, whatsapp_bot) usando los
echo nombres de red de Docker definidos en SERVICES dentro de
echo backend/api_gateway/main.py. Si esos servicios no estan tambien
echo accesibles con esos hostnames, /health respondera pero el proxy
echo hacia ellos fallara.
echo.
echo Para detener los servicios, cierra las dos ventanas de cmd abiertas.
pause
