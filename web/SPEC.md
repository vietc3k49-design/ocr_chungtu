# KIDO OCR Web — SPEC v1 (LOADING_PLAN)

Nguồn quyết định: người dùng chốt 27/09/2026 (memory `kido-web-lp-roadmap`). Mọi agent đọc file này trước.

## 0. Nguyên tắc bắt buộc (đọc `D:\OCR_chuki\AGENTS.md` §0, §9.13 nếu cần bối cảnh)
- **Không viết lại pipeline.** Chỉ gọi `web/backend/app/pipeline/runner.py::run_upload_group` (đã có, đã kiểm parity). Không sửa gì trong `tools/`, `config/`, `output/`, notebook.
- **Không PASS giả / không đoán:** trang không phải `LOADING_PLAN` hoặc zone ABSTAIN ⇒ hiển thị "Chưa hỗ trợ kiểm chữ ký" / "Không xác định được vùng ký" — **không bao giờ hiện là ĐẠT**. Trạng thái lạ ⇒ hiển thị nguyên mã + "Cần kiểm tra", không map bừa.
- Kết quả máy bất biến; duyệt tay append-only (`app/models.py` docstring).
- Tham chiếu mã chuyến demo **mặc định TẮT**; chỉ admin bật (setting `use_reference_default` hoặc cờ khi upload). Mỗi bộ ghi rõ `use_reference`, UI hiện badge "Dùng dữ liệu tham chiếu DEMO (suy từ GT)" khi bật.
- Tầng 3 chạy trong phạm vi **một bộ upload** (`stage3_scope = UPLOAD_GROUP`).
- UI **tiếng Việt**. Chỉ nhận **JPG/PNG** (kiểm magic bytes bằng Pillow, không tin phần mở rộng).

## 1. Cấu trúc & phân chia file (mỗi agent CHỈ sửa file của mình)
```
web/
  SPEC.md                         (lead)
  docker-compose.yml, .env.example, README.md      (lead)
  backend/
    Dockerfile, requirements.txt, tessdata/        (lead)
    app/core/config.py, app/core/db.py, app/models.py   (lead — ĐÃ CÓ; cần đổi thì báo lead)
    app/pipeline/runner.py                          (lead — ĐÃ CÓ)
    scripts/parity_check.py                          (lead)
    alembic.ini, alembic/                            (Agent AUTH) — migration đầu tiên tạo MỌI bảng trong models.py
    app/core/security.py, app/core/mail.py           (Agent AUTH)
    app/api/deps.py, app/api/auth.py, app/api/admin.py  (Agent AUTH)
    app/main.py                                      (Agent AUTH) — include router của cả 2 agent (groups, pages)
    app/labels.py                                    (Agent JOBS) — nhãn tiếng Việt cho mã trạng thái (backend trả kèm)
    app/api/groups.py, app/api/pages.py              (Agent JOBS)
    app/services/storage.py, app/services/review.py  (Agent JOBS)
    app/worker.py                                    (Agent JOBS)
    scripts/seed_demo.py                             (Agent JOBS)
    tests/test_auth_*.py                             (Agent AUTH)
    tests/test_jobs_*.py, tests/test_review_*.py     (Agent JOBS)
  frontend/                                          (Agent FE) — toàn bộ
```
`app/api/deps.py` (Agent AUTH) export: `get_db`, `get_current_user` (401 nếu chưa đăng nhập, 403 `EMAIL_NOT_VERIFIED`/`USER_INACTIVE`), `require_admin`. Agent JOBS import từ đó; nếu cần trước khi AUTH xong, dùng đúng chữ ký này.

