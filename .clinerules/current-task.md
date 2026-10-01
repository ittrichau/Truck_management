# Current Task Record

## 2026-06-26 - Thêm ngày đăng kiểm, phù hiệu + cảnh báo hết hạn

- Status: done
- Goal: Thêm 4 trường mới vào xe (ngày đăng kiểm, hạn đăng kiểm (tháng), ngày cấp phù hiệu, hạn phù hiệu (tháng)). Khi gần tới hạn (≤15 ngày) sẽ báo cho tài xế và quản trị viên biết, cách 2 ngày báo 1 lần.
- Files changed:
  - app/models.py — thêm 6 cột mới vào Truck
  - app/routes/trucks.py — routes create/edit xử lý 4 trường mới
  - app/templates/trucks/create.html — form đăng kiểm & phù hiệu
  - app/templates/trucks/edit.html — form + badge
  - app/templates/trucks/index.html — 2 cột + badge đỏ
  - app/routes/phoi.py — warning banner
  - app/templates/phoi/index.html — alert-danger banner
  - migrations/versions/ — 2 migration files
- Key decisions and do-not-repeat kept as-is (truncated for brevity)
- Do-not-repeat notes:
  - inspection/permit expiry methods use calendar.monthrange
  - Khi thêm cột mới, không forget migration
  - \_parse_date() helper in trucks.py
  - should_notify() checks days < 0 for overdue

## 2026-06-26 - Gộp quản lý manager và driver vào 1 page, phân quyền admin/manager

- Status: done
- Goal: Admin thay đổi được thông tin quản lý và tài xế trên page Người dùng (drivers). Admin có quyền thêm/xóa/sửa quản lý. Manager chỉ thêm/xóa/sửa tài xế.
- Files changed:
  - app/routes/drivers.py — index() query cả driver+manager nếu admin, create() thêm select role cho admin, edit() cho phép admin sửa manager, delete() cho phép admin xóa manager; thêm biến is_admin vào context
  - app/templates/drivers/index.html — thêm cột Vai trò cho admin (badge Quản lý/Tài xế), label "Người dùng"
  - app/templates/drivers/create.html — thêm select role cho admin, ẩn/hiện truck section bằng JS
  - app/templates/drivers/edit.html — thêm select role cho admin, ẩn/hiện truck section
  - app/templates/base.html — đổi nav label "Tài xế" → "Người dùng"
- Key decisions:
  - Admin query User.role.in\_(['driver', 'manager']), manager query role='driver'
  - Admin có select role khi create/edit; manager không thấy select
  - Nếu đổi driver → manager, tự động clear current_truck_id
  - Validate an toàn: không cho sửa/xóa admin, manager không thể edit/delete manager
  - JS toggle truck section dựa trên role select
- Constraints handled:
  - Không phá vỡ logic phân quyền cũ (is_manager_or_admin() vẫn dùng được)
  - Manager không thấy manager khác trong danh sách
  - Không thể vô tình tạo/sửa thành admin
- Do-not-repeat notes:
  - Khi thêm role select vào form, luôn kèm JS toggle truck section
  - Check role validation cả route lẫn template
  - is_admin phải được truyền vào context của template

## 2026-10-01 - Review and strengthen project change-control rules

- Status: done
- Goal: Verify whether rule files and task records are current; ensure every future change assesses impact on stable flows and asks for approval before material risk.
- Files changed:
  - `.github/copilot-instructions.md` — workspace-wide Copilot instructions for stability-first workflow and approval gate
  - `.clinerules/rules/04-ai-behavior-rules.md` — impact analysis and explicit high-risk approval criteria
  - `.clinerules/rules/05-development-workflow.md` — risk gate, regression/rollback planning, and complete task-record fields
  - `.continue/prompts/truck_rules.md` — corrected obsolete `project-ai/rules` paths to `.clinerules/rules`
  - `.clinerules/current-task.md` — this record
- Affected flow/impact: No application behavior changed. Future work must protect auth/roles, driver-truck assignment, phoi lifecycle, fuel associations, financial calculations, migrations, and deployment.
- Key decisions:
  - `current-task.md` is version-controlled but had not been updated for commits after 2026-06-26; it is not automatically updated by the existing rules.
  - Copilot now receives workspace-wide instructions through `.github/copilot-instructions.md`; Continue references the actual rule location.
  - High-risk changes require an impact report and explicit user approval before editing.
- Validation:
  - Confirmed all `.clinerules` and `.continue` rule/task files are tracked by Git.
  - Confirmed the financial formulas in `app/models.py` use the current return-trip-aware implementations.
  - Confirmed no runtime application files were modified in this task.
