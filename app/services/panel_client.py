import logging
import httpx
from typing import Any

from app.config.settings import Settings

log = logging.getLogger("panel_client")


class PanelClient:
    """
    Заготовка под интеграцию с панелью remnawave (или твоим API).
    По умолчанию ничего не ломает: если PANEL_BASE_URL пустой — просто не делает запросов.

    Подстрой:
      PANEL_USER_INFO_PATH_TEMPLATE
      PANEL_BAN_PATH_TEMPLATE
    """
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

        if self._settings.panel_base_url:
            headers = {}
            if self._settings.panel_api_token:
                headers["Authorization"] = f"Bearer {self._settings.panel_api_token}"
            headers["Content-Type"] = "application/json"
            self._client = httpx.AsyncClient(
                base_url=self._settings.panel_base_url.rstrip("/"),
                headers=headers,
                timeout=self._settings.panel_timeout_seconds,
            )

    async def aclose(self) -> None:
        if self._client:
            await self._client.aclose()

    def enabled(self) -> bool:
        return self._client is not None
    
    async def _get_sub_info(self, user_id: str) -> dict[str, Any] | None:
        path = self._settings.panel_user_info_path.format(user_id=user_id)
        try:
            r = await self._client.get(path)
            if r.status_code == 200:
                return r.json()
            log.warning("_get_sub_info HTTP %s: %s", r.status_code, r.text[:300])
            return None
        except Exception:
            log.exception("_get_sub_info failed")
            return None
    
    async def _get_full_user_info_by_telegram_id(self, telegram_id: int) -> dict[str, Any] | None:
        path = self._settings.panel_full_user_info_path.format(telegram_id=telegram_id)
        try:
            r = await self._client.get(path)
            if r.status_code == 200:
                return r.json()
            log.warning("_get_full_user_info_by_telegram_id HTTP %s: %s", r.status_code, r.text[:300])
            return None
        except Exception:
            log.exception("_get_full_user_info_by_telegram_id failed")
            return None

    async def get_full_user_info(self, user_id: str) -> dict[str, Any] | None:
        if not self._client:
            return None
        
        telegram_id = (await self._get_sub_info(user_id=user_id))["response"]["telegramId"]
        if telegram_id is None:
            return None
        
        return await self._get_full_user_info_by_telegram_id(telegram_id=telegram_id)

    async def ban_user(self, user_id: str, reason: str = "abuse_detected") -> bool:
        if not self._client:
            return False

        path = self._settings.panel_ban_path.format(user_id=user_id)
        try:
            r = await self._client.post(path, json={"reason": reason})
            if 200 <= r.status_code < 300:
                return True
            log.warning("ban_user HTTP %s: %s", r.status_code, r.text[:300])
            return False
        except Exception:
            log.exception("ban_user failed")
            return False