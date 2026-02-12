"""Runtime configuration for the web backend."""

from __future__ import annotations

import stat
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv_if_available(env_path: Path) -> None:
    """Load .env only when it is locally available.

    On macOS with iCloud optimization, files can be present but marked
    dataless. Attempting to read them may block. We skip those files.
    """
    try:
        metadata = env_path.stat()
    except FileNotFoundError:
        return
    except OSError:
        return

    dataless_flag = getattr(stat, "SF_DATALESS", 0)
    if dataless_flag and (metadata.st_flags & dataless_flag):
        return

    try:
        load_dotenv(env_path, override=True)
    except OSError:
        # Ignore transient filesystem provider failures.
        return


_load_dotenv_if_available(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    """Environment-backed application settings."""

    anthropic_api_key: str | None
    storage_dir: Path
    max_pdf_pages: int
    model_name: str
    transcript_model_name: str
    cors_origins: list[str]



def _parse_origins(raw: str | None) -> list[str]:
    if not raw:
        return [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]

    origins = [value.strip() for value in raw.split(",") if value.strip()]
    return origins or ["http://localhost:5173"]



def get_settings() -> Settings:
    """Build immutable runtime settings from environment."""
    storage_dir = PROJECT_ROOT / "backend" / ".data"
    storage_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        storage_dir=storage_dir,
        max_pdf_pages=int(os.getenv("MAX_PDF_PAGES", "100")),
        model_name=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        transcript_model_name=os.getenv("ANTHROPIC_TRANSCRIPT_MODEL", "claude-haiku-4-5-20251001"),
        cors_origins=_parse_origins(os.getenv("CORS_ORIGINS")),
    )


settings = get_settings()
