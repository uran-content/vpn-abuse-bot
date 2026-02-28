from pydantic import BaseModel, ConfigDict, Field


class WatchdogWebhook(BaseModel):
    """
    Ожидаемый формат от твоего remnanode-watchdog (из Go).
    """
    model_config = ConfigDict(extra="ignore")

    event: str = Field(default="pattern_match")
    node: str
    patternId: str
    userId: str
    count: int
    windowSeconds: int
    observedAt: str  # RFC3339 string
    sample: str | None = None