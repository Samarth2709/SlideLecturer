"""Main application window."""

from typing import Optional, List

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QMessageBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeyEvent

from .slide_viewer import SlideViewer
from .slide_navigator import SlideNavigator
from .chat_sidebar import ChatSidebar
from ..services.slide_loader import SlideLoader
from ..services.ai_service import AIService
from ..models.slide import Slide


class MainWindow(QMainWindow):
    """Main application window with slide viewer and chat sidebar."""

    def __init__(self, loader: SlideLoader, file_path: str, ai_service: Optional[AIService] = None):
        super().__init__()
        self.loader = loader
        self.file_path = file_path
        self.ai_service = ai_service

        self.current_index = 0
        self.total_slides = 0
        self.slides: List[Slide] = []

        self._setup_ui()
        self._load_file()

    def _setup_ui(self):
        """Set up the user interface."""
        self.setWindowTitle("SlideLecturer")
        self.setMinimumSize(1200, 700)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        # Main layout
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(0)

        # Create splitter for slide area and chat
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #dee2e6;
            }
        """)

        # Left side: Slide viewer + navigator
        slide_container = QWidget()
        slide_layout = QVBoxLayout(slide_container)
        slide_layout.setContentsMargins(0, 0, 10, 0)
        slide_layout.setSpacing(0)

        # Slide viewer
        self.slide_viewer = SlideViewer()
        slide_layout.addWidget(self.slide_viewer, stretch=1)

        # Navigation controls
        self.navigator = SlideNavigator()
        self.navigator.previous_clicked.connect(self.prev_slide)
        self.navigator.next_clicked.connect(self.next_slide)
        slide_layout.addWidget(self.navigator)

        splitter.addWidget(slide_container)

        # Right side: Chat sidebar
        self.chat_sidebar = ChatSidebar(self.ai_service)
        splitter.addWidget(self.chat_sidebar)

        # Set initial splitter sizes (70% slide, 30% chat)
        splitter.setSizes([700, 300])

        main_layout.addWidget(splitter)

    def _load_file(self):
        """Load the slide file."""
        try:
            self.total_slides = self.loader.load(self.file_path)
            self.slides = self.loader.get_all_slides()
            self.current_index = 0
            self._update_display()

            # Update chat context
            if self.slides:
                self.chat_sidebar.set_context(
                    self.slides[self.current_index],
                    self.slides
                )

        except Exception as e:
            self.slide_viewer.show_error(f"Error loading file:\n{str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to load file:\n{str(e)}")

    def _update_display(self):
        """Update the slide display and navigation."""
        if self.total_slides == 0:
            self.navigator.set_state(0, 0)
            return

        # Update navigator
        self.navigator.set_state(self.current_index, self.total_slides)

        # Display current slide
        slide = self.loader.get_slide(self.current_index)
        if slide.image and not slide.image.isNull():
            self.slide_viewer.set_slide(slide.image)

        # Update chat context
        if self.slides:
            self.chat_sidebar.set_context(
                self.slides[self.current_index],
                self.slides
            )

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard navigation."""
        if event.key() in (Qt.Key_Right, Qt.Key_Space, Qt.Key_Return):
            self.next_slide()
        elif event.key() in (Qt.Key_Left, Qt.Key_Backspace):
            self.prev_slide()
        elif event.key() == Qt.Key_Home:
            self.go_to_slide(0)
        elif event.key() == Qt.Key_End:
            self.go_to_slide(self.total_slides - 1)
        elif event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def next_slide(self):
        """Go to the next slide."""
        if self.current_index < self.total_slides - 1:
            self.current_index += 1
            self._update_display()

    def prev_slide(self):
        """Go to the previous slide."""
        if self.current_index > 0:
            self.current_index -= 1
            self._update_display()

    def go_to_slide(self, index: int):
        """Go to a specific slide."""
        if 0 <= index < self.total_slides:
            self.current_index = index
            self._update_display()

    def closeEvent(self, event):
        """Handle window close."""
        if self.loader:
            self.loader.close()
        super().closeEvent(event)
