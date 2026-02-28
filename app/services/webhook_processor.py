import asyncio
import html
import logging
from aiogram import Bot

from app.config.settings import Settings
from app.models.webhook import WatchdogWebhook
from app.services.panel_client import PanelClient
from app.bot.keyboards import abuse_keyboard

log = logging.getLogger("webhook_processor")


def _fmt_user_info(user_info: dict | None) -> str:
    if not user_info:
        return "ℹ️ <i>Доп. информация не найдена (панель не настроена или API недоступен)</i>"
    # Тут ты сможешь красиво отформатировать реальные поля панели.
    # Пока — максимально безопасный дефолт:
    safe_parts = []
    for k in ("id", "email", "status", "created_at", "expires_at", "last_seen", "note"):
        if k in user_info and user_info[k] is not None:
            safe_parts.append(f"<b>{html.escape(str(k))}</b>: {html.escape(str(user_info[k]))}")
    if not safe_parts:
        return "ℹ️ <i>Панель вернула данные, но ключевые поля не распознаны</i>"
    return "👤 <b>User info</b>\n" + "\n".join(safe_parts)


class WebhookProcessor:
    """
    Принимает события (webhook), кладёт в очередь и обрабатывает воркерами.
    В HTTP handler отвечаем быстро, тяжёлую работу делаем асинхронно.
    """
    def __init__(self, settings: Settings, bot: Bot, panel: PanelClient) -> None:
        self._settings = settings
        self._bot = bot
        self._panel = panel

        self._queue: asyncio.Queue[WatchdogWebhook] = asyncio.Queue(
            maxsize=max(1, settings.webhook_queue_size)
        )
        self._workers: list[asyncio.Task] = []
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._stop.clear()
        n = max(1, int(self._settings.webhook_workers))
        for i in range(n):
            self._workers.append(asyncio.create_task(self._worker(i)))
        log.info("webhook processor started with %d worker(s)", n)

    async def stop(self) -> None:
        self._stop.set()
        for t in self._workers:
            t.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        log.info("webhook processor stopped")

    async def enqueue(self, event: WatchdogWebhook) -> bool:
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            # Защита от перегруза: дропаем, но сервер не умирает
            log.warning("webhook queue full; dropping event userId=%s", event.userId)
            return False

    async def _worker(self, idx: int) -> None:
        while not self._stop.is_set():
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                return

            try:
                await self._process(event)
            except Exception:
                log.exception("failed to process webhook event")
            finally:
                self._queue.task_done()

    async def _process(self, e: WatchdogWebhook) -> None:
        # 1) Обогащение инфы (по желанию)
        user_info = await self._panel.get_user_info(e.userId) if self._panel.enabled() else None

        # 2) Текст админу
        text = (
            f"⚠️ <b>Возможное злоупотребление</b>\n\n"
            f"<b>UserID</b>: <code>{html.escape(e.userId)}</code>\n"
            f"<b>Node</b>: <code>{html.escape(e.node)}</code>\n"
            f"<b>Pattern</b>: <code>{html.escape(e.patternId)}</code>\n"
            f"<b>Count</b>: <code>{e.count}</code> за <code>{e.windowSeconds}</code> сек\n"
            f"<b>ObservedAt</b>: <code>{html.escape(e.observedAt)}</code>\n\n"
            f"{_fmt_user_info(user_info)}"
        )
        if e.sample:
            # Коротко (чтобы не раздувать сообщение)
            sample = html.escape(e.sample.strip())
            if len(sample) > 600:
                sample = sample[:600] + "…"
            text += f"\n\n<b>Sample</b>:\n<code>{sample}</code>"

        # 3) Кнопки
        kb = abuse_keyboard(user_id=e.userId)

        await self._bot.send_message(
            chat_id=self._settings.admin_telegram_id,
            text=text,
            reply_markup=kb,
            disable_web_page_preview=True,
        )