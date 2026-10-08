# Current Task Record

## 2026-10-07 - Display porter fees after phơi confirmation

- Status: done
- Goal: Make recorded bồi dưỡng/bốc vác costs visible when reviewing or printing a submitted/confirmed phơi, and make the printed text modestly larger.
- Files changed:
  - `app/templates/phoi/detail.html` — shows each return trip's non-zero bốc vác advance in the trip section and as an individual line in the manager/admin financial breakdown.
  - `app/templates/phoi/detail_print.html` — shows each non-zero return-trip bốc vác amount in the financial breakdown and return-trip summary; increases the base, information-table, and financial-table font sizes slightly; adds owner and driver signature areas at the printed footer.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Presentation only for phơi review and print. Existing stored porter-fee values, finance visibility rules, `Phoi.total_expenses()`, `Phoi.driver_out_of_pocket_expenses()`, `Phoi.balance()`, and `Phoi.owner_profit()` remain unchanged. The manager/admin financial section continues to be restricted to its existing roles. The signature areas are hidden on screen and appear only on the printed document.
- Key decisions:
  - Render return-trip bốc vác separately rather than changing the total calculation, so the visible breakdown reconciles exactly with the existing total.
  - Omit zero-value bốc vác rows to keep the review and print layouts compact.
  - Increase only print-specific layout typography by a small amount to preserve the single-page A4-oriented layout.
  - Use two equal signature columns labelled Chủ xe and Tài xế, with a fixed signing area and page-break avoidance.
- Validation:
  - Re-read the modified Jinja sections to verify the non-zero conditional, return-trip number, formatted amounts, and print-only signature rules.
  - Loaded the changed templates through the Flask/Jinja environment.
  - Ran `git diff --check`; no whitespace error was reported.
  - Editor diagnostics reported no errors after the change.
  - No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - A phơi with many return trips may use more vertical print space because every non-zero bốc vác line and the signature section are now shown.
  - Do not change the existing manager/admin-only financial visibility without separate approval.
- Do-not-repeat notes:
  - Preserve the model financial methods as the financial source of truth; display code must not independently recalculate totals.
  - Keep return-trip bốc vác clearly identified as a driver advance.
  - Keep signature fields print-only unless an on-screen approval/signature workflow is separately approved.

## 2026-10-07 - Improve phơi action button spacing

- Status: done
- Goal: Make action buttons on the phơi detail page visually separated and easier to scan, especially on desktop.
- Files changed:
  - `app/templates/phoi/detail.html` — groups the back action and operational actions in semantic action-bar containers; keeps the submit form compatible with the existing POST/CSRF flow.
  - `app/static/css/style.css` — adds a wrapping flex layout with consistent `0.5rem` gaps for phơi actions and narrow-screen alignment rules.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Presentation only on the phơi detail page. Back, print, edit, fuel, submit, cancel, reconciliation, and quick-confirm actions retain their existing routes, visibility rules, labels, POST method, confirmation dialog, and CSRF token. No business logic, persisted data, financial result, authorization, fuel association, migration, or URL changed.
- Key decisions:
  - Use a page-specific action-bar class rather than a global `.btn` margin, avoiding unintended spacing changes across forms, button groups, and input groups.
  - Use flex `gap` and wrapping so desktop buttons are consistently separated and overflow is avoided on narrower screens.
  - Use `display: contents` only for the existing submit form within the action group, preserving its DOM form submission behavior while allowing the button to participate in the flex gap.
- Validation:
  - Reviewed the phơi detail template action flow and shared stylesheet.
  - Editor diagnostics reported no errors after the change.
  - Re-read the modified template and CSS to verify the action-bar structure, form method, CSRF field, and selectors.
  - No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - Visual behavior is based on Bootstrap-supported modern browsers; the action buttons intentionally wrap rather than overlap if space is limited.
  - Do not apply a blanket button-spacing rule because it could disrupt Bootstrap button groups and input groups.
- Do-not-repeat notes:
  - Keep action-button spacing scoped to the phơi action bar unless another page is explicitly requested.
  - Preserve the submit form's POST method, CSRF input, and confirmation prompt when changing its layout.

## 2026-10-07 - Retain cancelled phơi and reallocate released fuel

