FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# WITH_CLAUDE=true installs Node.js + @anthropic-ai/claude-code for the
# Anthropic provider path.  Set to false (default) for the OpenAI-only path
# which shaves ~500 MB from the image.
ARG WITH_CLAUDE=false

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && if [ "$WITH_CLAUDE" = "true" ]; then \
           apt-get install -y --no-install-recommends nodejs npm \
           && npm install -g @anthropic-ai/claude-code; \
       fi \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/logs \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
