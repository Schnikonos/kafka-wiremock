"""
HTTP Mock Server — thin Starlette ASGI app + Uvicorn runner.

Each instance binds to ``config.port`` and forwards every inbound request
to ``MockDispatchHandler.dispatch()``.

Post-response coroutines (side-effects that fire after the HTTP reply) are
launched with ``asyncio.create_task()`` *before* the Response object is
returned so:
  • The event loop receives them while the current frame still holds all
    context references.
  • They start executing once the current coroutine yields (typically to
    the network layer sending the response).
  • Ordering relative to each other is preserved (create_task preserves
    insertion order within a single event-loop iteration).
"""
import asyncio
import logging
import threading
from typing import Optional

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from ..config.mock_server_config import MockServerConfig
from ..http.mock_dispatch import MockDispatchHandler

logger = logging.getLogger(__name__)

# HTTP methods that Starlette's Route should accept
_ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class HttpMockServer:
    """
    Manages the lifecycle of one Uvicorn / Starlette mock-server instance.

    Thread model:
        A dedicated daemon thread owns its own asyncio event loop so it is
        completely isolated from the FastAPI main-app event loop.
    """

    def __init__(self, config: MockServerConfig, dispatch_handler: MockDispatchHandler):
        self.config = config
        self.dispatch_handler = dispatch_handler

        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._uvicorn_server: Optional[uvicorn.Server] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the Uvicorn server in a background daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning(f"Mock server '{self.config.name}' is already running")
            return

        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"mock-server-{self.config.name}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            f"Mock server '{self.config.name}' started on port {self.config.port}"
            + (" (TLS)" if self.config.tls else "")
        )

    def stop(self) -> None:
        """Signal the Uvicorn server to shut down and wait for the thread."""
        if self._uvicorn_server is not None:
            # Schedule shutdown in the server's own event loop
            if self._loop is not None and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._uvicorn_server.shutdown(), self._loop
                )
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info(f"Mock server '{self.config.name}' stopped")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Internal — thread entry-point
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Create a new event loop, build the ASGI app, run Uvicorn."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._serve())
        except Exception as e:
            logger.error(f"Mock server '{self.config.name}' crashed: {e}", exc_info=True)
        finally:
            loop.close()

    async def _serve(self) -> None:
        """Build the Starlette app and run uvicorn.Server."""
        app = self._build_app()

        uv_config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=self.config.port,
            log_level="warning",   # silence uvicorn access log; our handler logs
            access_log=False,
            **self._tls_kwargs(),
        )
        server = uvicorn.Server(uv_config)
        self._uvicorn_server = server
        await server.serve()

    def _build_app(self) -> Starlette:
        """Build the minimal Starlette ASGI application."""
        server_name = self.config.name
        dispatch_handler = self.dispatch_handler

        async def health(_request: Request) -> Response:
            return Response(
                content='{"status":"ok","server":"' + server_name + '"}',
                media_type="application/json",
            )

        async def catch_all(request: Request) -> Response:
            return await _handle_request(request, server_name, dispatch_handler)

        return Starlette(
            routes=[
                Route("/health", health, methods=["GET", "HEAD"]),
                Route("/{path:path}", catch_all, methods=_ALL_METHODS),
                # Also handle root path "/"
                Route("/", catch_all, methods=_ALL_METHODS),
            ]
        )

    def _tls_kwargs(self) -> dict:
        """Return ssl_* kwargs for uvicorn.Config when TLS is configured."""
        if not self.config.tls:
            return {}
        tls = self.config.tls
        kwargs = {}
        if tls.cert:
            kwargs["ssl_certfile"] = tls.cert
        if tls.key:
            kwargs["ssl_keyfile"] = tls.key
        if tls.ca:
            kwargs["ssl_ca_certs"] = tls.ca
        if tls.key_password_env:
            import os
            pw = os.getenv(tls.key_password_env)
            if pw:
                kwargs["ssl_keyfile_password"] = pw
        return kwargs


# ---------------------------------------------------------------------------
# Request handler (module-level so it can reference the dispatch handler
# without needing it as an instance attribute of a class that Starlette
# holds — avoids circular reference issues in the Starlette Route closure).
# ---------------------------------------------------------------------------

async def _handle_request(
    request: Request,
    server_name: str,
    dispatch_handler: MockDispatchHandler,
) -> Response:
    """
    Core handler called for every non-health request on a mock server.

    1. Reads request data.
    2. Delegates to the dispatch handler.
    3. Launches post-response coroutines with ``create_task`` BEFORE
       constructing / returning the Response object so they are already
       scheduled when the event loop yields to send the reply bytes.
    """
    body_bytes = await request.body()
    query_params = dict(request.query_params)
    headers = dict(request.headers)

    # Starlette path_params gives us the "{path:path}" capture.
    # Prepend "/" to keep URLs consistent (dispatch expects leading slash).
    raw_path = request.path_params.get("path", "")
    path = f"/{raw_path}" if raw_path else "/"

    result = await dispatch_handler.dispatch(
        server_name=server_name,
        method=request.method,
        path=path,
        headers=headers,
        body_bytes=body_bytes,
        query_params=query_params,
    )

    # Launch post-response tasks BEFORE building/returning the Response.
    # asyncio.create_task schedules them in the current event loop; they
    # will not run until we yield (which happens when the network layer
    # sends the response bytes).
    for coro in result.post_response_coros:
        asyncio.create_task(coro)

    response_headers = dict(result.response_headers)
    response_headers.setdefault("Content-Type", result.content_type)

    logger.info(
        f"[{server_name}] {request.method} {path} → {result.status_code} "
        f"({result.matched_by})"
    )

    return Response(
        content=result.body,
        status_code=result.status_code,
        headers=response_headers,
        media_type=result.content_type,
    )

