# Deploy Truck Management lên Ubuntu VPS bằng Docker

Tài liệu này áp dụng cho VPS Linux/Ubuntu có IP `180.93.117.107`. Ứng dụng hiện đã có Dockerfile, Docker Compose, Gunicorn và endpoint kiểm tra sức khỏe `/health`.

> Không gửi mật khẩu VPS, `SECRET_KEY`, hoặc file `.env` vào GitHub/chat. Đổi mật khẩu `root` ngay sau lần đăng nhập đầu tiên.

## 1. Chuẩn bị DNS và firewall

Nếu dùng tên miền, tạo bản ghi **A** cho tên miền (ví dụ `app.example.com`) trỏ đến `180.93.117.107`. Đợi DNS cập nhật trước khi cấp HTTPS.

Trong cổng quản trị VPS/cloud, mở inbound TCP: **22** (SSH), **80** (HTTP), **443** (HTTPS). Không mở port `5000` ra Internet.

## 2. Đăng nhập và cài Docker

Đăng nhập từ PowerShell trên máy cá nhân:

```text
ssh root@180.93.117.107
```

Trên VPS Ubuntu, chạy lần lượt:

```bash
apt update && apt upgrade -y
apt install -y ca-certificates curl git nginx certbot python3-certbot-nginx ufw openssl
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker nginx
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
```

Kiểm tra Docker Compose:

```bash
docker compose version
```

## 3. Clone mã nguồn và tạo biến môi trường

Tạo deploy key *read-only* trong VPS nếu repository GitHub là private:

```bash
ssh-keygen -t ed25519 -C "truck-management-vps"
cat ~/.ssh/id_ed25519.pub
```

Thêm public key vừa in vào GitHub repository: **Settings → Deploy keys → Add deploy key** (không chọn quyền ghi). Sau đó clone repository:

```bash
mkdir -p /opt/truck-management
cd /opt/truck-management
git clone git@github.com:YOUR_GITHUB_USER/YOUR_REPOSITORY.git .
```

Tạo file cấu hình bí mật (không commit file này):

```bash
cp .env.example .env
sed -i 's/^SECRET_KEY=.*/SECRET_KEY='"$(openssl rand -hex 32)"'/' .env
sed -i 's|^DATABASE_URL=.*|DATABASE_URL=sqlite:///instance/truck_management.db|' .env
```

Bổ sung cuối file `.env`:

```text
SEED_DEFAULT_DATA=false
```

`SEED_DEFAULT_DATA` mặc định tắt để không tự tạo tài khoản mẫu có mật khẩu công khai. Chỉ đặt `true` đúng **lần triển khai đầu tiên** nếu muốn lấy dữ liệu mẫu, sau đó đổi ngay mật khẩu các tài khoản hoặc đặt lại về `false` và deploy lại.

Với SQLite một VPS, dữ liệu và file tải lên nằm trong thư mục `instance/`. Cần sao lưu thư mục này định kỳ. Khi lượng dữ liệu/tải đồng thời tăng, chuyển sang PostgreSQL.

## 4. Chạy ứng dụng

Chuẩn bị các bind mount để container có quyền ghi. Image chạy bằng user có UID/GID `10001`.

```bash
mkdir -p instance/uploads logs data
chown -R 10001:10001 instance logs data
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 web
curl http://127.0.0.1:5000/health
```

Kết quả kiểm tra mong đợi:

```json
{"status":"ok","db":"ok"}
```

Docker Compose chỉ bind cổng `5000` vào loopback (`127.0.0.1`) để Nginx chuyển tiếp; port này không công khai ra Internet.

## 5. Cấu hình Nginx

Copy file mẫu và **thay toàn bộ** `YOUR_DOMAIN` bằng domain thực tế:

```bash
cp deploy/nginx/truck-management.conf /etc/nginx/sites-available/truck-management
nano /etc/nginx/sites-available/truck-management
ln -s /etc/nginx/sites-available/truck-management /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

Nếu chưa có domain, có thể truy cập tạm qua `http://180.93.117.107` sau khi sửa `server_name` thành `180.93.117.107 _;`. Không thể cấp chứng chỉ HTTPS tin cậy chỉ cho IP.

## 6. Cấp HTTPS

Sau khi DNS trỏ đúng IP và Nginx hoạt động:

```bash
certbot --nginx -d YOUR_DOMAIN -d www.YOUR_DOMAIN
systemctl status certbot.timer
```

Nếu không dùng `www`, chỉ truyền `-d YOUR_DOMAIN`. Certbot sẽ tự thêm redirect HTTP sang HTTPS. Khi HTTPS đã chạy, production config sẽ gửi session cookie bảo mật.

## 7. Cập nhật phiên bản mới

```bash
cd /opt/truck-management
git pull --ff-only
docker compose up -d --build
docker image prune -f
docker compose logs --tail=100 web
```

Entrypoint tự chạy `flask db upgrade` trước khi Gunicorn khởi động. Không chạy `flask seed-data` trừ khi `SEED_DEFAULT_DATA=true`.

## 8. Sao lưu và khôi phục

Sao lưu database SQLite và upload; dừng app ngắn để copy DB nhất quán:

```bash
cd /opt/truck-management
docker compose stop web
tar -czf /root/truck-management-backup-$(date +%F).tar.gz instance
docker compose start web
```

Tải file backup về máy an toàn hoặc storage khác. Khôi phục bằng cách dừng `web`, giải nén đè lại thư mục `instance/`, sửa ownership `chown -R 10001:10001 instance`, rồi khởi động lại container.

## Vận hành nhanh

```bash
cd /opt/truck-management
docker compose ps
docker compose logs -f web
docker compose restart web
curl -fsS http://127.0.0.1:5000/health
```
