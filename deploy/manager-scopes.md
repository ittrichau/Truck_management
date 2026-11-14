# Phân quyền theo quản lý

Sau triển khai, đăng nhập admin → **Phân quyền** (điện thoại: **Thêm → Phân quyền quản lý**), hoặc `/admin/management`.

1. Gán xe cho quản lý. Tài xế đang giữ xe tự chuyển cùng; không đổi liên kết xe/tài xế.
2. Gán tài xế chưa giữ xe ở mục Tài xế; sau đó chọn xe cùng quản lý ở trang sửa tài xế/xe.
3. Đánh dấu các quản lý được dùng từng khách hàng; có thể cấp chung. Dữ liệu admin tạo mới chưa gán mặc định chỉ admin quản lý.

Quản lý chỉ nhìn thấy xe/tài xế/khách được cấp. Phơi, công nợ, nhiên liệu và chứng từ theo xe; kể cả lịch sử trước ngày chuyển xe. Khách hàng của các chuyến lịch sử vẫn xuất hiện trong công nợ của xe sau chuyển, nhưng cần được cấp danh mục để chọn trong phơi mới. Khi sửa đúng phơi, lựa chọn khách cũ được giữ. Tài xế vẫn xem phơi của mình; danh sách xe chạy giùm/khách được giới hạn trong nhóm.

Thu tiền khách dùng chung chỉ phân bổ vào chuyến thuộc xe quản lý đang có quyền; admin phân bổ toàn bộ như trước. Tiền vượt nợ trong phạm vi không được ghi sang xe quản lý khác. Công thức đối chiếu tài xế và lợi nhuận không đổi.

Khách dùng chung chỉ admin được xóa. Không xóa/hạ vai trò quản lý còn xe, tài xế hoặc khách được cấp; chuyển/bỏ cấp hết trước. Nhật ký cũ chưa có scope chỉ admin xem. Thu hồi quyền danh mục khách không xóa nợ/chuyến lịch sử.

## Sao lưu và migration

Revision mới: `a1c2e3f4b5d6` sau `f8a9b0c1d2e3`. Bản ghi cũ không tự gán theo người tạo.

Deploy build image trước, chạy `python -m deploy.backup_database` bằng container dùng chung volume/DB nhưng override entrypoint, rồi mới thay container web và chạy migration. Lỗi backup ngăn deploy, web cũ tiếp tục chạy. Backup lưu trong volume `instance/backups` (chủ file UID 10001, mode 0600); không công khai thư mục này. SQLite được backup qua online backup API và kiểm tra integrity. PostgreSQL dùng pg_dump custom, xác minh danh sách bằng pg_restore; mật khẩu truyền qua môi trường. Chưa thử restore PostgreSQL thực trong môi trường kiểm thử này.

## Hoàn tác

Ưu tiên quay lại source trước thay đổi và giữ các cột/bảng bổ sung để không mất phân quyền. Source cũ cho quản lý thấy chung dữ liệu, nên cần cân nhắc trước khi quay lại.

Nếu phải khôi phục DB từ snapshot: dừng web và mọi tiến trình ghi, giữ bản sao DB hiện tại và đối chiếu các giao dịch phát sinh sau thời điểm backup, khôi phục snapshot bằng công cụ DB tương ứng rồi khởi chạy source phù hợp schema. Không chép đè SQLite đang chạy. Không tự downgrade trên production: downgrade xóa gán quyền và scope nhật ký.
