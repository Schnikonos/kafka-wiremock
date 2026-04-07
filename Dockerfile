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

# Create config directory
RUN mkdir -p /config

# Create non-root user and set permissions
RUN useradd -m appuser && \
    chown -R appuser:appuser /app /config

USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Environment variables
ENV KAFKA_BOOTSTRAP_SERVERS=kafka:9092
ENV CONFIG_DIR=/config
ENV HOST=0.0.0.0
ENV PORT=8000
ENV WORKERS=1

# Run application
CMD ["python", "run.py"]

