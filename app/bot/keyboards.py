from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup


class AbuseCb(CallbackData, prefix="abuse"):
    action: str  # details | ban | ignore
    user_id: str


def abuse_keyboard(user_id: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔍 Details", callback_data=AbuseCb(action="details", user_id=user_id).pack())
    b.button(text="⛔ Ban", callback_data=AbuseCb(action="ban", user_id=user_id).pack())
    b.button(text="✅ Ignore", callback_data=AbuseCb(action="ignore", user_id=user_id).pack())
    b.adjust(3)
    return b.as_markup()