- Status: done
- Goal: Let only manager/admin users cancel a draft phơi while retaining its evidence/history, then explicitly reassign sole-linked fuel fills to a replacement phơi of the same truck.
- Files changed:
  - `app/models.py` — adds cancellation metadata to `Phoi` and allocation/source tracking to `FuelLog`; financial formulas are unchanged.
  - `migrations/versions/e6f7a8b9c0d1_add_phoi_cancellation_and_fuel_allocation.py` — adds the new columns, foreign keys, and indexes; existing fuel rows default to `allocated`.
  - `app/routes/phoi.py` — adds the manager/admin-only cancellation endpoint, fuel release/reassignment checks, cancellation audit log, cancelled filter, and form context.
  - `app/templates/phoi/create.html`, `app/templates/phoi/edit.html` — manager/admin-only selection of same-truck fuel awaiting allocation.
  - `app/templates/phoi/detail.html`, `app/templates/phoi/index.html`, `app/templates/phoi/detail_print.html` — cancellation action, retained-state display/filtering, and prominent printed cancellation marker.
  - `app/templates/fuel/index.html` — identifies fuel waiting for allocation and the source cancelled phơi.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Only a `draft` phơi may be cancelled, and only by manager/admin. Cancellation removes its fuel associations without deleting fuel logs, receipts, attachments, expenses, or trips. A fuel fill becomes `unallocated` only if the cancelled phơi was its final association; historic multi-linked fills retain their other links. A manager/admin can assign waiting fuel only to a phơi of the same truck. The create form shows “Xăng chờ phân bổ” only after the manager selects a truck with fuel explicitly released from a cancelled phơi; normal unallocated records cannot surface or be submitted through this flow. Cancelled phơi are excluded from the existing active list, fuel creation choices, truck active-state calculation, confirmation, and confirmed-only debt reporting.
- Key decisions:
  - Retain cancelled records for audit rather than deleting persisted operational/financial evidence.
  - Require a cancellation reason and store actor/time/reason on the phơi.
  - Do not auto-transfer fuel to a newly created phơi; allocation is explicit and server-validated to avoid incorrect cost attribution.
  - Preserve `Phoi.balance()` and `Phoi.owner_profit()` exactly as the financial source of truth.
- Validation:
  - Reviewed the phơi lifecycle, fuel many-to-many association, truck status helper, fuel creation eligibility, confirmed-only reporting policy, templates, and Alembic graph before editing.
  - Ran `python -m compileall -q app migrations` successfully with the configured virtual environment.
  - Loaded all modified Jinja templates through Flask successfully.
  - Editor diagnostics reported no errors in all changed models, route, templates, and migration.
  - Verified the migration graph has one head: `e6f7a8b9c0d1`.
  - Ran `git diff --check` successfully; Git reported only LF/CRLF working-copy warnings. No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - The schema migration must be applied before deploying this source change.
  - The cancellation transaction is protected by request-time state validation but, like existing application-level lifecycle checks, concurrent requests could theoretically race.
  - Cancelled records remain visible for audit; they are intentionally not deleted or included in normal active/confirmed reports.
- Do-not-repeat notes:
  - Never auto-assign released fuel to the newest phơi; require explicit manager/admin selection and validate the truck on the server.
  - Do not mark a fuel log unallocated when it remains linked to another phơi.
  - Keep cancellation restricted to draft phơi and retain the confirmed-fuel immutability policy.


## 2026-10-06 - Improve quick-confirmation collection controls

- Status: done
- Goal: Format direct-manager collection inputs on the quick confirmation page and prevent non-applicable collection choices when a driver has already collected a trip in full.
- Files changed:
  - `app/static/js/app.js` — treats inputs marked with the existing `currency-input` class as currency fields, providing thousands separators while typing and number-only values at submit.
  - `app/templates/phoi/confirm.html` — identifies each trip whose driver-collected amount leaves no remaining revenue; disables “Chưa thu” and “Thu một phần”, selects “Đã thu đủ”, hides the partial-amount input, and displays an explanatory badge.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Presentation and client-side input handling for manager/admin quick confirmation only. Each outbound/return trip is evaluated independently using `revenue_full - revenue_collected`. The confirmation route, direct-manager collection storage, customer-debt calculation, fuel requirement, schema, migrations, and financial source-of-truth formulas remain unchanged.
