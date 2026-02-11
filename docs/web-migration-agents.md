# SlideLecturer Web Migration: Agent Findings and Plan

## Scope
Reimplement the current desktop app as a web system with:
- Node.js web app frontend
- Python backend API
- Feature parity for slide viewing, focus mode, and streamed AI chat

## Agent 1: Architecture Agent (Current-State Inventory)
### Current desktop modules
- `main.py`: app bootstrap, file validation, Qt startup
- `src/services/slide_loader.py`: PDF/PPTX ingestion (LibreOffice conversion for PPTX)
- `src/services/ai_service.py`: Claude integration with full deck PDF context + streaming
- `src/ui/continuous_slide_viewer.py`: scroll-based current-slide detection, focus mode, zoom
- `src/ui/chat_sidebar.py`: chat UI, markdown rendering, streaming responses
- `src/prompts/*.txt`: system/user/focus prompting strategy

### Current feature set
- Upload/open PDF and PPTX
- PPTX conversion to PDF
- Extract slide text and rendered images
- Continuous scrolling slide view
- Current slide tracking based on viewport
- Per-slide focus mode (click to focus/unfocus)
- Zoom controls (`+`, `-`, reset; keyboard shortcuts)
- AI chat with stream updates
- Focus mode attaches focused slide image to AI
- Conversation history persists for the active deck
- Clear chat resets history

## Agent 2: Backend Agent (Python Service Plan)
### Target stack
- FastAPI + Uvicorn
- PyMuPDF for PDF text/image extraction
- Anthropic SDK for streaming responses
- LibreOffice (`soffice`) for PPT/PPTX conversion

### API contract
- `POST /api/v1/decks/upload`: ingest PDF/PPTX and create deck session
- `GET /api/v1/decks/{deck_id}`: deck metadata
- `GET /api/v1/decks/{deck_id}/slides`: slide previews
- `GET /api/v1/decks/{deck_id}/slides/{index}/image`: slide image render
- `GET /api/v1/decks/{deck_id}/slides/{index}/text`: slide text
- `POST /api/v1/decks/{deck_id}/chat/stream`: SSE AI streaming endpoint
- `POST /api/v1/decks/{deck_id}/chat/clear`: reset deck conversation
- `DELETE /api/v1/decks/{deck_id}`: cleanup uploaded deck

### AI behavior mapping
- Always attach the deck PDF to AI requests
- On first request, set cache control on the PDF block
- In focus mode, also attach focused slide image
- Reuse system/user/focus prompt templates
- Keep rolling conversation history (text-only exchanges)

## Agent 3: Frontend Agent (Node.js Web App Plan)
### Target stack
- React + Vite (Node.js dev/build runtime)
- SSE stream consumption for live chat updates
- React Markdown for assistant response rendering

### UI mapping from desktop
- Two-pane workspace
  - Left: continuous slide viewer + zoom + slide counter + focus toggle
  - Right: chat panel with markdown responses and clear chat action
- Toolbar actions
  - Upload deck
  - Hide/show slide panel
- Keyboard parity
  - Slide navigation: arrows, space, page up/down, home/end
  - Zoom: Ctrl/Cmd `+`, `-`, `0`

### State model
- Deck state: `deck_id`, `slide_count`, metadata
- Slide view state: current index, focused index, zoom, visibility
- Chat state: messages list, streaming state, input state

## Agent 4: Integration Agent (Delivery Plan)
### Integration sequence
1. Boot Python backend and verify `/healthz`.
2. Upload deck from frontend and fetch slide list.
3. Load slide images in continuous panel.
4. Send chat messages in general mode.
5. Send chat message in focus mode and verify image context path.
6. Clear chat and verify state reset.

### Validation checklist
- PDF upload works
- PPTX upload works if LibreOffice exists
- Slide image endpoint returns PNG
- Current slide index tracks scroll position
- Focus toggle changes chat placeholder and request payload
- Streaming chat appends chunks live

## Implemented Structure
- `backend/` now contains FastAPI API, deck service, AI service, and prompt templates
- `web/` now contains React/Vite app with upload, viewer, focus mode, and streaming chat
- Existing desktop app under `src/` is left intact for backward compatibility during migration
