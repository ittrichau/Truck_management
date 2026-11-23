# Ngày hết hạn giấy tờ xe

Ở **Xe → Thêm/Sửa xe**, nhập ba ngày trực tiếp theo giấy tờ:

- Ngày hết hạn đăng kiểm.
- Ngày hết hạn phù hiệu.
- Ngày hết hạn bảo hiểm.

Không cần nhập ngày cấp hoặc tính lùi theo số tháng. Ngày đã qua vẫn được phép nhập để phản ánh giấy tờ thực tế; để trống nếu chưa biết. Khi sửa, bỏ hẳn một trường khỏi request giữ ngày cũ, gửi trường rỗng xóa ngày. Các tab mở trước cập nhật có trường ngày cấp/thời hạn sẽ được yêu cầu tải lại, không tự ghi đè ngày mới.

Danh sách xe luôn hiển thị ngày hết hạn đã lưu. Nhãn phân biệt **Quá hạn … ngày**, **Hết hạn hôm nay**, **Còn … ngày**; cảnh báo đăng kiểm/phù hiệu ở danh sách phơi tiếp tục dùng cửa sổ 15 ngày và chu kỳ nhắc hiện có. Đổi ngày sẽ reset lịch nhắc của đúng loại giấy tờ; ngày không đổi giữ lịch nhắc.

## Chuyển dữ liệu

Migration `c7e8f901a2b3` nối head `b8d2c4f6a091`, thêm `inspection_expires_on` và `permit_expires_on`. Trước khi thêm cột, kiểm tra các ngày/thời hạn cũ có tính được hay không. Sau đó backfill bằng chính phép tính trước đây (cộng tháng, chặn ngày theo cuối tháng/năm nhuận); giữ nguyên cột cũ, phân quyền, liên kết tài xế, bảo hiểm và lịch nhắc. Trường ngày/tháng cũ thiếu hoặc thời hạn bằng 0 cho kết quả null như trước.

Đây là bảo toàn ngày hệ thống đang hiển thị, không phải tự sửa giấy tờ nhập nhầm. Xe trước đây nhập sai vẫn phải đối chiếu giấy tờ rồi sửa ngày hết hạn thật. Không đoán ngày đúng hoặc cộng thêm tháng từ ngày hết hạn trực tiếp.

## Sao lưu và hoàn tác

Quy trình deploy hiện có tạo và kiểm tra snapshot trước migration. Có thể downgrade ngay sau backfill nếu chưa có ngày trực tiếp nào khác kết quả legacy; sau khi thêm/sửa/xóa ngày, downgrade sẽ bị chặn trước khi drop cột để tránh mất dữ liệu. Khi cần quay lại source cũ, xuất và đối chiếu các ngày trực tiếp đã sửa trước vì code cũ chỉ dùng ngày cấp/tháng. Khôi phục snapshot cần dừng ghi và đối chiếu mọi thay đổi phát sinh sau backup. Không sửa lại migration đã triển khai hoặc tự chuyển ngày hết hạn thành ngày cấp để vượt guard.
