"""Configuration management for SlideLecturer."""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


# Load .env file from project root on module import
# override=True ensures .env values take precedence over existing environment variables
_env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(_env_path, override=True)


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
