"""ElevenLabs text-to-speech integration for slide transcripts."""

from __future__ import annotations

import hashlib
import http.client
import json
import threading
from dataclasses import dataclass
from urllib import error, parse, request


class TTSConfigurationError(RuntimeError):
    """Raised when text-to-speech runtime configuration is invalid."""


class TTSProviderError(RuntimeError):
    """Raised when the upstream text-to-speech provider fails."""


@dataclass(frozen=True)
class SpeechSynthesisResult:
    """Speech bytes and metadata returned by the provider."""

    audio_bytes: bytes
    media_type: str
    voice_id: str


@dataclass(frozen=True)
class SpeechCacheIdentity:
    """Cache identity describing how a transcript audio file is keyed."""

    cache_key: str
    voice_id: str
    extension: str
    media_type: str


@dataclass(frozen=True)
class SpeechStreamResult:
    """Open upstream audio stream from ElevenLabs."""

    response: http.client.HTTPResponse
    media_type: str
    voice_id: str
    normalized_text: str


class ElevenLabsTTSService:
    """Synthesize transcript speech through ElevenLabs."""

    def __init__(
        self,
        *,
        api_key: str | None,
        voice_id: str | None,
        voice_name: str,
        model_id: str,
        output_format: str,
        base_url: str,
        timeout_seconds: int,
    ) -> None:
        self.api_key = str(api_key or "").strip() or None
        self.voice_id = str(voice_id or "").strip() or None
        self.voice_name = str(voice_name or "Rachel").strip() or "Rachel"
        self.model_id = str(model_id or "eleven_multilingual_v2").strip() or "eleven_multilingual_v2"
        self.output_format = str(output_format or "mp3_44100_128").strip() or "mp3_44100_128"
        self.base_url = str(base_url or "https://api.elevenlabs.io").rstrip("/")
        self.timeout_seconds = max(5, int(timeout_seconds or 45))
        self._resolved_voice_id: str | None = self.voice_id
        self._voice_lock = threading.RLock()

    @property
    def is_available(self) -> bool:
        return self.api_key is not None

    def synthesize(self, text: str) -> SpeechSynthesisResult:
        normalized_text = self._normalize_text(text)
        if not self.api_key:
            raise TTSConfigurationError("Text-to-speech is unavailable. Set ELEVENLABS_API_KEY.")

        voice_id = self._resolve_voice_id()
        endpoint = self._text_to_speech_endpoint(voice_id)
        payload = {
            "text": normalized_text,
            "model_id": self.model_id,
        }
        request_bytes = json.dumps(payload).encode("utf-8")
        req = request.Request(
            endpoint,
            method="POST",
            data=request_bytes,
            headers={
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "*/*",
            },
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                audio_bytes = response.read()
                media_type = response.headers.get_content_type() or "audio/mpeg"
        except error.HTTPError as exc:
            raise TTSProviderError(
                f"ElevenLabs request failed ({exc.code}): {self._read_http_error_detail(exc)}"
            ) from exc
        except error.URLError as exc:
            raise TTSProviderError(f"Unable to reach ElevenLabs: {exc.reason}") from exc

        if not audio_bytes:
            raise TTSProviderError("ElevenLabs returned an empty audio response.")

        return SpeechSynthesisResult(
            audio_bytes=audio_bytes,
            media_type=media_type,
            voice_id=voice_id,
        )

    def stream_synthesize(self, text: str) -> SpeechStreamResult:
        normalized_text = self._normalize_text(text)
        if not self.api_key:
            raise TTSConfigurationError("Text-to-speech is unavailable. Set ELEVENLABS_API_KEY.")

        voice_id = self._resolve_voice_id()
        endpoint = self._text_to_speech_stream_endpoint(voice_id)
        payload = {
            "text": normalized_text,
            "model_id": self.model_id,
        }
        request_bytes = json.dumps(payload).encode("utf-8")
        req = request.Request(
            endpoint,
            method="POST",
            data=request_bytes,
            headers={
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "*/*",
            },
        )

        try:
            response = request.urlopen(req, timeout=self.timeout_seconds)
        except error.HTTPError as exc:
            raise TTSProviderError(
                f"ElevenLabs stream request failed ({exc.code}): {self._read_http_error_detail(exc)}"
            ) from exc
        except error.URLError as exc:
            raise TTSProviderError(f"Unable to reach ElevenLabs: {exc.reason}") from exc

        media_type = response.headers.get_content_type() or self._media_type_from_output_format()
        return SpeechStreamResult(
            response=response,
            media_type=media_type,
            voice_id=voice_id,
            normalized_text=normalized_text,
        )

    def build_cache_identity(self, text: str) -> SpeechCacheIdentity:
        normalized_text = self._normalize_text(text)
        if not self.api_key:
            raise TTSConfigurationError("Text-to-speech is unavailable. Set ELEVENLABS_API_KEY.")

        voice_id = self._resolve_voice_id()
        digest = hashlib.sha256()
        digest.update(normalized_text.encode("utf-8"))
        digest.update(b"\n")
        digest.update(voice_id.encode("utf-8"))
        digest.update(b"\n")
        digest.update(self.model_id.encode("utf-8"))
        digest.update(b"\n")
        digest.update(self.output_format.encode("utf-8"))

        return SpeechCacheIdentity(
            cache_key=digest.hexdigest(),
            voice_id=voice_id,
            extension=self._file_extension_from_output_format(),
            media_type=self._media_type_from_output_format(),
        )

    def _resolve_voice_id(self) -> str:
        if self.voice_id:
            return self.voice_id

        with self._voice_lock:
            if self._resolved_voice_id:
                return self._resolved_voice_id

            resolved = self._search_default_voice_id(self.voice_name)
            self._resolved_voice_id = resolved
            return resolved

    def _search_default_voice_id(self, voice_name: str) -> str:
        if not self.api_key:
            raise TTSConfigurationError("Text-to-speech is unavailable. Set ELEVENLABS_API_KEY.")

        voices = self._fetch_voices(search=voice_name)
        if not voices:
            voices = self._fetch_voices(search=None)
        if not voices:
            raise TTSProviderError("No ElevenLabs voices were found for this API key.")

        normalized_name = voice_name.strip().lower()
        exact_match = next(
            (
                item
                for item in voices
                if isinstance(item, dict)
                and str(item.get("name") or "").strip().lower() == normalized_name
            ),
            None,
        )
        selected = exact_match or voices[0]
        if not isinstance(selected, dict):
            raise TTSProviderError("Unable to resolve a valid ElevenLabs voice.")

        voice_id = str(selected.get("voice_id") or "").strip()
        if not voice_id:
            raise TTSProviderError("Resolved ElevenLabs voice is missing a voice_id.")

        return voice_id

    def _fetch_voices(self, search: str | None) -> list[dict]:
        if not self.api_key:
            raise TTSConfigurationError("Text-to-speech is unavailable. Set ELEVENLABS_API_KEY.")

        query_params: dict[str, str | int] = {
            "voice_type": "default",
            "page_size": 50,
        }
        if search:
            query_params["search"] = search

        query = parse.urlencode(query_params)
        endpoint = f"{self.base_url}/v2/voices?{query}"
        req = request.Request(
            endpoint,
            method="GET",
            headers={
                "xi-api-key": self.api_key,
                "Accept": "application/json",
            },
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise TTSProviderError(
                f"Unable to resolve ElevenLabs voice ({exc.code}): {self._read_http_error_detail(exc)}"
            ) from exc
        except error.URLError as exc:
            raise TTSProviderError(f"Unable to resolve ElevenLabs voice: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise TTSProviderError("ElevenLabs voice lookup returned invalid JSON.") from exc

        voices = payload.get("voices")
        if not isinstance(voices, list):
            return []

        return [voice for voice in voices if isinstance(voice, dict)]

    def _text_to_speech_endpoint(self, voice_id: str) -> str:
        encoded_voice_id = parse.quote(voice_id, safe="")
        query = parse.urlencode({"output_format": self.output_format})
        return f"{self.base_url}/v1/text-to-speech/{encoded_voice_id}?{query}"

    def _text_to_speech_stream_endpoint(self, voice_id: str) -> str:
        encoded_voice_id = parse.quote(voice_id, safe="")
        query = parse.urlencode({"output_format": self.output_format})
        return f"{self.base_url}/v1/text-to-speech/{encoded_voice_id}/stream?{query}"

    def _file_extension_from_output_format(self) -> str:
        codec = self.output_format.split("_", 1)[0].strip().lower() or "mp3"
        if codec in {"mp3", "wav", "pcm", "ulaw", "alaw"}:
            return codec
        return "bin"

    def _media_type_from_output_format(self) -> str:
        codec = self.output_format.split("_", 1)[0].strip().lower() or "mp3"
        if codec == "mp3":
            return "audio/mpeg"
        if codec == "wav":
            return "audio/wav"
        if codec == "pcm":
            return "audio/pcm"
        if codec in {"ulaw", "alaw"}:
            return "audio/basic"
        return "application/octet-stream"

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized_text = " ".join(str(text or "").split())
        if not normalized_text:
            raise ValueError("Transcript is empty and cannot be converted to speech.")
        return normalized_text

    @staticmethod
    def _read_http_error_detail(exc: error.HTTPError) -> str:
        try:
            raw = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001
            return "Unknown ElevenLabs error."

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip() or "Unknown ElevenLabs error."

        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, dict):
                status = str(detail.get("status") or "").strip()
                message = str(detail.get("message") or "").strip()
                if status and message:
                    return f"{status}: {message}"
                if message:
                    return message
            if isinstance(detail, str) and detail.strip():
                return detail.strip()

            for key in ("message", "error"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        return raw.strip() or "Unknown ElevenLabs error."
