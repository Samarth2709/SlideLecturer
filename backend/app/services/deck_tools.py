"""RLM-style tool schemas and resolver for multi-deck sessions.

The AI navigates deck content as external state via 4 lightweight tools,
fetching only what is relevant to the current query.
"""

from __future__ import annotations

import json
from typing import Any

from .deck_service import DeckService, DeckNotFoundError, SessionRecord

# ── Tool schemas ─────────────────────────────────────────────────────

TOOL_LIST_DECKS = {
    "name": "list_decks",
    "description": (
        "List all decks in the session with index, filename, slide count, "
        "and a one-line description from slide 1. Call this first when you "
        "don't know which deck is relevant."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

TOOL_GET_DECK_OUTLINE = {
    "name": "get_deck_outline",
    "description": (
        "Get a lightweight slide-by-slide outline (120 char preview per slide) "
        "for a specific deck. Use before loading full content to confirm relevance."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"deck_id": {"type": "string"}},
        "required": ["deck_id"],
    },
}

TOOL_GET_DECK_SLIDES = {
    "name": "get_deck_slides",
    "description": (
        "Load the full text corpus of a specific deck. Heavy — only call after "
        "confirming relevance via list_decks or get_deck_outline. Never load "
        "more than one full deck per turn."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"deck_id": {"type": "string"}},
        "required": ["deck_id"],
    },
}

TOOL_GET_SLIDE_CONTENT = {
    "name": "get_slide_content",
    "description": (
        "Get text for a single slide by index. Use for targeted lookups "
        "when the student asks about a specific slide."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "deck_id": {"type": "string"},
            "slide_index": {
                "type": "integer",
                "description": "0-based slide index",
            },
        },
        "required": ["deck_id", "slide_index"],
    },
}

SESSION_DECK_TOOLS = [
    TOOL_LIST_DECKS,
    TOOL_GET_DECK_OUTLINE,
    TOOL_GET_DECK_SLIDES,
    TOOL_GET_SLIDE_CONTENT,
]


# ── Resolver ─────────────────────────────────────────────────────────

class DeckToolResolver:
    """Executes deck navigation tools against the session environment."""

    def __init__(self, session: SessionRecord, deck_service: DeckService):
        self.session = session
        self.deck_service = deck_service
        self.last_fetched_deck_id: str | None = None

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        dispatch = {
            "list_decks": self._list_decks,
            "get_deck_outline": self._get_deck_outline,
            "get_deck_slides": self._get_deck_slides,
            "get_slide_content": self._get_slide_content,
        }
        handler = dispatch.get(tool_name)
        if handler is None:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        try:
            return handler(tool_input)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)})

    def _list_decks(self, _tool_input: dict[str, Any]) -> str:
        result = []
        for idx, deck_id in enumerate(self.session.deck_ids):
            try:
                deck = self.deck_service.get_deck(deck_id)
                first_slide = (deck.slide_text[0][:120] if deck.slide_text else "").strip()
                result.append({
                    "index": idx,
                    "deck_id": deck_id,
                    "filename": deck.filename,
                    "slide_count": deck.slide_count,
                    "first_slide_preview": first_slide,
                })
            except DeckNotFoundError:
                result.append({
                    "index": idx,
                    "deck_id": deck_id,
                    "error": "Deck not found",
                })
        return json.dumps(result, ensure_ascii=False)

    def _get_deck_outline(self, tool_input: dict[str, Any]) -> str:
        deck_id = tool_input.get("deck_id", "")
        deck = self.deck_service.get_deck(deck_id)
        slides = []
        for i, text in enumerate(deck.slide_text):
            preview = " ".join(text.split())[:120]
            slides.append({"slide": i, "preview": preview})
        return json.dumps({
            "deck_id": deck_id,
            "filename": deck.filename,
            "slide_count": deck.slide_count,
            "slides": slides,
        }, ensure_ascii=False)

    def _get_deck_slides(self, tool_input: dict[str, Any]) -> str:
        deck_id = tool_input.get("deck_id", "")
        deck = self.deck_service.get_deck(deck_id)
        self.last_fetched_deck_id = deck_id

        parts = [f"Deck: {deck.filename} — {deck.slide_count} slides", ""]
        for i, text in enumerate(deck.slide_text):
            parts.append(f"--- Slide {i + 1} ---")
            parts.append(text.strip() or "(no text content)")
            parts.append("")
        return "\n".join(parts)

    def _get_slide_content(self, tool_input: dict[str, Any]) -> str:
        deck_id = tool_input.get("deck_id", "")
        slide_index = tool_input.get("slide_index", 0)
        text = self.deck_service.get_slide_text(deck_id, slide_index)
        self.last_fetched_deck_id = deck_id
        return json.dumps({
            "deck_id": deck_id,
            "slide_index": slide_index,
            "text": text,
        }, ensure_ascii=False)

    @staticmethod
    def tool_call_label(tool_name: str, tool_input: dict[str, Any]) -> str:
        if tool_name == "list_decks":
            return "Listing available decks..."
        if tool_name == "get_deck_outline":
            return "Scanning deck outline..."
        if tool_name == "get_deck_slides":
            return "Loading full deck content..."
        if tool_name == "get_slide_content":
            idx = tool_input.get("slide_index", "?")
            return f"Reading slide {idx}..."
        return f"Using {tool_name}..."
