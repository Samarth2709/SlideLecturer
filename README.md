# SlideLecturer

SlideLecturer now includes both:
- Existing desktop app (`PyQt5`) under `src/`
- New web app stack:
  - Node.js frontend (`web/`)
  - Python FastAPI backend (`backend/`)

## Web App Architecture
- Frontend: React + Vite (`web/`)
- Backend: FastAPI + PyMuPDF + Anthropic (`backend/`)
- File support: `.pdf`, `.ppt`, `.pptx`
- PPT/PPTX conversion: LibreOffice (`soffice`) required on the backend host

## Run the Web Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Environment variables (project root `.env` or shell):
```bash
ANTHROPIC_API_KEY=your_key_here
# Optional
ANTHROPIC_MODEL=claude-sonnet-4-20250514
MAX_PDF_PAGES=100
CORS_ORIGINS=http://localhost:5173
```

## Run the Web Frontend
```bash
cd web
npm install
npm run dev
```

Frontend runs on `http://localhost:5173` and proxies `/api/*` to `http://localhost:8000`.

## Main Web API Endpoints
- `POST /api/v1/decks/upload`
- `GET /api/v1/decks/{deck_id}`
- `GET /api/v1/decks/{deck_id}/slides`
- `GET /api/v1/decks/{deck_id}/slides/{slide_index}/image`
- `GET /api/v1/decks/{deck_id}/slides/{slide_index}/text`
- `POST /api/v1/decks/{deck_id}/chat/stream` (SSE)
- `POST /api/v1/decks/{deck_id}/chat/clear`
- `DELETE /api/v1/decks/{deck_id}`

## Desktop App (Existing)
Desktop app remains runnable:
```bash
pip install -r requirements.txt
python main.py /path/to/slides.pdf
```
