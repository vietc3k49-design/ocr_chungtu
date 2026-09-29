# Hệ Thống Kiểm Tra & Đối Soát Chứng Từ Giao Nhận KIDO

Hệ thống OCR & Computer Vision phục vụ tự động hóa kiểm tra, gom lô và nghiệm thu chứng từ giao nhận vận tải cho Tập đoàn KIDO theo quy chuẩn kế toán & kiểm soát nội bộ.

> **Cập nhật:** 2026-09-27 (đêm — **WEB LOCAL `LOADING_PLAN`**, `AGENTS.md` §9.14, code [`web/`](web/README.md)). FastAPI + React + PostgreSQL + Mailpit + worker, **toàn bộ Docker Linux**: `cd web && docker compose up -d --build` → http://localhost:8080. Đăng nhập + xác thực email, admin/user, upload **1 bộ nhiều trang** (web cấp `upload_group_id` + `scan_index`), tiến độ T1→T4, khung ô ký + **duyệt tay append-only**. Adapter gọi `tools/` không viết lại — parity **Windows 0 lệch** (T1 72/72, T2 72/72, T4 LP 19/19); ⚠️ **Docker Linux: T2 khác 6/72 trang** (5 xấu hơn / 1 tốt hơn theo GT; 4/6 trang ảnh T1 trùng pixel ⇒ lệch ở OCR T2), T4 LP 0/19 lệch — người dùng chấp nhận. Backend test **133/133** (kể cả giới hạn đăng nhập sai).
> **Cập nhật trước:** 2026-09-27 (tối — **đợt "HOÀN THIỆN 4 NOTEBOOK"**, `AGENTS.md` §9.13). 4 notebook chính thức + E2E sinh lại bằng generator mỏng; chuỗi chạy chính thức 2 lần **DIFF = 0** cả 5 artifact (thứ tự lệnh: §2.B). Tầng 1 hết từ chối oan `THU_HOI_4.2__0` (❗ **không phải "ảnh trắng"**). Tầng 2 **gỡ phụ thuộc tên file** — vote theo `upload_group_id` + `scan_index`. Tầng 3 R **72.00%** (72/0/28) ⇒ `test_stage3_suite.py` **FAIL, không hạ ngưỡng** — số cũ 81% dựa vào gom theo tên file. Tầng 4 ver2: 62 biến thể thiếu chữ ký tổng hợp — **72/72 ô bị xóa phát hiện, 0 ca thiếu required ra DAT** (v1 0/72).
> **Cập nhật trước:** 2026-09-27 (khuya — **Giai đoạn 5 hoàn tất**, `AGENTS.md` §9.12). Chữ ký bắt buộc `LOADING_PLAN` nay **theo kênh SOP** (sheet Guideline, người dùng duyệt; `config/stage4_lp_required_policy.json`) ⇒ 14/14 trang có khối ký `DAT_CHUAN_GOC` (trước 3), 0 ô đổi `detected`; phán quyết **hồ sơ đa trang** 14/14 DAT. Tầng 3 tách mã chuyến demo ra `config/stage3_shipment_reference.json` — không có nó Recall chỉ **56.00%** (P 91.80%). **E2E `LOADING_PLAN` nay chạy engine ver2** (❗ trước chạy v1), `test_pipeline_e2e.py` 22/22. Tool lỗi thời chuyển sang `scratch/_archive_tools/`.
> **Cập nhật trước:** 2026-09-27 (tối — Giai đoạn 4 hoàn tất, `AGENTS.md` §9.11). Nguyên nhân TN = 0 là **scale ×2.6 làm vỡ ngưỡng pixel tuyệt đối** (không phải cân sáng); engine chữ ký ver2 viết lại theo mm ⇒ GT production v4 (69 ô): **ver2 P = R = 100%** vs v1 P 63.77% — ⚠️ **không phải ước lượng tổng quát hóa** (engine thiết kế sau khi xem toàn bộ GT, holdout thật chỉ 5 ô, chưa đo bút đen/BW); hộp tĩnh ver2 R 13.33% nên v1 giữ cho hộp tĩnh. Tầng 3b: `Load_3.5__0` hết ABSTAIN. Tầng 3: gỡ rule đoán mò ⇒ R 85.00% → 81.00%, 25 lô.
> **Cập nhật trước:** 2026-09-27 (cuối chiều — Giai đoạn 1a/1b/2/3). Manifest chính thức Tầng 4 ver2 **đã sinh lại**; E2E hết PASS giả `KHONG_YEU_CAU`; Tầng 3b chuẩn hóa về H=2200; GT thứ ba trên đúng đường production cho thấy **v1 = ver2 = P 64.06%, TN 0** trên zone động `LOADING_PLAN` ⇒ **ĐÍNH CHÍNH** kết luận cũ "ver2 hơn v1" (đo trên ảnh raw ~850px). Mọi chỉ số dưới đây lấy trực tiếp từ artifact trong `output/`. Chi tiết kiến trúc, bài học và nợ kỹ thuật: [`AGENTS.md`](file:///d:/OCR_chuki/AGENTS.md).

---

## 1. Bức Tranh Toàn Hệ Thống (8 thành phần: 7 tầng/pipeline + web)

| Thành phần | Trọng tâm công nghệ | Notebook | Trạng thái | Đầu ra chính |
|---|---|---|:---:|---|
| **Tầng 1**<br>Chuẩn hóa ảnh | OpenCV rule-based, nắn A4, xoay 4 hướng, cân sáng bảo toàn mộc đỏ & mực xanh. Gác cổng đúng contract: **0 ảnh rò**; **đợt 9.13:** `DAT` 13 · `CANH_BAO` 59 · `CHUP_LAI` **0** (hết từ chối oan `THU_HOI_4.2__0`), JSON 35 khóa mọi trang, 66.6s / 72 ảnh, tái lập DIFF = 0 | [`ocr-tang1-ver2.ipynb`](file:///d:/OCR_chuki/ocr-tang1-ver2.ipynb) *(viết lại mỏng: `tools/generate_nb1.py`)* | ✅ Đã sửa xong | `output/stage1_out/` |
| **Tầng 2**<br>Phân loại chứng từ | Fast Header OCR + RapidFuzz + Confidence Gate; **vote đa trang theo `upload_group_id` + `scan_index`, 0 phụ thuộc tên file** (đợt 9.13). doc_type **98.61%**, page_role **98.61%**, Trục 2 strict **87.50%** / cấp họ **91.67%** (đợt 9.15), `shipment_id` P 95.7% R 84.6%, `DAT` 70/72 (report v3.5.0) | [`ocr-tang2-classify.ipynb`](file:///d:/OCR_chuki/ocr-tang2-classify.ipynb) *(`tools/generate_nb2.py`)* | ✅ Đã sửa xong | `output/stage2_out/stage2_classified_results.json` |
| **Tầng 3**<br>Gom lô & đối soát | **Đợt 9.13:** guard G1/G2 Pass 3.2 + tách lô thu hồi theo biểu mẫu ⇒ ShipmentBatch **72/0/28 · P 100% · R 72.00% · F1 83.72% · 28 lô**, Reconciliation 6/8 ⇒ **suite FAIL ngưỡng R 80%, không hạ ngưỡng** (số cũ dựa vào gom theo tên file ở Tầng 2). *Lịch sử Giai đoạn 5:* 4-Pass Shipment Resolver, Zero Filename Leakage. Multi-page F1 **100%**; ShipmentBatch **có tham chiếu demo**: P **100% (0 FP)** / R **81.00%** / F1 **89.50%** (81/0/19); **không tham chiếu** (`--no-reference`): P 91.80% / R **56.00%** / F1 69.57% (56/5/44, 35 lô); Checklist **25/25 lô**; Reconciliation **87.50% (7/8)**; 60 OrderDossier F1 **100%** | [`ocr-tang3-ver2.ipynb`](file:///d:/OCR_chuki/ocr-tang3-ver2.ipynb) **Phần A** (đợt 9.13; engine `tools/stage3_resolver.py`, kiểm bằng `tools/test_stage3_suite.py`) | 🔴 Suite FAIL (R 72% < 80%) · P 100%, 12/12, permutation DIFF 0 | `output/stage3_out/stage3_batched_manifest.json` (28 lô, 297.3 KB) |
| **Tầng 3b**<br>Vùng ký động | `LOADING_PLAN`: dò đáy bảng + cột theo nhãn chức danh, chuẩn hóa nội bộ H=2200, mép ngoài/đáy per-column. Suite **20/22 + 2 KNOWN-LIMIT**; production: 5/5 trang không khối ký đúng, **`Load_3.5__0` hết ABSTAIN**; còn 24/27 ô chữ ký bị cắt (chủ yếu vắt ranh giới cột) | [`ocr-tang3-ver2.ipynb`](file:///d:/OCR_chuki/ocr-tang3-ver2.ipynb) **Phần B** *(đợt 9.13: notebook hợp nhất 44 cells; fallback PSM 4/11/3, 70/70 box không đổi)* | 🚧 Chỉ `LOADING_PLAN` (`HOA_DON` hoãn) | `tools/stage3b_zone_resolver.py` |
| **Tầng 4 v1**<br>Chữ ký & mộc đỏ | HSV Color-Layer Separation + Fallback hình thái học cho bản photo. P **95.35%** / R **100%** / F1 **97.62%** trên Independent GT v2 (hộp tĩnh). Zone động production LP (GT v4): **44/0/25/0, P 63.77%, TN 0** ⇒ không dùng cho zone động (E2E đã thôi dùng v1 cho LP, Giai đoạn 5) | [`ocr-tang4-verify.ipynb`](file:///d:/OCR_chuki/ocr-tang4-verify.ipynb) | ✅ Production-ready candidate (hộp tĩnh) | `output/stage4_out/` |
| **Tầng 4 ver2**<br>Mộc + cổng hình học | Zone động, engine chữ ký **theo mm**, box chặt, dải biên 20%; **required theo kênh SOP** + phán quyết hồ sơ đa trang. Scope chỉ `LOADING_PLAN`: 19 in-scope / 53 ABSTAIN; `DAT_CHUAN_GOC` 14 · `THIEU` 0 · `TRANG_1_CHUA_KY` 5; hồ sơ 14/14 DAT. Zone động production LP (GT v4, 69 ô): **44/25/0/0, P = R = 100%** ⚠️ không phải ước lượng tổng quát hóa; hộp tĩnh: **R 13.33%**. **Đợt 9.13:** thiếu chữ ký tổng hợp 62 biến thể — **72/72** ô required bị xóa phát hiện, 0 ca ra DAT (v1 0/72) | [`ocr-tang4-stamp-ver2.ipynb`](file:///d:/OCR_chuki/ocr-tang4-stamp-ver2.ipynb) | ✅ Zone động LP (`known_issues: []`, contract 41/41) · ⚠️ chỉ dùng zone động, v1 giữ cho hộp tĩnh | `output/stage4_out/stage4_verification_manifest_v2.json` |
| **E2E**<br>Hợp nhất | Orchestrator 1 ảnh → phán quyết. `LOADING_PLAN` → **engine ver2** + chính sách kênh (Giai đoạn 5; mỗi trang ghi `engine`); zone ABSTAIN → `CHUA_CHUAN_HOA_VUNG_KY`/ABSTAIN; `HOA_DON` → `UNMAPPED`/ABSTAIN. **22/22** (**6.09 s/trang**, đợt 9.13, 1 lần chạy; TEST 6 dùng ảnh trắng tổng hợp); parity engine 19/19; ⚠️ 5 trang CONTINUATION lệch verdict khi chạy đơn trang (kênh `COMMON`) | [`ocr-pipeline-e2e.ipynb`](file:///d:/OCR_chuki/ocr-pipeline-e2e.ipynb) | ✅ · ⚠️ chưa có chế độ hồ sơ đa trang | *(in trực tiếp trong notebook)* |
| **Web local**<br>`LOADING_PLAN` | Upload bộ nhiều trang → worker chạy T1→T2 (vote `upload_group_id`)→T3 (**gom trong 1 bộ**)→T4 ver2 LP + hồ sơ đa trang; đăng nhập + xác thực mail (Mailpit), admin/user, duyệt tay từng ô (append-only, phán quyết sau duyệt tính lại bằng `evaluate_document_verdict_v2`). Tham chiếu mã chuyến demo **mặc định TẮT**. 52 bộ demo: LP 14 DAT / 5 TRANG_1, hồ sơ 14/14 DAT, 670s | *(không notebook)* — [`web/README.md`](web/README.md), [`web/SPEC.md`](web/SPEC.md) | ✅ Docker Linux · ⚠️ T2 lệch Windows 6/72 | PostgreSQL (volume `kido_pg`) + ảnh (volume `kido_data`) |

> ⚠️ **Hai phiên bản Tầng 4 đang cùng tồn tại** và không dùng chung nguồn bounding box. Sự cố ver2 ghi đè artifacts v1 **đã sửa** (tách `_v1` / `_v2`) — xem `AGENTS.md` §7.F.
> ❗ **ĐÍNH CHÍNH Tầng 1:** "0 mismatch / 77.7s" công bố trước đây không tái hiện được ngày 27/09 chiều — xem `AGENTS.md` §3.E.
> ⚠️ `ocr-tang3-ver2.ipynb` **không phải** bản 2 của Tầng 3; đó là Tầng 3b (sinh vùng ký hình học cho Tầng 4). ❗ **ĐÍNH CHÍNH (đợt 9.13):** nay notebook này là **Tầng 3 hợp nhất** — Phần A gom lô + Phần B Tầng 3b.
> ❗ **ĐÍNH CHÍNH Tầng 4 zone động:** "ver2 hơn v1" (P 79.63% / 76.92%), "`ink_ratio` AUC 0.962", "Tầng 3b 5/5" đo trên ảnh raw `output/form_samples` ~850px với nhãn tính mực tràn — **không còn hiệu lực cho production**. Số production: `output/stage4_out/stage4_lp_prod_benchmark.json` — xem `AGENTS.md` §9.10, §9.11.
> ❗ **ĐÍNH CHÍNH E2E (Giai đoạn 5):** đến hết Giai đoạn 4, E2E verify ô ký `LOADING_PLAN` bằng **v1** (TN = 0 trên zone động), không phải ver2 như tài liệu ngụ ý — xem `AGENTS.md` §9.12.D.
> ⚠️ **14/14 DAT không phải bằng chứng độ chính xác:** với chính sách kênh, cả 32 ô required trong GT v4 đều đã ký — tập demo không còn ca "thiếu chữ ký bắt buộc" để kiểm. Xem `AGENTS.md` §9.12.A.
> 🔴 **CẢNH BÁO khi trích dẫn "ver2 100%":** engine thiết kế **sau khi xem toàn bộ GT v3**; quy tắc chạm mép là hậu kiểm (trước đó 41/22/1/0); holdout thật chỉ 5 ô (`Load_3.5__0`, 5/5 đúng); chưa đo bút đen / ảnh BW. Xem `AGENTS.md` §9.11.D.

---

## 2. Hướng Dẫn Cài Đặt & Chạy

### A. Thiết lập môi trường Python
1. Mở PowerShell tại thư mục dự án:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```
2. Cài Tesseract OCR cho Windows tại `C:\Program Files\Tesseract-OCR\tesseract.exe` (kèm gói ngôn ngữ `vie` và OSD).

### B. Chạy chuỗi chính thức (đợt 9.13 — theo đúng thứ tự, mỗi bước đọc artifact của bước trước)
```powershell
.\.venv\Scripts\python.exe tools/generate_nb1.py    && .\.venv\Scripts\python.exe tools/run_and_populate_nb1.py                              # Tầng 1 -> output/stage1_out/
.\.venv\Scripts\python.exe tools/generate_nb2.py    && .\.venv\Scripts\python.exe tools/run_and_populate_nb2.py ocr-tang2-classify.ipynb     # Tầng 2 -> output/stage2_out/ (+ output/stage2_upload_groups.json)
.\.venv\Scripts\python.exe tools/generate_nb3_ver2.py && .\.venv\Scripts\python.exe tools/run_and_populate_nb3.py ocr-tang3-ver2.ipynb       # Tầng 3 (Phần A gom lô -> manifest) + 3b (Phần B)
.\.venv\Scripts\python.exe tools/stage4_verifier.py                                                                            # Tầng 4 v1 (hộp tĩnh) -> *_v1.json
.\.venv\Scripts\python.exe tools/generate_nb4_ver2.py && .\.venv\Scripts\python.exe tools/run_and_populate_nb4_ver2.py ocr-tang4-stamp-ver2.ipynb  # Tầng 4 ver2 -> *_v2.json
.\.venv\Scripts\python.exe tools/generate_nb_e2e.py && .\.venv\Scripts\python.exe tools/run_and_populate_nb_e2e.py ocr-pipeline-e2e.ipynb    # E2E
```
- Chuỗi này chạy 2 lần cho **DIFF = 0** cả 5 artifact (`scratch/_nb/chain/SUMMARY.txt`). Runner `--help` chỉ in usage; ⚠️ riêng `tools/generate_nb1.py --help` **vẫn sinh lại notebook** (vô hại, chưa sửa).
- Notebook là **đầu ra của generator** — sửa generator, không sửa tay notebook. Mở xem trên VS Code: chọn kernel Python tại `.venv`.
- *(Lịch sử)* Thứ tự: Tầng 1 → Tầng 2 → Tầng 3b → Tầng 4 (v1 hoặc ver2). Tầng 3 không có notebook, chạy bằng test suite.
- **Không dùng `%matplotlib inline`** — IPython 9.x trên VS Code đã tự bật inline, gọi directive này sẽ ném lỗi.

### C. Chạy test suite
```powershell
python tools/stage3_resolver.py      # LỆNH CHÍNH THỨC sinh manifest Tầng 3 (--out PATH để ghi chỗ khác; --no-reference: không dữ liệu tham chiếu demo)
python tools/test_stage3_suite.py    # 12 regression + permutation + benchmark + kiểm IN_SYNC (mặc định KHÔNG ghi; --write-manifest để ghi; --no-reference đo năng lực thật) — đợt 9.13: FAIL R 72% < 80%
python tools/test_stage2_filename_invariance.py # bất biến tên file Tầng 2 + đối chứng dương (đợt 9.13)
python tools/test_lp_missing_signature.py      # 62 biến thể thiếu chữ ký tổng hợp, ver2 vs v1 (đợt 9.13)
python tools/test_stage4_suite.py    # 25 edge cases & contract hardening (v1; CASE 8 kỳ vọng theo nghĩa, đợt 9.13)
python tools/test_pipeline_e2e.py    # 22 test E2E (AGENTS.md §9.12.D)
python tools/test_stage3b_zone_suite.py        # 22 ca Tầng 3b (20 PASS + 2 KNOWN-LIMIT)
python tools/test_stage4_v2_verdict_contract.py # 41 ca contract verdict Tầng 4 ver2 (gồm chính sách kênh + hồ sơ đa trang)
python tools/test_v2_signature_unit.py         # 13 ca ảnh tổng hợp engine chữ ký ver2
python tools/test_stage4_v2_suite.py           # bench ver2 vs v1 trên hộp tĩnh
python tools/bench_lp_prod.py                  # bench zone động LP trên GT v4 (đường production)
```
~~⚠️ Đừng chạy `tools/generate_nb3_v2.py` nếu không muốn ghi đè manifest Tầng 3 chính thức (còn một cell ghi đè).~~ → đã chuyển sang `scratch/_archive_tools/` (Giai đoạn 5) cùng `generate_report_from_saved.py`, `run_benchmark_cli.py`.
Config (7 file, `config/`): thêm `stage3_shipment_reference.json` (mã chuyến **demo suy từ GT** — triển khai thật phải thay bằng danh mục ERP) và `stage4_lp_required_policy.json` (vai trò ký bắt buộc theo kênh). Thiếu `stage4_lp_required_policy.json` → `Stage4PolicyError`.
Dùng `.venv\Scripts\python.exe` (Python hệ thống trên PATH không có đủ thư viện / IPython).

### D. Web local `LOADING_PLAN` (Docker)
```powershell
cd web
copy .env.example .env       # đặt SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD
docker compose up -d --build
docker compose exec api python -m scripts.seed_demo              # tạo admin
docker compose exec api python -m scripts.seed_demo --with-demo  # + 52 bộ demo (tham chiếu TẮT)
```
Web http://localhost:8080 · Mailpit http://localhost:8025 · API docs http://localhost:8000/api/docs. Gốc repo mount **read-only** — web không ghi vào `tools/`, `config/`, `output/`.
Test/parity/smoke: [`web/README.md`](web/README.md) §Kiểm tra. ⚠️ Số Tầng 2 trong file này đo trên **Windows**; web Docker Linux lệch 6/72 trang (`AGENTS.md` §9.14.C). Tầng 3 web gom **trong 1 bộ upload** — không so thẳng với 72/0/28.

---

## 3. Tài Liệu Tham Chiếu
- **Kiến trúc, bài học kinh nghiệm & nợ kỹ thuật:** [`AGENTS.md`](file:///d:/OCR_chuki/AGENTS.md) — nguồn sự thật chi tiết.
- **Tóm tắt nhanh tiến độ:** [`GEMINI.md`](file:///d:/OCR_chuki/GEMINI.md).
- **Kế hoạch kỹ thuật:** `docs/STAGE3_FIX_PLAN_v3.1.md`, `docs/STAGE4_FIX_PLAN_v2.0.md`.
- **Tài liệu nghiệp vụ KIDO gốc:** `docs/Copy of HUONG DAN CHUNG TU GIAO NHAN.xlsx`.

---

## 4. Việc Cần Làm Tiếp (ưu tiên)

~~**Không còn hạng mục P0.**~~ → **Đợt 9.13:** `test_stage3_suite.py` FAIL (R 72%) — sửa bằng năng lực thật, không hạ ngưỡng. Các việc còn lại:

0. ✅ **Web local `LOADING_PLAN` đã build** (`AGENTS.md` §9.14). ✅ Giới hạn đăng nhập sai đã có (5/email, 20/IP trong 15 phút ⇒ khóa 15 phút). Việc còn mở của web: benchmark Tầng 3 chế độ trong-bộ · tách nguồn lệch T2 Linux · danh sách hồ sơ có lọc/tìm + xuất Excel · SMTP thật · siết ngưỡng Tầng 1 cho ảnh scan thật.
0b. 🔴 **Việc từ đợt 9.13** (`AGENTS.md` §9.13.I): (a) ✅ ~~web **gửi `upload_group_id` + `scan_index`** cho từng trang, **không giả định "1 upload = 1 chuyến"**~~ (web đã làm); (b) danh mục mã chuyến ERP; (c) ảnh thật thiếu chữ ký / bút đen / BW; (d) Tầng 2 bóc ngày giao / biển số để nâng Recall Tầng 3; (e) `generate_nb1.py --help` vẫn sinh notebook; (f) `HOA_DON` template; (g) `DX_THUHOI4.1__0` Tầng 2 vẫn ra `MT_COOP`.

1. ✅ ~~🔴 **Engine chữ ký không phân biệt được ô chưa ký trên đường production** (v1 = ver2 = TN 0, P 64.06%; FP dồn ở `Trưởng BP Kho` 12/12, `Người nhận hàng` 9, `Người lập phiếu` 2) — 🚧 **Giai đoạn 4 đang chạy**~~ → **Giai đoạn 4 xong**: ver2 GT v4 44/25/0/0 (⚠️ không phải ước lượng tổng quát hóa, `AGENTS.md` §9.11.D).
1b. ✅ ~~🟡 **Giai đoạn 5:** gộp phán quyết hồ sơ đa trang `LOADING_PLAN`; thống nhất preset tĩnh 3 vai trò vs zone động 5 vai trò; sinh lại notebook Tầng 3b (`generate_nb3_ver2.py`, nhãn "✅ 100%" lỗi thời); sửa mô tả `HOA_DON` sai ở `generate_nb_e2e.py:228-239`; dọn dead code; `bench_lp_dynamic.py` còn dùng box cũ~~ → **Giai đoạn 5 xong** (`AGENTS.md` §9.12): hồ sơ đa trang, notebook 3b, mô tả E2E, banner `DEPRECATED` ✅; preset tĩnh LP chỉ **đánh dấu legacy**; dead code chỉ **liệt kê**; holdout **chưa thu**.
1c. 🟡 **E2E chế độ hồ sơ đa trang** — lấy kênh từ trang đầu; hiện 5 trang CONTINUATION chạy đơn trang ra kênh `COMMON` ⇒ chính sách nghiêm ⇒ `THIEU_MOT_SO_CHU_KY` (manifest: DAT).
1d. 🟡 **Thu dữ liệu holdout** — chữ ký bút đen, ảnh BW, biểu mẫu `LOADING_PLAN` mới, ảnh thiếu chữ ký required thật (engine ver2 thiết kế sau khi xem GT).
1e. 🔴 **Danh mục mã chuyến ERP cho Tầng 3 — bắt buộc khi triển khai** (không có: R 56.00%, 5 FP). Kèm Tầng 2 bóc ngày giao / biển số để gỡ giả định 1 chuyến/hệ thống.
2. ✅ ~~**Tầng 3b cần Ground Truth độc lập**~~ — đã có GT v3 trên đúng đường production (`output/stage4_dynamic_gt_v3/`, 3 annotator, nhãn `own_signature` κ 1.0).
3. ✅ ~~**Tầng 2 không phân biệt KHO_THUE vs KHO_NOIBO**~~ — đã tách `INTERNAL_KHO_THUE`/`INTERNAL_KHO_NOIBO` (27/09 chiều), Tầng 3 về 0 FP.
3b. ✅ ~~**Sinh lại manifest chính thức Tầng 4 ver2**~~ — đã làm (Giai đoạn 1a): 19 in-scope / 54 ABSTAIN, `Load_3.5__0` → ABSTAIN.
3c. ✅ ~~❓ **Chờ quyết định người dùng:** `Người lập phiếu` **và `Người nhận hàng`** có `required` không (hiện cả hai `True`). Với engine mới, 11 trang `THIEU_MOT_SO_CHU_KY` đều do hai ô này trống thật (10 trang ô `Người nhận hàng`, 2 trang ô `Người lập phiếu`).~~ → **đã quyết (27/09):** required theo kênh SOP; 11 trang → `DAT_CHUAN_GOC`.
3d. ✅ ~~❓ **Chờ quyết định người dùng:** `business_exceptions` / `shipment_aliases` trong `config/stage3_business_rules.json` còn chứa mã chuyến từ bộ ảnh demo (cùng bản chất `AGENTS.md` §9.2).~~ → tách sang `config/stage3_shipment_reference.json` (Giai đoạn 5), xem 1e.
3e. ⚠️ **Tầng 3 `len(sys_shipments) == 1`** — không thể sửa tổng quát trên demo (23/65 chứng từ phụ thuộc, tắt → R 28%); đã gắn cảnh báo `SINGLE_KNOWN_ANCHOR_ASSUMPTION`. Cần dữ liệu ≥ 2 chuyến/hệ thống + Tầng 2 bóc ngày giao / biển số / mã điểm giao.
4. 🟡 **1/68 quy chuẩn chưa ánh xạ** — `"4.2 Phiếu đề xuất thu hồi tem que LAP"`, cần người nghiệp vụ xác nhận thuộc `doc_type` nào.
5. ✅ ~~**Tách `tools/stage3b_zone_resolver.py`**~~ — đã tách (`AGENTS.md` §11.2).
5b. 🟡 `HOA_DON` — template Tầng 3b theo từng chi nhánh/kênh · gộp 5 `run_and_populate_nb*.py` · xóa 2 hàm dead code Tầng 3 (`has_identity_conflict`, `resolve_batch_identity`).
6. 🟡 **Dọn `scratch/`** (352 file / 15 MB) và xem xét xóa hẳn `scratch/_archive_output/` (20.3 MB).

Chi tiết đầy đủ kèm `file:line`: [`AGENTS.md`](file:///d:/OCR_chuki/AGENTS.md) §9.
