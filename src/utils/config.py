"""Configuration management for SlideLecturer."""

import stat
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


_env_path = Path(__file__).parent.parent.parent / ".env"


def _load_dotenv_if_available(env_path: Path) -> None:
    """Load .env only when the file is locally available.

    On macOS with iCloud optimization enabled, files can appear but be
    marked as dataless placeholders. Accessing them may block.
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
        # Ignore transient file-provider errors.
        return


_load_dotenv_if_available(_env_path)


@dataclass
class Config:
    """Application configuration."""

    anthropic_api_key: Optional[str] = None

    @property
    def has_api_key(self) -> bool:
        """Check if API key is configured."""
        return bool(self.anthropic_api_key)


def get_api_key() -> Optional[str]:
    """Get Anthropic API key from environment.

    The .env file is automatically loaded into the environment
    when this module is imported.
    """
    return os.environ.get("ANTHROPIC_API_KEY")


def load_config() -> Config:
    """Load application configuration."""
    return Config(anthropic_api_key=get_api_key())
