"""Chat sidebar for AI interaction."""

import base64
from typing import List, Optional
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QLineEdit, QPushButton, QScrollArea,
    QFrame, QSizePolicy, QTextBrowser
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, pyqtSlot, QBuffer, QIODevice, QTimer
from PyQt5.QtGui import QFont, QPixmap

from ..models.message import ChatMessage, MessageRole
from ..models.slide import Slide
from ..services.ai_service import AIService
from ..utils.theme import Theme
from ..utils.markdown_renderer import render_markdown, render_markdown_streaming


class TypingIndicator(QFrame):
    """Animated typing indicator showing '...' animation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dot_count = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._setup_ui()

    def _setup_ui(self):
        """Set up the typing indicator UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        # Role label
        role_label = QLabel("AI")
        role_label.setStyleSheet(f"""
            QLabel {{
                font-weight: bold;
                font-size: 13px;
                color: {Theme.TEXT_SECONDARY};
                background-color: transparent;
                padding: 0;
                margin: 0;
            }}
        """)
        layout.addWidget(role_label)

        # Dots label
        self._dots_label = QLabel(".")
        self._dots_label.setStyleSheet(f"""
            QLabel {{
                font-size: 24px;
                color: {Theme.TEXT_SECONDARY};
                background-color: transparent;
                padding: 0;
                margin: 0;
                letter-spacing: 4px;
            }}
        """)
        layout.addWidget(self._dots_label)

        # Style the frame
        self.setStyleSheet(f"""
            TypingIndicator {{
                background-color: {Theme.AI_BG};
                border-radius: {Theme.RADIUS_LG};
                margin-right: 30px;
            }}
        """)

    def _animate(self):
        """Animate the dots."""
        self._dot_count = (self._dot_count % 3) + 1
        self._dots_label.setText("." * self._dot_count)

    def start(self):
        """Start the animation."""
        self._dot_count = 0
        self._dots_label.setText(".")
        self._timer.start(400)  # 400ms interval

    def stop(self):
        """Stop the animation."""
        self._timer.stop()


class StreamWorker(QThread):
    """Worker thread for streaming AI responses."""

    chunk_received = pyqtSignal(str)
    finished_streaming = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        ai_service: AIService,
        question: str,
        current_slide: Optional[Slide],
        focused_image_base64: Optional[str] = None
    ):
        super().__init__()
        self.ai_service = ai_service
        self.question = question
        self.current_slide = current_slide
        self.focused_image_base64 = focused_image_base64

    def run(self):
        try:
            for chunk in self.ai_service.ask_streaming(
                self.question,
                self.current_slide,
                self.focused_image_base64
            ):
                self.chunk_received.emit(chunk)
            self.finished_streaming.emit()
        except Exception as e:
            self.error_occurred.emit(str(e))


class MessageBubble(QFrame):
    """A single message bubble in the chat."""

    def __init__(self, message: ChatMessage, parent=None):
        super().__init__(parent)
        self.message = message
        self._content_widget = None
        self._setup_ui()

    def _setup_ui(self):
        """Set up the message bubble UI."""
        is_user = self.message.is_user
        bg_color = Theme.USER_BG if is_user else Theme.AI_BG
        text_color = Theme.USER_TEXT if is_user else Theme.AI_TEXT

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        # Role label - styled to match bubble background
        role_label = QLabel("You" if is_user else "AI")
        role_label.setStyleSheet(f"""
            QLabel {{
                font-weight: bold;
                font-size: 13px;
                color: {Theme.TEXT_SECONDARY};
                background-color: transparent;
                padding: 0;
                margin: 0;
            }}
        """)
        layout.addWidget(role_label)

        # Message content - QLabel for both (simpler, cleaner)
        content_label = QLabel(self.message.content if is_user else "")
        content_label.setWordWrap(True)
        content_label.setTextFormat(Qt.RichText if not is_user else Qt.PlainText)
        content_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        content_label.setOpenExternalLinks(True)
        content_label.setStyleSheet(f"""
            QLabel {{
                font-size: 16px;
                color: {text_color};
                background-color: transparent;
                padding: 0;
                margin: 0;
            }}
        """)

        # Set content for AI messages with markdown
        if not is_user and self.message.content:
            html = render_markdown(self.message.content)
            content_label.setText(html)

        self._content_widget = content_label
        layout.addWidget(content_label)

        # Style the bubble frame
        margin = "margin-left: 30px;" if is_user else "margin-right: 30px;"
        self.setStyleSheet(f"""
            MessageBubble {{
                background-color: {bg_color};
                border-radius: {Theme.RADIUS_LG};
                {margin}
            }}
        """)

    def update_content(self, content: str, streaming: bool = True):
        """Update the message content (for streaming).
        
        Args:
            content: The message content
            streaming: If True, uses streaming-safe markdown rendering
                      that handles incomplete syntax gracefully
        """
        self.message.content = content

        if self.message.is_user:
            self._content_widget.setText(content)
        else:
            # Use streaming-aware renderer during streaming to handle
            # incomplete markdown syntax without producing broken HTML
            if streaming:
                html = render_markdown_streaming(content)
            else:
                html = render_markdown(content)
            self._content_widget.setText(html)

    def finalize_content(self):
        """Finalize the message content after streaming is complete.
        
        Re-renders the content with the full markdown renderer for
        proper formatting now that all content is received.
        """
        if not self.message.is_user and self.message.content:
            html = render_markdown(self.message.content)
            self._content_widget.setText(html)


