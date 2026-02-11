"""Claude-powered chat service with deck and focus slide context."""

from __future__ import annotations

import base64
from typing import Generator

from anthropic import Anthropic

from ..config import settings
from ..prompts import SYSTEM_PROMPT, build_focus_prompt, build_user_prompt
from .deck_service import DeckRecord, DeckService


class AIService:
    """Coordinates AI requests against a loaded slide deck."""

    def __init__(self, deck_service: DeckService):
        self.deck_service = deck_service
        self.client = Anthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None

    @property
    def is_available(self) -> bool:
        return self.client is not None

    def stream_answer(
        self,
        deck: DeckRecord,
        question: str,
        current_slide_index: int | None,
        focused_slide_index: int | None,
    ) -> Generator[str, None, None]:
        if not self.is_available:
            yield "[Error: AI service not available. Set ANTHROPIC_API_KEY.]"
            return

        if deck.slide_count > settings.max_pdf_pages:
            yield (
                f"[Error: Deck has {deck.slide_count} pages, which exceeds the limit of "
                f"{settings.max_pdf_pages} pages supported by the AI service.]"
            )
            return

        with deck.lock:
            is_first_message = deck.is_first_message
            history = list(deck.conversation_history[-20:])

        user_content: list[dict] = [
            self._build_pdf_document_block(deck.get_pdf_base64(), with_cache=is_first_message)
        ]

        prompt_text = build_user_prompt(question)
        if focused_slide_index is not None:
            slide_number = focused_slide_index + 1
            focus_png = self.deck_service.render_slide_png(deck.deck_id, focused_slide_index, scale=2.0)
            user_content.append(self._build_image_block(base64.b64encode(focus_png).decode("utf-8")))
            prompt_text = build_focus_prompt(question, slide_number)
        elif current_slide_index is not None:
            # Keep contextual continuity in the prompt, even without focus image.
            prompt_text = build_user_prompt(f"(Current slide: {current_slide_index + 1})\n\n{question}")

        user_content.append(self._build_text_block(prompt_text))

        messages = history + [{"role": "user", "content": user_content}]

        full_response = ""
        try:
            with self.client.messages.stream(
                model=settings.model_name,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield text
        except Exception as exc:  # noqa: BLE001
            yield f"[Error: {exc}]"
            return

        with deck.lock:
            deck.conversation_history.append({"role": "user", "content": prompt_text})
            deck.conversation_history.append({"role": "assistant", "content": full_response})
            deck.is_first_message = False

    @staticmethod
    def _build_pdf_document_block(pdf_base64: str, with_cache: bool = False) -> dict:
        block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_base64,
            },
        }
        if with_cache:
            block["cache_control"] = {"type": "ephemeral"}
        return block

    @staticmethod
    def _build_image_block(image_base64: str) -> dict:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": image_base64,
            },
        }

    @staticmethod
    def _build_text_block(text: str) -> dict:
        return {
            "type": "text",
            "text": text,
        }
