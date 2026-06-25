# 03 - Coding Standards (Compact)

## Naming

- Python file/folder/var/function/column: `snake_case`.
- Class: `PascalCase`.
- Constant: `UPPER_SNAKE_CASE`.
- Route URL: `kebab-case`.
- Template: `templates/<feature>/<action>.html`.

## Imports

Use 3 import groups, separated by one blank line:

1. stdlib
2. third-party
3. app-local (`app.*`)

## Route Error Pattern (Required)

- Use `try/except` in routes when writing to DB.
- In `except`: always call `db.session.rollback()` before flash/redirect.
- Flash errors in Vietnamese; never silently swallow errors.
- For not found: prefer `get_or_404`.

## Style

- Prefer SQLAlchemy ORM; avoid raw SQL unless necessary.
- Prefer f-strings.
- Use concise boolean checks: `if flag`, `if not items`.
- New code should include type hints.
- Add comments only to explain non-obvious decisions (the why).

## Limits

- File <= 500 lines.
- Function <= 50 lines.
- Nesting <= 3.
- Template <= 200 lines.
- Line length <= 120 characters.

## Logging

- Use `app.logger`.
- `error` for exceptions, `warning` for validation, `info` for key business actions.
- Do not use `print()` in production code.
