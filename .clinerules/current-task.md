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

## 2026-10-01 - Enforce one active phơi per truck and KM correction alerts

- Status: done
- Goal: Let drivers adjust an auto-filled KM đầu, create a prominent activity-log warning for a driver correction greater than 50 km, and prevent a truck from having more than one active phơi.
- Files changed:
  - `app/routes/phoi.py` — server-side active-phơi validation and KM-difference alert creation on create/edit.
  - `app/templates/phoi/create.html` — KM đầu remains auto-filled but is editable and explains the alert threshold.
  - `app/routes/activity_logs.py` — permits managers and admins to view logs and exposes the `ALERT` filter.
  - `app/templates/activity_logs/index.html` — highlights KM alerts in red with a warning badge.
  - `app/templates/base.html` — exposes Nhật ký to managers on desktop and mobile navigation.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: `Truck.current_km` is the create-time KM baseline. A truck is blocked from creating another phơi while one is `draft` or `submitted`; it becomes available only once the existing phơi is confirmed. The existing rule that KM cuối advances `Truck.current_km` on save is retained.
- Key decisions:
  - Only driver-initiated KM đầu changes create a warning; manager/admin corrections do not.
  - A correction with an absolute difference strictly greater than 50 km creates an `ActivityLog` entry with action `ALERT`, phơi number, truck plate, old/new KM, and difference.
  - Existing `ActivityLog` storage is reused; no schema migration is required.
- Validation:
  - Ran `python -m compileall -q app` successfully using the configured virtual environment.
  - Ran `git diff --check` successfully.
  - Editor diagnostics report no errors in `app/routes/phoi.py` or `app/routes/activity_logs.py`.
  - No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - The one-active-phơi constraint is enforced in application code rather than a database partial unique constraint, so simultaneous requests can theoretically race; normal UI use is protected.
  - The alert is visible in Nhật ký to manager/admin users; it is not a push or email notification.
- Do-not-repeat notes:
  - Keep the one-active-phơi check in both create and edit, excluding the edited phơi itself.
  - Keep the >50 km comparison server-side and store alert details before the phơi transaction commits.

## 2026-10-01 - Allow next phơi after driver submission

- Status: done
- Goal: Permit a driver to begin the next trip for a truck once the prior phơi is chốt (`submitted`), while still preventing two concurrently in-progress phơi.
- Files changed:
  - `app/routes/phoi.py` — changed the server-side per-truck blocker to consider only `draft` phơi and updated its Vietnamese validation message.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: A `draft` phơi continues to block another phơi for the same truck. Submitting it changes its status to `submitted`, which releases creation of the next phơi while the prior record remains available for manager/admin final confirmation. Multiple `submitted` phơi for one truck are now permitted, as explicitly approved. `Truck.current_km`, fuel-log attachment eligibility, confirmation requirements, and financial calculations are unchanged.
- Key decisions:
  - The create and edit routes retain the same shared validation helper, so the rule is applied consistently.
  - Truck display status remains `in_trip` while a draft or submitted phơi exists; this is display/status behavior only and does not block the approved next-phơi creation flow.
- Validation:
  - Reviewed the create/edit call sites, submit/confirm lifecycle, truck status updates, and fuel-log selection behavior.
  - Ran `python -m compileall -q app` successfully using the configured virtual environment.
  - Ran `git diff --check` successfully; editor diagnostics report no errors in `app/routes/phoi.py`.
  - No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - Multiple submitted phơi require manager/admin confirmation to be selected and completed deliberately; no automatic confirmation ordering was added.
  - The application-level draft check retains its existing theoretical concurrent-request race condition.
- Do-not-repeat notes:
  - Keep the per-truck blocker scoped to `draft`; do not re-add `submitted` without revisiting the approved sequential-trip workflow.

## 2026-10-01 - Owner reconciliation for submitted phơi

