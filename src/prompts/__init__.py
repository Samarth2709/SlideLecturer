"""Prompts module for AI service."""

from pathlib import Path

# Load prompts from txt files
_PROMPTS_DIR = Path(__file__).parent


def _load_prompt(filename: str) -> str:
    """Load a prompt from a txt file."""
    filepath = _PROMPTS_DIR / filename
    return filepath.read_text(encoding="utf-8")


# Load prompts
SYSTEM_PROMPT = _load_prompt("system_prompt.txt")
USER_PROMPT_TEMPLATE = _load_prompt("user_prompt.txt")
FOCUS_PROMPT_TEMPLATE = _load_prompt("focus_prompt.txt")


def build_user_prompt(question: str) -> str:
    """Build the user prompt for non-focus mode.

    Args:
        question: The user's question

    Returns:
        Formatted prompt string
    """
    return USER_PROMPT_TEMPLATE.format(question=question)


def build_focus_prompt(question: str, slide_number: int) -> str:
    """Build the user prompt for focus mode.

    Args:
        question: The user's question
        slide_number: The slide number (1-indexed)

    Returns:
        Formatted prompt string
    """
    return FOCUS_PROMPT_TEMPLATE.format(
        question=question,
        slide_number=slide_number,
    )


__all__ = [
    "SYSTEM_PROMPT",
    "USER_PROMPT_TEMPLATE",
    "FOCUS_PROMPT_TEMPLATE",
    "build_user_prompt",
    "build_focus_prompt",
]