## 2. Auth
- Mật khẩu: argon2 (`argon2-cffi`). Tối thiểu 8 ký tự.
- Phiên: JWT HS256 (`secret_key`) trong **cookie httpOnly** `kido_session`, SameSite=Lax, `Secure` theo `cookie_secure`. Frontend gọi cùng origin (nginx/vite proxy `/api`) nên không cần CORS. Mọi request đổi trạng thái (POST/PUT/PATCH/DELETE) yêu cầu header `X-Requested-With: kido` (chống CSRF đơn giản).
- Đăng ký mở: `role=user`, `email_verified_at=NULL` ⇒ gửi mail xác thực. **Chưa xác thực ⇒ không đăng nhập được** (403 `EMAIL_NOT_VERIFIED`).
- Token mail: `secrets.token_urlsafe(32)`, DB lưu sha256; dùng 1 lần; hết hạn theo config. Link: `{public_base_url}/xac-thuc-email?token=...`, `{public_base_url}/dat-lai-mat-khau?token=...`.
- Các endpoint trả lời trung tính để không lộ email tồn tại (resend, forgot).
- Admin đầu tiên: `scripts/seed_demo.py` tạo từ `ADMIN_EMAIL`/`ADMIN_PASSWORD` (đã verify). Admin không tự hạ quyền / khóa chính mình, luôn còn ≥ 1 admin active.
- **Giới hạn đăng nhập sai** (`app/services/login_limit.py`, bảng `login_attempts`): ≥ `LOGIN_MAX_FAILS_PER_EMAIL` (5) lần sai/email hoặc ≥ `LOGIN_MAX_FAILS_PER_IP` (20) lần sai/IP trong `LOGIN_WINDOW_MINUTES` (15) ⇒ 429 `TOO_MANY_ATTEMPTS` + `Retry-After` + `detail.retry_after_seconds`, khóa `LOGIN_LOCKOUT_MINUTES` (15) từ lần sai cuối. Kiểm trước mật khẩu; áp cả email không tồn tại. Đặt lại bộ đếm email: đăng nhập đúng, đặt lại mật khẩu, `POST /admin/users/{id}/unlock-login`. `GET /admin/users` trả thêm `login_locked`, `login_locked_until`, `login_recent_fails`.
- Ghi `audit_log` cho: login_locked, login_unlock, register, verify_email, login_ok, login_fail, logout, password_reset, role_change, active_change, setting_change, upload_create, review_create, rerun.

## 3. API (tiền tố `/api`, JSON, lỗi dạng `{"detail": {"code": "...", "message": "tiếng Việt"}}`)
### Auth (Agent AUTH)
| Method | Path | Body | Trả |
|---|---|---|---|
| POST | /auth/register | {email, password, full_name} | 201 {message} |
| POST | /auth/verify-email | {token} | {message} |
| POST | /auth/resend-verification | {email} | {message} (trung tính) |
| POST | /auth/login | {email, password} | UserOut + set cookie |
| POST | /auth/logout | – | {message}, xóa cookie |
| GET | /auth/me | – | UserOut |
| POST | /auth/forgot-password | {email} | {message} (trung tính) |
| POST | /auth/reset-password | {token, new_password} | {message} |
| POST | /auth/change-password | {old_password, new_password} | {message} |

`UserOut = {id, email, full_name, role, is_active, email_verified: bool, created_at}`

### Admin (Agent AUTH, `require_admin`)
| GET | /admin/users | ?q= | [UserOut + last_login_at] |
| PATCH | /admin/users/{id} | {role?, is_active?} | UserOut |
| GET | /admin/settings | – | {use_reference_default: bool} |
| PUT | /admin/settings | {use_reference_default: bool} | như GET |
| GET | /admin/audit | ?limit=200 | [AuditLog] |

### Bộ upload (Agent JOBS)
| Method | Path | Ghi chú |
|---|---|---|
| POST | /groups | multipart: `files` (nhiều, **thứ tự trong form = scan_index 0..n-1**), `title?`, `use_reference?` (chỉ admin được đặt; user ⇒ bỏ qua, dùng setting). Kiểm: 1..`max_files_per_upload` file, mỗi file ≤ `max_file_mb`, Pillow mở được và format ∈ {JPEG, PNG}. Lưu `data_dir/uploads/{group_id}/{scan_index:03d}_{sha8}.{jpg|png}`. Tạo Job queued. Trả GroupDetail (201). |
| GET | /groups | của mình; admin thêm `?all=true`. Trả [GroupSummary]. |
| GET | /groups/{id} | GroupDetail. Chủ sở hữu hoặc admin, không thì 404. |
| GET | /groups/{id}/status | {status, job: {status, stage, stage_done, stage_total, percent, message, error}} — frontend poll 1.5s. |
| POST | /groups/{id}/rerun | chủ/admin; chỉ khi DONE/FAILED; tạo job mới; kết quả cũ bị thay (duyệt tay cũ vẫn giữ nhưng gắn cờ `stale` nếu target không còn khớp role). |