- Status: done
- Goal: Treat driver input as operational data collection while allowing manager/admin (owner) to correct every phơi detail and finalize unknown per-ton prices before final confirmation.
- Files changed:
  - `app/routes/phoi.py` — permits manager/admin edits and attachment changes for `submitted` phơi; keeps drivers limited to their own `draft` phơi; supports incomplete per-ton pricing during data entry; requires complete positive revenue or tonnage/price data only at confirmation; records manager reconciliation updates in `ActivityLog`.
  - `app/templates/phoi/detail.html` — exposes the owner reconciliation action and evidence controls for submitted phơi, and explains the review stage.
  - `app/templates/phoi/edit.html` — identifies submitted edits as the final owner reconciliation step.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: `draft → submitted → confirmed` is retained without a schema migration. A driver can submit evidence even when an agreed per-ton price is unavailable. Manager/admin may revise trip, driver/truck, operational, financial, and evidence details while submitted. `confirmed` records remain locked. Existing `Phoi.balance()` and `Phoi.owner_profit()` formulas are unchanged.
- Key decisions:
  - Confirmation blocks a fixed-price trip with revenue ≤ 0 and a per-ton trip without positive tonnage and price; this applies to outbound and every return trip.
  - A submitted phơi update creates an `UPDATE` activity-log item; no new log table or migration is needed.
  - Managers may delete as well as upload evidence during reconciliation so they can fully correct the record before locking it.
- Validation:
  - Reviewed phơi create/edit/submit/confirm routes, attachment permissions, financial model formulas, and detail/edit templates before changing behavior.
  - Ran `python -m compileall -q app` successfully using the configured virtual environment.
  - Ran `git diff --check` successfully; Git reported only existing line-ending conversion warnings.
  - Editor diagnostics report no errors in the changed route and templates. No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - Fixed-price revenue may still be entered as zero until final confirmation, intentionally allowing drivers to submit a record when the price is unknown.
  - The current form permits a manager to edit all submitted fields in one save; the activity log records the reconciliation event but not a field-by-field audit diff.
- Do-not-repeat notes:
  - Keep financial completeness enforcement in the confirmation route, not only JavaScript or the submitted form.
  - Do not alter the established balance and owner-profit formulas while changing reconciliation permissions.

## 2026-10-01 - Track manager direct collections in customer debt

- Status: done
- Goal: Let manager/admin distinguish customer money received directly by management from money held by the driver, then calculate confirmed-trip customer debt from both receipt sources.
- Files changed:
  - `app/models.py` — added `manager_revenue_collected` to outbound `Phoi` and each `PhoiReturnTrip`.
  - `migrations/versions/c6d7e8f9a0b1_add_manager_collections_to_trip_revenue.py` — adds the non-null numeric columns with a zero default; downgrade removes them.
  - `app/routes/phoi.py` — saves direct-management collections during manager reconciliation and blocks confirmation when a trip's driver plus manager collections are negative or exceed its full revenue.
  - `app/templates/phoi/edit.html` — exposes manager collection fields and a convenience checkbox that fills the remaining amount after driver-collected cash; includes dynamically added return trips.
  - `app/routes/debts.py` and `app/templates/debts/index.html` — count both driver and manager collections as customer payments, while retaining per-customer outbound/return-trip aggregation.
  - `app/templates/phoi/detail.html` — shows the direct-management receipt total separately from driver-held cash.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: During submitted-phơi owner reconciliation, driver-collected cash remains the sole input to `Phoi.balance()`. Direct manager/customer payments reduce the relevant customer's confirmed debt but do not change driver settlement or owner-profit. Existing rows begin with a direct-management receipt of zero, preserving their previous debt result.
- Key decisions:
  - The checkbox means management received the remaining revenue after money already collected by the driver; partial direct payments remain available through the amount field.
  - The server, rather than only JavaScript, rejects a negative receipt or combined driver and manager receipts above full revenue for each outbound or return trip.
  - Debt calculation remains per trip/customer; never combine mixed-customer phơi totals.
