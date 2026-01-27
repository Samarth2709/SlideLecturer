"""Slide loaders for PDF and PPTX files."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional
import subprocess
import tempfile
import shutil

import fitz  # PyMuPDF
from PyQt5.QtGui import QPixmap, QImage

from ..models.slide import Slide


class SlideLoader(ABC):
    """Abstract base class for slide loaders."""

    @abstractmethod
    def load(self, file_path: str) -> int:
        """Load slides from file. Returns the number of slides."""
        pass

    @abstractmethod
    def get_slide(self, index: int) -> Slide:
        """Get slide at index."""
        pass

    @abstractmethod
    def get_slide_image(self, index: int) -> QPixmap:
        """Get slide image at index as QPixmap."""
        pass

    @abstractmethod
    def get_slide_text(self, index: int) -> str:
        """Get text content of slide at index."""
        pass

    @abstractmethod
    def get_all_slides(self) -> List[Slide]:
        """Get all slides."""
        pass

    @abstractmethod
    def slide_count(self) -> int:
        """Return total number of slides."""
        pass

    @abstractmethod
    def get_pdf_path(self) -> Optional[str]:
        """Get the path to the PDF file (for AI context)."""
        pass

    def close(self):
        """Clean up resources."""
        pass


class PDFLoader(SlideLoader):
    """Loader for PDF files using PyMuPDF."""

    def __init__(self):
        self.doc: Optional[fitz.Document] = None
        self._slide_count = 0
        self._slides: List[Slide] = []
        self._pdf_path: Optional[str] = None

    def load(self, file_path: str) -> int:
        self._pdf_path = file_path
        self.doc = fitz.open(file_path)
        self._slide_count = len(self.doc)

        # Pre-extract text for all slides
        self._slides = []
        for i in range(self._slide_count):
            page = self.doc[i]
            text = page.get_text()
            self._slides.append(Slide(index=i, text=text))

        return self._slide_count

    def get_slide(self, index: int) -> Slide:
        if index < 0 or index >= self._slide_count:
            return Slide(index=index, text="")

        slide = self._slides[index]
        # Lazy load image if not already loaded
        if slide.image is None:
            slide.image = self.get_slide_image(index)
        return slide

    def get_slide_image(self, index: int) -> QPixmap:
        if self.doc is None or index < 0 or index >= self._slide_count:
            return QPixmap()

        page = self.doc[index]
        # Render at 2x for better quality
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)

        # Convert to QPixmap
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        return QPixmap.fromImage(img)

    def get_slide_text(self, index: int) -> str:
        if index < 0 or index >= self._slide_count:
            return ""
        return self._slides[index].text

    def get_all_slides(self) -> List[Slide]:
        return self._slides

    def slide_count(self) -> int:
        return self._slide_count

    def get_pdf_path(self) -> Optional[str]:
        return self._pdf_path

    def close(self):
        if self.doc:
            self.doc.close()


class PPTXLoader(SlideLoader):
    """Loader for PowerPoint files by converting to PDF via LibreOffice."""

    def __init__(self):
        self._pdf_loader: Optional[PDFLoader] = None
        self._temp_dir: Optional[str] = None
        self._slide_count = 0
        self._pdf_path: Optional[str] = None

    def load(self, file_path: str) -> int:
        # Find LibreOffice
        soffice = self._find_libreoffice()
        if not soffice:
            raise RuntimeError(
                "LibreOffice is required to view PowerPoint files.\n"
                "Install it from: https://www.libreoffice.org/download/download/"
            )

        # Create temp directory for PDF conversion
        self._temp_dir = tempfile.mkdtemp(prefix="slidelect_")

        # Convert PPTX to PDF using LibreOffice
        try:
            subprocess.run(
                [soffice, "--headless", "--convert-to", "pdf",
                 "--outdir", self._temp_dir, file_path],
                check=True,
                capture_output=True,
                timeout=60
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Conversion timed out. The file may be too large.")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to convert PowerPoint: {e.stderr.decode()}")

        # Find the converted PDF
        pptx_path = Path(file_path)
        pdf_path = Path(self._temp_dir) / f"{pptx_path.stem}.pdf"

        if not pdf_path.exists():
            raise RuntimeError("Conversion failed: PDF file not created")

        # Store the PDF path for AI context
        self._pdf_path = str(pdf_path)

        # Use PDF loader to load the converted file
        self._pdf_loader = PDFLoader()
        self._slide_count = self._pdf_loader.load(self._pdf_path)
        return self._slide_count

    def _find_libreoffice(self) -> Optional[str]:
        """Find LibreOffice executable."""
        candidates = [
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",  # macOS
            "/usr/bin/soffice",  # Linux
            "/usr/bin/libreoffice",  # Linux alternative
            "soffice",  # In PATH
            "libreoffice",  # In PATH
        ]

        for candidate in candidates:
            if shutil.which(candidate):
                return candidate
            if Path(candidate).exists():
                return candidate

        return None

    def get_slide(self, index: int) -> Slide:
        if self._pdf_loader is None:
            return Slide(index=index, text="")
        return self._pdf_loader.get_slide(index)

    def get_slide_image(self, index: int) -> QPixmap:
        if self._pdf_loader is None:
            return QPixmap()
        return self._pdf_loader.get_slide_image(index)

    def get_slide_text(self, index: int) -> str:
        if self._pdf_loader is None:
            return ""
        return self._pdf_loader.get_slide_text(index)

    def get_all_slides(self) -> List[Slide]:
        if self._pdf_loader is None:
            return []
        return self._pdf_loader.get_all_slides()

    def slide_count(self) -> int:
        return self._slide_count

    def get_pdf_path(self) -> Optional[str]:
        return self._pdf_path

    def close(self):
        if self._pdf_loader:
            self._pdf_loader.close()
        if self._temp_dir and Path(self._temp_dir).exists():
            shutil.rmtree(self._temp_dir, ignore_errors=True)


def get_loader(file_path: str) -> SlideLoader:
    """Factory function to get appropriate loader based on file extension."""
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == '.pdf':
        return PDFLoader()
    elif ext in ('.pptx', '.ppt'):
        return PPTXLoader()
    else:
        raise ValueError(f"Unsupported file type: {ext}")
