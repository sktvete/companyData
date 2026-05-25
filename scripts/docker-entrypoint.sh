#!/usr/bin/env sh
# equity-os container entrypoint
# Optionally syncs outputs from S3 before starting gunicorn.
#
# Environment variables:
#   OUTPUTS_S3_URI   s3://my-bucket/equity-os/outputs
#                    If set, aws s3 sync is run once at startup to populate
#                    /app/outputs (useful when EFS is pre-seeded from S3).
#   PORT             HTTP port (default: 3000, matches gunicorn.conf.py)

set -eu

OUTPUTS_DIR="/app/outputs"

# --------------------------------------------------------------------------
# Optional: sync from S3
# --------------------------------------------------------------------------
if [ -n "${OUTPUTS_S3_URI:-}" ]; then
    echo "[entrypoint] Syncing outputs from ${OUTPUTS_S3_URI} ..."
    aws s3 sync "${OUTPUTS_S3_URI}" "${OUTPUTS_DIR}" \
        --no-progress \
        --exact-timestamps \
        --exclude "*.db-shm" \
        --exclude "*.db-wal" \
        && echo "[entrypoint] S3 sync complete." \
        || echo "[entrypoint] WARNING: S3 sync failed — continuing with local data."
fi

# --------------------------------------------------------------------------
# Ensure required output directories exist (EFS mount or ephemeral storage)
# --------------------------------------------------------------------------
mkdir -p \
    "${OUTPUTS_DIR}/fundamentals_cache" \
    "${OUTPUTS_DIR}/scaled_analysis" \
    "${OUTPUTS_DIR}/analyst_yf_cache"

# --------------------------------------------------------------------------
# Start gunicorn — all config in gunicorn.conf.py
# --------------------------------------------------------------------------
echo "[entrypoint] Starting gunicorn ..."
exec gunicorn -c gunicorn.conf.py app_enhanced:app