- Validation:
  - Ran `python -m compileall -q app migrations` successfully using the configured virtual environment.
  - Ran `git diff --check` successfully; output only reports existing LF-to-CRLF conversion warnings.
  - Ran an in-memory validation check: collection $20 + $80 against revenue $100 passes; $20 + $81 is rejected with the expected Vietnamese message.
  - Editor diagnostics report no errors in changed models, routes, templates, or migration. No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - The fields represent accumulated receipt totals entered at reconciliation, not a dated payment ledger; later payment events still require a separate ledger/workflow.
  - Deployments must run the new Alembic migration before using owner-receipt fields.
- Do-not-repeat notes:
  - Do not include manager direct receipts in `total_revenue_collected()` or `balance()`; that method is strictly for money the driver holds.
  - Keep the confirmation upper-bound check for every return trip as well as the outbound trip.

## 2026-10-01 - Streamline manager collection confirmation

- Status: done
- Goal: Reduce manager reconciliation work by moving direct-customer-collection choices out of the long phơi edit form into a short final confirmation screen.
- Files changed:
  - `app/routes/phoi.py` — `confirm` now renders a GET confirmation page and, on POST, applies each outbound/return-trip collection choice before running existing financial validation. Normal edit saves preserve existing direct-manager receipt totals.
  - `app/templates/phoi/confirm.html` — added the quick confirmation screen with default “Chưa thu”, per-trip “Đã thu đủ”, optional partial amount, and “Đã thu đủ tất cả”.
  - `app/templates/phoi/detail.html` — replaces direct POST confirmation with the quick-confirmation action and explains the streamlined flow.
  - `app/templates/phoi/edit.html` — removes manager receipt controls from the long reconciliation form; it now directs managers to confirmation for that decision.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Manager/admin first corrects only operational/financial source data if needed, then opens `Xác nhận nhanh`. Unpaid is the default and creates debt; full collection automatically records only the amount remaining after driver cash; partial collection exposes a single amount input. Driver balance, owner profit, customer debt aggregation, schema, and migration remain unchanged.
- Key decisions:
  - All confirmation receipt choices are applied server-side; the existing per-trip no-negative/no-over-collection validation remains authoritative.
  - A normal submitted-phơi edit does not erase direct-manager collections already selected in an earlier confirmation attempt.
  - The route accepts GET only for manager/admin on a submitted phơi and POST performs the final state transition.
- Validation:
  - Ran `python -m compileall -q app migrations` successfully using the configured virtual environment.
  - Ran `git diff --check` successfully; only existing LF-to-CRLF conversion warnings were reported.
  - Verified in memory: a $100$ trip with driver receipt $20$ passes for manager receipt $0$ (unpaid) and $80$ (paid in full), and rejects $81$ as over-collection.
  - Editor diagnostics report no errors in the modified route or templates. No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - “Đã thu đủ tất cả” is intentionally explicit; it should only be used after management has verified each customer payment.
  - Historical confirmed phơi remain immutable and are not changed by this UI simplification.
- Do-not-repeat notes:
  - Keep the default quick-confirmation option as unpaid; do not silently assume direct customer payment.
  - Do not move the confirmation financial validation into JavaScript alone.

## 2026-10-01 - Separate driver settlement from trip revenue display

- Status: done
- Goal: Prevent drivers from seeing trip revenue and owner profit in phơi views, while retaining a clear settlement amount showing whether the owner must pay the driver or the driver must remit to the owner.
- Files changed:
  - `app/templates/phoi/index.html` — hides each phơi's total revenue from drivers; manager/admin retain it.
  - `app/templates/phoi/detail.html` — hides return-trip revenue detail, the revenue/expense table, and owner profit from drivers; retains the settlement card with the driver advance/wage and driver-collected amounts.
  - `app/templates/phoi/detail_print.html` — applies the same role-aware visibility to the printable phơi.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Presentation-only role separation across the phơi list, detail, and print views. Drivers still see their own phơi and the existing `Phoi.balance()` outcome. Manager/admin continue to see full revenue, collections, expenses, and owner profit. No persisted data, schema, URLs, forms, confirmation rules, fuel associations, or financial source-of-truth formulas changed.
