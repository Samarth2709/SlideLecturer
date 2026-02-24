"""Prompt loading and templating for backend AI requests."""

from __future__ import annotations

from pathlib import Path


_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"



def _load_prompt(filename: str) -> str:
    return (_PROMPT_DIR / filename).read_text(encoding="utf-8")


SYSTEM_PROMPT = _load_prompt("system_prompt.md")
FOCUS_PROMPT_TEMPLATE = _load_prompt("focus_prompt.md")
TRANSCRIPT_PROMPT_TEMPLATE = _load_prompt("transcript_prompt.md")
TRANSCRIPT_SYSTEM_PROMPT = _load_prompt("transcript_system_prompt.md")
URL_FOCUS_PROMPT_TEMPLATE = _load_prompt("url_focus_prompt.md")
URL_TRANSCRIPT_PROMPT_TEMPLATE = _load_prompt("url_transcript_prompt.md")
SESSION_SYSTEM_PROMPT = _load_prompt("session_system_prompt.md")


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


def build_url_focus_prompt(question: str, section_heading: str, section_number: int) -> str:
    return URL_FOCUS_PROMPT_TEMPLATE.format(
        question=question,
        section_heading=section_heading,
        section_number=section_number,
    )


def build_url_transcript_prompt(
    section_number: int,
    total_sections: int,
    target_words: int,
    section_heading: str,
    section_text: str,
) -> str:
    normalized_text = section_text.strip() if section_text else "(No text found in this section.)"
    return URL_TRANSCRIPT_PROMPT_TEMPLATE.format(
        section_number=section_number,
        total_sections=total_sections,
        target_words=target_words,
        section_heading=section_heading,
        section_text=normalized_text,
    )
