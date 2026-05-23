# Equity OS — production image (screener + company pages + Moonstocks report API)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=3000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY web/requirements.txt /app/web/requirements.txt
RUN pip install --no-cache-dir -r /app/web/requirements.txt gunicorn==22.0.0

COPY src /app/src
COPY web /app/web
COPY scripts /app/scripts

WORKDIR /app/web
EXPOSE 3000

# load_data() runs once per container start
CMD ["gunicorn", "-c", "gunicorn.conf.py", "--bind", "0.0.0.0:3000", \
     "--workers", "1", "--threads", "4", "--timeout", "120", "app_enhanced:app"]
