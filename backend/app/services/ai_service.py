"""Claude-powered chat service with deck and focus slide context."""

from __future__ import annotations

import base64
import json
import re
import threading
from datetime import datetime, timezone
from typing import Any, Generator

from anthropic import Anthropic, NOT_GIVEN

from ..config import settings
from ..prompts import (
    SYSTEM_PROMPT,
    TRANSCRIPT_SYSTEM_PROMPT,
    build_focus_prompt,
    build_transcript_prompt,
    build_user_prompt,
)
from .content_tools import ALL_TOOLS, ContentToolResolver
from .deck_service import DeckNotFoundError, DeckRecord, DeckService

_MAX_TOOL_ROUNDS = 5
_TOOL_INDICATOR_RE = re.compile(r"\n*> \*(?:Listing additional content|Reading \"[^\"]*\"|Using [^*]*)\.{3}\*\n*")


class AIService:
    """Coordinates AI requests against a loaded slide deck."""

    def __init__(self, deck_service: DeckService):
        self.deck_service = deck_service
        self.client = Anthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None
        self._conversation_log_lock = threading.RLock()
        self._conversation_log_path = settings.storage_dir / "logs" / "ai_conversations.log"
        self._conversation_log_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def is_available(self) -> bool:
        return self.client is not None

    def start_transcript_generation(self, deck_id: str, target_words: int = 175) -> None:
        try:
            should_start = self.deck_service.mark_transcript_generation_started(deck_id)
        except DeckNotFoundError:
            return

        if not should_start:
            return

        worker = threading.Thread(
            target=self._generate_transcripts_worker,
            args=(deck_id, target_words),
            daemon=True,
            name=f"transcript-worker-{deck_id[:8]}",
        )
        worker.start()

    def stream_answer(
        self,
        deck: DeckRecord,
        question: str,
        focused_slide_index: int | None,
        history: list[dict[str, str]] | None = None,
        additional_content: list[dict[str, Any]] | None = None,
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

        if history is not None:
            normalized_history = []
            for entry in history[-20:]:
                if entry.get("role") not in {"user", "assistant"} or not entry.get("content"):
                    continue
                content = entry["content"]
                if entry["role"] == "assistant":
                    content = _TOOL_INDICATOR_RE.sub("\n\n", content).strip()
                if content:
                    normalized_history.append({"role": entry["role"], "content": content})
        else:
            with deck.lock:
                normalized_history = list(deck.conversation_history[-20:])

        messages = self._build_history_messages(normalized_history)
        user_content: list[dict] = []

        # Keep deck context as a single prior conversation message when history exists.
        if history is not None:
            if not messages:
                user_content.append(self._build_pdf_document_block(deck.get_pdf_base64(), with_cache=True))
            elif not self._attach_pdf_to_first_user_message(messages, deck.get_pdf_base64()):
                user_content.append(self._build_pdf_document_block(deck.get_pdf_base64(), with_cache=True))
        else:
            with deck.lock:
                is_first_message = deck.is_first_message
            if is_first_message:
                user_content.append(self._build_pdf_document_block(deck.get_pdf_base64(), with_cache=True))

        resolver = ContentToolResolver(additional_content or [])
        tools = ALL_TOOLS if resolver.has_content() else None

        if resolver.has_content():
            user_content.append(self._build_text_block(resolver.content_names_summary()))

        prompt_text = build_user_prompt(question)
        if focused_slide_index is not None:
            slide_number = focused_slide_index + 1
            focus_png = self.deck_service.render_slide_png(deck.deck_id, focused_slide_index, scale=2.0)
            user_content.append(self._build_image_block(base64.b64encode(focus_png).decode("utf-8")))
            prompt_text = build_focus_prompt(question, slide_number)

        user_content.append(self._build_text_block(prompt_text))

        messages = messages + [{"role": "user", "content": user_content}]
        conversation_started = len(normalized_history) == 0
        self._log_provider_request(
            deck=deck,
            model_name=settings.model_name,
            system_prompt=SYSTEM_PROMPT,
            system_prompt_logged=conversation_started,
            messages=messages,
            focused_slide_index=focused_slide_index,
            history_turns=len(normalized_history),
        )

        full_response = ""
        clean_response = ""
        try:
            for round_num in range(_MAX_TOOL_ROUNDS + 1):
                tool_use_blocks: list[dict] = []

                with self.client.messages.stream(
                    model=settings.model_name,
                    max_tokens=2048,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    tools=tools if tools else NOT_GIVEN,
                ) as stream:
                    current_block_type: str | None = None
                    current_tool_use: dict | None = None

                    for event in stream:
                        if event.type == "content_block_start":
                            block = event.content_block
                            if block.type == "text":
                                current_block_type = "text"
                            elif block.type == "tool_use":
                                current_block_type = "tool_use"
                                current_tool_use = {
                                    "id": block.id,
                                    "name": block.name,
                                    "input_json": "",
                                }

                        elif event.type == "content_block_delta":
                            if current_block_type == "text" and hasattr(event.delta, "text"):
                                full_response += event.delta.text
                                clean_response += event.delta.text
                                yield event.delta.text
                            elif current_block_type == "tool_use" and hasattr(event.delta, "partial_json"):
                                current_tool_use["input_json"] += event.delta.partial_json

                        elif event.type == "content_block_stop":
                            if current_block_type == "tool_use" and current_tool_use:
                                tool_use_blocks.append(current_tool_use)
                            current_block_type = None
                            current_tool_use = None

                    final_message = stream.get_final_message()

                # If model did not request tool use, we are done.
                if not tool_use_blocks or final_message.stop_reason != "tool_use":
                    break

                # Build the assistant message content from the final message.
                assistant_content: list[dict] = []
                for block in final_message.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                messages.append({"role": "assistant", "content": assistant_content})

                # Execute each tool and build the tool results message.
                tool_results: list[dict] = []
                for tool_block in tool_use_blocks:
                    try:
                        input_data = json.loads(tool_block["input_json"]) if tool_block["input_json"] else {}
                    except json.JSONDecodeError:
                        input_data = {}
                    label = self._tool_call_label(tool_block["name"], input_data)
                    indicator = f"\n\n> *{label}*\n\n"
                    full_response += indicator
                    yield indicator
                    result = resolver.execute(tool_block["name"], input_data)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block["id"],
                        "content": result,
                    })
                messages.append({"role": "user", "content": tool_results})

        except Exception as exc:  # noqa: BLE001
            self._log_provider_error(deck.deck_id, str(exc))
            yield f"[Error: {exc}]"
            return

        self._log_provider_response(deck.deck_id, full_response)

        if history is None:
            with deck.lock:
                deck.conversation_history.append({"role": "user", "content": prompt_text})
                deck.conversation_history.append({"role": "assistant", "content": clean_response})
                deck.is_first_message = False

    def _generate_transcripts_worker(self, deck_id: str, target_words: int) -> None:
        try:
            deck = self.deck_service.get_deck(deck_id)
        except DeckNotFoundError:
            return

        if not self.is_available:
            try:
                self.deck_service.mark_transcript_generation_error(
                    deck_id,
                    "AI service not available. Set ANTHROPIC_API_KEY.",
                )
            except DeckNotFoundError:
                return
            return

        if deck.slide_count > settings.max_pdf_pages:
            try:
                self.deck_service.mark_transcript_generation_error(
                    deck_id,
                    (
                        f"Deck has {deck.slide_count} pages, which exceeds the configured limit of "
                        f"{settings.max_pdf_pages} pages."
                    ),
                )
            except DeckNotFoundError:
                return
            return

        try:
            pdf_base64 = deck.get_pdf_base64()
        except FileNotFoundError:
            try:
                self.deck_service.mark_transcript_generation_error(
                    deck_id,
                    "Deck files are no longer available for transcript generation.",
                )
            except DeckNotFoundError:
                return
            return

        slide_errors: list[str] = []

        for slide_index in range(deck.slide_count):
            try:
                self.deck_service.mark_transcript_slide_started(deck_id, slide_index)
                transcript = self._generate_slide_transcript(
                    deck=deck,
                    slide_index=slide_index,
                    target_words=target_words,
                    pdf_base64=pdf_base64,
                )
                self.deck_service.mark_transcript_slide_completed(deck_id, slide_index, transcript)
            except DeckNotFoundError:
                return
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc).strip() or "Unknown transcript generation error"
                try:
                    self.deck_service.mark_transcript_slide_error(deck_id, slide_index, error_text)
                except DeckNotFoundError:
                    return
                slide_errors.append(f"Slide {slide_index + 1}: {error_text}")

        try:
            if slide_errors:
                summary = "; ".join(slide_errors[:3])
                if len(slide_errors) > 3:
                    summary += f"; ... ({len(slide_errors) - 3} additional slide errors)"
                self.deck_service.mark_transcript_generation_error(
                    deck_id,
                    f"Transcript generation completed with errors. {summary}",
                )
            else:
                self.deck_service.mark_transcript_generation_completed(deck_id)
        except DeckNotFoundError:
            return

    def _generate_slide_transcript(
        self,
        deck: DeckRecord,
        slide_index: int,
        target_words: int,
        pdf_base64: str,
    ) -> str:
        if not self.client:
            raise RuntimeError("AI service not available.")

        slide_text = self.deck_service.get_slide_text(deck.deck_id, slide_index)
        slide_text = slide_text[:8000]

        prompt_text = build_transcript_prompt(
            slide_number=slide_index + 1,
            total_slides=deck.slide_count,
            target_words=target_words,
            slide_text=slide_text,
        )

        user_content = [
            self._build_pdf_document_block(pdf_base64, with_cache=True),
            self._build_text_block(prompt_text),
        ]

        response = self.client.messages.create(
            model=settings.transcript_model_name,
            max_tokens=900,
            system=TRANSCRIPT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )

        transcript = self._extract_response_text(response)
        normalized_transcript = " ".join(transcript.split())
        if not normalized_transcript:
            raise RuntimeError("Model returned an empty transcript.")
        return normalized_transcript

    @staticmethod
    def _tool_call_label(tool_name: str, tool_input: dict[str, Any]) -> str:
        if tool_name == "list_additional_content":
            return "Listing additional content..."
        if tool_name == "get_additional_content":
            name = tool_input.get("name", "")
            return f"Reading \"{name}\"..." if name else "Reading additional content..."
        return f"Using {tool_name}..."

    @staticmethod
    def _extract_response_text(response) -> str:
        text_chunks: list[str] = []
        for block in getattr(response, "content", []):
            text_value = getattr(block, "text", None)
            if text_value:
                text_chunks.append(text_value)
                continue

            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                text_chunks.append(str(block["text"]))

        return "".join(text_chunks).strip()

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

    @classmethod
    def _build_history_messages(cls, history: list[dict[str, str]]) -> list[dict]:
        messages: list[dict] = []
        for entry in history:
            role = str(entry.get("role") or "").strip()
            content = str(entry.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            messages.append(
                {
                    "role": role,
                    "content": [cls._build_text_block(content)],
                }
            )
        return messages

    def _attach_pdf_to_first_user_message(self, messages: list[dict], pdf_base64: str) -> bool:
        for message in messages:
            if message.get("role") != "user":
                continue

            content = message.get("content")
            if not isinstance(content, list):
                content = [self._build_text_block(str(content or ""))]

            has_document_block = any(
                isinstance(block, dict) and block.get("type") == "document" for block in content
            )
            if not has_document_block:
                content.insert(0, self._build_pdf_document_block(pdf_base64, with_cache=True))

            message["content"] = content
            return True
        return False

    def _log_provider_request(
        self,
        deck: DeckRecord,
        model_name: str,
        system_prompt: str,
        system_prompt_logged: bool,
        messages: list[dict],
        focused_slide_index: int | None,
        history_turns: int,
    ) -> None:
        focus_mode_enabled = focused_slide_index is not None
        attachment_count = self._count_attachments(messages)

        lines = [
            f"[{self._utc_timestamp()}] OUTBOUND -> anthropic.messages.stream",
            f"deck_id={deck.deck_id} filename={deck.filename!r} model={model_name}",
            f"focus_mode={focus_mode_enabled} focused_slide_index={focused_slide_index}",
            f"history_turns={history_turns} attachments={attachment_count}",
        ]

        if system_prompt_logged:
            lines.extend(
                [
                    "SYSTEM PROMPT:",
                    system_prompt,
                ]
            )

        lines.append("MESSAGES SENT:")
        for idx, message in enumerate(messages, start=1):
            lines.extend(self._format_message_for_log(message, idx))

        self._append_conversation_log(lines)

    def _log_provider_response(self, deck_id: str, response_text: str) -> None:
        lines = [
            f"[{self._utc_timestamp()}] INBOUND <- anthropic.messages.stream",
            f"deck_id={deck_id}",
            "ASSISTANT RESPONSE:",
            response_text,
            "--------------------------------------------------------------------------------",
        ]
        self._append_conversation_log(lines, trailing_newlines=3)

    def _log_provider_error(self, deck_id: str, error_text: str) -> None:
        lines = [
            f"[{self._utc_timestamp()}] INBOUND <- anthropic.messages.stream",
            f"deck_id={deck_id}",
            f"ERROR: {error_text}",
        ]
        self._append_conversation_log(lines, trailing_newlines=3)

    def _append_conversation_log(self, lines: list[str], trailing_newlines: int = 1) -> None:
        payload = "\n".join(lines) + ("\n" * trailing_newlines)
        with self._conversation_log_lock:
            with self._conversation_log_path.open("a", encoding="utf-8") as handle:
                handle.write(payload)

    def _format_message_for_log(self, message: dict, index: int) -> list[str]:
        role = message.get("role", "unknown")
        output = [f"- message[{index}] role={role}"]
        content = message.get("content")

        if not isinstance(content, list):
            output.append(f"  text={str(content or '')}")
            return output

        for block_index, block in enumerate(content, start=1):
            if not isinstance(block, dict):
                output.append(f"  block[{block_index}] raw={str(block)}")
                continue

            block_type = str(block.get("type") or "unknown")
            if block_type == "text":
                output.append(f"  block[{block_index}] type=text")
                output.append(str(block.get("text") or ""))
                continue

            source = block.get("source") if isinstance(block.get("source"), dict) else {}
            media_type = source.get("media_type", "unknown")
            data = source.get("data")
            base64_chars = len(data) if isinstance(data, str) else 0
            cache_control = block.get("cache_control")
            output.append(
                f"  block[{block_index}] type={block_type} media_type={media_type} "
                f"base64_chars={base64_chars} cache_control={cache_control}"
            )

        return output

    @staticmethod
    def _count_attachments(messages: list[dict]) -> int:
        attachment_count = 0
        for message in messages:
            content = message.get("content")
            if not isinstance(content, list):
                continue

            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") in {"document", "image"}:
                    attachment_count += 1
        return attachment_count

    @staticmethod
    def _utc_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()
