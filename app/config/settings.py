from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=False)

    # Telegram
    bot_token: str = Field(alias="BOT_TOKEN")
    admin_telegram_id: int = Field(alias="ADMIN_TELEGRAM_ID")

    # HTTPS API server
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8443, alias="API_PORT")

    ssl_cert_file: str = Field(default="/certs/fullchain.pem", alias="API_SSL_CERT_FILE")
    ssl_key_file: str = Field(default="/certs/privkey.pem", alias="API_SSL_KEY_FILE")

    webhook_path: str = Field(default="/api/webhook", alias="WEBHOOK_PATH")
    patterns_path: str = Field(default="/api/patterns", alias="PATTERNS_PATH")
    health_path: str = Field(default="/health", alias="HEALTH_PATH")

    # Inbound auth
    webhook_token_in: str = Field(default="", alias="WEBHOOK_TOKEN_IN")
    patterns_token_in: str = Field(default="", alias="PATTERNS_TOKEN_IN")

    # Patterns
    patterns_file: str = Field(default="/data/patterns.json", alias="PATTERNS_FILE")
    patterns_cache_seconds: int = Field(default=5, alias="PATTERNS_CACHE_SECONDS")

    # Queue/Workers
    webhook_queue_size: int = Field(default=256, alias="WEBHOOK_QUEUE_SIZE")
    webhook_workers: int = Field(default=1, alias="WEBHOOK_WORKERS")

    # Panel integration (optional)
    panel_base_url: str = Field(default="", alias="PANEL_BASE_URL")
    panel_api_token: str = Field(default="", alias="PANEL_API_TOKEN")
    panel_timeout_seconds: float = Field(default=5, alias="PANEL_TIMEOUT_SECONDS")
    panel_user_info_path: str = Field(
        default="/api/users/{user_id}",
        alias="PANEL_USER_INFO_PATH",
    )
    panel_full_user_info_path: str = Field(
        default="/api/users/{user_id}",
        alias="PANEL_FULL_USER_INFO_PATH",
    )
    panel_ban_path: str = Field(
        default="/api/users/{user_id}/ban",
        alias="PANEL_BAN_PATH",
    )

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