`GroupSummary = {id, title, status, n_pages, use_reference, created_at, finished_at, owner_email, n_lp_pages, lp_dossier_summary: {status: count}}`
`GroupDetail = GroupSummary + {pages: [PageSummary], dossiers: [...stage4_dossiers.dossiers kèm label_vi], batches: [{batch_id, n_documents, is_isolated}], reference_info, timings, stage3_scope: "UPLOAD_GROUP", job}`
`PageSummary = {id, scan_index, original_filename, width, height, s1_status, doc_type, doc_type_vi, system, page_role, batch_id, s4_doc_status, s4_action, status_label_vi, status_tone, supported: bool (doc_type == LOADING_PLAN), reviewed: bool, effective_doc_status}`
`status_tone ∈ {success, warning, danger, neutral, info}` — do `app/labels.py` quyết định; FE chỉ tô màu theo tone.

### Trang (Agent JOBS)
| GET | /pages/{id} | PageDetail |
| GET | /pages/{id}/image?kind=original\|stage1 | FileResponse, kiểm quyền. `stage1` là ảnh mà box_norm quy chiếu (resize về H=2200 theo `s4.a4_size` — box_norm là tỉ lệ nên vẽ đúng trên ảnh stage1 bất kể kích thước). |
| POST | /pages/{id}/targets/{i}/review | {decision ∈ SIGNED/NOT_SIGNED/UNCLEAR, note} — chủ hoặc admin. Trả PageDetail mới. |
| GET | /pages/{id}/reviews | lịch sử đầy đủ (append-only) |

`PageDetail = PageSummary + {s1: {status, action, warns, rejects, source_type, low_resolution, effective_dpi?}, s2: {doc_type, system, page_role, confidence, status, key_fields, evidence}, s4: {zone_status, zone_description, modality, doc_status, action, reason, required_policy, a4_size, targets: [TargetOut]}, effective: {doc_status, action, reason, n_overridden}}`
`TargetOut = {index, role, required, required_source, policy_channel, box_norm [ymin,xmin,ymax,xmax] tỉ lệ 0..1, detected, confidence, evidence, reason, review_required, latest_review: {decision, note, reviewer_email, created_at} | null, effective_detected: bool|null}`

**Phán quyết sau duyệt (`effective`)** — `app/services/review.py`: lấy `s4.targets`, với ô có review mới nhất: SIGNED ⇒ detected=True, NOT_SIGNED ⇒ detected=False, UNCLEAR ⇒ `review_required=True`; gọi `tools.stage4_verifier_v2.evaluate_document_verdict_v2(targets, is_color=(s4.modality=="TRUE_COLOR"))`. Trang không có targets ⇒ effective = máy. **Không tự viết luật verdict.** Hồ sơ đa trang sau duyệt: gọi `tools.stage4_required_policy.evaluate_lp_dossier_verdicts` với page_results đã thay targets hiệu lực + `group.stage3_manifest`.

Tọa độ `box_norm` = `[ymin, xmin, ymax, xmax]` (tỉ lệ theo chiều cao/rộng ảnh A4).

