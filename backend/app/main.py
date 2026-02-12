"""FastAPI backend for the SlideLecturer web app."""

from __future__ import annotations

import json
from collections.abc import Generator

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response, StreamingResponse

from .config import settings
from .models import (
    ChatStreamRequest,
    ClearChatResponse,
    DeckInfoResponse,
    DeckSlidesResponse,
    DeckTranscriptsResponse,
    DeckUploadResponse,
    DeleteDeckResponse,
    SlideSummary,
)
from .services.ai_service import AIService
from .services.deck_service import DeckNotFoundError, DeckService, DeckValidationError


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


deck_service = DeckService(settings.storage_dir)
ai_service = AIService(deck_service)

app = FastAPI(title="SlideLecturer Web API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz", response_class=PlainTextResponse)
def healthcheck() -> str:
    return "ok"


@app.post("/api/v1/decks/upload", response_model=DeckUploadResponse)
def upload_deck(file: UploadFile = File(...)) -> DeckUploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    try:
        record = deck_service.create_deck(file.filename, file.file)
    except DeckValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    ai_service.start_transcript_generation(record.deck_id, target_words=175)

    return DeckUploadResponse(
        deck_id=record.deck_id,
        filename=record.filename,
        slide_count=record.slide_count,
        created_at=record.created_at,
    )


@app.get("/api/v1/decks/{deck_id}", response_model=DeckInfoResponse)
def get_deck(deck_id: str) -> DeckInfoResponse:
    try:
        deck = deck_service.get_deck(deck_id)
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc

    return DeckInfoResponse(
        deck_id=deck.deck_id,
        filename=deck.filename,
        slide_count=deck.slide_count,
        created_at=deck.created_at,
    )


@app.get("/api/v1/decks/{deck_id}/slides", response_model=DeckSlidesResponse)
def get_slides(deck_id: str) -> DeckSlidesResponse:
    try:
        deck = deck_service.get_deck(deck_id)
        slides_raw = deck_service.list_slides(deck_id)
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc

    return DeckSlidesResponse(
        deck_id=deck_id,
        slide_count=deck.slide_count,
        slides=[SlideSummary(**slide) for slide in slides_raw],
    )


@app.get("/api/v1/decks/{deck_id}/slides/{slide_index}/text")
def get_slide_text(deck_id: str, slide_index: int) -> dict:
    try:
        text = deck_service.get_slide_text(deck_id, slide_index)
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {"deck_id": deck_id, "slide_index": slide_index, "text": text}


@app.get("/api/v1/decks/{deck_id}/transcripts", response_model=DeckTranscriptsResponse)
def get_deck_transcripts(deck_id: str) -> DeckTranscriptsResponse:
    try:
        snapshot = deck_service.get_transcript_snapshot(deck_id)
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc

    return DeckTranscriptsResponse(**snapshot)


@app.get("/api/v1/decks/{deck_id}/slides/{slide_index}/image")
def get_slide_image(
    deck_id: str,
    slide_index: int,
    scale: float = Query(default=2.0, ge=0.5, le=4.0),
) -> Response:
    try:
        png_bytes = deck_service.render_slide_png(deck_id, slide_index, scale=scale)
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return Response(content=png_bytes, media_type="image/png")


@app.post("/api/v1/decks/{deck_id}/chat/clear", response_model=ClearChatResponse)
def clear_chat(deck_id: str) -> ClearChatResponse:
    try:
        deck_service.clear_chat(deck_id)
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc

    return ClearChatResponse(status="ok")


@app.delete("/api/v1/decks/{deck_id}", response_model=DeleteDeckResponse)
def delete_deck(deck_id: str) -> DeleteDeckResponse:
    try:
        deck_service.delete_deck(deck_id)
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc

    return DeleteDeckResponse(status="deleted")


@app.post("/api/v1/decks/{deck_id}/chat/stream")
def stream_chat(deck_id: str, body: ChatStreamRequest) -> StreamingResponse:
    try:
        deck = deck_service.get_deck(deck_id)
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc

    if body.focused_slide_index is not None and body.focused_slide_index >= deck.slide_count:
        raise HTTPException(status_code=400, detail="Focused slide index is out of range")

    if body.current_slide_index is not None and body.current_slide_index >= deck.slide_count:
        raise HTTPException(status_code=400, detail="Current slide index is out of range")

    def event_stream() -> Generator[str, None, None]:
        yield _sse({"type": "start"})

        for chunk in ai_service.stream_answer(
            deck=deck,
            question=body.question,
            current_slide_index=body.current_slide_index,
            focused_slide_index=body.focused_slide_index,
            history=[entry.model_dump() for entry in body.history],
        ):
            if chunk.startswith("[Error:"):
                error_message = chunk.removeprefix("[Error:").removesuffix("]").strip()
                yield _sse({"type": "error", "message": error_message})
                yield _sse({"type": "done"})
                return
            yield _sse({"type": "chunk", "text": chunk})

        yield _sse({"type": "done"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
