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
├── ui/           # PyQt5 widgets (main window, viewers, chat)
├── services/     # Business logic (AI client, slide loading)
├── models/       # Data classes (Slide, ChatMessage)
├── prompts/      # AI prompt templates (txt files)
└── utils/        # Config, theming, markdown rendering
```

### Key Components

- **main.py** → Entry point; validates file, initializes AI service, applies global theme, launches MainWindow
- **src/ui/main_window.py** → QMainWindow with collapsible QSplitter; slide container can be fully hidden
- **src/ui/continuous_slide_viewer.py** → PDF-like scrollable view of all slides; emits `current_slide_changed` signal based on scroll position
- **src/ui/chat_sidebar.py** → Chat widget with streaming responses via QThread worker; renders AI responses as markdown
- **src/services/slide_loader.py** → Abstract SlideLoader with PDF/PPTX implementations; extracts both images and text
- **src/services/ai_service.py** → Claude API client; sends entire PDF as document attachment with prompt caching
- **src/prompts/** → AI prompt templates loaded from txt files (system_prompt.txt, user_prompt.txt, focus_prompt.txt)
- **src/utils/theme.py** → Centralized dark mode theme constants and stylesheet generators
- **src/utils/markdown_renderer.py** → Converts markdown to HTML with inline styles for QLabel

### Data Flow

1. SlideLoader extracts slide images + text from PDF/PPTX
2. ContinuousSlideViewer displays all slides in a scrollable view
3. Scrolling triggers `current_slide_changed` → updates ChatSidebar context
4. ChatSidebar sends questions to AIService with PDF attachment
5. AIService streams responses → rendered as markdown in chat bubbles

### AI Modes

- **Non-focus mode**: Sends entire PDF as document attachment + user question
- **Focus mode**: Sends PDF + focused slide image (PNG) + user question; triggered when user clicks a slide
- Both modes maintain conversation history (text only, not PDF/images)
- PDF is sent with each API call; Anthropic prompt caching handles efficiency

## Key Dependencies

- **PyQt5** - GUI framework
- **PyMuPDF (fitz)** - PDF rendering and text extraction
- **anthropic** - Claude API client
- **markdown2** - Markdown to HTML conversion
- **LibreOffice** - External requirement for PPTX (converts to PDF)

## Notes

- PPTX support requires LibreOffice installed on the system
- AI features require ANTHROPIC_API_KEY environment variable or .env file
- **PDF limit**: Anthropic API allows max 100 pages per PDF document
- Slides rendered at 2x resolution for quality
- Chat uses streaming for real-time response display
- Theme uses dark mode with indigo accent (#6366f1)
