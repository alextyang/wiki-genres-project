"""Runtime configuration. All settings are env-driven via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Single source of truth for configuration.

    Values are loaded from env vars (preferred) or a `.env` file in the project
    root. See `.env.example` for the canonical list of keys.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database -----------------------------------------------------------

    database_url: str = Field(
        default="postgresql+asyncpg://wiki_genres:wiki_genres@localhost:5433/wiki_genres",
        alias="DATABASE_URL",
    )

    # --- Wikimedia client identity ------------------------------------------

    wiki_user_agent: str = Field(
        default=(
            "wiki-genres/0.0.1 "
            "(https://github.com/koopakondra/wiki-genres-project; "
            "koopakondra@gmail.com)"
        ),
        alias="WIKI_USER_AGENT",
    )

    # --- API ----------------------------------------------------------------

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")  # noqa: S104
    api_port: int = Field(default=8080, alias="API_PORT")
    admin_token: str | None = Field(default=None, alias="ADMIN_TOKEN")

    # --- Crawler ------------------------------------------------------------

    crawler_concurrency: int = Field(default=4, alias="CRAWLER_CONCURRENCY")
    crawler_request_interval_ms: int = Field(default=250, alias="CRAWLER_REQUEST_INTERVAL_MS")
    crawler_cache_dir: Path = Field(default=Path("./.cache"), alias="CRAWLER_CACHE_DIR")

    # --- Sync worker --------------------------------------------------------

    eventstream_url: str = Field(
        default="https://stream.wikimedia.org/v2/stream/recentchange",
        alias="EVENTSTREAM_URL",
    )
    eventstream_reconnect_delay_ms: int = Field(
        default=2000, alias="EVENTSTREAM_RECONNECT_DELAY_MS"
    )

    # --- Logging ------------------------------------------------------------

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Reset by calling `get_settings.cache_clear()`."""
    return Settings()
