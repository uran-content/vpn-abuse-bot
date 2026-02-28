import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from app.config.settings import Settings
from app.bot.handlers import build_admin_router
from app.services.panel_client import PanelClient
from app.services.pattern_store import PatternStore
from app.services.webhook_processor import WebhookProcessor
from app.web.server import WebServer


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def main() -> None:
    # Удобно для локального запуска; в docker обычно env уже прокинут через env_file
    load_dotenv(override=False)

    settings = Settings()
    setup_logging(settings.log_level)

    bot = Bot(token=settings.bot_token, parse_mode=ParseMode.HTML)
    dp = Dispatcher()

    # Services
    panel = PanelClient(settings=settings)
    pattern_store = PatternStore(settings=settings)
    processor = WebhookProcessor(settings=settings, bot=bot, panel=panel)
    web_server = WebServer(settings=settings, pattern_store=pattern_store, processor=processor)

    # Bot routes
    dp.include_router(build_admin_router())

    async def on_startup(*_: object, **__: object) -> None:
        await pattern_store.warmup()
        await processor.start()
        await web_server.start()
        await bot.send_message(
            settings.admin_telegram_id,
            f"✅ vpn-abuse-bot запущен.\n"
            f"HTTPS: {settings.api_host}:{settings.api_port}\n"
            f"Paths: webhook={settings.webhook_path}, patterns={settings.patterns_path}",
        )

    async def on_shutdown(*_: object, **__: object) -> None:
        await web_server.stop()
        await processor.stop()
        await panel.aclose()
        await bot.session.close()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Dependency injection в handlers через start_polling kwargs
    await dp.start_polling(
        bot,
        settings=settings,
        panel=panel,
        pattern_store=pattern_store,
        processor=processor,
    )
