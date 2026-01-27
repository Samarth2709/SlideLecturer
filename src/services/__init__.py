"""Services for SlideLecturer."""

from .slide_loader import SlideLoader, PDFLoader, PPTXLoader, get_loader
from .ai_service import AIService

__all__ = ["SlideLoader", "PDFLoader", "PPTXLoader", "get_loader", "AIService"]
