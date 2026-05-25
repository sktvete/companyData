# Equity OS — production image (screener + company pages + Moonstocks report API)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=3000

WORKDIR /app

# System deps: ca-certs for HTTPS; awscli for optional S3 sync at startup
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        unzip \
    && curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install \
    && rm -rf /tmp/awscliv2.zip /tmp/aws /var/lib/apt/lists/*

# Python dependencies
COPY web/requirements.txt /app/web/requirements.txt
RUN pip install --no-cache-dir -r /app/web/requirements.txt gunicorn==22.0.0

# Application code
COPY src /app/src
COPY web /app/web
COPY scripts /app/scripts

WORKDIR /app/web

# Entrypoint handles optional S3 sync + starting gunicorn
COPY scripts/docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 3000

# Gunicorn config lives in gunicorn.conf.py — no flags needed here.
# Workers, timeouts, bind are all controlled via env vars (GUNICORN_WORKERS, etc.)
ENTRYPOINT ["/app/docker-entrypoint.sh"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${PORT}/health', timeout=8)"
