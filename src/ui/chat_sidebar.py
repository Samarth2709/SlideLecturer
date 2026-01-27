"""Chat sidebar for AI interaction."""

from typing import List, Optional
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QLineEdit, QPushButton, QScrollArea,
    QFrame, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, pyqtSlot
from PyQt5.QtGui import QFont

from ..models.message import ChatMessage, MessageRole
from ..models.slide import Slide
from ..services.ai_service import AIService


class StreamWorker(QThread):
    """Worker thread for streaming AI responses."""

    chunk_received = pyqtSignal(str)
    finished_streaming = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, ai_service: AIService, question: str, current_slide: Slide, all_slides: List[Slide]):
        super().__init__()
        self.ai_service = ai_service
        self.question = question
        self.current_slide = current_slide
        self.all_slides = all_slides

    def run(self):
        try:
            for chunk in self.ai_service.ask_streaming(
                self.question,
                self.current_slide,
                self.all_slides
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
        self._setup_ui()

    def _setup_ui(self):
        """Set up the message bubble UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Role label
        role_label = QLabel("You" if self.message.is_user else "AI")
        role_label.setStyleSheet(
            "font-weight: bold; font-size: 12px; color: #666;"
        )
        layout.addWidget(role_label)

        # Message content
        content_label = QLabel(self.message.content)
        content_label.setWordWrap(True)
        content_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(content_label)

        # Style based on role
        if self.message.is_user:
            self.setStyleSheet("""
                MessageBubble {
                    background-color: #e3f2fd;
                    border-radius: 8px;
                    margin-left: 20px;
                }
            """)
        else:
            self.setStyleSheet("""
                MessageBubble {
                    background-color: #f5f5f5;
                    border-radius: 8px;
                    margin-right: 20px;
                }
            """)

    def update_content(self, content: str):
        """Update the message content (for streaming)."""
        self.message.content = content
        # Find and update the content label
        for i in range(self.layout().count()):
            widget = self.layout().itemAt(i).widget()
            if isinstance(widget, QLabel) and widget.text() != "You" and widget.text() != "AI":
                widget.setText(content)
                break


class ChatSidebar(QWidget):
    """Sidebar widget for AI chat."""

    message_sent = pyqtSignal(str)  # Emitted when user sends a message

    def __init__(self, ai_service: Optional[AIService] = None, parent=None):
        super().__init__(parent)
        self.ai_service = ai_service
        self._messages: List[ChatMessage] = []
        self._current_slide: Optional[Slide] = None
        self._all_slides: List[Slide] = []
        self._streaming_bubble: Optional[MessageBubble] = None
        self._worker: Optional[StreamWorker] = None
        self._setup_ui()

    def _setup_ui(self):
        """Set up the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border-bottom: 1px solid #dee2e6;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 12, 15, 12)

        title = QLabel("Ask AI")
        title.setFont(QFont("", 14, QFont.Bold))
        header_layout.addWidget(title)
        header_layout.addStretch()

        layout.addWidget(header)

        # Messages area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: white;
            }
        """)

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
        input_frame.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border-top: 1px solid #dee2e6;
            }
        """)
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(10, 10, 10, 10)
        input_layout.setSpacing(8)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ask a question about this slide...")
        self.input_field.setStyleSheet("""
            QLineEdit {
                padding: 10px;
                border: 1px solid #dee2e6;
                border-radius: 6px;
                font-size: 14px;
                background-color: white;
            }
            QLineEdit:focus {
                border-color: #0078d4;
            }
        """)
        self.input_field.returnPressed.connect(self._on_send)
        input_layout.addWidget(self.input_field)

        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
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

    def set_context(self, current_slide: Slide, all_slides: List[Slide]):
        """Set the slide context for AI queries.

        Args:
            current_slide: The currently viewed slide
            all_slides: All slides in the deck
        """
        self._current_slide = current_slide
        self._all_slides = all_slides

    def set_ai_service(self, ai_service: AIService):
        """Set the AI service."""
        self.ai_service = ai_service

    def _on_send(self):
        """Handle send button click."""
        question = self.input_field.text().strip()
        if not question:
            return

        if not self.ai_service or not self.ai_service.is_available:
            self._show_error("AI service not available. Please set your ANTHROPIC_API_KEY.")
            return

        if self._current_slide is None:
            self._show_error("No slide loaded.")
            return

        # Clear input
        self.input_field.clear()

        # Add user message
        user_message = ChatMessage(
            role=MessageRole.USER,
            content=question,
            slide_index=self._current_slide.index
        )
        self._messages.append(user_message)
        self._add_message_bubble(user_message)

        # Disable input while processing
        self._set_input_enabled(False)

        # Create streaming bubble for AI response
        ai_message = ChatMessage(
            role=MessageRole.ASSISTANT,
            content="",
            slide_index=self._current_slide.index
        )
        self._streaming_bubble = self._add_message_bubble(ai_message)

        # Start streaming worker
        self._worker = StreamWorker(
            self.ai_service,
            question,
            self._current_slide,
            self._all_slides
        )
        self._worker.chunk_received.connect(self._on_chunk_received)
        self._worker.finished_streaming.connect(self._on_streaming_finished)
        self._worker.error_occurred.connect(self._on_streaming_error)
        self._worker.start()

        self.message_sent.emit(question)

    @pyqtSlot(str)
    def _on_chunk_received(self, chunk: str):
        """Handle receiving a chunk of the streamed response."""
        if self._streaming_bubble:
            current_content = self._streaming_bubble.message.content
            self._streaming_bubble.update_content(current_content + chunk)
            self._scroll_to_bottom()

    @pyqtSlot()
    def _on_streaming_finished(self):
        """Handle streaming completion."""
        if self._streaming_bubble:
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
