"""
Dummy HTTP/HTTPS API for kafka-wiremock HTTP(S) integration tests.

Endpoints:
  GET  /hello          → {"message": "hello", "mode": "http|https", "port": <PORT>}
  POST /echo           → {"echoed": <body>, "content_type": <ct>}
  GET  /health         → {"status": "ok"}

Configuration (environment variables):
  PORT                      – port to listen on (default: 8080)
  MODE                      – "http" or "https" (default: "http")
  SSL_CERTFILE              – path to server TLS certificate (PEM)
  SSL_KEYFILE               – path to server TLS private key (PEM)
  SSL_CA_CERTS              – path to CA bundle used to verify client certs (mTLS)
  SSL_REQUIRE_CLIENT_CERT   – "true" to enforce mTLS CERT_REQUIRED (default: "false")
"""

import os
import ssl
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="kafka-wiremock-dummy-app")

_PORT = int(os.environ.get("PORT", 8080))
_MODE = os.environ.get("MODE", "http").lower()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/hello")
async def hello():
    return {"message": "hello", "mode": _MODE, "port": _PORT}


@app.post("/echo")
async def echo(request: Request):
    body_bytes = await request.body()
    body_text = body_bytes.decode("utf-8", errors="replace")
    content_type = request.headers.get("content-type", "")

    # Try to parse as JSON to return a proper JSON body
    import json
    try:
        body_parsed = json.loads(body_text)
    except Exception:
        body_parsed = body_text

    return JSONResponse(
        content={"echoed": body_parsed, "content_type": content_type},
        status_code=200,
    )


if __name__ == "__main__":
    ssl_kwargs: dict = {}

    if _MODE == "https":
        ssl_certfile = os.environ.get("SSL_CERTFILE")
        ssl_keyfile = os.environ.get("SSL_KEYFILE")
        if not ssl_certfile or not ssl_keyfile:
            raise RuntimeError("MODE=https requires SSL_CERTFILE and SSL_KEYFILE")

        ssl_kwargs["ssl_certfile"] = ssl_certfile
        ssl_kwargs["ssl_keyfile"] = ssl_keyfile

        ca_certs = os.environ.get("SSL_CA_CERTS")
        require_client = os.environ.get("SSL_REQUIRE_CLIENT_CERT", "false").lower() == "true"

        if ca_certs:
            ssl_kwargs["ssl_ca_certs"] = ca_certs
            ssl_kwargs["ssl_cert_reqs"] = (
                ssl.CERT_REQUIRED if require_client else ssl.CERT_OPTIONAL
            )

    print(f"Starting dummy app on {_MODE.upper()}://0.0.0.0:{_PORT}")
    uvicorn.run(app, host="0.0.0.0", port=_PORT, **ssl_kwargs)
