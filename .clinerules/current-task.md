# Current Task Record

## 2026-06-25 - Translate Rules To English + Add Task Memory Rule

- Status: done
- Goal: Convert all rule files to English and add a mandatory post-task update rule to prevent repeated work.
- Files changed:
  - .clinerules/rules/01-project-context.md
  - .clinerules/rules/02-system-architecture.md
  - .clinerules/rules/03-coding-standards.md
  - .clinerules/rules/04-ai-behavior-rules.md
  - .clinerules/rules/05-development-workflow.md
  - .clinerules/current-task.md
- Key decisions:
  - Keep rules compact for token efficiency.
  - Preserve all hard business constraints.
  - Define a single persistent task record file at .clinerules/current-task.md.
- Constraints handled:
  - Existing architecture and formulas were not changed.
  - UI language constraint remains Vietnamese.
- Do-not-repeat notes:
  - Do not reintroduce mixed Vietnamese/English rule text.
  - Do not omit post-task update in .clinerules/current-task.md after task completion.

## 2026-06-25 - Deployment Readiness Assessment

- Status: done
- Goal: Evaluate current project to identify what is needed to deploy to production and document actionable gaps.
- Files analyzed:
  - `config.py` — 3-tier config (dev/prod/test), ProdConfig has good security defaults (HTTPS, secure cookies).
  - `Dockerfile` — Gunicorn + non-root user + python:3.12-slim. OK as baseline.
  - `docker-compose.yml` — web service only, no DB service, no migration step.
  - `app/__init__.py` — App factory with `create_app()`, Limiter (Flask-Limiter) configured with memory storage.
  - `app/routes/auth.py` — Login with rate-limit (5/min), Vietnamese flash messages.
  - `app/routes/phoi.py` — Full phoi CRUD + confirm flow.
  - `app/routes/fuel.py` — Fuel log + price management.
  - `app/models.py` — All models, hard financial formulas intact.
  - `app/cli.py` — `seed-data` and `health` CLI commands.
  - `migrations/` — Alembic present with 2 migration versions.

### Deployment Readiness Summary

| Area                  | Status  | Details                                                                                    |
| --------------------- | ------- | ------------------------------------------------------------------------------------------ |
| **Docker**            | Partial | Dockerfile + compose exist but no `.dockerignore`, no DB service, no startup migration     |
| **Database**          | Partial | SQLite default, PostgreSQL in prod config — but compose doesn't include PostgreSQL service |
| **Secret management** | OK      | SECRET_KEY enforced via env in prod, compose uses `${SECRET_KEY:?err}`                     |
| **HTTPS/security**    | Partial | ProdConfig sets secure cookies, but no reverse proxy (nginx/Caddy) config provided         |
| **Static files**      | OK      | Flask serves static/, fine for small-scale internal app                                    |
| **Health check**      | Partial | CLI `flask health` exists but no HTTP `/health` endpoint for container orchestration       |
| **Logging**           | Partial | File-based logging to `/var/log/app/`, no log rotation configured                          |
| **Backup**            | Missing | No backup strategy for SQLite or PostgreSQL                                                |
| **CI/CD**             | Missing | No GitHub Actions, GitLab CI, or other pipeline                                            |
| **Env template**      | Missing | No `.env.example` for ops reference                                                        |

### What Must Be Done To Deploy (Priority Order)

#### 🔴 P1 - Critical (Blockers)

1. **Add `.dockerignore`** — exclude `.git`, `__pycache__`, `*.pyc`, `.clinerules`, `logs/*.log`, `migrations/__pycache__`, `venv/`, `.env`.
2. **Add DB service to `docker-compose.yml`** — either PostgreSQL service block or keep SQLite with proper volume mount. If keeping SQLite: ensure DB file lives in `./instance/` and volume is correct. If using PostgreSQL: add `db` service + healthcheck + env vars.
3. **Startup migration script** — create `docker-entrypoint.sh` that runs `flask db upgrade` before gunicorn. Update Dockerfile CMD to use entrypoint.
4. **HTTP health endpoint** — add `GET /health` returning JSON `{"status":"ok","db":"ok"}` for container orchestration (Docker healthcheck, k8s probes).
5. **`.env.example`** — document all required env vars: `FLASK_ENV`, `SECRET_KEY`, `DATABASE_URL`, `LOG_LEVEL`, `LOG_FILE`.

