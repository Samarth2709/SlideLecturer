#!/usr/bin/env python3
"""SlideLecturer - A slide viewer for PDF and PowerPoint files."""

import sys
from pathlib import Path

from PyQt5.QtWidgets import QApplication, QMessageBox

from loader import get_loader
from viewer import SlideViewer


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
        loader = get_loader(file_path)
        viewer = SlideViewer(loader, str(path.absolute()))
        viewer.setWindowTitle(f"SlideLecturer - {path.name}")
        viewer.show()
        sys.exit(app.exec_())
    except Exception as e:
        QMessageBox.critical(None, "Error", f"Failed to open file:\n{str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
