# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SlideLecturer is a web application for viewing lecture slides (PDF/PPTX) with an AI-powered chat interface.

## Commands

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd web
npm install
npm run dev

# API key (required for AI features)
export ANTHROPIC_API_KEY=your_key_here
# Or create .env file from template: cp .env.example .env
```

## Architecture

```
backend/
├── app/main.py              # FastAPI routes
├── app/services/deck_service.py
├── app/services/ai_service.py
└── app/prompts/             # Prompt templates

web/
├── src/App.jsx              # Main React app
├── src/App.css              # Styling
└── vite.config.js
```

### Key Components

- **`backend/app/main.py`** → API endpoints for deck lifecycle, slides, and chat streaming
- **`backend/app/services/deck_service.py`** → PDF/PPTX ingest, conversion, text extraction, image rendering
- **`backend/app/services/ai_service.py`** → Claude streaming with deck + optional focus-slide context
- **`web/src/App.jsx`** → Upload, continuous slide view, focus mode, and streaming chat UI

### Data Flow

1. Frontend uploads deck to backend
2. Backend extracts slide metadata and serves rendered PNGs/text
3. Frontend tracks current and focused slide context
4. Frontend calls chat stream endpoint (SSE) with question + context
5. Backend streams AI chunks back to frontend chat UI

### AI Modes

- **Non-focus mode**: sends full deck PDF + question
- **Focus mode**: sends full deck PDF + focused slide image + question
- Conversation history is stored per deck session (text only)

## Key Dependencies

- **FastAPI** - backend API server
- **PyMuPDF (fitz)** - PDF rendering and text extraction
- **anthropic** - Claude API client
- **React + Vite** - frontend UI
- **LibreOffice** - required for PPTX conversion to PDF

## Notes

- Desktop app code has been removed
- PPTX support still requires LibreOffice on the backend host
- AI features require `ANTHROPIC_API_KEY`
- API streaming uses SSE (`/api/v1/decks/{deck_id}/chat/stream`)