- Key decisions:
  - The driver settlement card continues to show only the two reconciliation inputs: `Tài xế đã ứng + Công` and `Tài xế đã thu`, plus the resulting amount to receive or remit.
  - Revenue disclosure is protected in templates with `current_user.is_manager_or_admin()` in all three viewing surfaces, including print.
  - Return-trip operational details remain available to drivers, but the Full amount and per-ton pricing are hidden.
- Validation:
  - Reviewed the role checks, phơi routes, financial methods, and all three affected templates before editing.
  - Editor diagnostics report no errors in `app/templates/phoi/index.html`, `app/templates/phoi/detail.html`, or `app/templates/phoi/detail_print.html`.
  - Loaded all three templates through the configured Flask/Jinja environment and ran `git diff --check`; no failure was reported. No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - This is display-level access control within already authorized phơi pages; it does not introduce a new data API or alter model-level financial permissions.
  - Drivers can still infer limited amounts from their own settlement inputs by design, but cannot view the trip's full revenue, direct owner collections, or owner profit.
- Do-not-repeat notes:
  - Keep the role guard on every new phơi revenue/profit display, including printable layouts.
  - Do not change `Phoi.balance()` or `Phoi.owner_profit()` when adjusting role-based financial visibility.

## 2026-10-01 - Prevent ambiguous Alembic migration deploys

- Status: done
- Goal: Restore one unambiguous Alembic migration head and prevent a multiple-head migration graph from reaching the VPS deployment job.
- Files changed:
  - `migrations/versions/d4e5f6a7b8c9_merge_manager_revenue_head.py` — empty merge revision joining the payment/fuel and manager-revenue heads without DDL or data changes.
  - `.github/workflows/deploy.yml` — adds a required pre-deploy job that fails unless `flask --app run:app db heads` reports exactly one head.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Pushes to `main` now verify Alembic topology in GitHub Actions before the production SSH deployment. The container retains `flask db upgrade`; it now has a single, deterministic target revision. The merge migration modifies migration history only and does not alter application tables or rows.
- Key decisions:
  - Do not use `flask db upgrade heads`: it hides an invalid branching history instead of enforcing a linear deploy target.
  - Make `deploy` depend on `verify-migrations`, so a topology failure prevents the VPS deploy step from starting.
  - Keep the CI test independent of production credentials and databases; it inspects only the revision files.
- Validation:
  - Ran `flask --app run:app db heads` with the configured virtual environment and asserted exactly one head.
  - Confirmed the workflow contains the required head-count failure guard and `deploy` dependency.
  - Editor diagnostics report no errors in the workflow or merge migration. No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - A developer must resolve migrations to a single head (usually with an explicit empty merge migration) before merging to `main`; the CI gate correctly blocks otherwise.
  - The merge revision must be committed and deployed with all referenced ancestor migration files.
- Do-not-repeat notes:
  - Never delete, rewrite, or manually stamp already-deployed migration revisions to resolve a branch; add a merge revision instead.
  - Retain the pre-deploy single-head gate when modifying deployment workflows.

## 2026-10-05 - Reset KM workflow per phơi

- Status: done
- Goal: Hide KM đầu and all new KM-photo uploads. Each new or edited phơi starts at KM 0 and requires only KM cuối before it can be chốt.
- Files changed:
  - `app/routes/phoi.py` — sets `km_start = 0`, accepts only `km_end`, removes truck odometer advancement and KM-start alerts, removes KM-photo submission requirements, and rejects new KM-photo attachment uploads.
  - `app/models.py` — calculates total KM correctly when `km_start` is zero.
  - `app/templates/phoi/create.html` and `app/templates/phoi/edit.html` — show only the KM cuối input and remove the KM-đầu upload control.
  - `app/templates/phoi/detail.html` and `app/templates/phoi/detail_print.html` — hide KM đầu and remove KM image choices/checklist while continuing to list historical attachments.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: A driver records KM cuối after returning to the yard. Chốt still requires a return trip, linked fuel log, and positive KM cuối, but no longer requires KM-start/end photos. Existing attachment records, including historical KM photos, are neither deleted nor altered. `Truck.current_km` is no longer updated from a phơi because the vehicle resets its KM per trip.
