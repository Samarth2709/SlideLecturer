# Repository Guidelines

## Project Structure & Module Organization
`SlideLecturer` is split into a web frontend and a Python API backend:
- `web/`: React + Vite client (`src/App.jsx`, `src/App.css`, `src/main.jsx`)
- `backend/`: FastAPI service (`app/main.py`, `app/services/`, `app/prompts/`)
- `docs/`: architecture and migration notes (for example `docs/web-migration-agents.md`)
- `slides/` and `resources/`: sample/input assets

Runtime deck artifacts are stored under `backend/.data/` (created automatically). Keep generated files out of source control.

## Build, Test, and Development Commands
Backend (Python):
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend (Node.js):
```bash
cd web
npm install
npm run dev
npm run build
npm run preview
```

Quick backend sanity check:
```bash
python -m compileall backend/app
```

## Coding Style & Naming Conventions
- Python: 4-space indentation, type hints, small focused modules, `snake_case` for functions/variables.
- React/JS: functional components, hooks-first patterns, `camelCase` for helpers/state, `PascalCase` for components.
- API routes live in `backend/app/main.py`; keep business logic in `backend/app/services/`.
- Prefer explicit error handling and user-facing error messages over silent failures.

## Testing Guidelines
There is no full automated test suite yet. Minimum validation for changes:
1. `npm run build` in `web/`
2. `python -m compileall backend/app`
3. Manual smoke flow: upload deck, view slides, run chat stream, clear/delete deck.

When adding tests, place backend tests under `backend/tests/` and frontend tests near source files (for example `web/src/*.test.jsx`).

## Commit & Pull Request Guidelines
- Prefer Conventional Commit prefixes used in recent history: `feat:`, `fix:`, `chore:`.
- Keep commits focused (one logical change per commit).
- PRs should include: what changed, why, validation steps, and screenshots/GIFs for UI changes.
- Call out API contract changes explicitly (endpoint, request/response shape, streaming behavior).

## Security & Configuration Tips
- Configure secrets via environment variables (`ANTHROPIC_API_KEY`); never commit secrets.
- PPT/PPTX conversion requires LibreOffice (`soffice`) available on the backend host.
- CORS and model settings are environment-driven (`CORS_ORIGINS`, `ANTHROPIC_MODEL`, `MAX_PDF_PAGES`).
