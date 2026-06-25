# 02 - System Architecture (Compact)

## Pattern

- Monolithic MVC, server-rendered.
- No SPA, no service layer, no async.

## Source Of Truth

- Models + business logic: `app/models.py`.
- HTTP/controller: `app/routes/*.py` (one blueprint per feature).
- View: `app/templates/<feature>/*.html`.
- Schema changes: Alembic in `migrations/versions/`.
- AI rules: `.clinerules/rules/`.

## Dependency Direction

`routes -> models -> db` and `routes -> templates`.

Rules:

- Routes must not contain complex business logic.
- Templates must not query DB.
- Models must not depend on request/session.
- No circular dependencies.

## Request Flow

1. Route receives request, performs auth/role checks.
2. Parse input and call model methods.
3. `db.session.add/commit`.
4. On error: `rollback` + Vietnamese flash message.
5. Return `render_template` or `redirect`.

## Structural Rules

- Keep each feature in existing route files (auth, phoi, fuel, trucks, customers, drivers).
- Template names follow action style: `index/create/edit/detail/...`.
- Reuse existing helpers/model methods before adding new ones.
