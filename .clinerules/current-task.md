# Current Task Record

## 2026-06-26 - Thêm ngày đăng kiểm, phù hiệu + cảnh báo hết hạn

- Status: done
- Goal: Thêm 4 trường mới vào xe (ngày đăng kiểm, hạn đăng kiểm (tháng), ngày cấp phù hiệu, hạn phù hiệu (tháng)). Khi gần tới hạn (≤15 ngày) sẽ báo cho tài xế và quản trị viên biết, cách 2 ngày báo 1 lần.
- Files changed:
  - app/models.py — thêm 6 cột mới vào Truck: `inspection_date`, `inspection_expiry_months`, `permit_date`, `permit_expiry_months`, `last_inspection_notified_at`, `last_permit_notified_at`; thêm methods: `inspection_expiry_date()`, `inspection_days_until_expiry()`, `permit_expiry_date()`, `permit_days_until_expiry()`, `inspection_should_notify()`, `permit_should_notify()`, `get_expiry_warnings()`, `mark_expiry_notified()`
  - app/routes/trucks.py — routes create/edit xử lý 4 trường mới bằng `_parse_date()` helper; thêm `datetime` import
  - app/templates/trucks/create.html — thêm form section "Đăng kiểm & Phù hiệu" (2 dòng row g-2)
  - app/templates/trucks/edit.html — thêm form section "Đăng kiểm & Phù hiệu" + badge cảnh báo còn bao nhiêu ngày
  - app/templates/trucks/index.html — thêm 2 cột "Đăng kiểm" và "Phù hiệu" trong table, hiển thị ngày hết hạn + badge đỏ nếu ≤15 ngày
  - app/routes/phoi.py — thêm warning banner (alert-danger) đầu trang phoi/index, quét tất cả xe active, kiểm tra should_notify() và commit lại last_notified_at
  - app/templates/phoi/index.html — thêm alert-danger banner với danh sách xe sắp hết hạn đăng kiểm/phù hiệu
  - migrations/versions/ — 2 migration files mới (4bf8cef8c966, 406506709a7c)
- Key decisions:
  - Lưu hạn đăng kiểm/phù hiệu dạng "số tháng" (inspection_expiry_months/permit_expiry_months) để linh hoạt tính ngày hết hạn
  - `inspection_expiry_date()` và `permit_expiry_date()` tính trực tiếp từ date gốc + số tháng (ví dụ: đăng kiểm 15/01/2026 + 6 tháng = 15/07/2026)
  - Cảnh báo xuất hiện trên trang chính (phoi/index) để cả tài xế và admin đều thấy được
  - `last_*_notified_at` tracking cho phép cách 2 ngày báo lại: notify → set timestamp → skip nếu <2 ngày → 2 ngày sau notify lại
  - Trên trang xe (trucks/index) badge đỏ hiển thị số ngày còn lại, không cần tracking vì chỉ hiển thị số ngày realtime
- Constraints handled:
  - Không thay đổi schema cũ (soft delete vẫn giữ nguyên)
  - UI text Vietnamese
  - Follow existing coding patterns (MVC, thin routes, model methods cho business logic)
- Do-not-repeat notes:
  - `inspection_expiry_date()` và `permit_expiry_date()` phải dùng calendar.monthrange để xử lý ngày cuối tháng (ví dụ 31/01 + 1 tháng = 28/02)
  - Khi thêm cột mới, không forget tạo migration và upgrade
  - `_parse_date()` helper đã định nghĩa trong trucks.py, không tạo lại ở nơi khác
  - `inspection_should_notify()` và `permit_should_notify()` kiểm tra `days < 0` để vẫn báo khi đã quá hạn