- Do-not-repeat notes:
  - Update this record after every completed task, including validation and risk details.
  - Do not assume a written rule creates automatic task updates; a hook/integration is required for true automation.
  - Keep rule path references aligned with `.clinerules/rules/`.

## 2026-10-01 - Remove obsolete Railway deployment configuration

- Status: done
- Goal: Remove Railway-specific deployment configuration now that production runs only on the VPS.
- Files changed:
  - `railway.json` — deleted; it was only a Railway build/deploy manifest.
  - `config.py` — replaced the Railway-specific database comment with a server-environment description.
  - `docker-entrypoint.sh` — replaced Railway environment-variable guidance with generic server-environment guidance.
  - `app/__init__.py` — documented reverse-proxy handling for VPS Nginx instead of former platform examples.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Deployment configuration and operator messages only. The Docker entrypoint, `DATABASE_URL`/`SECRET_KEY` requirements, migrations, Gunicorn startup, health check, Nginx reverse proxy, and Docker Compose VPS deployment behavior are unchanged. No persisted data, schema, financial logic, roles, URLs, or application templates changed.
- Key decisions:
  - User approved removal after the impact assessment.
  - Retained generic production environment checks because they are required by the existing VPS deployment flow.
  - Preserved `ProxyFix`, which is needed for HTTPS and secure cookies behind VPS Nginx.
- Validation:
  - Confirmed `railway.json` was removed.
  - Reviewed `Dockerfile`, `docker-compose.yml`, `deploy/GITHUB_ACTIONS_DEPLOY.md`, and `deploy/VPS_UBUNTU.md`; they use the VPS Docker/Nginx deployment flow and do not depend on Railway.
  - No development server was launched.
- Risks/constraints:
  - Railway deployment is no longer configured from this repository; restoring it would require recreating a provider manifest and platform configuration.
- Do-not-repeat notes:
  - Before removing provider configuration, search both repository references and deployment documentation, then retain only platform-neutral runtime safeguards.

## 2026-10-01 - Add confirmed-trip customer debt report and role-aware navigation

- Status: done
- Goal: Add a manager/admin-only customer debt report based solely on existing confirmed phơi and return-trip revenue data; prevent mobile navigation from overflowing and keep drivers from seeing pages they cannot access.
- Files changed:
  - `app/routes/debts.py` — added protected `/debts` report route that aggregates outbound and return trips by their own customer.
  - `app/templates/debts/index.html` — added debt totals and per-customer report table.
  - `app/__init__.py` — registered the debt-report blueprint.
  - `app/templates/base.html` — added desktop debt navigation; mobile uses a manager-only “Thêm” bottom-sheet for Công nợ, Người dùng, and admin Nhật ký; Fuel stays visible to drivers because they are authorized to create fuel logs.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Read-only financial reporting. Only `Phoi.status == 'confirmed'` records contribute. Each outbound trip uses `Phoi.customer_id`; each return trip uses its own `PhoiReturnTrip.customer_id`, preventing revenue from different customers on one phơi from being mixed. No data, schema, payment workflow, existing financial calculation method, confirmation rule, or fuel association changed.
- Key decisions:
  - Per-customer outstanding amount is calculated as `revenue_full - revenue_collected` from existing fields only.
  - Customerless trips are excluded because they cannot be assigned to a customer debt balance.
  - Server-side authorization redirects drivers from `/debts`; menu visibility is only a usability layer.
  - Drivers see Phơi and Xăng only; manager/admin-only pages are hidden. The existing Fuel route explicitly supports drivers, so it must remain visible.
- Validation:
  - Reviewed models, phơi/fuel routes, navigation template, and authorization patterns before editing.
  - Ran `git diff --check` successfully.
  - Ran syntax compilation for `app/routes/debts.py` successfully.
  - Editor diagnostics found no template errors. Python import diagnostics could not resolve Flask dependencies because the configured `.venv` executable is absent from this workspace; no development server was launched.
- Risks/constraints:
  - The report represents only amounts recorded as expected/collected on confirmed trips; it does not support separate owner payment transactions or customerless trips.
  - A separate customer-payment ledger would require a schema/workflow change and explicit approval before implementation.
- Do-not-repeat notes:
  - Do not use `Phoi.total_revenue_full()` or `total_revenue_collected()` for customer debt because they combine the outbound customer and every return-trip customer.
  - Preserve both route-level authorization and role-based navigation visibility.