- Key decisions:
  - Reused the existing `currency-input` semantic class rather than maintaining a second list of dynamic quick-confirmation input names.
  - A driver-collected-full trip submits the already supported `full` choice; the server continues to compute a direct-manager amount of zero from the zero remaining amount.
  - No server-side validation rule changed; existing validation remains authoritative for modified requests.
- Validation:
  - Editor diagnostics found no errors in `app/templates/phoi/confirm.html` and `app/static/js/app.js`.
  - Ran `python -m compileall -q app` successfully using the configured virtual environment.
  - Ran `git diff --check` successfully; output contained only pre-existing LF-to-CRLF conversion warnings.
  - No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - The disabled controls are a usability safeguard, not a new authorization or backend validation boundary; the existing confirmation route still validates amounts.
  - Currency formatting continues to support non-negative whole VND values only, consistent with all existing currency fields.
- Do-not-repeat notes:
  - Keep quick-confirmation collection decisions per trip; do not infer them from a phơi-wide total or `Phoi.balance()`.
  - Do not add manager direct collections to driver settlement calculations.

## 2026-10-06 - Simplify weigh-ticket inputs

- Status: done
- Goal: Remove the confusing weigh-ticket-number input from the phơi interface and combine outbound weight/evidence with outbound revenue, matching the simpler return-trip layout.
- Files changed:
  - `app/routes/phoi.py` — stops writing absent weigh-ticket-number form fields so existing values are preserved; allows outbound weigh-ticket images to be uploaded from the edit form.
  - `app/templates/phoi/create.html` — moves outbound tonnage and weigh-ticket image upload into Doanh thu chuyến đi; removes number input from outbound and return trips.
  - `app/templates/phoi/edit.html` — applies the same simplified layout and removes obsolete client-side ticket-field injection.
  - `app/templates/phoi/detail.html` and `app/templates/phoi/detail_print.html` — no longer display weigh-ticket numbers; retain tonnage and attached image evidence.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Create and edit forms no longer submit or overwrite `Phoi.weigh_ticket_number` or `PhoiReturnTrip.weigh_ticket_number`. Existing database columns and historical values are intentionally retained but hidden. Per-ton revenue calculation, attached weigh-ticket images, confirmation eligibility, fuel links, and financial formulas remain unchanged.
- Key decisions:
  - No migration or persisted-data rewrite was made.
  - Existing ticket-number values remain intact when a phơi or return trip is edited.
  - Outbound evidence supports up to five images per edit submission, consistent with existing upload limits.
- Validation:
  - Editor diagnostics found no errors in all changed routes and templates.
  - Confirmed the only remaining `weigh_ticket_number` references are the two retained model columns.
  - Ran Python compilation, template loading, and `git diff --check`; no validation failure was reported. No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - Historical ticket-number data is intentionally inaccessible through the UI; it remains available only at database level.
  - Do not remove the retained columns without separate approval and a migration/data-retention plan.
- Do-not-repeat notes:
  - Keep cargo weight available for per-ton revenue calculations even when the ticket number is hidden.
  - Preserve all existing attachment size/count checks and confirmation/fuel requirements.

## 2026-10-06 - Correct and delete fuel fills before confirmation

- Status: done
- Goal: Allow authorized users to correct or delete mistakenly entered fuel fills while a phơi is in draft or submitted reconciliation, without permitting changes after confirmation.
- Files changed:
  - `app/routes/fuel.py` — allows a driver to delete only a fill they created when every linked phơi belongs to them; keeps manager/admin access, blocks confirmed phơi, and returns to the linked phơi after deletion.
  - `app/templates/fuel/index.html` — shows the delete action to the same eligible user group as the edit action.
  - `app/templates/phoi/detail.html` — adds a CSRF-protected delete action beside the existing liters/date correction action for non-confirmed phơi.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: A fuel fill attached to a draft or submitted phơi can be corrected through the existing edit flow or deleted by its authorized creator/manager/admin. A fill attached to any confirmed phơi remains immutable. Deleting the final fill is intentionally allowed; existing `submission_error()` then prevents confirmation until a replacement fill is recorded. No schema, migration, financial formula, fuel-to-phơi association policy, or persisted-data rewrite changed.
