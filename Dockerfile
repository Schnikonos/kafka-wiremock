# ============================================================
# Stage 1: Build Angular frontend
# ============================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /ui
COPY ui/package*.json ./
RUN npm ci
COPY ui .
RUN npm run build

# ============================================================
# Stage 2: Download IBM MQ redistributable client
#
# Uses /mqdev/redist/ (the "Redistributable Client") — NOT /mqadv/.
# Plain tar.gz, no license ceremony, extracts to /opt/mqm directly.
# ============================================================
FROM ubuntu:22.04 AS mq-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/mqm && \
    DOWNLOADED=false && \
    for VERSION in 9.3.5.0 9.3.4.0 9.3.3.0 9.3.2.0 9.3.1.0 9.3.0.0; do \
        URL="https://public.dhe.ibm.com/ibmdl/export/pub/software/websphere/messaging/mqdev/redist/${VERSION}-IBM-MQC-Redist-LinuxX64.tar.gz"; \
        echo "Trying ${VERSION} ..."; \
        # Download to file first — piping curl into tar hides download errors
        curl -fsSL --retry 3 --retry-delay 5 -m 300 "${URL}" -o /tmp/mq-redist.tar.gz && \
        # Sanity-check: redistributable client should be at least 10 MB
        SIZE=$(stat -c%s /tmp/mq-redist.tar.gz 2>/dev/null || echo 0) && \
        echo "  Downloaded ${SIZE} bytes" && \
        if [ "$SIZE" -gt 10485760 ]; then \
            echo "  Extracting..." && \
            tar xzf /tmp/mq-redist.tar.gz -C /opt/mqm && \
            rm -f /tmp/mq-redist.tar.gz && \
            DOWNLOADED=true && \
            echo "✅ IBM MQ redist client ${VERSION} ready" && \
            break; \
        else \
            echo "  ⚠️  File too small (truncated or wrong URL), skipping"; \
            rm -f /tmp/mq-redist.tar.gz; \
        fi; \
    done && \
    [ "$DOWNLOADED" = "true" ] || { echo "❌ All versions failed to download"; exit 1; } && \
    test -f /opt/mqm/inc/cmqc.h   || { echo "❌ cmqc.h not found after extraction"; exit 1; } && \
    ls /opt/mqm/lib64/libmqic_r.* > /dev/null 2>&1 || { echo "❌ libmqic_r not found after extraction"; exit 1; } && \
    echo "✅ Headers and libraries verified"

# ============================================================
# Stage 3: Python application
# ============================================================
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ build-essential \
    libffi-dev libssl-dev libxml2-dev libstdc++6 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=mq-builder /opt/mqm/inc   /opt/mqm/inc
COPY --from=mq-builder /opt/mqm/lib64 /opt/mqm/lib64
COPY --from=mq-builder /opt/mqm/lib   /opt/mqm/lib

ENV CPATH=/opt/mqm/inc \
    LIBRARY_PATH=/opt/mqm/lib64:/opt/mqm/lib \
    LD_LIBRARY_PATH=/opt/mqm/lib64:/opt/mqm/lib \
    MQ_INSTALLATION_PATH=/opt/mqm \
    PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN echo "=== Verifying IBM MQ headers ===" && \
    ls /opt/mqm/inc/cmqc.h && echo "✅ cmqc.h present" && \
    echo "" && \
    echo "=== Installing Python dependencies ===" && \
    pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir pymqi==1.12.13 && \
    echo "✅ pymqi compiled and installed" && \
    pip install --no-cache-dir \
        fastapi uvicorn confluent-kafka PyYAML jsonpath-ng \
        pydantic pydantic-settings six fastavro requests httpx \
        stomp.py pika && \
    echo "" && \
    echo "=== Verifying imports ===" && \
    python -c "import pymqi; print('✅ pymqi OK')" && \
    python -c "import stomp;  print('✅ stomp.py OK')" && \
    python -c "import pika;   print('✅ pika OK')"

COPY src/ src/
COPY run.py .
COPY --from=frontend-builder /ui/dist/ui/browser src/static

# Bundle JSON schemas as a downloadable ZIP served as a static asset
COPY json-schema/*.json /tmp/schemas/
RUN python3 -c "import zipfile, glob, os; files = sorted(glob.glob('/tmp/schemas/*.json')); zf = zipfile.ZipFile('src/static/schemas.zip', 'w', zipfile.ZIP_DEFLATED); [zf.write(f, os.path.basename(f)) for f in files]; zf.close(); print('schemas.zip created with', str(len(files)), 'files')" \
    && rm -rf /tmp/schemas

RUN mkdir -p /config /testSuite /send && \
    useradd -m appuser && \
    chown -R appuser:appuser /app /config /testSuite /send

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

ENV KAFKA_BOOTSTRAP_SERVERS=kafka:9092 \
    CONFIG_DIR=/config \
    HOST=0.0.0.0 \
    PORT=8000 \
    WORKERS=1

CMD ["python", "run.py"]
