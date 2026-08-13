FROM python:3.11-slim

WORKDIR /app

# Contexto de build ahora es ./backend (docker-compose.yml,
# refactor/shared-negocio-id, 12 ago 2026) - mismo patron ya probado en
# administracion. COPY selectivo a proposito: NO copiar todo el contexto
# (COPY . /app traeria facturacion/administracion/whatsapp_bot dentro de
# esta imagen).
COPY shared /app/shared
COPY microservices/auth_usuarios /app

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8005
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005"]
