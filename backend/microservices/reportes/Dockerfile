FROM python:3.11-slim

WORKDIR /app

# Contexto de build ampliado a ./backend (20 ago 2026, seguridad
# X-Internal-Key) - mismo patron ya probado en facturacion/administracion/
# auth_usuarios/ia. COPY selectivo a proposito: NO copiar todo el contexto
# (COPY . /app traeria los demas microservicios dentro de esta imagen).
COPY shared /app/shared
COPY microservices/reportes /app

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8004
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
