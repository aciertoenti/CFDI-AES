FROM python:3.12-slim

# Tesseract para OCR de constancias de situación fiscal
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-spa \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Contexto de build = ./backend (docker-compose.yml, zg5nT_8, 07 sep 2026) -
# mismo patron ya probado en administracion/auth_usuarios/facturacion/ia
# (12-14 ago 2026). whatsapp_bot era el ultimo con el context viejo: se movio
# para poder COPY backend/shared/ (fiscal_validator unificado, antes duplicado
# como fiscal_catalogo.py en facturacion). COPY selectivo a proposito: NO
# "COPY . ." - traeria los demas microservicios dentro de esta imagen.
COPY microservices/whatsapp_bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared /app/shared
COPY microservices/whatsapp_bot /app

EXPOSE 8006
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8006"]
