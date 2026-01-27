"""Slide navigation controls."""

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel
from PyQt5.QtCore import Qt, pyqtSignal


BUTTON_STYLE = """
    QPushButton {
        background-color: #0078d4;
        color: white;
        border: none;
        padding: 10px 20px;
        border-radius: 4px;
        font-size: 14px;
    }
    QPushButton:hover {
        background-color: #106ebe;
    }
    QPushButton:pressed {
        background-color: #005a9e;
    }
    QPushButton:disabled {
        background-color: #cccccc;
        color: #666666;
    }
"""


class SlideNavigator(QWidget):
    """Navigation controls for slides."""

    # Signals
    previous_clicked = pyqtSignal()
    next_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_index = 0
        self._total_slides = 0
        self._setup_ui()

    def _setup_ui(self):
        """Set up the UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(20)

        # Previous button
        self.prev_btn = QPushButton("Previous")
        self.prev_btn.setFixedWidth(120)
        self.prev_btn.setStyleSheet(BUTTON_STYLE)
        self.prev_btn.clicked.connect(self._on_previous)
        layout.addWidget(self.prev_btn)

        # Slide counter
        self.counter_label = QLabel("Slide 0 of 0")
        self.counter_label.setAlignment(Qt.AlignCenter)
        self.counter_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.counter_label, stretch=1)

        # Next button
        self.next_btn = QPushButton("Next")
        self.next_btn.setFixedWidth(120)
        self.next_btn.setStyleSheet(BUTTON_STYLE)
        self.next_btn.clicked.connect(self._on_next)
        layout.addWidget(self.next_btn)

        self._update_buttons()

    def _on_previous(self):
        """Handle previous button click."""
        self.previous_clicked.emit()

    def _on_next(self):
        """Handle next button click."""
        self.next_clicked.emit()

    def set_state(self, current_index: int, total_slides: int):
        """Update the navigator state.

        Args:
            current_index: Current slide index (0-based)
            total_slides: Total number of slides
        """
        self._current_index = current_index
        self._total_slides = total_slides
        self._update_display()
        self._update_buttons()

    def _update_display(self):
        """Update the counter display."""
        if self._total_slides == 0:
            self.counter_label.setText("No slides")
        else:
            self.counter_label.setText(
                f"Slide {self._current_index + 1} of {self._total_slides}"
            )

    def _update_buttons(self):
        """Update button enabled states."""
        self.prev_btn.setEnabled(self._current_index > 0)
        self.next_btn.setEnabled(self._current_index < self._total_slides - 1)

    @property
    def current_index(self) -> int:
        """Get current slide index."""
        return self._current_index

    @property
    def total_slides(self) -> int:
        """Get total number of slides."""
        return self._total_slides
