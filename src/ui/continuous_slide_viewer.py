"""Continuous scroll slide viewer widget."""

from typing import List, Optional
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QLabel,
    QSizePolicy, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QPixmap

from ..models.slide import Slide
from ..utils.theme import Theme


class SlideWidget(QFrame):
    """Individual slide widget within the continuous view."""

    # Signal emitted when this slide is clicked
    clicked = pyqtSignal(int)  # Emits slide index (0-based)

    # Minimum width for slides
    MIN_WIDTH = 300

    def __init__(self, slide: Slide, slide_number: int, parent=None):
        super().__init__(parent)
        self.slide = slide
        self.slide_number = slide_number
        self._slide_index = slide_number - 1  # 0-based index
        self._pixmap: Optional[QPixmap] = None
        self._is_focused = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 24)  # Space between slides
        layout.setSpacing(8)

        # Slide number label
        self.number_label = QLabel(f"Slide {self.slide_number}")
        self.number_label.setStyleSheet(f"""
            font-size: 12px;
            color: {Theme.TEXT_SECONDARY};
            font-weight: 600;
            padding: 4px 0;
        """)
        layout.addWidget(self.number_label)

        # Slide image container
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._apply_unfocused_style()
        layout.addWidget(self.image_label)

        # Frame style and cursor
        self.setStyleSheet("background-color: transparent;")
        self.setCursor(Qt.PointingHandCursor)

    def _apply_focused_style(self):
        """Apply focused (green border) style to the image label."""
        self.image_label.setStyleSheet(f"""
            QLabel {{
                background-color: {Theme.SURFACE};
                border-radius: {Theme.RADIUS_LG};
                padding: 4px;
                border: 3px solid {Theme.SUCCESS};
            }}
        """)

    def _apply_unfocused_style(self):
        """Apply unfocused (transparent border) style to the image label."""
        self.image_label.setStyleSheet(f"""
            QLabel {{
                background-color: {Theme.SURFACE};
                border-radius: {Theme.RADIUS_LG};
                padding: 4px;
                border: 3px solid transparent;
            }}
        """)

    def set_focused(self, focused: bool):
        """Set the focused state of this slide."""
        self._is_focused = focused
        if focused:
            self._apply_focused_style()
        else:
            self._apply_unfocused_style()

    @property
    def is_focused(self) -> bool:
        """Check if this slide is focused."""
        return self._is_focused

    def get_pixmap(self) -> Optional[QPixmap]:
        """Get the original pixmap for this slide."""
        return self._pixmap

    def mousePressEvent(self, event):
        """Handle mouse click on the slide."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._slide_index)
        super().mousePressEvent(event)

    def set_pixmap(self, pixmap: QPixmap):
        """Set the slide image."""
        self._pixmap = pixmap
        self._update_display()

    def _update_display(self):
        """Scale and display the pixmap to fit container width."""
        if self._pixmap is None or self._pixmap.isNull():
            return

        # Scale to fit width while maintaining aspect ratio
        # Account for padding (4px) and border (3px) on each side = 14px total
        available_width = self.width() - 14
        if available_width < self.MIN_WIDTH:
            available_width = self.MIN_WIDTH

        scaled = self._pixmap.scaledToWidth(
            available_width,
            Qt.SmoothTransformation
        )
        self.image_label.setPixmap(scaled)
        self.image_label.setFixedHeight(scaled.height() + 14)  # Account for padding + border

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()


class ContinuousSlideViewer(QWidget):
    """Continuous scroll viewer showing all slides vertically."""

    # Signal emitted when visible slide changes
    current_slide_changed = pyqtSignal(int)  # Emits slide index (0-based)
    # Signal emitted when slide focus changes (index, is_focused, pixmap or None)
    slide_focus_changed = pyqtSignal(int, bool, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slides: List[Slide] = []
        self._slide_widgets: List[SlideWidget] = []
        self._current_index = 0
        self._focused_index: Optional[int] = None
        self._scroll_timer = QTimer()
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._update_current_slide)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {Theme.BACKGROUND};
            }}
            QScrollBar:vertical {{
                background: {Theme.SURFACE};
                width: 10px;
                border-radius: 5px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: {Theme.BORDER};
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {Theme.TEXT_MUTED};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)

        # Connect scroll signal
        self.scroll_area.verticalScrollBar().valueChanged.connect(
            self._on_scroll
        )

        # Container for slides
        self.container = QWidget()
        self.container.setStyleSheet(f"background-color: {Theme.BACKGROUND};")
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(20, 20, 20, 20)
        self.container_layout.setSpacing(0)
        self.container_layout.addStretch()

        self.scroll_area.setWidget(self.container)
        layout.addWidget(self.scroll_area)

    def set_slides(self, slides: List[Slide]):
        """Load all slides into the viewer."""
        # Clear existing slides
        self._clear_slides()

        self._slides = slides
        self._focused_index = None

        # Create slide widgets
        for i, slide in enumerate(slides):
            widget = SlideWidget(slide, i + 1)
            widget.clicked.connect(self._on_slide_clicked)
            if slide.image and not slide.image.isNull():
                widget.set_pixmap(slide.image)

            self._slide_widgets.append(widget)
            # Insert before the stretch
            self.container_layout.insertWidget(
                self.container_layout.count() - 1,
                widget
            )

        # Scroll to top
        self.scroll_area.verticalScrollBar().setValue(0)
        self._current_index = 0

    def _on_slide_clicked(self, index: int):
        """Handle when a slide is clicked."""
        if self._focused_index == index:
            # Clicking the focused slide removes focus
            self._slide_widgets[index].set_focused(False)
            self._focused_index = None
            self.slide_focus_changed.emit(index, False, None)
        else:
            # Clear previous focus
            if self._focused_index is not None:
                self._slide_widgets[self._focused_index].set_focused(False)

            # Set new focus
            self._slide_widgets[index].set_focused(True)
            self._focused_index = index
            pixmap = self._slide_widgets[index].get_pixmap()
            self.slide_focus_changed.emit(index, True, pixmap)

    def get_focused_slide_index(self) -> Optional[int]:
        """Get the currently focused slide index, or None if no focus."""
        return self._focused_index

    def get_focused_slide_pixmap(self) -> Optional[QPixmap]:
        """Get the pixmap of the focused slide, or None if no focus."""
        if self._focused_index is not None:
            return self._slide_widgets[self._focused_index].get_pixmap()
        return None

    def clear_focus(self):
        """Clear any focused slide."""
        if self._focused_index is not None:
            self._slide_widgets[self._focused_index].set_focused(False)
            old_index = self._focused_index
            self._focused_index = None
            self.slide_focus_changed.emit(old_index, False, None)

    def _clear_slides(self):
        """Remove all slide widgets."""
        for widget in self._slide_widgets:
            widget.deleteLater()
        self._slide_widgets.clear()

    def _on_scroll(self, value: int):
        """Handle scroll events with debouncing."""
        # Debounce scroll events to avoid excessive updates
        self._scroll_timer.start(100)  # 100ms debounce

    def _update_current_slide(self):
        """Determine which slide is currently most visible."""
        if not self._slide_widgets:
            return

        viewport = self.scroll_area.viewport()
        viewport_height = viewport.height()
        viewport_top_third = viewport_height // 3  # Upper third as "current"

        scroll_pos = self.scroll_area.verticalScrollBar().value()

        # Find the slide whose top is closest to the viewport's upper third
        best_index = 0
        best_distance = float('inf')

        for i, widget in enumerate(self._slide_widgets):
            # Get widget position relative to container
            widget_pos = widget.mapTo(self.container, widget.rect().topLeft())
            widget_top = widget_pos.y() - scroll_pos

            # Distance from viewport's upper third
            distance = abs(widget_top - viewport_top_third)

            # Also consider if widget is visible
            widget_bottom = widget_top + widget.height()
            is_visible = widget_bottom > 0 and widget_top < viewport_height

            if is_visible and distance < best_distance:
                best_distance = distance
                best_index = i

        if best_index != self._current_index:
            self._current_index = best_index
            self.current_slide_changed.emit(best_index)

    def scroll_to_slide(self, index: int):
        """Scroll to bring a specific slide into view."""
        if 0 <= index < len(self._slide_widgets):
            widget = self._slide_widgets[index]
            # Scroll to position the slide at the top of the viewport
            self.scroll_area.ensureWidgetVisible(widget, 0, 50)
            self._current_index = index

    def get_current_index(self) -> int:
        """Get the currently visible slide index."""
        return self._current_index

    @property
    def slide_count(self) -> int:
        """Get total number of slides."""
        return len(self._slides)

    def clear(self):
        """Clear all slides."""
        self._clear_slides()
        self._slides.clear()
        self._current_index = 0
        self._focused_index = None

    def show_error(self, message: str):
        """Show an error message."""
        self._clear_slides()
        error_label = QLabel(message)
        error_label.setAlignment(Qt.AlignCenter)
        error_label.setWordWrap(True)
        error_label.setStyleSheet(f"""
            color: {Theme.ERROR};
            font-size: 16px;
            padding: 40px;
        """)
        self.container_layout.insertWidget(0, error_label)

    def refresh_slide_sizes(self):
        """Force all slides to recalculate their display size."""
        for widget in self._slide_widgets:
            widget._update_display()

    def resizeEvent(self, event):
        """Handle resize events - refresh all slide sizes."""
        super().resizeEvent(event)
        # Use a timer to debounce resize events
        QTimer.singleShot(50, self.refresh_slide_sizes)
