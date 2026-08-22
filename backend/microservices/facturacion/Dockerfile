FROM python:3.11-slim

# Pango para WeasyPrint (generacion de PDF, dependencia de satcfdi).
# cairo/gdk-pixbuf ya no son necesarios desde WeasyPrint >= 54.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# [REUTILIZABLE TAL CUAL] (21 ago 2026, clasificacion de reutilizacion
# para plantilla base de futuros proyectos SaaS) - el patron de
# build-context ampliado de este bloque (contexto de build = la carpeta
# PADRE de todos los microservicios, COPY selectivo de la carpeta
# compartida + la carpeta del servicio, en vez de copiar todo el
# contexto) aplica igual a cualquier proyecto de microservicios en Python
# que necesite compartir codigo (ej. backend/shared/) entre varios
# servicios sin publicarlo como paquete pip instalable. No depende de
# CFDI/fiscal en absoluto - solo depende de tener docker-compose.yml
# apuntando el "context:" de cada servicio a la carpeta padre en vez de
# a la carpeta del propio servicio. (Las dependencias de apt de arriba -
# Pango/WeasyPrint para PDF - SI son especificas de este servicio, no
# del patron; cada microservicio tendria las suyas segun lo que necesite.)
#
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