#### 🟡 P2 - Important (Production Quality)

6. **Log rotation** — configure `RotatingFileHandler` or use Docker logging driver. Current config writes to `/var/log/app/app.log` with no rotation → disk fill risk.
7. **Flask-Limiter storage** — currently defaults to in-memory (`MemoryStorage`). For multi-worker Gunicorn, switch to Redis or use `FixedWindowMemoryStorage` / env-based config. Memory storage doesn't share state across workers.
8. **Reverse proxy config** — provide nginx or Caddy config example for TLS termination + static file serving.
9. **Health check in docker-compose** — add `healthcheck` to web service using the new `/health` endpoint.
10. **Gunicorn config file** — extract gunicorn settings (workers, timeout, accesslog, errorlog) to `gunicorn.conf.py` for easier tuning.

#### 🟢 P3 - Nice To Have (Operational)

11. **Database backup script** — simple cron + `sqlite3 .dump` or `pg_dump` with retention.
12. **CI/CD pipeline** — GitHub Actions to build Docker image + run lint + run tests.
13. **Monitoring** — Sentry or basic Flask error alerting via email.
14. **Static asset versioning** — add cache-busting query strings for CSS/JS.

### Key Decisions Needed Before Deploy

- **SQLite vs PostgreSQL?** For single-server internal use with <50 concurrent users, SQLite with WAL mode is sufficient. PostgreSQL if multi-replica or >100 users expected.
- **Single container or multi-service?** Current Dockerfile puts all in one container (fine for simplicity). docker-compose could add PostgreSQL as separate service if needed.
- **Where to deploy?** Options: on-premise Linux server (Docker Compose), VPS (same), or cloud PaaS (needs Procfile/adaptation).

### Do-Not-Repeat Notes

- Do not remove the `SECRET_KEY` env enforcement in ProductionConfig.
- Do not change hard financial formulas (`balance`, `owner_profit`).
- Do not alter the phoi confirmation constraint (requires ≥1 attached fuel log).
- Do not add new dependencies unless truly needed (keep minimal).
- UI must remain Vietnamese.

## 2026-06-25 - Implement P1 Critical Deployment Blockers

- Status: done
- Goal: Implement all 5 P1 Critical items from the Deployment Readiness Assessment.
- Items completed:
  1. **`.dockerignore`** — Excludes `.git`, `__pycache__`, `*.pyc`, `.clinerules`, `logs/*.log`, `venv/`, `.env`, DB files.
  2. **DB service in `docker-compose.yml`** — Already properly configured with SQLite via `./instance:/app/instance` volume + `DATABASE_URL=sqlite:///instance/truck_management.db`. No changes needed.
  3. **`docker-entrypoint.sh`** — Runs `flask db upgrade` before exec gunicorn. Dockerfile updated to use `ENTRYPOINT` instead of `CMD`.
  4. **HTTP `/health` endpoint** — Existing endpoint enhanced with `db.session.execute(text('SELECT 1'))` returning `{"status":"ok","db":"ok"}` (200) or `{"status":"error","db":"unreachable"}` (503).
  5. **`.env.example`** — Documents FLASK_ENV, SECRET_KEY, DATABASE_URL, LOG_LEVEL, LOG_FILE, and PostgreSQL pool settings.
- Files changed:
  - `.dockerignore` (created)
  - `docker-entrypoint.sh` (created)
  - `Dockerfile` (updated CMD → ENTRYPOINT)
  - `app/__init__.py` (health endpoint with DB check, added `from sqlalchemy import text`)
  - `.env.example` (created)
- Key decisions:
  - Kept SQLite as default DB (single-server internal use); PostgreSQL supported via env override.
  - Entrypoint script is idempotent — safe to run `flask db upgrade` on every container start.
  - Health endpoint is unauthenticated for load balancer/orchestrator use.
- Constraints handled:
  - No new dependencies added.
  - No hard constraints broken.
- Do-not-repeat notes:
  - Do not revert Dockerfile CMD back to inline gunicorn; use ENTRYPOINT with the script.
  - Do not remove the `from sqlalchemy import text` import from `app/__init__.py`.
- Do not remove `.env.example` — ops reference needed for new deployments.

## 2026-06-25 - Prepare For Railway Deployment

