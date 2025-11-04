# Repository Guidelines

## Project Structure & Module Organization
- `whatsapp_bot/`: Flask webhook for the DASS-21 flow; integrations live in `services/`, shared DTOs in `models.py`.
- `chat_bot_api/`: FastAPI + MongoDB service storing students, responses, scores, and analytics logs.
- `dashboard-emotitrack/`: Laravel dashboard with assets in `resources/`, routes in `routes/`, tests in `tests/`.
- `kmeans/`: analytics scripts and generated charts.
- `docs/`: reference material and diagrams. `docker-compose.yml` assembles Mongo, API, and bot for local stacks.

## Build, Test, and Development Commands
- `docker compose up --build`: builds Mongo, API, and bot containers.
- `cd whatsapp_bot && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python app.py`: runs the Flask bot on port 5000.
- `cd chat_bot_api && uvicorn main:app --reload --port 8000`: serves the API against your Mongo instance.
- `cd dashboard-emotitrack && composer install && npm install && php artisan serve`: boots Laravel (add `npm run dev` for live assets).
- `python kmeans/main.py`: generates clustering outputs using `scores.json`.

## Coding Style & Naming Conventions
- Python: four-space indentation, snake_case functions, CamelCase pydantic models, and type hints on public endpoints.
- PHP: align with PSR-12, keep controllers thin, and name Blade templates with kebab-case (`stress-report.blade.php`).
- Front-end assets belong in `resources/js` and `resources/css`; use PascalCase component names.
- All configuration lives in `.env` files; never commit secrets or sample student data.

## Testing Guidelines
- Use `php artisan test` for the dashboard; group new cases by route or feature.
- Add `tests/` folders beside Python modules and run with `pytest`; mock WhatsApp payloads and Mongo responses.
- Capture manual checks (bot transcripts, screenshots) in PRs until automated coverage exists, and store reusable fixtures in `docs/validation/`.

## Commit & Pull Request Guidelines
- Use `type (scope) : summary` as seen in history (e.g., `feature (webhook) : add score summary step`), keeping subjects under ~72 characters.
- Squash work-in-progress commits before raising a PR, document context plus test evidence, and call out schema or env var updates.
- Tag reviewers for each touched service (bot, API, dashboard) to ensure cross-team visibility.

## Security & Configuration Tips
- Populate module-specific `.env` files (`whatsapp_bot/.env`, `chat_bot_api/.env`, `dashboard-emotitrack/.env`) with the required tokens, `MONGO_URI`, and `APP_KEY`.
- Keep `.env`, SQLite files, and raw exports out of Git; sanitize analytics outputs before distributing.
- Rotate Meta API and Mongo credentials after demos and audit Docker volumes so sensitive data stays within approved directories.
