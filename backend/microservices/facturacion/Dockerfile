FROM python:3.11-slim

# Pango para WeasyPrint (generacion de PDF, dependencia de satcfdi).
# cairo/gdk-pixbuf ya no son necesarios desde WeasyPrint >= 54.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
