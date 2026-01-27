# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SlideLecturer is a PyQt5 desktop application for viewing lecture slides (PDF/PPTX) with an AI-powered chat sidebar that helps users learn from the content. The AI has context of both the current slide and the entire deck.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python main.py /path/to/slides.pdf
python main.py /path/to/presentation.pptx

# Set API key (required for AI features)
export ANTHROPIC_API_KEY=your_key_here
# Or create .env file from template: cp .env.example .env
```

## Architecture

```
src/
├── ui/           # PyQt5 widgets
├── services/     # Business logic (AI, slide loading)
├── models/       # Data classes (Slide, ChatMessage)
└── utils/        # Configuration
```

### Key Components

- **main.py** → Entry point; validates file, initializes AI service, launches MainWindow
- **src/ui/main_window.py** → QMainWindow with QSplitter layout (70% slides, 30% chat)
- **src/ui/chat_sidebar.py** → Chat widget with streaming responses via QThread worker
- **src/services/slide_loader.py** → Abstract SlideLoader with PDF/PPTX implementations; extracts both images and text
- **src/services/ai_service.py** → Claude API client; builds context from current slide + deck overview

### Data Flow

1. SlideLoader extracts slide images + text from PDF/PPTX
2. MainWindow displays slides and passes context to ChatSidebar on navigation
3. ChatSidebar sends questions to AIService with current slide text + deck summary
4. AIService streams responses back via signals

## Key Dependencies

- **PyQt5** - GUI framework
- **PyMuPDF (fitz)** - PDF rendering and text extraction
- **anthropic** - Claude API client
- **LibreOffice** - External requirement for PPTX (converts to PDF)

## Notes

- PPTX support requires LibreOffice installed on the system
- AI features require ANTHROPIC_API_KEY environment variable or .env file
- Slides rendered at 2x resolution for quality
- Chat uses streaming for real-time response display
