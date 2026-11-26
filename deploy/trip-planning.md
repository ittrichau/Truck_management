# Kế hoạch chuyến hàng của quản lý

Mở **Kế hoạch** trên desktop hoặc **Thêm → Kế hoạch chuyến hàng** trên điện thoại. Chỉ manager/admin được vào; manager chỉ thao tác kế hoạch và phơi trong phạm vi của mình. Kế toán và tài xế không có quyền truy cập trang này.

Mỗi kế hoạch gồm xe, tài xế dự kiến (có thể chưa phân công), khách hàng, tuyến, hàng, ngày đi/ngày về dự kiến và tối đa 20 chặng hàng về. Xe phải được giao cho một quản lý đang hoạt động. Không cần nhập giờ. Lịch theo ngày và bảng đối chiếu dùng chung bộ lọc khoảng ngày, xe, tài xế, khách đi/về, trạng thái và tìm kiếm. Mặc định tháng hiện tại theo giờ Việt Nam; khoảng lọc tối đa 366 ngày chênh lệch, 30 kế hoạch mỗi trang. Chuyến bắt đầu trước kỳ nhưng chưa về vẫn xuất hiện.

## Liên kết và cập nhật thực tế

- Khi tài xế chốt phơi thành công, đồng bộ bằng một giao dịch riêng. Không yêu cầu thao tác mới của tài xế và không đổi điều kiện dầu/KM để chốt phơi.
- Tự ghép khi cùng xe, cùng khách đã xác định, ngày đi trong khoảng ±7 ngày và chỉ có một ứng viên ở cả hai phía. Không tự ghép chỉ dựa vào ngày hoặc khi thiếu khách. Có nhiều ứng viên thì quản lý chọn ở chi tiết kế hoạch. Mỗi phơi chỉ liên kết một kế hoạch.
- Phơi nháp có thể hiển thị như gợi ý thực tế tạm thời, chưa tự tạo liên kết hoặc lịch sử khi xem. Quản lý có thể liên kết thủ công; chỉ phơi đã chốt/xác nhận mới được chấp nhận đối soát.
- Sửa hoặc hủy phơi đã liên kết cập nhật lại thực tế; thay đổi thông tin sau khi đã kiểm tra làm mở lại cảnh báo. Xác nhận tài chính thuần túy không làm thay đổi dữ liệu chuyến.
- Lỗi đồng bộ không rollback phơi đã lưu; có ghi log phía server. Mở chi tiết kế hoạch và chọn **Đồng bộ lại từ phơi**, hoặc chọn phơi để liên kết khi không có kết quả duy nhất.
- Quản lý có thể **Cập nhật kế hoạch theo thực tế**, **Đã kiểm tra, giữ kế hoạch**, sửa kế hoạch hoặc thay/gỡ liên kết. Mọi thay đổi có lịch sử trước/sau và lý do; kế hoạch ban đầu vẫn được giữ. Các thao tác này không sửa phơi, tiền, nhiên liệu hoặc gán xe mặc định cho tài xế.
- Form có phiên bản kế hoạch và dấu nhận diện dữ liệu thực tế để chặn việc chấp nhận dữ liệu vừa thay đổi mà người dùng chưa xem.

Khoảng cách chuyến lấy ngày đi chuyến sau trừ ngày về chuyến trước, ưu tiên dữ liệu phơi khi đã xác định. Bằng 0 là về và đi tiếp cùng ngày, không tự coi là trùng lịch. Âm là chồng ngày; thiếu ngày về thì không suy đoán. Cảnh báo xét cả xe và tài xế. Phơi không có chặng về không đồng nghĩa xe đã về rỗng. Chuyến chưa liên kết được hiển thị riêng để kiểm tra, không tự kết luận thất thoát doanh thu.

Chuyển xe/phơi sang quản lý khác không tự chuyển quyền sở hữu kế hoạch cũ. Kế hoạch có liên kết vượt phạm vi bị ẩn với manager; đồng bộ không ghi dữ liệu quản lý mới vào kế hoạch cũ. Admin kiểm tra và điều chỉnh liên kết khi cần.

## Migration và hoàn tác

Migration `d8e9f0a1b2c3` nối head `c7e8f901a2b3`, chỉ tạo bảng `trip_plans` và `trip_plan_history`, không backfill hoặc sửa phơi/xe/tài chính hiện có. Cần nâng schema trước khi sử dụng source mới, qua quy trình deploy/snapshot đang dùng. Lệnh Flask tương ứng trong môi trường đã cấu hình đúng database:

```sh
flask --app run.py db upgrade
```

Không chạy lệnh này với database thực trong quá trình kiểm thử. Bản thay đổi được kiểm tra bằng SQLite trong bộ nhớ, gồm nâng/hạ/nâng và giữ dữ liệu cũ. Chưa xác thực PostgreSQL, tải dữ liệu lớn hoặc chạy đồng thời trên nhiều worker. Trang lịch còn đọc các kế hoạch trong phạm vi để tính khoảng cách đến chuyến tiếp, kể cả chuyến ngoài kỳ lọc.

Có thể quay lại source cũ và giữ nguyên hai bảng bổ sung. Nếu chưa có kế hoạch, có thể downgrade về `c7e8f901a2b3`. Khi đã có kế hoạch, downgrade bị chặn để bảo vệ lịch sử: cần xuất dữ liệu và chủ động xử lý dữ liệu kế hoạch trước khi gỡ bảng. Không khôi phục snapshot cũ để bỏ tính năng nếu chưa đối chiếu những phơi/tài chính phát sinh sau snapshot.
