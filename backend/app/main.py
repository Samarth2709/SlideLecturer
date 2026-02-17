"""FastAPI backend for the SlideLecturer web app."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4
from collections.abc import Generator

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse

from .config import settings
from .models import (
    ChatStreamRequest,
    ClearChatResponse,
    DeckInfoResponse,
    DeckSlidesResponse,
    DeckTranscriptsResponse,
    DeckUploadResponse,
    DeleteDeckResponse,
    SaveConversationRequest,
    SaveConversationResponse,
    SlideSummary,
)
from .services.ai_service import AIService
from .services.deck_service import DeckNotFoundError, DeckService, DeckValidationError
from .services.tts_service import ElevenLabsTTSService, TTSConfigurationError, TTSProviderError


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


deck_service = DeckService(settings.storage_dir)
ai_service = AIService(deck_service)
tts_service = ElevenLabsTTSService(
    api_key=settings.elevenlabs_api_key,
    voice_id=settings.elevenlabs_voice_id,
    voice_name=settings.elevenlabs_voice_name,
    model_id=settings.elevenlabs_model_id,
    output_format=settings.elevenlabs_output_format,
    base_url=settings.elevenlabs_base_url,
    timeout_seconds=settings.elevenlabs_timeout_seconds,
)


def _load_ready_transcript(deck_id: str, slide_index: int):
    try:
        deck = deck_service.get_deck(deck_id)
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc

    if not deck.narrate_enabled:
        raise HTTPException(
            status_code=409,
            detail="Narration is disabled for this deck.",
        )

    try:
        transcript = deck_service.get_slide_transcript(deck_id, slide_index)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if transcript is None:
        raise HTTPException(
            status_code=409,
            detail="Transcript is not ready for this slide yet.",
        )

    return deck, transcript


def _speech_cache_paths(deck, slide_index: int, transcript: str):
    identity = tts_service.build_cache_identity(transcript)
    cache_dir = deck.source_path.parent / "tts_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    audio_path = cache_dir / f"slide_{slide_index + 1:04d}_{identity.cache_key}.{identity.extension}"
    metadata_path = audio_path.with_suffix(f"{audio_path.suffix}.json")
    return identity, audio_path, metadata_path


def _load_cached_media_type(metadata_path: Path, fallback: str) -> str:
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fallback
    except Exception:  # noqa: BLE001
        return fallback

    if not isinstance(payload, dict):
        return fallback

    media_type = str(payload.get("media_type") or "").strip()
    return media_type or fallback


def _write_speech_cache_metadata(metadata_path: Path, media_type: str, voice_id: str) -> None:
    payload = {
        "media_type": media_type,
        "voice_id": voice_id,
        "model_id": settings.elevenlabs_model_id,
        "output_format": settings.elevenlabs_output_format,
    }
    temp_path = metadata_path.with_name(f".{metadata_path.name}.{uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(payload), encoding="utf-8")
    temp_path.replace(metadata_path)


def _write_speech_cache_bytes(
    audio_path: Path,
    metadata_path: Path,
    audio_bytes: bytes,
    media_type: str,
    voice_id: str,
) -> None:
    temp_path = audio_path.with_name(f".{audio_path.name}.{uuid4().hex}.tmp")
    temp_path.write_bytes(audio_bytes)
    temp_path.replace(audio_path)
    _write_speech_cache_metadata(metadata_path, media_type=media_type, voice_id=voice_id)


def _promote_streamed_speech_cache(
    temp_audio_path: Path,
    audio_path: Path,
    metadata_path: Path,
    media_type: str,
    voice_id: str,
) -> None:
    temp_audio_path.replace(audio_path)
    _write_speech_cache_metadata(metadata_path, media_type=media_type, voice_id=voice_id)

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
def upload_deck(
    file: UploadFile = File(...),
    narrate_enabled: bool = Form(default=True),
) -> DeckUploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    try:
        record = deck_service.create_deck(file.filename, file.file, narrate_enabled=narrate_enabled)
    except DeckValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if record.narrate_enabled:
        ai_service.start_transcript_generation(record.deck_id, target_words=175)

    conversation = deck_service.load_conversation(record.content_hash)

    return DeckUploadResponse(
        deck_id=record.deck_id,
        filename=record.filename,
        slide_count=record.slide_count,
        created_at=record.created_at,
        narrate_enabled=record.narrate_enabled,
        content_hash=record.content_hash,
        conversation=conversation,
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
        narrate_enabled=deck.narrate_enabled,
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


@app.post("/api/v1/decks/{deck_id}/slides/{slide_index}/transcript/speech")
def speak_slide_transcript(deck_id: str, slide_index: int) -> Response:
    deck, transcript = _load_ready_transcript(deck_id, slide_index)

    try:
        identity, audio_path, metadata_path = _speech_cache_paths(deck, slide_index, transcript)
    except TTSConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TTSProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if audio_path.exists():
        media_type = _load_cached_media_type(metadata_path, identity.media_type)
        return Response(
            content=audio_path.read_bytes(),
            media_type=media_type,
            headers={
                "Cache-Control": "no-store",
                "X-Speech-Cache": "hit",
            },
        )

    try:
        synthesis = tts_service.synthesize(transcript)
    except TTSProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        _write_speech_cache_bytes(
            audio_path=audio_path,
            metadata_path=metadata_path,
            audio_bytes=synthesis.audio_bytes,
            media_type=synthesis.media_type,
            voice_id=synthesis.voice_id,
        )
    except OSError:
        # Cache write failures should not block narration.
        pass

    return Response(
        content=synthesis.audio_bytes,
        media_type=synthesis.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Speech-Cache": "miss",
        },
    )


@app.get("/api/v1/decks/{deck_id}/slides/{slide_index}/transcript/speech/stream")
def stream_slide_transcript_speech(deck_id: str, slide_index: int):
    deck, transcript = _load_ready_transcript(deck_id, slide_index)

    try:
        identity, audio_path, metadata_path = _speech_cache_paths(deck, slide_index, transcript)
    except TTSConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TTSProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if audio_path.exists():
        media_type = _load_cached_media_type(metadata_path, identity.media_type)
        return FileResponse(
            path=audio_path,
            media_type=media_type,
            headers={
                "Cache-Control": "no-store",
                "X-Speech-Cache": "hit",
            },
        )

    try:
        upstream_stream = tts_service.stream_synthesize(transcript)
    except TTSConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except TTSProviderError as exc:
        # Some ElevenLabs voices/models intermittently fail on stream mode.
        # Fallback to non-stream synthesis so playback still succeeds.
        try:
            synthesis = tts_service.synthesize(transcript)
        except TTSProviderError as fallback_exc:
            raise HTTPException(
                status_code=502,
                detail=f"{str(exc)} | Fallback synth failed: {str(fallback_exc)}",
            ) from fallback_exc
        except ValueError as fallback_exc:
            raise HTTPException(status_code=400, detail=str(fallback_exc)) from fallback_exc

        try:
            _write_speech_cache_bytes(
                audio_path=audio_path,
                metadata_path=metadata_path,
                audio_bytes=synthesis.audio_bytes,
                media_type=synthesis.media_type,
                voice_id=synthesis.voice_id,
            )
        except OSError:
            # Cache write failures should not block narration.
            pass

        return Response(
            content=synthesis.audio_bytes,
            media_type=synthesis.media_type,
            headers={
                "Cache-Control": "no-store",
                "X-Speech-Cache": "miss",
                "X-Speech-Mode": "fallback-sync",
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    temp_audio_path = audio_path.with_name(f".{audio_path.name}.{uuid4().hex}.part")

    def iter_audio_chunks() -> Generator[bytes, None, None]:
        wrote_any_data = False
        cache_file = None
        cache_write_failed = False
        try:
            try:
                cache_file = temp_audio_path.open("wb")
            except OSError:
                # Cache persistence is best-effort. Keep streaming uncached.
                cache_file = None
                cache_write_failed = True

            while True:
                chunk = upstream_stream.response.read(16384)
                if not chunk:
                    break
                wrote_any_data = True
                if cache_file is not None:
                    try:
                        cache_file.write(chunk)
                    except OSError:
                        # Continue streaming even if local cache storage fails.
                        cache_write_failed = True
                        try:
                            cache_file.close()
                        except OSError:
                            pass
                        cache_file = None
                yield chunk

            if wrote_any_data and not cache_write_failed and cache_file is not None:
                try:
                    cache_file.close()
                except OSError:
                    cache_write_failed = True
                    cache_file = None

            if wrote_any_data and not cache_write_failed:
                try:
                    _promote_streamed_speech_cache(
                        temp_audio_path=temp_audio_path,
                        audio_path=audio_path,
                        metadata_path=metadata_path,
                        media_type=upstream_stream.media_type,
                        voice_id=upstream_stream.voice_id,
                    )
                except OSError:
                    pass
        finally:
            if cache_file is not None:
                try:
                    cache_file.close()
                except OSError:
                    pass
            upstream_stream.response.close()
            if temp_audio_path.exists():
                try:
                    temp_audio_path.unlink()
                except OSError:
                    pass

    return StreamingResponse(
        iter_audio_chunks(),
        media_type=upstream_stream.media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Speech-Cache": "miss",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/v1/decks/{deck_id}/conversation/save", response_model=SaveConversationResponse)
def save_conversation(deck_id: str, body: SaveConversationRequest) -> SaveConversationResponse:
    try:
        deck = deck_service.get_deck(deck_id)
    except DeckNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc

    conversation_data = {
        "version": 1,
        "content_hash": deck.content_hash,
        "filename": deck.filename,
        "slide_count": deck.slide_count,
        "branches_by_id": body.branches_by_id,
        "branch_order": body.branch_order,
        "active_branch_id": body.active_branch_id,
        "branch_counter": body.branch_counter,
        "context_entries": body.context_entries,
    }
    deck_service.save_conversation(deck.content_hash, conversation_data)
    return SaveConversationResponse(status="ok")


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

    def event_stream() -> Generator[str, None, None]:
        yield _sse({"type": "start"})

        for chunk in ai_service.stream_answer(
            deck=deck,
            question=body.question,
            focused_slide_index=body.focused_slide_index,
            history=[entry.model_dump() for entry in body.history],
            additional_context=body.additional_context,
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
