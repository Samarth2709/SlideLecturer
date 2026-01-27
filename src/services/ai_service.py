"""AI service for Claude integration with PDF support and prompt caching."""

import base64
from typing import List, Optional, Generator
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from anthropic import Anthropic

# Anthropic API limit for PDF pages
MAX_PDF_PAGES = 100

from ..models.slide import Slide
from ..models.message import ChatMessage, MessageRole
from ..utils.config import get_api_key
from ..prompts import SYSTEM_PROMPT, build_user_prompt, build_focus_prompt


@dataclass
class AIResponse:
    """Response from AI service."""
    content: str
    success: bool
    error: Optional[str] = None


class AIService:
    """Service for AI-powered slide explanations using Claude.

    Uses PDF document attachment with prompt caching for efficient
    multi-turn conversations about lecture slides.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or get_api_key()
        self.client: Optional[Anthropic] = None
        self._conversation_history: List[dict] = []  # Store API-format messages
        self._pdf_base64: Optional[str] = None
        self._pdf_page_count: int = 0
        self._is_first_message: bool = True

        if self.api_key:
            self.client = Anthropic(api_key=self.api_key)

    @property
    def is_available(self) -> bool:
        """Check if AI service is available."""
        return self.client is not None

    def set_pdf(self, pdf_path: str) -> bool:
        """Load and store PDF data for AI context.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            True if PDF was loaded successfully
        """
        try:
            pdf_file = Path(pdf_path)
            if not pdf_file.exists():
                return False

            # Check page count using PyMuPDF
            doc = fitz.open(pdf_path)
            self._pdf_page_count = len(doc)
            doc.close()

            with open(pdf_file, "rb") as f:
                self._pdf_base64 = base64.standard_b64encode(f.read()).decode("utf-8")

            # Reset conversation state when PDF changes
            self.clear_history()
            return True
        except Exception:
            return False

    def clear_history(self):
        """Clear conversation history."""
        self._conversation_history = []
        self._is_first_message = True

    def _build_pdf_document_block(self, with_cache: bool = False) -> dict:
        """Build the PDF document content block.

        Args:
            with_cache: Whether to include cache_control

        Returns:
            Document content block dict
        """
        block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": self._pdf_base64,
            },
        }

        if with_cache:
            block["cache_control"] = {"type": "ephemeral"}

        return block

    def _build_image_block(self, image_base64: str) -> dict:
        """Build an image content block.

        Args:
            image_base64: Base64-encoded PNG image

        Returns:
            Image content block dict
        """
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": image_base64,
            },
        }

    def _build_text_block(self, text: str) -> dict:
        """Build a text content block.

        Args:
            text: The text content

        Returns:
            Text content block dict
        """
        return {
            "type": "text",
            "text": text,
        }

    def ask_streaming(
        self,
        question: str,
        current_slide: Optional[Slide],
        focused_image_base64: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """Ask a question and stream the response.

        Args:
            question: The user's question
            current_slide: The slide currently being viewed (may be None)
            focused_image_base64: Base64-encoded PNG image of focused slide (optional)

        Yields:
            Chunks of the response text
        """
        if not self.is_available:
            yield "[Error: AI service not available. Please set your ANTHROPIC_API_KEY.]"
            return

        if not self._pdf_base64:
            yield "[Error: No PDF loaded. Please load a slide deck first.]"
            return

        if self._pdf_page_count > MAX_PDF_PAGES:
            yield (
                f"[Error: PDF has {self._pdf_page_count} pages, which exceeds the "
                f"maximum of {MAX_PDF_PAGES} pages supported by the AI service. "
                "Please use a shorter slide deck.]"
            )
            return

        try:
            # Build the user message content
            user_content = []

            # Always include PDF document first (with cache on first message)
            user_content.append(
                self._build_pdf_document_block(with_cache=self._is_first_message)
            )

            # Add focused slide image if in focus mode
            if focused_image_base64:
                user_content.append(self._build_image_block(focused_image_base64))
                # Build focus mode prompt
                slide_num = current_slide.index + 1 if current_slide else 1
                prompt_text = build_focus_prompt(question, slide_num)
            else:
                # Build non-focus mode prompt
                prompt_text = build_user_prompt(question)

            # Add the text prompt
            user_content.append(self._build_text_block(prompt_text))

            # Build the messages list
            # Include conversation history (assistant responses only, since user context changes)
            messages = []

            # For subsequent messages, we need to include the conversation flow
            if not self._is_first_message and self._conversation_history:
                # Replay the conversation with the same PDF prefix
                for msg in self._conversation_history[-10:]:  # Keep last 10 exchanges
                    messages.append(msg)

            # Add current user message
            messages.append({
                "role": "user",
                "content": user_content,
            })

            # Stream response
            full_response = ""
            with self.client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=messages
            ) as stream:
                for text in stream.text_stream:
                    full_response += text
                    yield text

            # Store the exchange in conversation history
            # Only store the text prompt, NOT the PDF or images (to avoid re-sending them)
            self._conversation_history.append({
                "role": "user",
                "content": prompt_text,  # Text only - PDF is sent fresh each time
            })
            self._conversation_history.append({
                "role": "assistant",
                "content": full_response,
            })

            # Mark that first message has been sent
            self._is_first_message = False

        except Exception as e:
            yield f"[Error: {str(e)}]"

    def ask(
        self,
        question: str,
        current_slide: Optional[Slide],
        focused_image_base64: Optional[str] = None,
    ) -> AIResponse:
        """Ask a question about the slides (non-streaming).

        Args:
            question: The user's question
            current_slide: The slide currently being viewed
            focused_image_base64: Base64-encoded PNG image of focused slide (optional)

        Returns:
            AIResponse with the answer or error
        """
        if not self.is_available:
            return AIResponse(
                content="",
                success=False,
                error="AI service not available. Please set your ANTHROPIC_API_KEY."
            )

        if not self._pdf_base64:
            return AIResponse(
                content="",
                success=False,
                error="No PDF loaded. Please load a slide deck first."
            )

        try:
            # Collect streaming response
            response_parts = []
            for chunk in self.ask_streaming(question, current_slide, focused_image_base64):
                response_parts.append(chunk)

            full_response = "".join(response_parts)

            if full_response.startswith("[Error:"):
                return AIResponse(
                    content="",
                    success=False,
                    error=full_response
                )

            return AIResponse(content=full_response, success=True)

        except Exception as e:
            return AIResponse(
                content="",
                success=False,
                error=f"Error communicating with AI: {str(e)}"
            )
