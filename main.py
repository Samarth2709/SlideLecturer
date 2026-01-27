#!/usr/bin/env python3
"""SlideLecturer - AI-powered slide viewer for PDF and PowerPoint files."""

import sys
from pathlib import Path

from PyQt5.QtWidgets import QApplication, QMessageBox

from src.services.slide_loader import get_loader
from src.services.ai_service import AIService
from src.ui.main_window import MainWindow
from src.utils.config import get_api_key


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <file_path>")
        print("Supported formats: .pdf, .pptx")
        sys.exit(1)

    file_path = sys.argv[1]
    path = Path(file_path)

    if not path.exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)

    if not path.is_file():
        print(f"Error: Not a file: {file_path}")
        sys.exit(1)

    ext = path.suffix.lower()
    if ext not in ('.pdf', '.pptx', '.ppt'):
        print(f"Error: Unsupported file type: {ext}")
        print("Supported formats: .pdf, .pptx")
        sys.exit(1)

    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("SlideLecturer")

    try:
        # Get loader for file type
        loader = get_loader(file_path)

        # Initialize AI service
        api_key = get_api_key()
        ai_service = None
        if api_key:
            ai_service = AIService(api_key)
        else:
            print("Warning: ANTHROPIC_API_KEY not set. AI features will be disabled.")
            print("Set it via environment variable or create a .env file.")

        # Create and show main window
        window = MainWindow(loader, str(path.absolute()), ai_service)
        window.setWindowTitle(f"SlideLecturer - {path.name}")
        window.show()

        sys.exit(app.exec_())

    except Exception as e:
        QMessageBox.critical(None, "Error", f"Failed to open file:\n{str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
