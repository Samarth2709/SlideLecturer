"""Slide viewer widget for displaying slides."""

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap


class SlideViewer(QWidget):
    """Widget for displaying a single slide."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_pixmap: QPixmap = None
        self._setup_ui()

    def _setup_ui(self):
        """Set up the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Slide display label
        self.slide_label = QLabel()
        self.slide_label.setAlignment(Qt.AlignCenter)
        self.slide_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.slide_label.setStyleSheet("""
            QLabel {
                background-color: #2d2d2d;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.slide_label)

    def set_slide(self, pixmap: QPixmap):
        """Set the slide to display.

        Args:
            pixmap: The slide image as QPixmap
        """
        self._current_pixmap = pixmap
        self._update_display()

    def _update_display(self):
        """Update the slide display with current pixmap."""
        if self._current_pixmap is None or self._current_pixmap.isNull():
            self.slide_label.clear()
            return

        # Scale to fit while maintaining aspect ratio
        scaled = self._current_pixmap.scaled(
            self.slide_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.slide_label.setPixmap(scaled)

    def resizeEvent(self, event):
        """Handle resize to rescale the slide."""
        super().resizeEvent(event)
        self._update_display()

    def clear(self):
        """Clear the display."""
        self._current_pixmap = None
        self.slide_label.clear()

    def show_error(self, message: str):
        """Show an error message in the viewer."""
        self._current_pixmap = None
        self.slide_label.setText(message)
        self.slide_label.setStyleSheet("""
            QLabel {
                background-color: #2d2d2d;
                color: #ff6b6b;
                font-size: 16px;
                padding: 20px;
                border-radius: 4px;
            }
        """)
