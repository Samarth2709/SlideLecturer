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


class ChatHistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=50000)


class ChatStreamRequest(BaseModel):
    question: str = Field(min_length=1, max_length=6000)
    history: list[ChatHistoryTurn] = Field(default_factory=list, max_length=40)
    current_slide_index: int | None = Field(default=None, ge=0)
    focused_slide_index: int | None = Field(default=None, ge=0)


class ClearChatResponse(BaseModel):
    status: Literal["ok"]


class DeleteDeckResponse(BaseModel):
    status: Literal["deleted"]


class ErrorResponse(BaseModel):
    detail: str
