"""Slide navigation controls."""

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt

from ..utils.theme import Theme


class SlideNavigator(QWidget):
    """Navigation controls for slides - displays slide counter only."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_index = 0
        self._total_slides = 0
        self._setup_ui()

    def _setup_ui(self):
        """Set up the UI."""
        # Navigator container styling
        self.setStyleSheet(f"""
            SlideNavigator {{
                background-color: {Theme.SURFACE};
                border-radius: {Theme.RADIUS_MD};
                padding: 8px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(20)

        # Slide counter (centered)
        self.counter_label = QLabel("Slide 0 of 0")
        self.counter_label.setAlignment(Qt.AlignCenter)
        self.counter_label.setStyleSheet(Theme.get_counter_label_style())
        layout.addWidget(self.counter_label, stretch=1)

    def set_state(self, current_index: int, total_slides: int):
        """Update the navigator state.

        Args:
            current_index: Current slide index (0-based)
            total_slides: Total number of slides
        """
        self._current_index = current_index
        self._total_slides = total_slides
        self._update_display()

    def _update_display(self):
        """Update the counter display."""
        if self._total_slides == 0:
            self.counter_label.setText("No slides")
        else:
            self.counter_label.setText(
                f"Slide {self._current_index + 1} of {self._total_slides}"
            )

    @property
    def current_index(self) -> int:
        """Get current slide index."""
        return self._current_index

    @property
    def total_slides(self) -> int:
        """Get total number of slides."""
        return self._total_slides
