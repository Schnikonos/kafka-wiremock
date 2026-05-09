FROM node:20-alpine AS frontend-builder

WORKDIR /ui

# Copy frontend files
COPY ui/package*.json ./
RUN npm ci

COPY ui .
RUN npm run build

# Python stage
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ src/
COPY run.py .

# Copy built frontend from frontend builder
COPY --from=frontend-builder /ui/dist/ui/browser src/static

# Create config directory
RUN mkdir -p /config /testSuite /send

# Create non-root user and set permissions
RUN useradd -m appuser && \
    chown -R appuser:appuser /app /config /testSuite /send

USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

# Environment variables
ENV KAFKA_BOOTSTRAP_SERVERS=kafka:9092
ENV CONFIG_DIR=/config
ENV HOST=0.0.0.0
ENV PORT=8000
ENV WORKERS=1

# Run application
CMD ["python", "run.py"]

