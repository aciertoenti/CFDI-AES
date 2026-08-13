FROM python:3.11-slim

# Pango para WeasyPrint (generacion de PDF, dependencia de satcfdi).
# cairo/gdk-pixbuf ya no son necesarios desde WeasyPrint >= 54.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Contexto de build ahora es ./backend (docker-compose.yml,
# refactor/shared-negocio-id, 12 ago 2026) - mismo patron ya probado en
# administracion y auth_usuarios. COPY selectivo a proposito: NO copiar
# todo el contexto (COPY . /app traeria administracion/auth_usuarios/
# whatsapp_bot dentro de esta imagen).
COPY shared /app/shared
COPY microservices/facturacion /app

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