class ChatSidebar(QWidget):
    """Sidebar widget for AI chat."""

    message_sent = pyqtSignal(str)  # Emitted when user sends a message

    def __init__(self, ai_service: Optional[AIService] = None, parent=None):
        super().__init__(parent)
        self.ai_service = ai_service
        self._messages: List[ChatMessage] = []
        self._current_slide: Optional[Slide] = None
        self._streaming_bubble: Optional[MessageBubble] = None
        self._worker: Optional[StreamWorker] = None
        self._typing_indicator: Optional[TypingIndicator] = None
        # Focused slide state
        self._focused_slide_index: Optional[int] = None
        self._focused_slide_pixmap: Optional[QPixmap] = None
        self._focused_slide: Optional[Slide] = None
        self._setup_ui()

    def _setup_ui(self):
        """Set up the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet(Theme.get_chat_header_style())
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 12, 15, 12)

        title = QLabel("Ask AI")
        title.setFont(QFont("", 14, QFont.Bold))
        title.setStyleSheet(f"color: {Theme.TEXT_PRIMARY};")
        header_layout.addWidget(title)
        header_layout.addStretch()

        layout.addWidget(header)

        # Messages area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(Theme.get_messages_area_style())

        self.messages_container = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(10, 10, 10, 10)
        self.messages_layout.setSpacing(10)
        self.messages_layout.addStretch()

        scroll_area.setWidget(self.messages_container)
        self.scroll_area = scroll_area
        layout.addWidget(scroll_area, stretch=1)

        # Welcome message
        self._add_welcome_message()

        # Input area
        input_frame = QFrame()
        input_frame.setStyleSheet(Theme.get_chat_input_frame_style())
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(12, 12, 12, 12)
        input_layout.setSpacing(10)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask a question about the slides...")
        self.input_field.setStyleSheet(f"""
            QLineEdit {{
                padding: 12px;
                border: 2px solid {Theme.BORDER};
                border-radius: {Theme.RADIUS_MD};
                font-size: 14px;
                background-color: {Theme.SURFACE_ELEVATED};
                color: {Theme.TEXT_PRIMARY};
            }}
            QLineEdit:focus {{
                border-color: {Theme.PRIMARY};
            }}
        """)
        self.input_field.returnPressed.connect(self._on_send)
        input_layout.addWidget(self.input_field)

        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.PRIMARY};
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: {Theme.RADIUS_MD};
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {Theme.PRIMARY_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {Theme.PRIMARY_PRESSED};
            }}
            QPushButton:disabled {{
                background-color: {Theme.BORDER};
                color: {Theme.TEXT_MUTED};
            }}
        """)
        self.send_btn.clicked.connect(self._on_send)
        input_layout.addWidget(self.send_btn)

        layout.addWidget(input_frame)

    def _add_welcome_message(self):
        """Add a welcome message to the chat."""
        welcome = ChatMessage(
            role=MessageRole.ASSISTANT,
            content="Hello! I'm here to help you understand these lecture slides. Ask me anything about the content, and I'll do my best to explain it clearly."
        )
        self._add_message_bubble(welcome)

    def _add_message_bubble(self, message: ChatMessage) -> MessageBubble:
        """Add a message bubble to the chat."""
        bubble = MessageBubble(message)

        # Insert before the stretch
        self.messages_layout.insertWidget(
            self.messages_layout.count() - 1,
            bubble
        )

        # Scroll to bottom
        self._scroll_to_bottom()

        return bubble

    def _scroll_to_bottom(self):
        """Scroll the messages area to the bottom."""
        # Use a timer to ensure layout is updated first
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(50, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))

    def set_context(self, current_slide: Slide):
        """Set the current slide context.

        Args:
            current_slide: The currently viewed slide
        """
        self._current_slide = current_slide

    def set_ai_service(self, ai_service: AIService):
        """Set the AI service."""
        self.ai_service = ai_service

    def set_pdf(self, pdf_path: str) -> bool:
        """Set the PDF for AI context.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            True if PDF was loaded successfully
        """
        if self.ai_service:
            return self.ai_service.set_pdf(pdf_path)
        return False

    def set_focused_slide(self, index: int, pixmap: QPixmap, slide: Slide):
        """Set the focused slide for AI context.

        Args:
            index: The slide index
            pixmap: The slide image
            slide: The slide object
        """
        self._focused_slide_index = index
        self._focused_slide_pixmap = pixmap
        self._focused_slide = slide
        # Update placeholder to indicate focus mode
        self.input_field.setPlaceholderText(
            f"Ask about Slide {index + 1} (image included)..."
        )

    def clear_focused_slide(self):
        """Clear the focused slide state."""
        self._focused_slide_index = None
        self._focused_slide_pixmap = None
        self._focused_slide = None
        # Update placeholder to indicate general mode
        self.input_field.setPlaceholderText(
            "Ask a question about the slides..."
        )

    def has_focused_slide(self) -> bool:
        """Check if there's a focused slide."""
        return self._focused_slide_index is not None

    @staticmethod
    def _pixmap_to_base64(pixmap: QPixmap) -> str:
        """Convert a QPixmap to base64-encoded PNG string."""
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        pixmap.save(buffer, "PNG")
        image_bytes = buffer.data().data()
        return base64.b64encode(image_bytes).decode('utf-8')

    def _on_send(self):
        """Handle send button click."""
        question = self.input_field.text().strip()
        if not question:
            return

        if not self.ai_service or not self.ai_service.is_available:
            self._show_error("AI service not available. Please set your ANTHROPIC_API_KEY.")
            return

        # Clear input
        self.input_field.clear()

        # Determine slide context based on focus state
        if self.has_focused_slide():
            context_slide = self._focused_slide
            image_base64 = self._pixmap_to_base64(self._focused_slide_pixmap)
        else:
            context_slide = self._current_slide
            image_base64 = None

        # Add user message
        user_message = ChatMessage(
            role=MessageRole.USER,
            content=question,
            slide_index=context_slide.index if context_slide else None
        )
        self._messages.append(user_message)
        self._add_message_bubble(user_message)

        # Disable input while processing
        self._set_input_enabled(False)

        # Show typing indicator
        self._show_typing_indicator()

        # Streaming bubble will be created when first chunk arrives
        self._streaming_bubble = None
        self._pending_ai_message_context = context_slide

        # Start streaming worker
        self._worker = StreamWorker(
            self.ai_service,
            question,
            context_slide,
            image_base64
        )
        self._worker.chunk_received.connect(self._on_chunk_received)
        self._worker.finished_streaming.connect(self._on_streaming_finished)
        self._worker.error_occurred.connect(self._on_streaming_error)
        self._worker.start()

        self.message_sent.emit(question)

    def _show_typing_indicator(self):
        """Show the typing indicator."""
        self._typing_indicator = TypingIndicator()
        # Insert before the stretch
        self.messages_layout.insertWidget(
            self.messages_layout.count() - 1,
            self._typing_indicator
        )
        self._typing_indicator.start()
        self._scroll_to_bottom()

    def _hide_typing_indicator(self):
        """Hide and remove the typing indicator."""
        if self._typing_indicator:
            self._typing_indicator.stop()
            self._typing_indicator.deleteLater()
            self._typing_indicator = None

    @pyqtSlot(str)
    def _on_chunk_received(self, chunk: str):
        """Handle receiving a chunk of the streamed response."""
        # On first chunk, hide typing indicator and create streaming bubble
        if self._streaming_bubble is None:
            self._hide_typing_indicator()
            context_slide = self._pending_ai_message_context
            ai_message = ChatMessage(
                role=MessageRole.ASSISTANT,
                content="",
                slide_index=context_slide.index if context_slide else None
            )
            self._streaming_bubble = self._add_message_bubble(ai_message)

        current_content = self._streaming_bubble.message.content
        self._streaming_bubble.update_content(current_content + chunk)
        self._scroll_to_bottom()

    @pyqtSlot()
    def _on_streaming_finished(self):
        """Handle streaming completion."""
        if self._streaming_bubble:
            # Re-render with full markdown now that streaming is complete
            self._streaming_bubble.finalize_content()
            self._messages.append(self._streaming_bubble.message)
        self._streaming_bubble = None
        self._worker = None
        self._set_input_enabled(True)
        self.input_field.setFocus()

    @pyqtSlot(str)
    def _on_streaming_error(self, error: str):
        """Handle streaming error."""
        if self._streaming_bubble:
            self._streaming_bubble.update_content(f"Error: {error}")
        self._streaming_bubble = None
        self._worker = None
        self._set_input_enabled(True)

    def _set_input_enabled(self, enabled: bool):
        """Enable or disable the input area."""
        self.input_field.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        if enabled:
            self.send_btn.setText("Send")
        else:
            self.send_btn.setText("...")

    def _show_error(self, message: str):
        """Show an error message in the chat."""
        error_message = ChatMessage(
            role=MessageRole.ASSISTANT,
            content=f"Error: {message}"
        )
        self._add_message_bubble(error_message)

    def clear_chat(self):
        """Clear all messages from the chat."""
        # Remove all message bubbles
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._messages.clear()
        self._add_welcome_message()

        # Clear AI service history too
        if self.ai_service:
            self.ai_service.clear_history()