- Key decisions:
  - The server assigns KM đầu to zero rather than relying on the hidden form field.
  - New attachment uploads allow only phiếu cân or chứng từ khác; existing KM attachments stay readable in the evidence list.
  - No schema, migration, financial formula, role, or fuel-link behavior was changed.
- Validation:
  - Ran `python -m compileall -q app` successfully using the configured virtual environment.
  - Loaded the four changed phơi templates in the Flask/Jinja environment and checked reset-KM total calculation (`0 → 125` yields `125`).
  - Ran `git diff --check` successfully; only existing LF-to-CRLF warnings were emitted.
  - Editor diagnostics report no errors in the changed route, model, or templates. No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - Saving an existing phơi through the edit form normalizes its stored KM đầu to zero, as required by the reset-per-trip rule.
  - The application retains historical KM evidence for audit/viewing, but no new KM evidence can be uploaded from the UI or attachment endpoint.
- Do-not-repeat notes:
  - Keep the positive KM cuối validation server-side in `submission_error`; do not depend solely on the input control.
  - Do not reintroduce `Truck.current_km` advancement unless the per-trip reset policy changes explicitly.

## 2026-10-05 - Treat porter fees as driver advances

- Status: done
- Goal: Ensure every outbound and return-trip bốc vác (porter fee) is treated as money advanced by the driver and added to the driver's settlement alongside wage.
- Files changed:
  - `app/models.py` — includes outbound `porter_fee` expenses and every return-trip `porter_fee` in `driver_out_of_pocket_expenses()`; `balance()` therefore reimburses them through the established settlement formula.
  - `app/templates/phoi/create.html` and `app/templates/phoi/edit.html` — label bốc vác inputs as driver advances for both outbound and return trips.
  - `app/templates/phoi/detail.html` — itemizes the total porter-fee advance in the driver settlement card.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Phơi create/edit data storage is unchanged. For current and historical phơi with porter fees, the settlement amount now includes those fees as a driver advance. `total_expenses()` still includes the same fees, so owner profit continues to deduct them exactly once.
- Key decisions:
  - No migration or persisted-data rewrite is needed because existing outbound fees already use `PhoiExpense.category='porter_fee'` and return-trip fees already use `PhoiReturnTrip.porter_fee`.
  - Fees are added only to the driver's advance side of `balance()`; they are not added to driver-collected revenue.
  - The financial source of truth remains `Phoi.balance() = driver_out_of_pocket_expenses() + driver_wage - total_revenue_collected()`.
- Validation:
  - Ran `python -m compileall -q app` successfully using the configured virtual environment.
  - Ran an isolated in-memory database calculation: wage 500,000, outbound bốc vác 200,000, return bốc vác 150,000, and other driver advance 30,000 yields driver advances 380,000, balance -520,000, and total expense 380,000.
  - Ran `git diff --check` successfully and editor diagnostics found no errors in all four changed application files.
  - No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - Historical phơi with porter fees will display a different settlement balance by the full fee amount, as explicitly approved.
  - Owner profit is intentionally unchanged by this update because porter fees were already included in total expenses.
- Do-not-repeat notes:
  - Keep every new porter-fee input included in both `total_expenses()` and `driver_out_of_pocket_expenses()` while the policy remains that the driver always advances it.
  - Do not add porter fees to `total_revenue_collected()`; that field is solely cash held from customers by the driver.

## 2026-10-05 - Clarify phơi status filter labels

