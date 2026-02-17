"""Slide deck ingestion, conversion, and rendering service."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Literal
from uuid import uuid4

import fitz


SUPPORTED_EXTENSIONS = {".pdf", ".ppt", ".pptx"}


class DeckValidationError(RuntimeError):
    """Raised when a deck cannot be ingested."""


class DeckNotFoundError(KeyError):
    """Raised when a deck ID does not exist."""


@dataclass
class DeckRecord:
    """In-memory metadata and runtime state for a deck."""

    deck_id: str
    filename: str
    source_path: Path
    pdf_path: Path
    slide_count: int
    narrate_enabled: bool
    slide_text: list[str]
    transcript_cache_key: str | None = None
    transcript_status: Literal["queued", "generating", "completed", "error", "disabled"] = "queued"
    transcript_error: str | None = None
    transcript_active_slide_index: int | None = None
    transcripts: list[str | None] = field(default_factory=list)
    transcript_slide_errors: list[str | None] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str = ""
    conversation_history: list[dict] = field(default_factory=list)
    is_first_message: bool = True
    _pdf_base64: str | None = None
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def get_pdf_base64(self) -> str:
        with self.lock:
            if self._pdf_base64 is None:
                self._pdf_base64 = base64.standard_b64encode(self.pdf_path.read_bytes()).decode("utf-8")
            return self._pdf_base64


class DeckService:
    """Service that manages deck lifecycle and slide extraction."""

    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_cache_dir = self.storage_dir / "transcript_cache"
        self.transcript_cache_dir.mkdir(parents=True, exist_ok=True)
        self.conversations_dir = self.storage_dir / "conversations"
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        self._decks: dict[str, DeckRecord] = {}
        self._lock = threading.RLock()

    def create_deck(self, filename: str, content_stream: BinaryIO, narrate_enabled: bool = True) -> DeckRecord:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise DeckValidationError(f"Unsupported file type '{suffix}'. Allowed: {allowed}")

        deck_id = uuid4().hex
        deck_dir = self.storage_dir / deck_id
        deck_dir.mkdir(parents=True, exist_ok=False)

        try:
            source_path = deck_dir / f"source{suffix}"
            with source_path.open("wb") as target:
                shutil.copyfileobj(content_stream, target)

            content_hash = self._compute_content_hash(source_path)

            if suffix == ".pdf":
                pdf_path = deck_dir / "deck.pdf"
                shutil.copy2(source_path, pdf_path)
            else:
                pdf_path = self._convert_powerpoint_to_pdf(source_path, deck_dir)

            slide_text = self._extract_slide_text(pdf_path)
            transcript_cache_key = self._build_transcript_cache_key(slide_text) if narrate_enabled else None
            cached_transcripts = None
            has_cached_transcripts = False
            if narrate_enabled and transcript_cache_key:
                cached_transcripts = self._load_cached_transcripts(
                    transcript_cache_key,
                    expected_slide_count=len(slide_text),
                )
                has_cached_transcripts = cached_transcripts is not None and len(cached_transcripts) == len(slide_text)
            record = DeckRecord(
                deck_id=deck_id,
                filename=filename,
                source_path=source_path,
                pdf_path=pdf_path,
                slide_count=len(slide_text),
                narrate_enabled=narrate_enabled,
                slide_text=slide_text,
                content_hash=content_hash,
                transcript_cache_key=transcript_cache_key,
                transcript_status="disabled" if not narrate_enabled else ("completed" if has_cached_transcripts else "queued"),
                transcripts=cached_transcripts if cached_transcripts is not None else [None] * len(slide_text),
                transcript_slide_errors=[None] * len(slide_text),
            )

            with self._lock:
                self._decks[deck_id] = record

            return record
        except DeckValidationError:
            shutil.rmtree(deck_dir, ignore_errors=True)
            raise
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(deck_dir, ignore_errors=True)
            raise DeckValidationError(f"Failed to process deck: {exc}") from exc

    def get_deck(self, deck_id: str) -> DeckRecord:
        with self._lock:
            deck = self._decks.get(deck_id)

        if deck is None:
            raise DeckNotFoundError(deck_id)

        return deck

    def list_slides(self, deck_id: str) -> list[dict]:
        deck = self.get_deck(deck_id)
        slides = []
        for index, text in enumerate(deck.slide_text):
            preview = " ".join(text.split())[:200]
            if len(preview) == 200:
                preview += "..."
            slides.append({"index": index, "text_preview": preview})
        return slides

    def get_slide_text(self, deck_id: str, slide_index: int) -> str:
        deck = self.get_deck(deck_id)
        if slide_index < 0 or slide_index >= deck.slide_count:
            raise IndexError(f"Slide index out of range: {slide_index}")
        return deck.slide_text[slide_index]

    def get_slide_transcript(self, deck_id: str, slide_index: int) -> str | None:
        deck = self.get_deck(deck_id)
        if slide_index < 0 or slide_index >= deck.slide_count:
            raise IndexError(f"Slide index out of range: {slide_index}")
        with deck.lock:
            return deck.transcripts[slide_index]

    def mark_transcript_generation_started(self, deck_id: str) -> bool:
        deck = self.get_deck(deck_id)
        with deck.lock:
            if not deck.narrate_enabled:
                deck.transcript_status = "disabled"
                deck.transcript_error = None
                deck.transcript_active_slide_index = None
                return False

            if deck.transcript_status == "generating":
                return False

            if deck.slide_count == 0:
                deck.transcript_status = "completed"
                deck.transcript_error = None
                deck.transcript_active_slide_index = None
                return False

            has_complete_transcripts = (
                len(deck.transcripts) == deck.slide_count
                and all(isinstance(transcript, str) and transcript.strip() for transcript in deck.transcripts)
            )
            if has_complete_transcripts:
                deck.transcript_status = "completed"
                deck.transcript_error = None
                deck.transcript_active_slide_index = None
                deck.transcript_slide_errors = [None] * deck.slide_count
                return False

            deck.transcript_status = "generating"
            deck.transcript_error = None
            deck.transcript_active_slide_index = None
            deck.transcripts = [None] * deck.slide_count
            deck.transcript_slide_errors = [None] * deck.slide_count
        return True

    def mark_transcript_slide_started(self, deck_id: str, slide_index: int) -> None:
        deck = self.get_deck(deck_id)
        if slide_index < 0 or slide_index >= deck.slide_count:
            raise IndexError(f"Slide index out of range: {slide_index}")

        with deck.lock:
            deck.transcript_active_slide_index = slide_index
            if deck.transcript_status != "generating":
                deck.transcript_status = "generating"
            deck.transcript_error = None

    def mark_transcript_slide_completed(self, deck_id: str, slide_index: int, transcript: str) -> None:
        deck = self.get_deck(deck_id)
        if slide_index < 0 or slide_index >= deck.slide_count:
            raise IndexError(f"Slide index out of range: {slide_index}")

        with deck.lock:
            deck.transcripts[slide_index] = transcript
            deck.transcript_slide_errors[slide_index] = None
            if deck.transcript_active_slide_index == slide_index:
                deck.transcript_active_slide_index = None

    def mark_transcript_slide_error(self, deck_id: str, slide_index: int, error: str) -> None:
        deck = self.get_deck(deck_id)
        if slide_index < 0 or slide_index >= deck.slide_count:
            raise IndexError(f"Slide index out of range: {slide_index}")

        with deck.lock:
            deck.transcript_slide_errors[slide_index] = error
            if deck.transcript_active_slide_index == slide_index:
                deck.transcript_active_slide_index = None

    def mark_transcript_generation_completed(self, deck_id: str) -> None:
        deck = self.get_deck(deck_id)
        with deck.lock:
            deck.transcript_status = "completed"
            deck.transcript_error = None
            deck.transcript_active_slide_index = None
            cache_key = deck.transcript_cache_key
            transcripts = list(deck.transcripts)

        if cache_key:
            self._persist_cached_transcripts(cache_key, transcripts)

    def mark_transcript_generation_error(self, deck_id: str, error: str) -> None:
        deck = self.get_deck(deck_id)
        with deck.lock:
            deck.transcript_status = "error"
            deck.transcript_error = error
            deck.transcript_active_slide_index = None

    def get_transcript_snapshot(self, deck_id: str) -> dict:
        deck = self.get_deck(deck_id)
        with deck.lock:
            completed_slides = sum(1 for transcript in deck.transcripts if transcript is not None)
            generation_status = deck.transcript_status
            active_slide_index = deck.transcript_active_slide_index
            generation_error = deck.transcript_error
            transcripts = list(deck.transcripts)
            slide_errors = list(deck.transcript_slide_errors)

        slides = []
        for index in range(deck.slide_count):
            transcript = transcripts[index]
            slide_error = slide_errors[index]
            if transcript is not None:
                status = "completed"
            elif slide_error:
                status = "error"
            elif generation_status == "generating" and active_slide_index == index:
                status = "generating"
            else:
                status = "pending"

            slides.append(
                {
                    "index": index,
                    "status": status,
                    "transcript": transcript,
                    "error": slide_error,
                }
            )

        return {
            "deck_id": deck.deck_id,
            "narrate_enabled": deck.narrate_enabled,
            "status": generation_status,
            "total_slides": deck.slide_count,
            "completed_slides": completed_slides,
            "error": generation_error,
            "slides": slides,
        }

    def render_slide_png(self, deck_id: str, slide_index: int, scale: float = 2.0) -> bytes:
        deck = self.get_deck(deck_id)
        if slide_index < 0 or slide_index >= deck.slide_count:
            raise IndexError(f"Slide index out of range: {slide_index}")

        with fitz.open(deck.pdf_path) as doc:
            page = doc[slide_index]
            matrix = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            return pix.tobytes("png")

    def clear_chat(self, deck_id: str) -> None:
        deck = self.get_deck(deck_id)
        with deck.lock:
            deck.conversation_history.clear()
            deck.is_first_message = True
            content_hash = deck.content_hash
        if content_hash:
            self.delete_conversation(content_hash)

    def _compute_content_hash(self, file_path: Path) -> str:
        return hashlib.sha256(file_path.read_bytes()).hexdigest()

    def _conversation_path(self, content_hash: str) -> Path:
        return self.conversations_dir / f"{content_hash}.json"

    def load_conversation(self, content_hash: str) -> dict | None:
        path = self._conversation_path(content_hash)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError):
            return None

        if not isinstance(payload, dict):
            return None
        if not isinstance(payload.get("branches_by_id"), dict):
            return None
        if not isinstance(payload.get("branch_order"), list):
            return None

        return payload

    def save_conversation(self, content_hash: str, data: dict) -> None:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        if "created_at" not in data:
            data["created_at"] = data["updated_at"]

        final_path = self._conversation_path(content_hash)
        temp_path = final_path.with_name(f".{final_path.name}.{uuid4().hex}.tmp")
        try:
            temp_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            temp_path.replace(final_path)
        except OSError:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass

    def delete_conversation(self, content_hash: str) -> None:
        path = self._conversation_path(content_hash)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def delete_deck(self, deck_id: str) -> None:
        with self._lock:
            deck = self._decks.pop(deck_id, None)

        if deck is None:
            raise DeckNotFoundError(deck_id)

        shutil.rmtree(deck.source_path.parent, ignore_errors=True)

    def _extract_slide_text(self, pdf_path: Path) -> list[str]:
        with fitz.open(pdf_path) as doc:
            return [page.get_text() for page in doc]

    def _build_transcript_cache_key(self, slide_text: list[str]) -> str:
        digest = hashlib.sha256()
        digest.update(str(len(slide_text)).encode("utf-8"))
        digest.update(b"\n")
        for index, text in enumerate(slide_text):
            normalized_text = " ".join(str(text or "").split())
            digest.update(str(index).encode("utf-8"))
            digest.update(b"\n")
            digest.update(normalized_text.encode("utf-8"))
            digest.update(b"\n")
        return digest.hexdigest()

    def _transcript_cache_path(self, cache_key: str) -> Path:
        safe_cache_key = cache_key.strip().lower()
        return self.transcript_cache_dir / f"{safe_cache_key}.json"

    def _load_cached_transcripts(self, cache_key: str, expected_slide_count: int) -> list[str] | None:
        path = self._transcript_cache_path(cache_key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError):
            return None

        if not isinstance(payload, dict):
            return None

        slide_count = payload.get("slide_count")
        transcripts = payload.get("transcripts")

        if not isinstance(slide_count, int) or slide_count != expected_slide_count:
            return None
        if not isinstance(transcripts, list) or len(transcripts) != expected_slide_count:
            return None

        normalized_transcripts: list[str] = []
        for entry in transcripts:
            if not isinstance(entry, str):
                return None
            normalized = " ".join(entry.split())
            if not normalized:
                return None
            normalized_transcripts.append(normalized)

        return normalized_transcripts

    def _persist_cached_transcripts(self, cache_key: str, transcripts: list[str | None]) -> None:
        if not cache_key:
            return

        normalized_transcripts: list[str] = []
        for entry in transcripts:
            if not isinstance(entry, str):
                return
            normalized = " ".join(entry.split())
            if not normalized:
                return
            normalized_transcripts.append(normalized)

        payload = {
            "version": 1,
            "slide_count": len(normalized_transcripts),
            "transcripts": normalized_transcripts,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        final_path = self._transcript_cache_path(cache_key)
        temp_path = final_path.with_name(f".{final_path.name}.{uuid4().hex}.tmp")
        try:
            temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temp_path.replace(final_path)
        except OSError:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass

    def _convert_powerpoint_to_pdf(self, source_path: Path, deck_dir: Path) -> Path:
        soffice = self._find_libreoffice()
        if not soffice:
            raise DeckValidationError(
                "LibreOffice is required for .ppt/.pptx uploads. Install LibreOffice and ensure `soffice` is available."
            )

        conversion_dir = Path(tempfile.mkdtemp(prefix="slidelect_web_", dir=deck_dir))
        try:
            subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(conversion_dir),
                    str(source_path),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise DeckValidationError("PowerPoint conversion timed out.") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode(errors="ignore") if exc.stderr else ""
            raise DeckValidationError(f"PowerPoint conversion failed: {stderr.strip()}") from exc

        generated_pdf = conversion_dir / f"{source_path.stem}.pdf"
        if not generated_pdf.exists():
            raise DeckValidationError("PowerPoint conversion failed: output PDF was not created.")

        final_pdf = deck_dir / "deck.pdf"
        shutil.move(str(generated_pdf), final_pdf)
        shutil.rmtree(conversion_dir, ignore_errors=True)
        return final_pdf

    def _find_libreoffice(self) -> str | None:
        candidates = [
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            "/usr/bin/soffice",
            "/usr/bin/libreoffice",
            "soffice",
            "libreoffice",
        ]

        for candidate in candidates:
            if shutil.which(candidate):
                return candidate
            if Path(candidate).exists():
                return candidate

        return None
