FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Certs are mounted at runtime via the /certs volume
ENV PORT=8080 \
    MODE=http

EXPOSE 8080

CMD ["python3", "app.py"]

