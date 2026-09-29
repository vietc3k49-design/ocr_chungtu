# KIDO OCR — Web local (LOADING_PLAN)

Hợp đồng + quyết định thiết kế: [`SPEC.md`](SPEC.md). Pipeline chạy qua `backend/app/pipeline/runner.py`, gọi đúng module trong `../tools/`, **không viết lại**.

## Chạy
```powershell
cd web
copy .env.example .env      # rồi đặt SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD
docker compose up -d --build
docker compose exec api python -m scripts.seed_demo              # tạo admin (idempotent)
docker compose exec api python -m scripts.seed_demo --with-demo  # + 52 bộ demo (72 ảnh), tham chiếu TẮT
```
| Dịch vụ | Địa chỉ |
|---|---|
| Web | http://localhost:8080 |
| Mailpit (đọc mail xác thực / quên mật khẩu) | http://localhost:8025 |
| API + Swagger | http://localhost:8000/api/docs |
| PostgreSQL | localhost:5433 (chỉ 127.0.0.1, tránh xung đột 5432) |

Gốc repo được mount **read-only** vào `/repo`: web không thể ghi vào `tools/`, `config/`, `output/`. Dữ liệu upload ở volume `kido_data`.
Đổi sang SMTP thật: sửa `SMTP_*`, `MAIL_FROM`, `PUBLIC_BASE_URL` trong `.env` rồi `docker compose up -d api worker`.

## Kiểm tra
```powershell
# Backend test (cần Postgres TẠM, KHÔNG trỏ vào DB compose — conftest drop/create bảng)
docker run -d --name kido_test_pg -e POSTGRES_USER=kido -e POSTGRES_PASSWORD=kido -e POSTGRES_DB=kido_test -p 55432:5432 postgres:16
cd backend; $env:SECRET_KEY="test"; $env:TEST_DATABASE_URL="postgresql+psycopg://kido:kido@localhost:55432/kido_test"
..\..\.venv\Scripts\python.exe -m pytest -q tests
# Smoke E2E trên compose đang chạy (đăng ký → mail → xác thực → upload → worker → duyệt)
..\..\.venv\Scripts\python.exe scripts\smoke_e2e.py
# Parity adapter web vs artifact notebook chính thức (72 ảnh, 52 bộ)
..\..\.venv\Scripts\python.exe scripts\parity_check.py --out ..\..\scratch\_web\parity_win
```
Frontend dev: `cd frontend; npm install; npm run dev` (5173, proxy `/api` → 8000) · mock không cần backend: `npm run dev:mock`.

## Khác biệt so với notebook — ĐỌC trước khi so số
- **Tầng 3 gom lô trong phạm vi 1 bộ upload** (notebook gom trên cả 72 ảnh) ⇒ số lô / ShipmentBatch KHÔNG so thẳng được với 72/0/28.
- **Tham chiếu mã chuyến DEMO (suy từ GT) mặc định TẮT** (notebook bật). Admin bật được ở Quản trị → Cài đặt hoặc khi upload.
- **Linux vs Windows:** trong Docker, Tầng 2 khác ở **6/72 trang** (so GT: 5 trang xấu hơn, 1 trang tốt hơn); **Tầng 1 status 0/72 lệch, Tầng 4 LOADING_PLAN 0/19 lệch**. Ảnh Tầng 1 lệch pixel 35/72 (33 ảnh ≤ 3 mức xám, 2 ảnh khác hẳn), nhưng **4/6 trang lệch T2 có ảnh T1 trùng pixel** ⇒ lệch nằm cả ở OCR Tầng 2 (Tesseract/leptonica Linux hoặc tiền xử lý OpenCV) — chưa tách được. Chạy adapter trên Windows `.venv`: **0 lệch cả T1/T2/T4**. Người dùng đã chọn giữ Docker. Log: `scratch/_web/parity_{win,linux}/parity_report.json`, `scratch/_web/linux_stage1_pixel_diff.log`. ✅ **Đo lại 28/09 sau đợt 9.15** (sửa Tầng 2, AGENTS.md §9.15): T1 **0/72** · T2 **6/72 trang** (đúng 6 file cũ: `BB_NO_HANG__0`, `Hoadon2.2__0`, `Hoadon_3.2__0/__1`, `Hoadon_3.6__0`, `PO_3.11__0`) · T4 LP **0/19** · hồ sơ LP 14/14 khớp ⇒ **thay đổi Tầng 2 KHÔNG làm lệch thêm trên Linux**. Tổng 672.4s; log `scratch/_stage2_fix_2809/parity_linux_after.log`.
- Ngưỡng Tầng 1 là bản **nới cho ảnh demo** (`STAGE1_CFG_KW` trong runner, lấy từ runner chính thức) — ảnh scan thật nên siết lại.

## Rủi ro đã biết
✅ Giới hạn đăng nhập sai: 5 lần/email hoặc 20 lần/IP trong 15 phút ⇒ khóa 15 phút (429 `TOO_MANY_ATTEMPTS`); admin gỡ ở Quản trị → Người dùng; tham số `LOGIN_*` trong `.env`. ⚠️ Docker Desktop: mọi request từ host cùng IP gateway ⇒ giới hạn theo IP = giới hạn **chung** toàn hệ thống (ổn khi chỉ 127.0.0.1; mở LAN phải xem lại) · logout chỉ xóa cookie (JWT sống tới hết hạn, trừ khi đổi mật khẩu) · engine chữ ký ver2 thiết kế trên chính ảnh demo (AGENTS.md §9.11.D) — cần ảnh thật (bút đen, photo BW, phiếu thiếu chữ ký) · `GET /groups` tính lại phán quyết hồ sơ sau duyệt mỗi lần gọi (chậm khi nhiều bộ).
