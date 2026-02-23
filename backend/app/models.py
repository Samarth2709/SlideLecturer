"""Pydantic models shared by API handlers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DeckUploadResponse(BaseModel):
    deck_id: str
    filename: str
    slide_count: int
    created_at: datetime
    narrate_enabled: bool
    content_hash: str
    content_type: str = "pdf"
    source_url: str | None = None
    conversation: dict | None = None


class SlideSummary(BaseModel):
    index: int
    text_preview: str


class DeckSlidesResponse(BaseModel):
    deck_id: str
    slide_count: int
    slides: list[SlideSummary]


class DeckInfoResponse(BaseModel):
    deck_id: str
    filename: str
    slide_count: int
    created_at: datetime
    narrate_enabled: bool
    content_type: str = "pdf"
    source_url: str | None = None


TranscriptGenerationStatus = Literal["queued", "generating", "completed", "error", "disabled"]
TranscriptSlideStatus = Literal["pending", "generating", "completed", "error"]


class SlideTranscript(BaseModel):
    index: int
    status: TranscriptSlideStatus
    transcript: str | None = None
    error: str | None = None


class DeckTranscriptsResponse(BaseModel):
    deck_id: str
    narrate_enabled: bool
    status: TranscriptGenerationStatus
    total_slides: int
    completed_slides: int
    error: str | None = None
    slides: list[SlideTranscript]


class ChatHistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=50000)


class ContentEntry(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=50000)
    type: Literal["text", "file"] = "text"


class ChatStreamRequest(BaseModel):
    question: str = Field(min_length=1, max_length=6000)
    history: list[ChatHistoryTurn] = Field(default_factory=list, max_length=40)
    current_slide_index: int | None = Field(default=None, ge=0)
    focused_slide_index: int | None = Field(default=None, ge=0)
    additional_content: list[ContentEntry] = Field(default_factory=list, max_length=20)


class ClearChatResponse(BaseModel):
    status: Literal["ok"]


class DeleteDeckResponse(BaseModel):
    status: Literal["deleted"]


class SaveConversationRequest(BaseModel):
    branches_by_id: dict
    branch_order: list[str]
    active_branch_id: str
    branch_counter: int
    context_entries: list[dict] = Field(default_factory=list)


class SaveConversationResponse(BaseModel):
    status: Literal["ok"]


class URLIngestRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    narrate_enabled: bool = True


class SectionSummary(BaseModel):
    index: int
    heading: str
    text_preview: str
    html_content: str


class DeckSectionsResponse(BaseModel):
    deck_id: str
    section_count: int
    sections: list[SectionSummary]


class DeckHistoryEntry(BaseModel):
    deck_id: str
    filename: str
    content_hash: str
    content_type: str = "pdf"
    source_url: str | None = None
    slide_count: int
    created_at: str
    last_accessed_at: str


class DeckHistoryResponse(BaseModel):
    decks: list[DeckHistoryEntry]


class RemoveHistoryResponse(BaseModel):
    status: Literal["removed"]


class ErrorResponse(BaseModel):
    detail: str