- Key decisions:
  - Server-side authorization remains authoritative: driver access requires ownership of both the fuel record and every linked phơi; manager/admin access is retained.
  - Both the list and phơi detail page warn that deleting the final fill requires a new fill before confirmation.
  - The delete route redirects to the linked phơi only when exactly one exists, preserving compatibility with historic multi-linked records.
- Validation:
  - Ran `python -m compileall -q app` successfully with the configured virtual environment.
  - Loaded `fuel/index.html`, `fuel/edit.html`, and `phoi/detail.html` through Flask/Jinja successfully.
  - Editor diagnostics found no errors in all changed files.
  - Ran `git diff --check` successfully. No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - Existing historical multi-linked fuel rows remain supported; a driver can only delete one when every attached phơi belongs to that driver, and the confirmed lock applies if any linked phơi is confirmed.
  - Confirmation eligibility continues to depend on the existing at-least-one-fuel-log check; do not bypass it for a deleted final fill.
- Do-not-repeat notes:
  - Keep confirmed fuel records locked in both UI and route authorization.
  - Do not authorize a driver solely from the visible page; always verify fuel creator and linked-phơi ownership on the server.

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

## 2026-10-05 - Collapsible create-phơi form sections

- Status: done
- Goal: Let users hide or show each section of the create-phơi form by clicking its title, while keeping every section expanded by default.
- Files changed:
  - `app/templates/phoi/create.html` — added accessible clickable titles and expand/collapse behavior for Chọn hàng, Tuyến đường, Thông tin chuyến, Ảnh chứng từ, Doanh thu chuyến đi, Chi phí chuyến, Ghi chú, and Các chuyến về.
  - `app/static/css/style.css` — added pointer, keyboard-focus, and icon alignment styling for collapsible section titles.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Presentation-only change to the create-phơi form. All fields stay in the form and retain their values when hidden. The creation route, persisted data, financial calculations, validation, return-trip handling, fuel association, roles, and URLs are unchanged. Fuel entry remains unchanged as requested.
- Key decisions:
  - Every section starts expanded; a title click or keyboard Enter/Space toggles only its paired card.
  - `aria-expanded`, `aria-controls`, focus indication, and directional chevrons provide accessible state feedback.
  - Visibility uses Bootstrap `d-none`, so hiding a section does not disable or omit its fields from form submission.
- Validation:
  - Reviewed the create route, create template, existing dynamic return-trip/repair scripts, fuel route/template, and shared CSS before editing.
  - Editor diagnostics found no errors in `app/templates/phoi/create.html`, `app/static/css/style.css`, or the application folder.
  - Ran `git diff --check` successfully; Git only reported existing LF-to-CRLF conversion warnings. No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - Browser-based interaction was not launched; the behavior is limited to standard DOM click/keyboard toggles and preserves all existing inputs.
- Do-not-repeat notes:
  - Keep new create-form section cards paired with unique title `data-collapse-target` values and default `aria-expanded="true"` unless an explicit default-collapsed requirement is approved.
  - Do not hide, disable, or remove fields solely to implement visual collapsing.

## 2026-10-05 - Add return-trip weigh-ticket evidence

- Status: done
- Goal: Record a weigh-ticket number and image evidence for each return trip, with create, edit, detail, and print support.
- Files changed:
  - `app/models.py` — added nullable `PhoiReturnTrip.weigh_ticket_number`, the per-return-trip attachment relationship, and nullable `PhoiAttachment.return_trip_id`.
  - `migrations/versions/aa1b2c3d4e5f_add_return_trip_weigh_tickets.py` — adds the return-trip ticket number plus indexed, cascading attachment foreign key.
  - `app/routes/phoi.py` — preserves retained return-trip IDs during edits, saves up to five images per return trip, and permits later per-trip ticket upload on the detail page.
  - `app/templates/phoi/create.html` and `app/templates/phoi/edit.html` — add ticket number/image inputs to every return-trip card and retain aligned upload indexes when cards are removed.
  - `app/templates/phoi/detail.html` and `app/templates/phoi/detail_print.html` — show each return trip's ticket number, weight, and evidence summary separately from outbound evidence.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: This is a schema and attachment-workflow addition. Existing outbound attachments remain valid with `return_trip_id = NULL`; existing return trips receive a nullable ticket number. Retained return trips are updated in place so their evidence is not erased by an ordinary phơi edit. Financial methods, roles, fuel rules, confirmation eligibility, and existing outbound attachment behavior are unchanged.