- Status: done
- Goal: Fix 4 issues blocking Railway deployment and add config file.
- Issues identified + fixed:
  1. **PORT hardcoded 5000** — Railway injects dynamic `$PORT` env var. Fixed `docker-entrypoint.sh` to use `${PORT:-5000}`.
  2. **WeasyPrint missing system deps** — PDF generation (phiếu) needs cairo, pango, gdk-pixbuf, fonts. Added `apt-get install` block to Dockerfile.
  3. **`db.create_all()` conflicts with Alembic** — `create_app()` called both `db.create_all()` and `flask db upgrade`, causing "table already exists" on first deploy. Removed `db.create_all()`, kept only Alembic migration.
  4. **Missing PostgreSQL driver** — Railway provides PostgreSQL, but `requirements.txt` lacked `psycopg2-binary`. Added.
  5. **`railway.json`** — Created with Dockerfile builder + health check path + restart policy.
- Files changed:
  - `docker-entrypoint.sh` — `:5000` → `:${PORT:-5000}`
  - `Dockerfile` — Added WeasyPrint system deps (cairo, pango, gdk-pixbuf, fonts)
  - `app/__init__.py` — Removed `db.create_all()` call, comment updated
  - `requirements.txt` — Added `psycopg2-binary==2.9.10`
  - `railway.json` (created)
- Key decisions:
  - Kept `db.create_all()` removal safe: `docker-entrypoint.sh` already runs `flask db upgrade` which handles both fresh DB and migrations.
  - WeasyPrint deps pinned to minimal set (no recommends) to keep image small.
  - `PORT` fallback to 5000 preserves local dev compatibility.
- Constraints handled:
  - No hard financial constraints affected.
  - No new Flask/Python dependencies beyond `psycopg2-binary`.
  - UI remains Vietnamese.
- Do-not-repeat notes:
  - Do not re-add `db.create_all()` in `create_app()` — Alembic handles table creation.
  - Do not hardcode port 5000 in gunicorn bind — always use `${PORT:-5000}`.
  - Do not deploy without WeasyPrint system deps — PDF generation will crash silently.
  - Do not forget to set `FLASK_ENV=production` and `SECRET_KEY` on Railway.
  - Do not forget to add PostgreSQL service on Railway and run `flask seed-data` after first deploy.

## 2026-06-25 - Fix WeasyPrint Package Name For Debian Trixie

- Status: done
- Goal: Fix Railway build failure caused by incorrect `libgdk-pixbuf2.0-0` package name not existing in Debian Trixie.
- Root cause: Debian Trixie renamed the package from `libgdk-pixbuf2.0-0` to `libgdk-pixbuf-2.0-0`.
- Files changed:
  - `Dockerfile` — Changed `libgdk-pixbuf2.0-0` → `libgdk-pixbuf-2.0-0` in the `apt-get install` line.
- Key decisions:
  - No other package changes needed; all other deps exist in Trixie.
- Constraints handled:
  - No financial or business logic affected.
  - No dependencies added or removed.
- Do-not-repeat notes:
  - Do not use `libgdk-pixbuf2.0-0` — it does not exist in Debian Trixie. Use `libgdk-pixbuf-2.0-0`.

## 2026-06-25 - Fix WeasyPrint Package Name For Debian Trixie (Round 2)

- Status: done
- Goal: Fix Railway build failure — `libgdk-pixbuf-2.0-0` also does not exist in Debian Trixie.
- Root cause: The first fix (libgdk-pixbuf2.0-0 → libgdk-pixbuf-2.0-0) was still incorrect. Debian Trixie replaced `libgdk-pixbuf-2.0-0` with `libgdk-pixbuf-xlib-2.0-0`.
- Error message: `E: Package 'libgdk-pixbuf-2.0-0' has no installation candidate / However the following packages replace it: libgdk-pixbuf-xlib-2.0-0`
- Files changed:
  - `Dockerfile` — Changed `libgdk-pixbuf-2.0-0` → `libgdk-pixbuf-xlib-2.0-0` on line 11.
- Key decisions:
  - `libgdk-pixbuf-xlib-2.0-0` is the correct replacement package for Debian Trixie.
- Constraints handled:
  - No financial or business logic affected.
  - No dependencies added or removed.
- Do-not-repeat notes:
  - Do not use `libgdk-pixbuf2.0-0` or `libgdk-pixbuf-2.0-0` — neither exists in Debian Trixie. Use `libgdk-pixbuf-xlib-2.0-0`.
