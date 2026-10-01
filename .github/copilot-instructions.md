# Truck Management – Stability-First Instructions

## Mandatory workflow

Before editing, inspect the relevant route, model, template, migration, and their call sites. State the affected flow, compatibility impact, and validation plan. Make the smallest compatible change; do not refactor working code unless explicitly required.

Treat these flows as regression-sensitive: authentication and roles; driver–truck assignment; phoi create → submit → confirm → print; fuel-log ↔ phoi linking; financial calculations; attachment uploads; schema migrations; deployment.

## Stop before high-risk changes

Do **not** edit until the user approves when a proposed change can alter persisted data/schema, financial results, roles/access, confirmation eligibility, existing URLs/forms/template context, fuel associations, migrations, or production/deployment behavior. Explain the affected flow, risk level, likely regression, safer alternatives, and validation/rollback plan first. Clarify ambiguous requirements before editing.

## Invariants

- Preserve the current model implementations as the financial source of truth: `Phoi.balance()` is `driver_out_of_pocket_expenses() + driver_wage - total_revenue_collected()`; `Phoi.owner_profit()` is `total_revenue_full() - total_expenses() - driver_wage`.
- A phoi can be confirmed only with at least one attached fuel log.
- A driver can create a fuel log only when an in-progress phoi exists for the same truck.
- `User.current_truck_id` remains unique; trucks and customers use soft deletion (`is_active=False`).
- Keep the Flask MVC architecture, thin routes, model business logic, and Vietnamese UI/error text.

## Completion requirements

Validate the changed flow and relevant edge cases without launching the development server unless requested. Report files changed and checks performed. Update `.clinerules/current-task.md` for every completed task with date, scope, files, decisions, validation, risks/constraints, and do-not-repeat notes. This is a required project record but is not technically auto-generated; keep it current manually as part of each task.
