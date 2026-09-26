# PeechaERP

Persian (RTL) multi-company ERP. User communicates in Persian; reply in Persian.

## Layout
- `src/peecha/` — PySide6 desktop. Business logic in `services/*.py`, UI in `ui/screens/*.py`, models in `db/models/`.
- `src/peecha_api/` — FastAPI layer for mobile (`routers/`, `schemas.py`). Thin: reuse desktop services, no duplicated logic.
- `mobile/` — React Native + Expo (SDK 57, React 19) "Peecha Field Sales". Talks only to `peecha_api`. Offline-first: writes go through `sync/offlineQueue.ts` → `sync/syncEngine.ts`.
- `db/schema/NNN_*.sql` — numbered migrations, applied by `schema_bootstrap.apply_pending_schema_files()`.
- Version string: `src/peecha/version.py` (`APP_VERSION = "R###"`), bumped every delivery.

## Conventions
- Dates shown to users are always Jalali: desktop `peecha.numerals.format_jalali_date`, mobile `src/jalali.ts`. Never `isoformat()` in UI.
- Mobile UI: RTL, Vazirmatn via `theme/typography` for every `Text`/`TextInput`, no emoji/icons, use themed components from `src/components`. Normalize Persian digits (`format.toAsciiDigits`) before math.
- Items that are variant parents are never transactable: use `list_items(..., transactable_only=True)` for pickers.
- Mobile 4xx responses drop the queued action permanently — never reject a real sale for server-config gaps; degrade to a warning.
- Keep code comments short; only for non-obvious reasons.

## Verify (run only what the change touches)
- Postgres: `service postgresql start`; user/pass `peecha`/`peecha`, host `localhost`.
- Integration tests: `tests/integration/run_all.sh [r209]` (filter by release number; it recreates each script's DB). Add a `test_rNNN_*.py` there for each backend change.
- Integration script pattern: `apply_pending_schema_files(get_engine())` → `bootstrap_system("admin", ..., "secret123", ...)` → create COA accounts/mappings via services → `fastapi.testclient.TestClient(peecha_api.main.app)`.
- Desktop screens: instantiate with `QT_QPA_PLATFORM=offscreen` and call `.refresh()`.
- Mobile: `cd mobile && npm run typecheck && npm test`; bundle check `npx expo export --platform android --output-dir <tmp>`.
- `npx expo install` is blocked by the network proxy; use `npm install <pkg>@sdk-57`.

## Delivery
Bump `APP_VERSION`, `git add` explicit paths (never `-A`), commit with a Persian message, push to the working branch, then `git archive --format=zip -o PeechaERP-R###.zip HEAD` and send it with install steps (restart uvicorn; `npm install` if mobile deps changed; `npx expo start -c`).
