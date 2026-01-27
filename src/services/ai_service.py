"""AI service for Claude integration."""

from typing import List, Optional, Generator
from dataclasses import dataclass

from anthropic import Anthropic

from ..models.slide import Slide
from ..models.message import ChatMessage, MessageRole
from ..utils.config import get_api_key


SYSTEM_PROMPT = """You are a helpful teaching assistant helping a student understand lecture slides.

Your role is to:
- Explain concepts from the slides clearly and thoroughly
- Answer questions about the material
- Help the student understand difficult topics
- Provide examples and analogies when helpful
- Connect ideas across different slides when relevant

You have access to:
1. An overview of all slides in the deck
2. The full content of the slide the student is currently viewing

Be encouraging, patient, and focused on helping the student learn. If asked about something not in the slides, you can provide general knowledge but note when information comes from outside the lecture material."""


@dataclass
class AIResponse:
    """Response from AI service."""
    content: str
    success: bool
    error: Optional[str] = None


class AIService:
    """Service for AI-powered slide explanations using Claude."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or get_api_key()
        self.client: Optional[Anthropic] = None
        self._conversation_history: List[ChatMessage] = []

        if self.api_key:
            self.client = Anthropic(api_key=self.api_key)

    @property
    def is_available(self) -> bool:
        """Check if AI service is available."""
        return self.client is not None

    def clear_history(self):
        """Clear conversation history."""
        self._conversation_history = []

    def _build_deck_overview(self, slides: List[Slide]) -> str:
        """Build a condensed overview of all slides."""
        overview_parts = []
        for slide in slides:
            if slide.text.strip():
                # First 150 chars of each slide
                preview = slide.text[:150].replace("\n", " ").strip()
                if len(slide.text) > 150:
                    preview += "..."
                overview_parts.append(f"Slide {slide.index + 1}: {preview}")
            else:
                overview_parts.append(f"Slide {slide.index + 1}: [No text content]")

        return "\n".join(overview_parts)

    def _build_context(
        self,
        question: str,
        current_slide: Slide,
        all_slides: List[Slide],
    ) -> str:
        """Build the context message for the AI."""
        deck_overview = self._build_deck_overview(all_slides)

        context = f"""## Slide Deck Overview
{deck_overview}

## Current Slide (Slide {current_slide.index + 1} of {len(all_slides)})
{current_slide.text if current_slide.text.strip() else "[This slide contains only images/diagrams, no text]"}

## Student's Question
{question}"""

        return context

    def _get_conversation_messages(self) -> List[dict]:
        """Convert conversation history to API format."""
        messages = []
        for msg in self._conversation_history[-10:]:  # Keep last 10 messages for context
            if msg.role in (MessageRole.USER, MessageRole.ASSISTANT):
                messages.append({
                    "role": msg.role.value,
                    "content": msg.content
                })
        return messages

    def ask(
        self,
        question: str,
        current_slide: Slide,
        all_slides: List[Slide],
    ) -> AIResponse:
        """Ask a question about the slides.

        Args:
            question: The user's question
            current_slide: The slide currently being viewed
            all_slides: All slides in the deck

        Returns:
            AIResponse with the answer or error
        """
        if not self.is_available:
            return AIResponse(
                content="",
                success=False,
                error="AI service not available. Please set your ANTHROPIC_API_KEY."
            )

        try:
            # Build context with slide information
            context = self._build_context(question, current_slide, all_slides)

            # Add user message to history
            user_message = ChatMessage(
                role=MessageRole.USER,
                content=question,
                slide_index=current_slide.index
            )
            self._conversation_history.append(user_message)

            # Build messages for API
            messages = self._get_conversation_messages()

            # Replace last user message content with full context
            if messages:
                messages[-1]["content"] = context

            # Call Claude API
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=messages
            )

            # Extract response text
            assistant_content = response.content[0].text

            # Add assistant message to history
            assistant_message = ChatMessage(
                role=MessageRole.ASSISTANT,
                content=assistant_content,
                slide_index=current_slide.index
            )
            self._conversation_history.append(assistant_message)

            return AIResponse(content=assistant_content, success=True)

        except Exception as e:
            return AIResponse(
                content="",
                success=False,
                error=f"Error communicating with AI: {str(e)}"
            )

    def ask_streaming(
        self,
        question: str,
        current_slide: Slide,
        all_slides: List[Slide],
    ) -> Generator[str, None, None]:
        """Ask a question and stream the response.

        Args:
            question: The user's question
            current_slide: The slide currently being viewed
            all_slides: All slides in the deck

        Yields:
            Chunks of the response text
        """
        if not self.is_available:
            yield "[Error: AI service not available. Please set your ANTHROPIC_API_KEY.]"
            return

        try:
            # Build context
            context = self._build_context(question, current_slide, all_slides)

            # Add user message to history
            user_message = ChatMessage(
                role=MessageRole.USER,
                content=question,
                slide_index=current_slide.index
            )
            self._conversation_history.append(user_message)

            # Build messages for API
            messages = self._get_conversation_messages()
            if messages:
                messages[-1]["content"] = context

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

            # Add complete response to history
            assistant_message = ChatMessage(
                role=MessageRole.ASSISTANT,
                content=full_response,
                slide_index=current_slide.index
            )
            self._conversation_history.append(assistant_message)

        except Exception as e:
            yield f"[Error: {str(e)}]"
