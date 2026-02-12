"""Prompt loading and templating for backend AI requests."""

from __future__ import annotations

from pathlib import Path


_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"



def _load_prompt(filename: str) -> str:
    return (_PROMPT_DIR / filename).read_text(encoding="utf-8")


SYSTEM_PROMPT = _load_prompt("system_prompt.txt")
USER_PROMPT_TEMPLATE = _load_prompt("user_prompt.txt")
FOCUS_PROMPT_TEMPLATE = _load_prompt("focus_prompt.txt")
TRANSCRIPT_PROMPT_TEMPLATE = _load_prompt("transcript_prompt.txt")



def build_user_prompt(question: str) -> str:
    return USER_PROMPT_TEMPLATE.format(question=question)



def build_focus_prompt(question: str, slide_number: int) -> str:
    return FOCUS_PROMPT_TEMPLATE.format(question=question, slide_number=slide_number)


def build_transcript_prompt(
    slide_number: int,
    total_slides: int,
    target_words: int,
    slide_text: str,
) -> str:
    normalized_slide_text = slide_text.strip() if slide_text else "(No extractable text found on this slide.)"
    return TRANSCRIPT_PROMPT_TEMPLATE.format(
        slide_number=slide_number,
        total_slides=total_slides,
        target_words=target_words,
        slide_text=normalized_slide_text,
    )