- Key decisions:
  - A ticket image is attached to exactly one `PhoiReturnTrip` through `PhoiAttachment.return_trip_id`; it also keeps the parent `phoi_id` for existing authorization and file routes.
  - Each create/edit card accepts at most five JPG, PNG, or WEBP images. The existing compression and rollback cleanup helper is reused.
  - Removing a return trip deletes its attachment database rows through the relationship/database cascade; stored files for those cascade-deleted rows may require storage cleanup review in a future maintenance task.
- Validation:
  - Reviewed the model, create/edit/detail routes, dynamic return-trip templates, existing attachment handler, print template, and migration head before editing.
  - Editor diagnostics report no errors in all changed application files and the migration.
  - Ran `python -m compileall -q app migrations` successfully using the configured virtual environment.
  - Ran `git diff --check` successfully; output contained only existing LF-to-CRLF conversion warnings.
  - Validated SQLAlchemy mappings and requested Alembic heads through Flask; the command emitted only application startup log matches, so migration-head output should be rechecked during deployment.
  - No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - Run `flask --app run:app db upgrade` before deploying this application version; the new model fields require migration `aa1b2c3d4e5f`.
  - Physical files tied to a trip removed during edit are not currently explicitly deleted after the database cascade; do not add synchronous pre-commit deletion because a rolled-back edit would lose evidence.
- Do-not-repeat notes:
  - Do not restore delete-and-recreate synchronization for `PhoiReturnTrip`; it destroys child evidence associations.
  - Keep return-ticket image field names synchronized with each displayed card index, and verify a submitted return-trip ID belongs to the current phơi before updating it.

## 2026-10-05 - Phơi form validation feedback and unsaved-change warnings

- Status: done
- Goal: Make missing native form fields visibly invalid on create/edit, validate invalid partial manager collections before confirmation, and warn before a user leaves a changed phơi form without saving.
- Files changed:
  - `app/static/js/app.js` — added shared dirty-form tracking for opt-in phơi forms, Vietnamese navigation confirmation, and browser unload protection.
  - `app/templates/phoi/create.html` — opts into unsaved-change protection and adds Bootstrap invalid-state feedback for native required inputs.
  - `app/templates/phoi/edit.html` — opts into unsaved-change protection and adds Bootstrap invalid-state feedback for native required inputs.
  - `app/templates/phoi/confirm.html` — opts into unsaved-change protection and rejects/marks a partial collection that is empty, non-positive, or above the displayed remaining revenue.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Presentation and browser-side validation only. Existing create/edit/save/chốt/xác nhận routes remain authoritative; no models, data, schema, financial methods, fuel association, confirmation eligibility, role checks, URLs, or server validation logic changed. The detail page already shows each chốt prerequisite with a visible pass/fail indicator; source fields remain on the create/edit forms.
- Key decisions:
  - The leave warning is activated only after user input/change and is disabled once a form starts submitting; dynamic return-trip inputs are covered through delegated form events.
  - In-page navigation uses the requested Vietnamese confirmation text. Browser close/reload dialogs are controlled by the browser and may show generic wording.
  - Partial collection checks are convenience feedback only; `confirm()` keeps the server-side over-collection validation as the final source of truth.
- Validation:
  - Reviewed the phơi submit/confirm routes, detail-page chốt conditions, all affected form templates, and existing shared submit/currency behavior before editing.
  - Editor diagnostics found no errors in the changed JavaScript and templates.
  - Ran `python -m compileall -q app migrations` successfully with the configured virtual environment.
  - Ran `git diff --check` successfully; Git only reported repository LF-to-CRLF conversion warnings.
  - No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - The native browser close/reload prompt cannot guarantee custom Vietnamese text because modern browsers intentionally control that dialog.
  - Server-side flashes remain the feedback mechanism for chốt prerequisites that have no input on the detail page (such as an absent fuel log); the detail condition card continues to expose those failures before chốt.
- Do-not-repeat notes:
  - Keep final chốt/xác nhận rules on the server; JavaScript must not become the only enforcement layer.
  - Ensure any new editable phơi form explicitly opts into `warn-unsaved-changes` only when its fields can be lost by navigation.

## 2026-10-06 - Merge parallel Alembic migration heads

