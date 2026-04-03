#!/usr/bin/env python
"""
Entry point for Kafka Wiremock application.
"""
import os
import sys
import uvicorn

if __name__ == "__main__":
    # Get configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    workers = int(os.getenv("WORKERS", 1))

    # Run uvicorn server
    uvicorn.run(
        "src.main:app",
        host=host,
        port=port,
        workers=workers,
        reload=False,
        log_level="info",
    )

