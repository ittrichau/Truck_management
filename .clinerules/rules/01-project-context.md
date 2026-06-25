# 01 - Project Context (Compact)

## Product

- App: Truck Management (Flask monolith).
- Domain: trip sheets (phoi), fuel, drivers, trucks, customers.
- UI: server-rendered Jinja2, Vietnamese language.

## Users

- Driver: create/edit own trip sheets, log fuel.
- Manager: review/confirm trip sheets, view operations data.
- Admin: full access (users, fuel prices, system-wide data).

## Core Business

- Phoi code format: `P-YYYYMMDD-NNN`.
- Main calculations: revenue, expenses, driver wage, settlement balance, owner profit.
- Fuel logs are linked to trucks and phoi.
- Truck/customer records use soft delete (`is_active=False`).
- Role-based access via Flask-Login.

## Technical Constraints

- Python + Flask + SQLAlchemy + SQLite (default).
- Simple run flow: `python run.py` or Docker.
- Prefer minimal dependencies and single-developer maintainability.

## Out Of Scope

- Multi-tenant, real-time features, native mobile app, external API integrations, multilingual UI.
