# Current Task

## Active task
- None.

## Recent completed
- **2026-10-08 — Whole-phơi toll confirmation:** In `app/routes/phoi.py` and `app/templates/phoi/confirm.html`, manager/admin must explicitly choose whether the full phơi incurred tolls when confirming; a positive single total is required when incurred, otherwise the manager records no toll. The `toll_fee` remains an owner-paid expense, so existing profit and driver-settlement formulas are unchanged. Validated with `compileall`, application import, no editor errors, and mock-based checks for both toll decisions; no migration or persisted-data change. Do not move this decision back to driver creation/submission or add tolls to driver balance.
- **2026-10-08 — Required-field popup:** Lists visible Vietnamese labels in form order and expands established collapsed phơi sections containing missing fields. Client-side usability only; server validation remains authoritative.
- **2026-10-07 — Post-confirm porter fee display:** Shows non-zero return porter fees as driver advances in review/print; print includes owner/driver signatures; financial display remains manager/admin-only.
- **2026-10-07 — Phơi cancellation and fuel release:** Manager/admin cancel draft records only; retain evidence/history; released fuel requires explicit same-truck reallocation.
- **2026-10-06 — Fuel correction and confirmation controls:** Eligible pre-confirmed fuel can be corrected/deleted; confirmed-linked fuel stays immutable; quick-confirm decisions are per trip.

## Persistent safeguards
- Preserve financial source of truth: `Phoi.balance() = driver_out_of_pocket_expenses() + driver_wage - total_revenue_collected()` and `Phoi.owner_profit() = total_revenue_full() - total_expenses() - driver_wage`.
- A phơi needs at least one fuel log before confirmation. Confirmed phơi and their fuel logs are immutable.
- A driver creates a fuel log only for an in-progress phơi of the same truck. New fuel links exactly one phơi; legacy multi-links retain proportional expense allocation.
- Only `draft` phơi blocks a new phơi for the same truck; `submitted` does not. Cancellation is manager/admin-only and draft-only.
- Never automatically reassign fuel released by cancellation; manager/admin must explicitly select a same-truck replacement phơi.
- Manager-direct collections reduce per-customer debt, but must not enter driver settlement or `total_revenue_collected()`.
- Customer debt uses only confirmed trips and aggregates outbound/return trips by their own customer.
- Drivers must not see revenue or owner profit, including printed layouts; settlement visibility remains.
- Per-phơi KM starts at zero; require positive end KM on submission; do not advance `Truck.current_km`.
- Porter fees are both expenses and driver advances; do not add them to driver-collected revenue.
- Preserve Vietnamese UI/error text, Flask MVC/thin routes/model business logic, soft deletion, and unique `User.current_truck_id`.
- Keep one Alembic head. Add merge revisions for branches; never rewrite deployed migration history.
- Before schema, persisted-data, financial, role/access, confirmation, fuel-association, migration, or deployment changes: explain risk, alternatives, validation/rollback plan, and obtain approval.

## History
- Compact archives: `.clinerules/task-history/2026-10.md`, `.clinerules/task-history/2026-06.md`.
- Older detailed records: `.clinerules/archive-task.md`.
- Full historical detail remains recoverable from Git history.
