import asyncio
import html
import logging
import ipaddress
from aiogram import Bot
from typing import Dict, List, Any

from app.config.settings import Settings
from app.models.webhook import WatchdogWebhook
from app.services.panel_client import PanelClient
from app.bot.keyboards import abuse_keyboard

log = logging.getLogger("webhook_processor")


def _fmt_user_info(user_info: dict | None) -> str:
    if not user_info:
        return "ℹ️ <i>Доп. информация не найдена (панель не настроена или API недоступен)</i>"
    
    response: List[Dict[str, Any]] = user_info["response"]

    telegram_id = response[0]['telegramId']
    text = (
        "<b>User info</b>\n"
        "\n"
        f"👤 Telegram ID: {telegram_id}\n"
        "\n"
    )
    for sub in response:
        text += "<blockquote expandable>"
        text += f"L sid: {sub['shortUuid']}\n"
        text += f"L username: {sub['username']}\n"
        text += f"L expireAt: {sub['expireAt']}\n"
        text += f"L createdAt: {sub['createdAt']}\n"

        int_squads = sub['activeInternalSquads']
        int_sq_text = []
        for int_sq in int_squads:
            int_sq_text.append(int_sq['name'])
        int_sq_text = ", ".join(int_sq_text)
        text += f"L Сквады: {int_sq_text}\n"

        if sub.get('trafficLimitBytes') and sub['trafficLimitBytes'] != 0:
            traffic_limit = round(sub['trafficLimitBytes'] / 1073741824, 2)
            used_traffic = round(sub['userTraffic']['usedTrafficBytes'] / 1073741824, 2)
            text += f"L Трафик: {used_traffic}ГБ / {traffic_limit}ГБ\n"
        
        lifetime_used_traffic = round(sub['userTraffic']['lifetimeUsedTrafficBytes'] / 1073741824, 2)
        text += f"L Трафик общ.: {lifetime_used_traffic}ГБ"
        text += "</blockquote>\n\n"
    
    if len(text) > 3500:
        text = html.escape(text[:3500] + "\n…")

    return text


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
        text = (
            f"⚠️ <b>Возможное злоупотребление</b>\n\n"
            f"<b>UserID</b>: <code>{html.escape(e.userId)}</code>\n"
            f"<b>Node</b>: <code>{html.escape(e.node)}</code>\n"
            f"<b>Pattern</b>: <code>{html.escape(e.patternId)}</code>\n"
            f"<b>Count</b>: <code>{e.count}</code> за <code>{e.windowSeconds}</code> сек\n"
            f"<b>ObservedAt</b>: <code>{html.escape(e.observedAt)}</code>\n"
        )

        if e.destination:
            text += f"<b>Destination</b>: <code>{html.escape(e.destination)}</code>\n"

        ban_type = (e.banType or "WEBHOOK").upper()

        ban_block = ""
        kb = None
        is_fw_ban = ban_type in ("FIRST_IP_WEBHOOK_AFTER", "FIRST_IP_WEBHOOK_AUTO_BAN")
        if is_fw_ban:
            dur_label = e.nftBanDuration if e.nftBanDuration and e.nftBanDuration != "0" else "permanent"
            ban_block += f"\n🚫 <b>Firewall ban applied</b> ({html.escape(dur_label)})"
            ban_block += f"\n<b>Banned IP</b>: <code>{e.bannedIp or '—'}</code>"
            if e.firewallOk is not None:
                ban_block += f"\n<b>Firewall</b>: <code>{e.firewallType or 'nftables'}</code> ok=<code>{e.firewallOk}</code>"
            if e.firewallError:
                err = e.firewallError.strip()
                if len(err) > 300:
                    err = err[:300] + "…"
                ban_block += f"\n<b>Firewall error</b>: <code>{err}</code>"

            # AUTO_BAN: also ban the user via panel
            if ban_type == "FIRST_IP_WEBHOOK_AUTO_BAN":
                auto_ban_ok = False
                if self._panel.enabled() and e.userId:
                    try:
                        auto_ban_ok = await self._panel.ban_user_by_email(
                            e.userId, reason="auto_ban_from_pattern",
                        )
                    except Exception:
                        log.exception("auto-ban failed for userId=%s", e.userId)
                if auto_ban_ok:
                    ban_block += "\n\n⛔ <b>User auto-banned via panel</b>"
                else:
                    ban_block += "\n\n❌ <b>User auto-ban failed</b> (panel error or not configured)"

            text += f"{ban_block}"
        else:
            def _is_ipv4(s: str) -> bool:
                try:
                    return isinstance(ipaddress.ip_address(s), ipaddress.IPv4Address)
                except ValueError:
                    return False
            
            user_id_type = (e.userIdType or "EMAIL").upper()
            is_ip = (user_id_type == "IP") or (user_id_type != "IPOREMAIL" and _is_ipv4(e.userId))
            is_ip_or_email = (user_id_type == "IPOREMAIL")
            
            user_info = None
            if is_ip_or_email:
                # IPorEMAIL: userId may be an email or an IP
                if _is_ipv4(e.userId):
                    text += f"<b>Detected by IP</b>: <code>{e.userId or '—'}</code>"
                elif self._panel.enabled():
                    user_info = await self._panel.get_full_user_info(e.userId)
                    text += f"{_fmt_user_info(user_info)}"
                    kb = abuse_keyboard(user_id=e.userId)
                else:
                    text += f"<b>Detected by Email</b>: <code>{e.userId or '—'}</code>"
            elif not is_ip and self._panel.enabled():
                user_info = await self._panel.get_full_user_info(e.userId) if self._panel.enabled() else None
                text += f"{_fmt_user_info(user_info)}"
                kb = abuse_keyboard(user_id=e.userId)
            else:
                text += f"<b>Banned</b>: <code>{e.userId or '—'}</code>"

        if e.sample:
            # Коротко (чтобы не раздувать сообщение)
            sample = html.escape(e.sample.strip())
            if len(sample) > 600:
                sample = sample[:600] + "…"
            text += f"\n\n<b>Sample</b>:\n<code>{sample}</code>"

        await self._bot.send_message(
            chat_id=self._settings.admin_telegram_id,
            text=text,
            reply_markup=kb,
            disable_web_page_preview=True,
        )