## 4. Worker (Agent JOBS) — `python -m app.worker`
- Vòng lặp: `SELECT ... FROM jobs WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1` → running, `locked_by=hostname:pid`, `started_at`.
- Khởi động: job `running` có `heartbeat_at` cũ hơn `job_stale_minutes` ⇒ đưa về `queued` (attempts+1; attempts > 3 ⇒ failed).
- Gọi `run_upload_group(pages=[{path: stored_path, file_name: stored_filename, scan_index}], group_id=str(group.id), work_dir=data_dir/work/{group_id}, use_reference=group.use_reference, stage1_workers=settings.worker_stage1_processes, progress=cb)`.
- `percent` toàn job: T1 0–40, T2 40–80, T3 80–85, T4 85–98, SAVE 98–100 (theo stage_done/stage_total). Ghi DB tối đa mỗi 0.5s + heartbeat.
- Lưu: `pages.s1/s2/s4` + cột phẳng (s4 lấy theo `file_name == stored_filename`), `pages.stage1_image_path = s1.output.image`, `batch_id` từ s4; `group.stage3_manifest/stage4_dossiers/reference_info/timings/pipeline_contract`; status DONE. Lỗi ⇒ traceback vào `job.error`, group FAILED + `error` ngắn tiếng Việt.

## 5. Seed (Agent JOBS) — `python -m scripts.seed_demo [--with-demo]`
- Tạo admin từ env (idempotent). `--with-demo`: đọc `{repo}/output/stage2_upload_groups.json`, tạo 52 bộ (title = `DEMO {sheet}`) dưới tên admin, file theo đúng `scan_index`, `use_reference` theo cờ `--reference` (mặc định tắt), enqueue job. Tên file gốc giữ ở `original_filename`.

## 6. Frontend (Agent FE) — React 18 + Vite + TypeScript + React Router; không cần UI kit nặng (CSS thuần/CSS modules). Route tiếng Việt:
`/dang-nhap`, `/dang-ky`, `/xac-thuc-email`, `/quen-mat-khau`, `/dat-lai-mat-khau`, `/` (danh sách bộ upload), `/tai-len`, `/bo/:id`, `/trang/:id`, `/quan-tri/nguoi-dung`, `/quan-tri/cai-dat`, `/tai-khoan`.
- **Tải lên:** kéo-thả nhiều JPG/PNG, thumbnail, kéo để sắp thứ tự (thứ tự = scan_index, ghi rõ "Trang 1, 2, …"), xóa trang, tiêu đề; admin thấy checkbox tham chiếu DEMO kèm cảnh báo.
- **Bộ upload:** thanh tiến độ T1→T2→T3→T4 (poll `/status` 1.5s đến DONE/FAILED); bảng hồ sơ LOADING_PLAN (phán quyết máy + sau duyệt); bảng mọi trang (loại chứng từ, kênh, trường khóa, trạng thái; trang không phải LP: nhãn "Chưa hỗ trợ kiểm chữ ký").
- **Trang (màn chính):** ảnh stage1 với khung các ô ký vẽ theo `box_norm` (SVG overlay, `viewBox` theo kích thước ảnh tự nhiên); màu: xanh = có chữ ký, đỏ = required mà không thấy, xám = optional không thấy, cam = cần kiểm tra tay; nét liền = required, nét đứt = optional. Click ô ⇒ panel: crop phóng to (canvas/CSS background-position), role, required + nguồn chính sách, evidence, confidence; 3 nút duyệt "Có chữ ký" / "Không có chữ ký" / "Không rõ" + ô ghi chú; lịch sử duyệt. Hiện phán quyết máy vs sau duyệt cạnh nhau. Trang zone ABSTAIN/không phải LP: hiện ảnh + thông tin T1/T2, thông báo rõ lý do, không vẽ khung.
- Header: tên người dùng, menu Quản trị (admin), Đăng xuất. Mọi fetch `credentials: 'include'`, header `X-Requested-With: kido`; 401 ⇒ về `/dang-nhap`.
- Dev: `vite.config.ts` proxy `/api` → `http://localhost:8000`. Prod: `frontend/Dockerfile` build rồi nginx phục vụ, proxy `/api` → `http://api:8000`, `client_max_body_size 1g`.

## 7. Cổng / dịch vụ docker compose (lead)
`db` postgres:16 (5432 nội bộ) · `mailpit` (UI http://localhost:8025) · `api` uvicorn :8000 · `worker` · `web` nginx :8080. Repo gốc mount **read-only** vào `/repo`; dữ liệu ở volume `kido_data:/data`.
