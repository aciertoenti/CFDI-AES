FROM python:3.11-slim

WORKDIR /app

# Contexto de build ahora es ./backend (docker-compose.yml,
# refactor/shared-negocio-id, 12 ago 2026) - COPY selectivo a proposito:
# NO copiar todo el contexto (COPY . /app traeria facturacion/auth_usuarios/
# whatsapp_bot dentro de esta imagen). shared/ primero, con __init__.py,
# es un paquete Python real importable desde /app (from shared.negocio_id
# import requerir_negocio_id) porque WORKDIR/cwd ya esta en sys.path.
COPY shared /app/shared
COPY microservices/administracion /app

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8002
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
