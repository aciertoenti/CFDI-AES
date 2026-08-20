FROM python:3.11-slim

WORKDIR /app

# Contexto de build es ./backend (mismo patron ya probado en
# facturacion/administracion/auth_usuarios/ia). COPY selectivo a proposito:
# NO copiar todo el contexto (COPY . /app traeria los demas microservicios
# dentro de esta imagen).
# requirements.txt copiado por separado (antes del resto del codigo) para
# que pip install y playwright install queden cacheados entre rebuilds -
# editar main.py ya no invalida estas dos capas pesadas (~300MB de
# Chromium + dependencias X11).
COPY microservices/portal_automation/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium
# xauth no viene incluido en --with-deps pero xvfb-run lo requiere
# (headless=False necesita Xvfb + xauth para el display virtual).
RUN apt-get update && apt-get install -y --no-install-recommends xauth \
    && rm -rf /var/lib/apt/lists/*

COPY shared /app/shared
COPY microservices/portal_automation /app

EXPOSE 8008
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8008"]
