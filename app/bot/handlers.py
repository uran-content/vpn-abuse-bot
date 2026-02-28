import html
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from app.config.settings import Settings
from app.services.panel_client import PanelClient
from app.bot.keyboards import AbuseCb

log = logging.getLogger("bot_handlers")


def _is_admin(user_id: int | None, settings: Settings) -> bool:
    return bool(user_id) and int(user_id) == int(settings.admin_telegram_id)


def _pretty_json(data: dict | None) -> str:
    if not data:
        return "—"
    # Безопасно обрезаем, чтобы не улететь в лимиты Telegram
    import json
    s = json.dumps(data, ensure_ascii=False, indent=2)
    if len(s) > 3500:
        s = s[:3500] + "\n…"
    return html.escape(s)


def build_admin_router() -> Router:
    r = Router()

    @r.message(Command("start"))
    async def start_cmd(message: Message, settings: Settings) -> None:
        if not _is_admin(message.from_user.id if message.from_user else None, settings):
            return

        await message.answer(
            "🛡️ <b>vpn-abuse-bot</b>\n\n"
            "Команды:\n"
            "• <code>/user &lt;id&gt;</code> — показать инфо о пользователе\n"
            "• <code>/ban &lt;telegramId&gt;</code> — забанить пользователя (через панель)\n"
            "• <code>/patterns</code> — показать источник паттернов\n"
        )

    @r.message(Command("patterns"))
    async def patterns_cmd(message: Message, settings: Settings) -> None:
        if not _is_admin(message.from_user.id if message.from_user else None, settings):
            return

        await message.answer(
            "📌 <b>Patterns</b>\n"
            f"Файл: <code>{settings.patterns_file}</code>\n"
            f"Кэш: <code>{settings.patterns_cache_seconds}</code> сек\n"
        )

    @r.message(Command("user"))
    async def user_cmd(message: Message, settings: Settings, panel: PanelClient) -> None:
        if not _is_admin(message.from_user.id if message.from_user else None, settings):
            return

        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Использование: <code>/user 669211</code>")
            return

        user_id = parts[1].strip()
        info = await panel._get_sub_info(user_id) if panel.enabled() else None

        await message.answer(
            f"👤 <b>User</b>: <code>{html.escape(user_id)}</code>\n\n"
            f"<code>{_pretty_json(info)}</code>"
        )

    @r.message(Command("ban"))
    async def ban_cmd(message: Message, settings: Settings, panel: PanelClient) -> None:
        if not _is_admin(message.from_user.id if message.from_user else None, settings):
            return

        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Использование: <code>/ban 669211</code>")
            return

        telegram_id = parts[1].strip()
        if not panel.enabled():
            await message.answer("Панель не настроена (PANEL_BASE_URL пустой).")
            return

        ok = await panel.ban_user(telegram_id, reason="manual_ban_from_bot")
        await message.answer("⛔ Бан выполнен." if ok else "Не удалось забанить (проверь API/логи).")

    @r.callback_query(AbuseCb.filter())
    async def abuse_callback(
        cq: CallbackQuery,
        callback_data: AbuseCb,
        settings: Settings,
        panel: PanelClient,
    ) -> None:
        if not _is_admin(cq.from_user.id if cq.from_user else None, settings):
            await cq.answer("Not allowed", show_alert=True)
            return

        action = callback_data.action
        user_id = callback_data.user_id

        if action == "ignore":
            await cq.answer("Ignored ✅")
            # Можешь здесь добавить свою бизнес‑логику: пометка, запись в БД и т.д.
            return

        if action == "details":
            info = await panel._get_sub_info(user_id) if panel.enabled() else None
            await cq.message.answer(
                f"🔍 <b>Details</b> for <code>{html.escape(user_id)}</code>\n\n"
                f"<code>{_pretty_json(info)}</code>"
            )
            await cq.answer()
            return

        if action == "ban":
            if not panel.enabled():
                await cq.answer("Панель не настроена", show_alert=True)
                return
            ok = await panel.ban_user_by_email(user_id, reason="ban_from_alert_button")
            await cq.answer("Banned ✅" if ok else "Ban failed ❌", show_alert=True)
            return

        await cq.answer()

    return r