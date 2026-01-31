"""Main application window."""

from typing import Optional, List

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QMessageBox, QPushButton, QFrame, QLabel
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeyEvent, QPixmap

from .continuous_slide_viewer import ContinuousSlideViewer
from .slide_navigator import SlideNavigator
from .chat_sidebar import ChatSidebar
from ..services.slide_loader import SlideLoader
from ..services.ai_service import AIService
from ..models.slide import Slide
from ..utils.theme import Theme


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

        # Track slide visibility state
        self._slides_visible = True
        self._last_slide_width = 700  # Remember width when hiding

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        # Main layout
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(0)

        # Create splitter for slide area and chat
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(False)  # Don't allow collapse via drag
        self.splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {Theme.BORDER};
                border-radius: 3px;
            }}
            QSplitter::handle:hover {{
                background-color: {Theme.PRIMARY};
            }}
        """)

        # Left side: Slide viewer + navigator
        self.slide_container = QWidget()
        self.slide_container.setMinimumWidth(350)  # Minimum width for slides
        slide_layout = QVBoxLayout(self.slide_container)
        slide_layout.setContentsMargins(0, 0, 10, 0)
        slide_layout.setSpacing(8)

        # Toggle button at the top
        toggle_container = QWidget()
        toggle_layout = QHBoxLayout(toggle_container)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(0)

        self.toggle_btn = QPushButton("◀")
        self.toggle_btn.setFixedSize(28, 28)
        self.toggle_btn.setToolTip("Hide slides")
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self._toggle_slides)
        self.toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.SURFACE};
                color: {Theme.TEXT_SECONDARY};
                border: 1px solid {Theme.BORDER};
                border-radius: 6px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {Theme.SURFACE_ELEVATED};
                color: {Theme.TEXT_PRIMARY};
                border-color: {Theme.PRIMARY};
            }}
        """)
        toggle_layout.addWidget(self.toggle_btn)
        toggle_layout.addStretch()

        # Zoom controls
        zoom_btn_style = f"""
            QPushButton {{
                background-color: {Theme.SURFACE};
                color: {Theme.TEXT_SECONDARY};
                border: 1px solid {Theme.BORDER};
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {Theme.SURFACE_ELEVATED};
                color: {Theme.TEXT_PRIMARY};
                border-color: {Theme.PRIMARY};
            }}
        """

        self.zoom_out_btn = QPushButton("-")
        self.zoom_out_btn.setFixedSize(28, 28)
        self.zoom_out_btn.setToolTip("Zoom out (Ctrl+-)")
        self.zoom_out_btn.setCursor(Qt.PointingHandCursor)
        self.zoom_out_btn.setStyleSheet(zoom_btn_style)
        self.zoom_out_btn.clicked.connect(self._on_zoom_out)
        toggle_layout.addWidget(self.zoom_out_btn)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setFixedWidth(50)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setStyleSheet(f"""
            QLabel {{
                color: {Theme.TEXT_SECONDARY};
                font-size: 12px;
                font-weight: 600;
            }}
        """)
        toggle_layout.addWidget(self.zoom_label)

        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setFixedSize(28, 28)
        self.zoom_in_btn.setToolTip("Zoom in (Ctrl++)")
        self.zoom_in_btn.setCursor(Qt.PointingHandCursor)
        self.zoom_in_btn.setStyleSheet(zoom_btn_style)
        self.zoom_in_btn.clicked.connect(self._on_zoom_in)
        toggle_layout.addWidget(self.zoom_in_btn)

        self.zoom_reset_btn = QPushButton("Reset")
        self.zoom_reset_btn.setFixedSize(50, 28)
        self.zoom_reset_btn.setToolTip("Reset zoom (Ctrl+0)")
        self.zoom_reset_btn.setCursor(Qt.PointingHandCursor)
        self.zoom_reset_btn.setStyleSheet(zoom_btn_style)
        self.zoom_reset_btn.clicked.connect(self._on_zoom_reset)
        toggle_layout.addWidget(self.zoom_reset_btn)

        slide_layout.addWidget(toggle_container)

        # Continuous slide viewer
        self.slide_viewer = ContinuousSlideViewer()
        self.slide_viewer.current_slide_changed.connect(self._on_slide_changed)
        self.slide_viewer.slide_focus_changed.connect(self._on_slide_focus_changed)
        self.slide_viewer.zoom_changed.connect(self._on_zoom_changed)
        slide_layout.addWidget(self.slide_viewer, stretch=1)

        # Navigation controls (slide counter only)
        self.navigator = SlideNavigator()
        slide_layout.addWidget(self.navigator)

        self.splitter.addWidget(self.slide_container)

        # Right side: Chat sidebar
        self.chat_sidebar = ChatSidebar(self.ai_service)
        self.chat_sidebar.setMinimumWidth(250)  # Keep chat at minimum width
        self.splitter.addWidget(self.chat_sidebar)

        # Set initial splitter sizes (70% slide, 30% chat)
        self.splitter.setSizes([700, 300])

        # Connect splitter moved signal to refresh slides
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        main_layout.addWidget(self.splitter)

    def _load_file(self):
        """Load the slide file."""
        try:
            self.total_slides = self.loader.load(self.file_path)
            self.slides = self.loader.get_all_slides()

            # Load all slide images
            for i, slide in enumerate(self.slides):
                if slide.image is None:
                    slide.image = self.loader.get_slide_image(i)

            # Set slides in continuous viewer
            self.slide_viewer.set_slides(self.slides)

            # Update navigator
            self.current_index = 0
            self.navigator.set_state(self.current_index, self.total_slides)

            # Set PDF for AI context (must be done after loader.load())
            pdf_path = self.loader.get_pdf_path()
            if pdf_path:
                self.chat_sidebar.set_pdf(pdf_path)

            # Set initial chat context
            if self.slides:
                self.chat_sidebar.set_context(self.slides[self.current_index])

        except Exception as e:
            self.slide_viewer.show_error(f"Error loading file:\n{str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to load file:\n{str(e)}")

    def _on_slide_changed(self, index: int):
        """Handle when the visible slide changes due to scrolling."""
        self.current_index = index
        self.navigator.set_state(index, self.total_slides)

        # Update chat context
        if self.slides:
            self.chat_sidebar.set_context(self.slides[index])

    def _on_slide_focus_changed(self, index: int, is_focused: bool, pixmap: Optional[QPixmap]):
        """Handle when slide focus changes."""
        if is_focused and pixmap and self.slides:
            # Pass focused slide image to chat sidebar
            self.chat_sidebar.set_focused_slide(index, pixmap, self.slides[index])
        else:
            # Clear focus - chat should use deck context
            self.chat_sidebar.clear_focused_slide()

    def _on_splitter_moved(self, pos: int, index: int):
        """Handle splitter resize - refresh slide sizes."""
        self.slide_viewer.refresh_slide_sizes()

    def _on_zoom_in(self):
        """Handle zoom in button click."""
        self.slide_viewer.zoom_in()

    def _on_zoom_out(self):
        """Handle zoom out button click."""
        self.slide_viewer.zoom_out()

    def _on_zoom_reset(self):
        """Handle zoom reset button click."""
        self.slide_viewer.reset_zoom()

    def _on_zoom_changed(self, zoom_level: float):
        """Handle zoom level change from viewer."""
        self.zoom_label.setText(f"{int(zoom_level * 100)}%")

    def _toggle_slides(self):
        """Toggle visibility of the slide viewer."""
        if self._slides_visible:
            # Hide slides
            self._last_slide_width = self.splitter.sizes()[0]
            self.slide_viewer.hide()
            self.navigator.hide()
            self.slide_container.setMinimumWidth(28)  # Just enough for the button
            self.slide_container.setMaximumWidth(50)
            self.toggle_btn.setText("▶")
            self.toggle_btn.setToolTip("Show slides")
            self._slides_visible = False
        else:
            # Show slides
            self.slide_container.setMinimumWidth(350)
            self.slide_container.setMaximumWidth(16777215)  # Qt max
            self.slide_viewer.show()
            self.navigator.show()
            self.toggle_btn.setText("◀")
            self.toggle_btn.setToolTip("Hide slides")
            self._slides_visible = True
            # Restore previous width
            sizes = self.splitter.sizes()
            total = sum(sizes)
            self.splitter.setSizes([self._last_slide_width, total - self._last_slide_width])
            # Refresh slide sizes after showing
            self.slide_viewer.refresh_slide_sizes()

    def _scroll_to_previous(self):
        """Scroll to previous slide."""
        if self.current_index > 0:
            self.slide_viewer.scroll_to_slide(self.current_index - 1)

    def _scroll_to_next(self):
        """Scroll to next slide."""
        if self.current_index < self.total_slides - 1:
            self.slide_viewer.scroll_to_slide(self.current_index + 1)

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard navigation and zoom."""
        # Don't handle keys when typing in chat input
        if self.chat_sidebar.input_field.hasFocus():
            super().keyPressEvent(event)
            return

        modifiers = event.modifiers()
        key = event.key()

        # Zoom controls: Ctrl+Plus / Ctrl+Minus / Ctrl+0
        if modifiers & Qt.ControlModifier:
            if key in (Qt.Key_Plus, Qt.Key_Equal):  # + or = key
                self.slide_viewer.zoom_in()
                return
            elif key == Qt.Key_Minus:
                self.slide_viewer.zoom_out()
                return
            elif key == Qt.Key_0:
                self.slide_viewer.reset_zoom()
                return

        # Navigation
        if key in (Qt.Key_Right, Qt.Key_Space):
            self._scroll_to_next()
        elif key in (Qt.Key_Left, Qt.Key_Backspace):
            self._scroll_to_previous()
        elif key in (Qt.Key_PageDown, Qt.Key_Down):
            self._scroll_to_next()
        elif key in (Qt.Key_PageUp, Qt.Key_Up):
            self._scroll_to_previous()
        elif key == Qt.Key_Home:
            self.go_to_slide(0)
        elif key == Qt.Key_End:
            self.go_to_slide(self.total_slides - 1)
        elif key == Qt.Key_Escape:
            # Clear focus instead of closing
            self.setFocus()
        else:
            super().keyPressEvent(event)

    def go_to_slide(self, index: int):
        """Go to a specific slide."""
        if 0 <= index < self.total_slides:
            self.slide_viewer.scroll_to_slide(index)

    def closeEvent(self, event):
        """Handle window close."""
        if self.loader:
            self.loader.close()
        super().closeEvent(event)
