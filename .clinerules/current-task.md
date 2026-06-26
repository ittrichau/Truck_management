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
