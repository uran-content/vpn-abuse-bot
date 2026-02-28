import json
import logging
import os
import time
import aiofiles

from app.config.settings import Settings

log = logging.getLogger("pattern_store")


DEFAULT_PATTERNS = {
    "patterns": [
        {
            "id": "block_3_per_minute",
            "enabled": True,
            "serverPolicy": "DEFAULT_APPLY",
            "serverExceptions": [],
            "banType": "WEBHOOK",
            "mustContain": ["accepted", "BLOCK]", "email:"],
            "matchRegex": r"\[[^\]]+\s(?:->|>>)\s*BLOCK\]",
            "extract": {"type": "after", "after": "email:", "until": ""},
            "threshold": 3,
            "windowSeconds": 60,
            "cooldownSeconds": 600,
            "maxTrackedUsers": 20000,
            "includeSample": False,
        }
    ]
}


class PatternStore:
    """
    Хранит/отдаёт паттерны watchdog'ам.
    По умолчанию читает JSON из файла (PATTERNS_FILE) и кэширует.
    """
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache: dict = DEFAULT_PATTERNS
        self._cache_until: float = 0.0
        self._last_mtime: float = 0.0

    async def warmup(self) -> None:
        await self._maybe_reload(force=True)

    async def get_patterns(self) -> dict:
        await self._maybe_reload(force=False)
        return self._cache

    async def _maybe_reload(self, force: bool) -> None:
        now = time.time()
        if not force and now < self._cache_until:
            return

        path = self._settings.patterns_file
        try:
            st = os.stat(path)
            mtime = st.st_mtime
        except FileNotFoundError:
            log.warning("patterns file not found: %s (using defaults)", path)
            self._cache = DEFAULT_PATTERNS
            self._cache_until = now + max(1, self._settings.patterns_cache_seconds)
            return
        except Exception:
            log.exception("stat patterns failed (using cached)")
            self._cache_until = now + max(1, self._settings.patterns_cache_seconds)
            return

        if not force and mtime == self._last_mtime and self._cache:
            self._cache_until = now + max(1, self._settings.patterns_cache_seconds)
            return

        try:
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                raw = await f.read()
            data = json.loads(raw)
            if not isinstance(data, dict) or "patterns" not in data:
                raise ValueError("Invalid patterns json structure")
            self._cache = data
            self._last_mtime = mtime
            log.info("patterns reloaded from %s", path)
        except Exception:
            log.exception("failed to load patterns (keeping previous/default)")

        self._cache_until = now + max(1, self._settings.patterns_cache_seconds)