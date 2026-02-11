"""Prompt loading and templating for backend AI requests."""

from __future__ import annotations

from pathlib import Path


_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"



def _load_prompt(filename: str) -> str:
    return (_PROMPT_DIR / filename).read_text(encoding="utf-8")


SYSTEM_PROMPT = _load_prompt("system_prompt.txt")
USER_PROMPT_TEMPLATE = _load_prompt("user_prompt.txt")
FOCUS_PROMPT_TEMPLATE = _load_prompt("focus_prompt.txt")



def build_user_prompt(question: str) -> str:
    return USER_PROMPT_TEMPLATE.format(question=question)



def build_focus_prompt(question: str, slide_number: int) -> str:
    return FOCUS_PROMPT_TEMPLATE.format(question=question, slide_number=slide_number)
