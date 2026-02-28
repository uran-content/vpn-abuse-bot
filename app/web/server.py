import json
import logging
import os
import ssl
from aiohttp import web

from app.config.settings import Settings
from app.models.webhook import WatchdogWebhook
from app.services.pattern_store import PatternStore
from app.services.webhook_processor import WebhookProcessor

log = logging.getLogger("web_server")


def _bearer_ok(request: web.Request, expected_token: str) -> bool:
    if not expected_token:
        return True
    auth = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not auth.startswith(prefix):
        return False
    token = auth[len(prefix):].strip()
    return token == expected_token


class WebServer:
    def __init__(self, settings: Settings, pattern_store: PatternStore, processor: WebhookProcessor) -> None:
        self._settings = settings
        self._pattern_store = pattern_store
        self._processor = processor

        self._app = web.Application()
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

        self._setup_routes()

    def _setup_routes(self) -> None:
        self._app.router.add_get(self._settings.health_path, self._handle_health)
        self._app.router.add_get(self._settings.patterns_path, self._handle_patterns)
        self._app.router.add_post(self._settings.webhook_path, self._handle_webhook)

    def _ssl_context(self) -> ssl.SSLContext | None:
        cert = self._settings.ssl_cert_file
        key = self._settings.ssl_key_file

        if not (cert and key):
            log.warning("SSL cert/key not set, starting WITHOUT TLS")
            return None
        if not (os.path.exists(cert) and os.path.exists(key)):
            log.warning("SSL files not found (%s, %s), starting WITHOUT TLS", cert, key)
            return None

        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(certfile=cert, keyfile=key)
        return ctx

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        ssl_ctx = self._ssl_context()
        self._site = web.TCPSite(
            self._runner,
            host=self._settings.api_host,
            port=self._settings.api_port,
            ssl_context=ssl_ctx,
        )
        await self._site.start()
        log.info("web server started on %s:%s (tls=%s)",
                 self._settings.api_host, self._settings.api_port, bool(ssl_ctx))

    async def stop(self) -> None:
        if self._site:
            await self._site.stop()
            self._site = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        log.info("web server stopped")

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def _handle_patterns(self, request: web.Request) -> web.Response:
        if not _bearer_ok(request, self._settings.patterns_token_in):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        data = await self._pattern_store.get_patterns()
        return web.json_response(data)

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        if not _bearer_ok(request, self._settings.webhook_token_in):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "bad_json"}, status=400)

        try:
            event = WatchdogWebhook(**payload)
        except Exception as e:
            return web.json_response({"ok": False, "error": f"invalid_payload: {e}"}, status=400)

        enqueued = await self._processor.enqueue(event)
        # Всегда отвечаем быстро и успешно, чтобы watchdog не зависал.
        return web.json_response({"ok": True, "enqueued": enqueued})