# 04 - AI Behavior Rules (Compact)

## Must

- Read relevant files before editing; never assume.
- Follow existing patterns (route/model/template/error handling).
- Create a short plan before multi-file changes.
- Prefer the smallest possible change.
- Keep current architecture: business logic in models, thin routes, Vietnamese UI.
- If schema changes are required: create migration.
- After task completion, update the current task record to capture what was done and prevent repeating the same work later.

## Must Not

- Do not refactor working code unless the task requires it.
- Do not overengineer (new service layer, async, unnecessary abstraction).
- Do not add dependencies if stdlib/Flask/SQLAlchemy can solve it.
- Do not break existing APIs (URL, method, template var names, critical signatures).
- Do not create new files if logic can live in existing feature files.

## Decision Order

1. Correctness
2. Simplicity
3. Maintainability
4. Scalability
5. Performance

## Hard Constraints (Do Not Break)

- `balance = total_expenses + driver_wage - revenue_collected`
- `owner_profit = revenue_full - total_expenses - driver_wage`
- Phoi confirmation requires at least one attached fuel log.
- Fuel log creation requires at least one in-progress phoi for the same truck.
- `current_truck_id` is unique in users.
- Trucks/customers use soft delete (`is_active=False`).
- UI text must be Vietnamese.

## High-Risk Files

- `app/models.py`: financial formulas.
- `app/routes/phoi.py`: create -> submit -> confirm -> print flow.
- `app/routes/fuel.py`: fuel-phoi constraints.
- `app/routes/auth.py`: login security.
