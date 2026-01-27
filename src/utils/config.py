"""Configuration management for SlideLecturer."""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Application configuration."""

    anthropic_api_key: Optional[str] = None

    @property
    def has_api_key(self) -> bool:
        """Check if API key is configured."""
        return bool(self.anthropic_api_key)


def get_api_key() -> Optional[str]:
    """Get Anthropic API key from environment or .env file.

    Checks in order:
    1. ANTHROPIC_API_KEY environment variable
    2. .env file in project root
    """
    # Check environment variable first
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return api_key

    # Try loading from .env file
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")

    return None


def load_config() -> Config:
    """Load application configuration."""
    return Config(anthropic_api_key=get_api_key())