- Status: done
- Goal: Restore one deterministic Alembic migration head so the deployment topology gate permits safe database upgrades.
- Files changed:
  - `migrations/versions/b2c3d4e5f6a7_merge_driver_paid_and_return_trip_tickets.py` — empty merge revision joining `975a0bd04827` and `aa1b2c3d4e5f`.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Migration history only. The merge revision has no DDL or data operations; it causes normal upgrade traversal to apply both existing branch migrations, then records one shared head. Application data, schema definitions, financial calculations, roles, fuel rules, URLs, and phơi workflows are unchanged.
- Key decisions:
  - Used the standard Alembic empty merge revision rather than rewriting or deleting already-created revisions.
  - Kept the workflow's exactly-one-head CI gate; it correctly prevents ambiguous production deployments.
- Validation:
  - Ran `python -m compileall -q migrations` successfully with the configured virtual environment.
  - Ran `python -m flask --app run:app db heads`; output is exactly `b2c3d4e5f6a7 (head)`.
  - Ran `git diff --check` successfully. No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - Production must receive all three revisions (`975a0bd04827`, `aa1b2c3d4e5f`, and this merge revision); deployment's standard `db upgrade` handles the ordering.
- Do-not-repeat notes:
  - Before generating any migration, update from `main` and verify there is exactly one Alembic head.
  - If parallel migrations are already committed, add an empty merge revision; never rewrite or delete deployed revision history.

## 2026-10-06 - Normalize decimal values in edit inputs

- Status: done
- Goal: Prevent fixed-scale database values from making weight or fuel-quantity edit inputs look like they were changed (for example, show `15` instead of `15.000` while preserving `15.245`).
- Files changed:
  - `app/templates/phoi/edit.html` — formats outbound and return-trip tonnage values with up to three decimals, removing only trailing zeros before setting their `type="number"` input values.
  - `app/templates/fuel/edit.html` — formats fuel-liter values with up to two decimals, removing only trailing zeros before setting the edit input value.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Presentation-only change to existing edit forms. The existing `Numeric(10, 3)` tonnage storage, `Numeric(12, 2)` fuel-liter storage, form field names, server parsers, per-ton revenue calculation, financial source-of-truth methods, confirmation eligibility, roles, URLs, and schema remain unchanged. Values such as `15.245` stay `15.245`; padded database values `15.000`, `15.200`, and `20.00` display as `15`, `15.2`, and `20`.
- Key decisions:
  - Keep `type="number"`, `step`, and the period (`.`) decimal submission convention unchanged to preserve browser validation and the existing server parsing path.
  - Apply the formatting only to persisted values shown on edit; creation fields and currency formatting are not changed.
  - Cover both outbound and return-trip tonnage to prevent the same confusion in either phơi flow.
- Validation:
  - Ran `python -m compileall -q app` successfully with the configured virtual environment.
  - Loaded `phoi/edit.html` and `fuel/edit.html` through Flask/Jinja successfully.
  - Verified display expressions: `15.245 → 15.245`, `15.000 → 15`, and `20.00 → 20`.
  - Editor diagnostics found no errors and `git diff --check` passed. No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - Browser locale rendering of a standard numeric input remains browser-controlled; the HTML value sent to the existing server parser continues to use `.` as the decimal separator.
- Do-not-repeat notes:
  - For decimal edit inputs backed by fixed-scale `Numeric` columns, remove display-only trailing zeros without changing stored precision or switching to currency/thousand-separator handling.
  - Keep a three-decimal display limit for cargo weight and a two-decimal display limit for fuel liters, matching their existing database columns.

## 2026-10-07 - Keep collapsed create-phơi titles on separate lines

- Status: done
- Goal: Ensure each collapsible create-phơi section title occupies its own row on mobile, including when several sections are collapsed.
- Files changed:
  - `app/static/css/style.css` — makes `.collapsible-section-title` span the full available width.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Presentation-only change to the create-phơi form. Collapse/expand behavior, form fields, saved values, routes, validation, financial calculations, fuel association, roles, and persistence are unchanged.
- Key decisions:
  - Retained the existing flex layout and automatic right-aligned chevron; added only `width: 100%` so an inline `span` cannot share a row with the following title.
- Validation:
  - Editor diagnostics found no errors in the changed CSS or create template.
  - Ran `git diff --check` successfully; Git only reported the repository's LF-to-CRLF conversion warning.
  - No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - Visual browser testing was not launched; the fix relies on standard CSS block-width behavior within the existing form layout.
