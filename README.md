# SlideLecturer

SlideLecturer is a web application with:
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
ELEVENLABS_API_KEY=your_key_here
# Optional
ANTHROPIC_MODEL=claude-sonnet-4-20250514
ANTHROPIC_TRANSCRIPT_MODEL=claude-haiku-4-5-20251001
ELEVENLABS_VOICE_ID=
ELEVENLABS_VOICE_NAME=Rachel
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
ELEVENLABS_OUTPUT_FORMAT=mp3_44100_128
ELEVENLABS_BASE_URL=https://api.elevenlabs.io
ELEVENLABS_TIMEOUT_SECONDS=45
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
- `POST /api/v1/decks/{deck_id}/slides/{slide_index}/transcript/speech`
- `GET /api/v1/decks/{deck_id}/slides/{slide_index}/transcript/speech/stream`
- `GET /api/v1/decks/{deck_id}/transcripts` (auto-generated after upload)
- `POST /api/v1/decks/{deck_id}/chat/stream` (SSE)
- `POST /api/v1/decks/{deck_id}/chat/clear`
- `DELETE /api/v1/decks/{deck_id}`

Transcript narration notes:
- First playback streams from ElevenLabs and starts audio as chunks arrive.
- Generated slide audio is cached under the deck runtime directory and reused on later plays.

Transcript generation cache notes:
- Completed slide transcripts are persisted by a content hash derived from normalized extracted slide text.
- Re-uploading an equivalent deck reuses cached transcripts immediately and skips regeneration.
- The cache stores transcript text only (not a copy of prior uploaded source documents).
