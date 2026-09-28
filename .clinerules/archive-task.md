# Archived Task Records

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
- Files analyzed: config.py, Dockerfile, docker-compose.yml, app/**init**.py, app/routes/auth.py, app/routes/phoi.py, app/routes/fuel.py, app/models.py, app/cli.py, migrations/
- Key decisions: SQLite sufficient for <50 users; 3 priority tiers defined (P1/P2/P3).
- Do-not-repeat notes:
  - Do not remove the SECRET_KEY env enforcement in ProductionConfig.
  - Do not change hard financial formulas (balance, owner_profit).
  - Do not alter the phoi confirmation constraint (requires ≥1 attached fuel log).
  - Do not add new dependencies unless truly needed (keep minimal).
  - UI must remain Vietnamese.

## 2026-06-25 - Implement P1 Critical Deployment Blockers

- Status: done
- Goal: Implement all 5 P1 Critical items from the Deployment Readiness Assessment.
- Files changed: .dockerignore (created), docker-entrypoint.sh (created), Dockerfile (CMD→ENTRYPOINT), app/**init**.py (health endpoint + sqlalchemy.text import), .env.example (created)
- Key decisions: Kept SQLite as default; entrypoint script is idempotent; health endpoint unauthenticated.
- Do-not-repeat notes:
  - Do not revert Dockerfile CMD back to inline gunicorn; use ENTRYPOINT with the script.
  - Do not remove the `from sqlalchemy import text` import from `app/__init__.py`.
  - Do not remove `.env.example` — ops reference needed for new deployments.

## 2026-06-25 - Prepare For Railway Deployment

- Status: done
- Goal: Fix 4 issues blocking Railway deployment and add config file.
- Issues fixed: PORT hardcoded 5000, WeasyPrint missing system deps, db.create_all() conflicts with Alembic, missing PostgreSQL driver.
- Files changed: docker-entrypoint.sh (PORT), Dockerfile (WeasyPrint deps), app/**init**.py (removed db.create_all()), requirements.txt (added psycopg2-binary), railway.json (created)
- Do-not-repeat notes:
  - Do not re-add `db.create_all()` in `create_app()` — Alembic handles table creation.
  - Do not hardcode port 5000 in gunicorn bind — always use `${PORT:-5000}`.
  - Do not deploy without WeasyPrint system deps — PDF generation will crash silently.
  - Do not forget to set FLASK_ENV=production and SECRET_KEY on Railway.
  - Do not forget to add PostgreSQL service on Railway and run `flask seed-data` after first deploy.

## 2026-06-25 - Fix WeasyPrint Package Name For Debian Trixie

- Status: done
- Goal: Fix Railway build failure — libgdk-pixbuf2.0-0 not found in Debian Trixie.
- Root cause: Debian Trixie renamed the package from libgdk-pixbuf2.0-0 to libgdk-pixbuf-2.0-0.
- Files changed: Dockerfile — libgdk-pixbuf2.0-0 → libgdk-pixbuf-2.0-0.
- Do-not-repeat notes: Do not use libgdk-pixbuf2.0-0 — use libgdk-pixbuf-2.0-0.

## 2026-06-25 - Fix WeasyPrint Package Name For Debian Trixie (Round 2)

- Status: done
- Goal: Fix Railway build failure — libgdk-pixbuf-2.0-0 also not found in Debian Trixie.
- Root cause: Debian Trixie further renamed to libgdk-pixbuf-xlib-2.0-0.
- Files changed: Dockerfile — libgdk-pixbuf-2.0-0 → libgdk-pixbuf-xlib-2.0-0.
- Do-not-repeat notes: Do not use libgdk-pixbuf2.0-0 or libgdk-pixbuf-2.0-0 — use libgdk-pixbuf-xlib-2.0-0.

## 2026-06-25 - Fix App Deployment Crash (SECRET_KEY Validation In Class Body)

- Status: done
- Goal: Fix app failing to boot — docker-entrypoint.sh looped forever because config.py raised RuntimeError at import time.
- Root cause: ProductionConfig class body ran SECRET_KEY validation on every Python import, regardless of FLASK_ENV.
- Files changed: config.py — moved SECRET_KEY validation from class body into get_config() function.
- Key decisions: Validation logic preserved and made conditional on env == 'production'.
- Do-not-repeat notes:
  - Do not revert class-body validation — will crash on import in any environment.
