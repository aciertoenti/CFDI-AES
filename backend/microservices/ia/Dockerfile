FROM python:3.11-slim

WORKDIR /app

# Contexto de build ahora es ./backend (docker-compose.yml,
# refactor/shared-internal-key, 14 ago 2026) - mismo patron ya probado en
# facturacion/administracion/auth_usuarios (12-13 ago 2026). ia se habia
# quedado fuera de ese refactor porque hasta ahora no necesitaba nada de
# backend/shared/. COPY selectivo a proposito: NO copiar todo el contexto
# (COPY . /app traeria facturacion/administracion/auth_usuarios/
# whatsapp_bot dentro de esta imagen).
COPY shared /app/shared
COPY microservices/ia /app

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8007
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8007"]