- Status: done
- Goal: Make the phơi list's status filter explicitly distinguish a driver-submitted phơi from a manager-confirmed phơi.
- Files changed:
  - `app/templates/phoi/index.html` — renamed the `submitted` option to “Tài xế đã chốt” and the `confirmed` option to “Quản lý đã chốt”.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Presentation-only change to the phơi list filter. The existing query values (`submitted` and `confirmed`), route filtering, permissions, confirmation eligibility, data, schema, and financial calculations are unchanged.
- Key decisions:
  - Retained the existing status values to preserve saved URLs and pagination links.
  - Kept “Đang hoạt động” and “Đang thực hiện” unchanged.
- Validation:
  - Reviewed `Phoi.status` values and the index route's accepted filters.
  - Editor diagnostics found no errors in `app/templates/phoi/index.html`.
  - Ran `git diff --check` successfully; Git reported only the repository's LF-to-CRLF conversion warning.
  - No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - This explains the existing workflow in the filter only; status badges elsewhere intentionally retain their current wording.
- Do-not-repeat notes:
  - Preserve the underlying filter values when changing user-facing status wording so existing filter URLs remain compatible.

## 2026-10-05 - One-phơi fuel logs and fuel-cost profit accounting

- Status: done
- Goal: Require each newly recorded fuel fill to link to exactly one active phơi, remove the refuel-KM input, let authorized users correct fuel quantity and refuel date before confirmation, and deduct fuel from phơi profit.
- Files changed:
  - `app/models.py` — adds `fuel_expenses()` and includes it in `total_expenses()`; legacy multi-phơi fuel records are split evenly to avoid duplicate deductions.
  - `app/routes/fuel.py` — validates exactly one active same-truck phơi on fuel creation; removes refuel-KM processing; adds protected quantity/date editing that is blocked once any linked phơi is confirmed.
  - `app/templates/fuel/create.html` — replaces multiple phơi checkboxes with one required phơi selector and removes the KM-at-refuel field.
  - `app/templates/fuel/edit.html` — new focused form for changing only liters and refuel date.
  - `app/templates/fuel/index.html` — removes historical KM display and provides an edit action to authorized users.
  - `app/templates/phoi/edit.html` and `app/templates/phoi/detail.html` — display the number/list of linked fuel fills and an authorized edit action.
  - `app/templates/phoi/detail.html` and `app/templates/phoi/detail_print.html` — itemize fuel as a trip expense before the total cost and owner profit.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: New fuel logs link to one `draft` or `submitted` phơi of the selected truck. Liter changes recalculate the stored total using the original per-liter price; changing fuel logs tied to confirmed phơi remains blocked. Owner profit now correctly uses total expenses including fuel. No schema migration or persisted-data rewrite is required.
- Key decisions:
  - Existing historical rows that already link one fill to several phơi remain readable; `fuel_expenses()` divides their cost by the number of linked phơi to preserve one total deduction across those phơi.
  - The existing `km_at_refuel` column remains for compatibility, but no new UI or route logic writes or displays it.
  - Drivers may edit only fuel logs they created and only where every linked phơi belongs to them; manager/admin may edit any eligible log.
- Validation:
  - Ran `python -m compileall -q app` successfully with the configured virtual environment.
  - Loaded the changed fuel/phơi Jinja templates through the Flask environment successfully.
  - Editor diagnostics found no errors in all changed application files.
  - Ran `git diff --check` successfully. No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - A database-level unique constraint was not added because historical `fuel_log_phois` data may contain multiple links; application validation enforces the new policy without a data migration.
  - The quantity/date correction intentionally does not alter price, payer, receipts, truck, or phơi association; those changes need separate approval because they affect accounting/audit semantics.
- Do-not-repeat notes:
  - Keep historical multi-link allocation in `fuel_expenses()` until those rows are explicitly migrated or reconciled.
  - Keep fuel inside `total_expenses()` so `owner_profit()` deducts it via the established formula; do not add fuel to driver settlement unless the payment policy is changed explicitly.
