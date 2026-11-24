# Nodos del SEN: mapa + API que se actualiza sola con datos del Coordinador Eléctrico Nacional.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DBT_SEND_ANONYMOUS_USAGE_STATS=False \
    TZ=America/Santiago \
    NODOS_HOST=0.0.0.0 \
    NODOS_PORT=8000

WORKDIR /app

# Dependencias primero (capa cacheable). En la imagen dbt comparte entorno con la app.
COPY requirements.txt requirements-dbt.txt requirements-web.txt ./
RUN pip install -r requirements.txt -r requirements-dbt.txt -r requirements-web.txt

COPY nodos/ nodos/
COPY transform/ transform/
COPY web/ web/
COPY ubicaciones_manuales.csv ./
COPY semilla/ semilla/

# Usuario sin privilegios; data/ es el volumen con la caché y la base DuckDB.
RUN useradd --create-home --uid 1000 nodos \
    && mkdir -p /app/data \
    && chown -R nodos:nodos /app
USER nodos
VOLUME ["/app/data"]

EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/salud', timeout=4)"

CMD ["python", "-m", "nodos", "servir"]