- Do-not-repeat notes:
  - Keep a full-width rule on clickable collapsed-section titles so neighboring inline titles cannot appear on the same mobile row.

## 2026-10-07 - Standardize required-form validation feedback

- Status: done
- Goal: When a user submits any form with missing required information, show a Vietnamese popup, mark invalid fields red, and focus the first missing field.
- Files changed:
  - `app/templates/base.html` — adds the shared Bootstrap modal with the message “Bạn cần phải điền đủ thông tin.”
  - `app/static/js/app.js` — adds common required-field validation, invalid styling, Flatpickr date-input handling, and first-invalid-field focus; avoids currency formatting, unsaved-form submission state, and submit-button loading while invalid submissions are blocked.
  - `app/templates/phoi/create.html` and `app/templates/phoi/edit.html` — remove duplicated phơi-only invalid-field handlers in favor of the shared mechanism.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Client-side feedback only for existing forms with `required` controls, including dynamically added phơi fields. Existing HTML required constraints, server validation, form fields, routes, authorization, financial calculations, fuel association rules, URLs, schema, and persisted data remain unchanged. Disabled required fields remain excluded, consistent with native browser validation.
- Key decisions:
  - Use a single base-template modal and delegated JavaScript events, so all existing required forms receive the same behavior without individually changing every template.
  - Set `novalidate` only for forms containing required controls, then use `checkValidity()` to retain the browser’s native constraint rules while replacing the default browser popup with the approved Vietnamese modal.
  - Focus the Flatpickr alternate input when relevant so date fields remain usable on mobile and desktop.
- Validation:
  - Editor diagnostics reported no errors.
  - Ran `node --check app/static/js/app.js` successfully.
  - Ran `git diff --check` successfully; Git only reported LF-to-CRLF working-copy warnings.
  - Reviewed the changed diff and verified the shared submit handler executes before currency formatting, unsaved-form submission state, and loading-button handling.
  - No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - Visual browser interaction was not launched; the behavior relies on standard Bootstrap 5 modal APIs and native HTML constraint validation.
  - Forms with no required controls retain their current submission behavior.
- Do-not-repeat notes:
  - Keep server-side validation authoritative; this shared client-side validation is a usability layer only.
  - Check `event.defaultPrevented` in later submit listeners so invalid submissions never create loading or unsaved-state side effects.

## 2026-10-08 - List missing fields and expand collapsed phơi sections

- Status: done
- Goal: Make the shared missing-required-fields popup list every missing field in top-to-bottom form order, and automatically open any collapsed create/edit phơi section containing a missing field.
- Files changed:
  - `app/templates/base.html` — changes the shared popup body to hold an ordered list of missing field labels.
  - `app/static/js/app.js` — derives accessible labels, renders missing fields in DOM order, expands matching collapsed sections, and then retains the existing first-field focus behavior.
  - `.clinerules/current-task.md` — this record.
- Affected flow/impact: Client-side validation feedback only. Existing form constraints, routes, authorization, server-side validation, financial calculations, fuel links, persisted data, and schema are unchanged. The expansion behavior applies only where an invalid field is inside an existing `d-none` section whose matching title has `data-collapse-target`.
- Key decisions:
  - Use each form control’s associated label first, with a safe fallback to its accessible name or input name, so existing and dynamically added return-trip fields are included without template-specific mappings.
  - Preserve DOM/form-control order to give users the requested top-to-bottom list.
  - Reuse the established section title attributes and icon conventions instead of duplicating phơi-specific collapse code in the shared validator.
- Validation:
  - Ran `node --check app/static/js/app.js` successfully.
  - Ran `git diff --check` successfully.
  - Editor diagnostics reported no errors in the changed JavaScript and base template.
  - No development server was launched and no persisted application data was changed.
- Risks/constraints:
  - Visual browser interaction was not launched; this uses the existing Bootstrap modal and section-collapse markup.
  - A required field without an associated label falls back to its accessible label or HTML field name.
- Do-not-repeat notes:
  - Keep the missing-field list generated from native form validity, not a duplicated manual list of required controls.
  - Only auto-expand sections that use the established `data-collapse-target`/matching-card-ID convention.
