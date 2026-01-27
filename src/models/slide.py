"""Slide data model."""

from dataclasses import dataclass
from typing import Optional

from PyQt5.QtGui import QPixmap


@dataclass
class Slide:
    """Represents a single slide in a presentation."""

    index: int
    text: str
    image: Optional[QPixmap] = None
    notes: str = ""

    @property
    def has_content(self) -> bool:
        """Check if slide has text content."""
        return bool(self.text.strip())

    @property
    def summary(self) -> str:
        """Get a short summary of the slide content."""
        if not self.text:
            return f"Slide {self.index + 1} (no text)"
        # First 100 chars of text
        preview = self.text[:100].replace("\n", " ").strip()
        if len(self.text) > 100:
            preview += "..."
        return preview
