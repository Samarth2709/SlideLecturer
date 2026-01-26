"""PyQt5 Slide Viewer window."""

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSizePolicy
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QKeyEvent

from loader import SlideLoader


class SlideViewer(QMainWindow):
    """Main window for viewing slides."""

    def __init__(self, loader: SlideLoader, file_path: str):
        super().__init__()
        self.loader = loader
        self.file_path = file_path
        self.current_index = 0
        self.total_slides = 0

        self._setup_ui()
        self._load_file()

    def _setup_ui(self):
        """Set up the user interface."""
        self.setWindowTitle("SlideLecturer")
        self.setMinimumSize(800, 600)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)

        # Main layout
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)

        # Slide display area
        self.slide_label = QLabel()
        self.slide_label.setAlignment(Qt.AlignCenter)
        self.slide_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.slide_label.setStyleSheet("background-color: #2d2d2d; border-radius: 4px;")
        layout.addWidget(self.slide_label, stretch=1)

        # Navigation controls
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(20)

        self.prev_btn = QPushButton("← Previous")
        self.prev_btn.setFixedWidth(120)
        self.prev_btn.clicked.connect(self.prev_slide)
        nav_layout.addWidget(self.prev_btn)

        self.slide_counter = QLabel("Slide 0 of 0")
        self.slide_counter.setAlignment(Qt.AlignCenter)
        self.slide_counter.setStyleSheet("font-size: 14px; font-weight: bold;")
        nav_layout.addWidget(self.slide_counter, stretch=1)

        self.next_btn = QPushButton("Next →")
        self.next_btn.setFixedWidth(120)
        self.next_btn.clicked.connect(self.next_slide)
        nav_layout.addWidget(self.next_btn)

        layout.addLayout(nav_layout)

        # Style the buttons
        button_style = """
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
        self.prev_btn.setStyleSheet(button_style)
        self.next_btn.setStyleSheet(button_style)

    def _load_file(self):
        """Load the slide file."""
        try:
            self.total_slides = self.loader.load(self.file_path)
            self.current_index = 0
            self._update_display()
        except Exception as e:
            self.slide_label.setText(f"Error loading file:\n{str(e)}")
            self.slide_label.setStyleSheet(
                "background-color: #2d2d2d; color: #ff6b6b; "
                "font-size: 16px; padding: 20px;"
            )

    def _update_display(self):
        """Update the slide display and navigation."""
        if self.total_slides == 0:
            self.slide_counter.setText("No slides")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return

        # Update counter
        self.slide_counter.setText(f"Slide {self.current_index + 1} of {self.total_slides}")

        # Update buttons
        self.prev_btn.setEnabled(self.current_index > 0)
        self.next_btn.setEnabled(self.current_index < self.total_slides - 1)

        # Display slide
        pixmap = self.loader.get_slide(self.current_index)
        if not pixmap.isNull():
            # Scale to fit while maintaining aspect ratio
            scaled = pixmap.scaled(
                self.slide_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.slide_label.setPixmap(scaled)

    def resizeEvent(self, event):
        """Handle window resize to rescale the slide."""
        super().resizeEvent(event)
        if self.total_slides > 0:
            self._update_display()

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
