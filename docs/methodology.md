# Phương pháp luận OCR — Hệ thống Kiểm Tra Chứng Từ Giao Nhận KIDO

> Tài liệu này trình bày **cách tiếp cận** (vì sao làm thế này), không phải nhật ký số liệu.
> Số liệu hiện trạng và lịch sử đính chính: `AGENTS.md`. Nguyên tắc chung: **mọi con số phải truy được về một artifact trên đĩa**. Tài liệu lệch artifact thì artifact đúng.
> Cập nhật: 2026-09-29. Bản trước (2026-09-28) lưu ở `scratch/_phanloai_2909/docs/before/methodology.md`.

---

## 1. Bài toán

Đầu vào là ảnh chụp hoặc scan bộ chứng từ giao nhận (Loading Plan, hóa đơn, PO, phiếu giao hàng, PXK kiêm vận chuyển nội bộ, biên bản bàn giao, biên bản thu hồi…). Hệ thống phải trả lời 4 câu hỏi:

1. Ảnh có đủ chất lượng để đọc không?
2. Đây là chứng từ gì, **loại con nào**, của kênh/hệ thống nào, mang những mã khóa nào?
3. Các trang/chứng từ nào thuộc cùng một chuyến xe, một hồ sơ đơn hàng?
4. Các vị trí bắt buộc đã được ký / đóng mộc đúng theo SOP chưa?

Căn cứ nghiệp vụ duy nhất là tài liệu SOP `docs/Copy of HUONG DAN CHUNG TU GIAO NHAN.xlsx` (sheet `Guideline` + 53 sheet biểu mẫu, 72 ảnh mẫu trích ra).

Câu hỏi 2 được tách làm hai mức từ 29/09/2026: **loại** (`doc_type`, 15 nhóm) và **loại con** (`subtype`, hiện làm cho hóa đơn). Lý do ở §5.2.

## 2. Nguyên tắc phương pháp luận

| # | Nguyên tắc | Hệ quả trong thiết kế |
|---|---|---|
| P1 | **Thà ABSTAIN còn hơn đoán** | Mọi tầng có trạng thái "không kết luận" tường minh (`UNRESOLVED_*`, `UNMAPPED`, `CHUA_CHUAN_HOA_VUNG_KY`, `CAN_KIEM_TRA_TAY`). Không có silent default, không fallback về hằng số. |
| P2 | **Trung thực hơn đẹp metric** | Khi gỡ hardcode làm chỉ số tụt, giữ con số thật (vd gỡ bảng 12 mã chuyến: `shipment_id` P 100% → 52.2%). Không hạ ngưỡng test để cho qua. |
| P3 | **Tách dữ liệu khỏi thuật toán** | Từ điển, ngưỡng, luật nghiệp vụ nằm trong `config/*.json`; thiếu file là lỗi tường minh. Dữ liệu suy từ ground truth phải tự khai báo `DEMO_DERIVED_FROM_GROUND_TRUTH`. |
| P4 | **Không dùng tên file làm bằng chứng** | Chỉ dùng nội dung ảnh + metadata tường minh (`upload_group_id`, `scan_index`). Có test hoán vị tên file bắt buộc `DIFF == 0`. |
| P5 | **Đo trên đúng đường production** | Benchmark phải chạy trên cùng ảnh, cùng độ phân giải, cùng hình học mà hệ thống thật dùng. Số đo trên đường khác không được trích dẫn cho production. |
| P6 | **Ground truth độc lập** | Nhãn do nhiều annotator gán mù (không xem kết quả máy), đo đồng thuận (Fleiss κ), hợp nhất bằng script không tự điền nhãn thiếu. |
| P7 | **Tái lập tuyệt đối** | Seed cố định, không phụ thuộc thứ tự set/hash, chạy chuỗi 2 lần phải `DIFF = 0` trên mọi artifact. |
| P8 | **Ngưỡng theo đơn vị vật lý** | Ngưỡng hình ảnh biểu diễn theo mm / tỉ lệ, không theo pixel tuyệt đối (bài học: scale ×2.6 làm vỡ ngưỡng pixel, xem §7). |
| **P9** | **Đọc CHỮ mà luật bắt buộc in, không đọc MÃ do hệ thống sinh** | Chữ tiêu đề do Nghị định 123/2020 bắt buộc, không đổi theo năm và theo nhà cung cấp phần mềm. Mã/ký hiệu đổi mỗi năm và có phần do người bán tự đặt ⇒ neo vào mã là hardcode trá hình. Chi tiết §5.2. |
| **P10** | **Cấm bằng lời không ăn thua, chặn bằng code thì ăn** | Với mô-đun không tất định (API vision), đừng dựa vào câu lệnh cấm trong prompt; hãy **lấy việc đó ra khỏi tay nó** và giao cho luật tất định. Chi tiết §7.4. |
| **P11** | **In BẰNG CHỨNG, đừng chỉ báo con số tổng** | Mọi kết luận nhận dạng phải kèm chuỗi/vùng thật mà máy đã dựa vào. Tổng đúng mà thành phần sai là dạng PASS giả khó thấy nhất — đã gặp hai lần trong một phiên (§8). |

### 2.1 Vì sao thêm P9, P10, P11

Ba nguyên tắc này rút ra từ các phép đo cụ thể ngày 28–29/09/2026, không phải từ suy luận:

- **P9** — cùng một tập 21 trang hóa đơn, đọc dòng chữ tiêu đề cho **21/21** (điểm khớp mờ 100/100 ở cả 21 tờ), còn giải mã ký hiệu `1C25TAA` chỉ cho **16/21** dù đã vá ba tầng đọc. Ký tự sai nhiều nhất lại đúng là ký tự quyết định loại hóa đơn.
- **P10** — API vision vẫn liệt kê khung `Signature Valid` thành "mộc đóng tay" dù prompt cấm tường minh. Ba vòng đổi prompt và một lần đổi sang model đắt hơn đều không sửa nổi; tách việc đó cho hình học thì sửa được ngay.
- **P11** — luật "tên in = đã ký" cho Loading Plan đo ra "2 ô đổi, đúng vai trò được phép, 4 vai trò kia 0/14", nhìn số thì hoàn hảo; in ra chuỗi máy đọc thì nó lấy `Quy đổi Pallct` — nhãn in sẵn của biểu mẫu, không phải họ tên. Phải tới lần thứ ba mới ra đúng họ tên thật.

## 3. Kiến trúc tầng

```
Ảnh ──► Tầng 1 Chuẩn hóa ──► Tầng 2 Phân loại + trường khóa ──► Tầng 3 Gom lô / hồ sơ
                                    │                                   │
                             Tầng 2b Loại con                           │
                                                                        │
                                            Tầng 3b Vùng ký động ◄──────┘
                                                    │
                                            Tầng 4 Verify chữ ký / mộc ──► Phán quyết trang + hồ sơ
```

Mỗi tầng ghi một artifact JSON có contract cố định; tầng sau chỉ đọc artifact của tầng trước. Notebook chỉ là lớp trình bày, sinh bằng generator (`tools/generate_nb*.py`), gọi module lõi trong `tools/`, không chứa logic riêng.

## 4. Tầng 1 — Chuẩn hóa ảnh (`tools/stage1_normalizer.py`)

**Mục tiêu:** đưa mọi ảnh về A4 thẳng, đúng chiều, cạnh dài 2200 px, cân sáng mà **bảo toàn mộc đỏ và mực xanh**; đồng thời quyết định ảnh có đi tiếp được không.

Phương pháp:
- **Tách giấy khỏi nền bằng GrabCut đồng thuận 3 seed + bỏ phiếu đa số.** Độ bất đồng giữa 3 lần chạy được dùng làm *tín hiệu chất lượng* (ngưỡng `agreement`), không chỉ để tái lập.
- **Dò tứ giác 3 chiến lược**, đo `ink_outside_quad` = tỉ lệ nét chữ bị cắt mất ngoài vùng nắn — đo trực tiếp thiệt hại nghiệp vụ (chữ ký/mộc thường ở rìa), thay vì chỉ IoU.
- **Xoay 3 lớp:** trục chữ → OCR lexical guard (từ khóa trong config) → Tesseract OSD (chỉ tin khi conf ≥ 2.0 và script Latin) → fallback. Khử nghiêng tinh giới hạn 2°. Triết lý "thà không xoay còn hơn xoay sai".
- **DPI hiệu dụng** tính trên cạnh giấy trong ảnh *gốc* (chống ảo giác "resize lên 2200 là đủ nét").
- **Gác cổng chất lượng**: mờ, lóa, DPI, đồng thuận mặt nạ, mực ngoài tứ giác. DPI thấp *một mình* chỉ là `CANH_BAO` + cờ `low_resolution`, không từ chối — thực nghiệm cho thấy từ chối vì DPI làm gãy cả hồ sơ đa trang trong khi Tầng 2 vẫn đọc đúng.
- Mặt nạ giấy chiếm < 12% khung ⇒ đo chất lượng trên toàn khung (tránh từ chối oan khi GrabCut chỉ bắt một ô màu).
- Đầu ra: `status ∈ {DAT, CANH_BAO, CHUP_LAI}`, `action`, JSON 35 khóa ở mọi trang (bước không chạy ⇒ `null` tường minh + `skipped_steps`).

## 5. Tầng 2 — Phân loại & bóc tách (`tools/stage2_classifier.py`)

### 5.1 Phân loại hai trục + vai trò trang

**Hai trục:** `doc_type` (loại chứng từ) × `system` (kênh: `GT`/NPP, `MT_*` siêu thị, `INTERNAL_KHO_THUE`, `INTERNAL_KHO_NOIBO`…), cộng `page_role` (`HEADER`/`CONTINUATION`).

Danh mục kênh hiện có **14 mã**: 9 siêu thị (`MT_BHX`, `MT_COOP`, `MT_BIGC`, `MT_WINMART`, `MT_AEON`, `MT_LOTTE`, `MT_EMART`, `MT_GS25`, `MT_SATRA`), 3 nội bộ (`INTERNAL_TRANSFER` là cấp cha của `INTERNAL_KHO_THUE` và `INTERNAL_KHO_NOIBO`), `GT` (nhà phân phối/đại lý), `COMMON` (không xác định). Circle K (3.9) và Mega (3.10) **chưa khai báo** — đã chốt bỏ qua vì chưa có mẫu; chúng rơi vào `COMMON` nên vô tình an toàn.

Phương pháp:
- **OCR Tesseract có vùng:** Vùng 1 (đầu trang) PSM 6 với early-exit khi đủ bằng chứng; Vùng 2 (0–60% trang, ở tỉ lệ resize khác) chỉ quét khi thiếu trường bắt buộc hoặc nhãn còn ở cấp cha. Chồng lấn giữa 2 vùng là **có chủ đích** — lần đọc thứ hai ở tỉ lệ khác cứu được trường Vùng 1 đọc trượt (đã đo: bỏ chồng lấn làm `po_no` R tụt mạnh).
- **Tiền xử lý:** CLAHE ở 1600 px; chuẩn hóa văn bản NFD bỏ dấu + uppercase áp cho *cả* từ điển lẫn chuỗi OCR. ⚠️ `đ`/`Đ` **không phân rã theo NFD** — phải ép về `d`/`D` **trước** khi chuẩn hóa, nếu không `"Quy đổi"` ra `QUY ĐOI` và mọi so khớp trượt.
- **Khớp từ khóa exact + fuzzy (rapidfuzz)** với luật chống "keyword shadowing": không dùng từ khóa quá ngắn/tiền tố, không dùng tên công ty chung (`KIDO FOODS`), kiểm tra loại dễ nhầm trước (PXKKVCNB trước Lệnh điều xe), xóa câu tham chiếu chéo, word-boundary cho tên siêu thị. Margin giữa top-1/top-2 loại bỏ các ứng viên không thực sự cạnh tranh (bao hàm chuỗi, lệch bậc exact/fuzzy).
- **Luật SOP ở cấp nghiệp vụ**, không phải từ khóa: vd biên bản thu hồi (mục 4) luôn kênh `GT`; nhãn cha `INTERNAL_TRANSFER` bắt buộc quét thêm để tách loại kho, chỉ gán khi khớp đúng một loại.
- **Bóc tách trường khóa có cổng doc_type:** mỗi trường (`shipment_id`, `invoice_no`, `po_no`, `pxk_no`, `transfer_order_no`) chỉ được trích trên doc_type hợp lệ, regex chứa biến thể OCR sai đã biết, kiểm tra cấu trúc (vd số hóa đơn 8 chữ số theo NĐ 123/2020). Đây là nguồn chính của precision.
- **Bỏ phiếu đa trang theo `upload_group_id` + `scan_index`**: chỉ giữa trang liền kề, cùng doc_type, không xung đột trường khóa. Không giả định "1 bộ upload = 1 chuyến".
- **Dữ liệu tham chiếu (danh mục mã chuyến)** là tùy chọn và thay thế được; không có thì đo năng lực OCR thuần. Lỗi OCR chữ số lặp lại trên mọi liên không thể phục hồi tổng quát nếu không đối chiếu danh mục ERP.

### 5.2 Tầng 2b — Loại con (`tools/stage2_subtype.py`, `config/stage2_doc_subtypes.json`)

Thêm 29/09/2026. Lý do tồn tại: `doc_type = HOA_DON` là **một nhãn cho nhiều loại chứng từ có luật nghiệp vụ khác nhau** — hóa đơn GTGT, hóa đơn bán hàng, hóa đơn điều chỉnh, hóa đơn thay thế, phiếu xuất kho kiêm vận chuyển nội bộ dạng hóa đơn điện tử. Không tách được loại con thì không thể áp đúng luật kiểm.

**Quyết định phương pháp trung tâm: đọc chữ làm chính, đọc mã làm đối chứng.** Ký hiệu hóa đơn (`1C25TAA`) tự nó đã mã hóa loại hóa đơn theo Thông tư 78/2021 — ký tự 1 là loại (`1`=GTGT, `2`=bán hàng, `6`=PXK VCNB…), ký tự 2 là có/không mã cơ quan thuế, ký tự 3–4 là năm, ký tự 5 là loại hóa đơn điện tử. Nghe thì đây là nguồn tốt nhất. Đo thì không:

| Cách | Kết quả trên 21 trang hóa đơn |
|---|---|
| Đọc dòng chữ in `HÓA ĐƠN GIÁ TRỊ GIA TĂNG` | **21/21**, điểm khớp mờ **100/100 ở cả 21 tờ** |
| Giải mã ký hiệu (mỏ neo tọa độ → quét trang → cắt ô whitelist) | 20/21 ra chuỗi hợp khuôn, nhưng chỉ **16/21** đúng chuỗi thật |

Hai lý do khiến ký hiệu không được làm căn cứ chính:

1. **Sai ở đúng chỗ nguy hiểm.** Ký hiệu là chữ nhỏ ở góc trang; OCR đọc `1`→`I`, `2`→`?`/`Đ`/`J`/`Z`. Ký tự bị đọc sai nhiều nhất chính là ký tự phân loại ⇒ `2C25TAA` (bán hàng) rất dễ thành `1C25TAA` (GTGT), tức PASS giả.
2. **Mã thay đổi theo thiết kế.** `1C25TAA` sang 2027 thành `1C27TAA`; hai ký tự cuối do người bán tự đặt; nhà cung cấp khác đặt khác. Neo vào danh sách mã đã biết là hardcode — đúng loại nợ kỹ thuật dự án này đã gỡ nhiều lần.

Ngược lại, dòng chữ `HÓA ĐƠN GIÁ TRỊ GIA TĂNG` do Nghị định 123/2020 **bắt buộc in**, không đổi theo năm và theo nhà cung cấp phần mềm. Đó là P9.

**Vai trò còn lại của ký hiệu** — vẫn đọc, nhưng chỉ để:
- **bắt mâu thuẫn**: chữ in nói GTGT mà ký hiệu suy ra loại khác ⇒ gắn cờ `mau_thuan`, đẩy người soát; **không tự chọn bên nào**;
- cung cấp hai thông tin chữ không cho: **có mã cơ quan thuế hay không** (ký tự 2) và **hóa đơn khởi tạo từ máy tính tiền hay không** (ký tự 5 = `M`).

Nhờ vậy điểm yếu 16/21 trở nên vô hại: đọc sai ký hiệu không đổi kết luận, chỉ làm mất một phép đối chứng.

**Kỹ thuật so khớp.** Dùng `rapidfuzz.partial_ratio` chứ không so khớp chính xác — OCR đọc `GIÁ TĂNG`/`GIA TẮNG` thường xuyên. Luật có **điểm ưu tiên**, cụm đặc hiệu (`HÓA ĐƠN ĐIỀU CHỈNH`) xét trước cụm chung (`HÓA ĐƠN GIÁ TRỊ GIA TĂNG`), vì tờ điều chỉnh in cả hai. Khớp ở **vùng đầu trang** được cộng điểm; khớp ngoài vùng đầu bị **nhân 0.55** chứ không chỉ mất thưởng — nếu chỉ mất thưởng thì một cụm nằm trong câu hướng dẫn cuối trang vẫn thắng cụm tiêu đề thật.

**Ngưỡng khớp mờ = 90, và đây là con số phải đo chứ không được chọn theo cảm tính.** Vòng đo đầu tiên đặt 80, kết quả 12/21 tờ bị gán nhầm `HOA_DON_DIEU_CHINH`. Phân bố `{GTGT: 9, DIEU_CHINH: 12}` trông như "máy phân biệt được nhiều loại", rất thuyết phục — cho tới khi in bằng chứng ra: cụm `HÓA ĐƠN ĐIỆN TỬ` khớp mờ với `HÓA ĐƠN ĐIỀU CHỈNH` được **83 điểm**. Đo lại khoảng cách trên cả 21 tờ: cụm đúng **100 điểm**, cụm nhầm cao nhất **83**. Ngưỡng 90 nằm giữa khe, và căn cứ đó được ghi thẳng vào config để sau này không ai hạ xuống mà không đo lại. Đây là minh họa trực tiếp của P11.

**Nhận bản chuyển đổi.** Chỉ **bản chuyển đổi ra giấy** mới có chữ ký tay để kiểm; bản điện tử gốc thì không. Nhận qua các cụm `HÓA ĐƠN CHUYỂN ĐỔI TỪ HÓA ĐƠN ĐIỆN TỬ` / `NGÀY CHUYỂN ĐỔI` / `NGƯỜI CHUYỂN ĐỔI` — đo được 21/21.

**Kiến trúc mở rộng.** `doc_type` nào chưa khai báo luật loại con thì hàm trả `None` — không đoán (P1). Đo: 51/51 trang không phải hóa đơn đều trả `None`.

### 5.3 Kỹ thuật vay mượn có kiểm chứng

Ba kỹ thuật lấy từ repo `github.com/vnb-vnb/kido-orc` (commit `c2b2858`), đã đọc mã và chạy thử trên chính tập 72 ảnh của dự án này trước khi nhận:

| Kỹ thuật | Vì sao đáng lấy |
|---|---|
| **Mỏ neo theo tọa độ** (`identifiers.py:_neo_theo_toa_do`) | Tìm nhãn rồi lấy giá trị **bên phải, cùng hàng** theo tọa độ từ. OCR đọc bảng theo cột nên nhãn và giá trị cách nhau rất xa trong văn bản phẳng; cắt N ký tự sau nhãn là lấy nhầm. Áp dụng làm số trang đọc được ký hiệu tăng từ 9/21 lên 15/21. |
| **Luật có điểm ưu tiên + hạ mạnh khi khớp ngoài vùng đầu** (`classifier.py`) | Giải đúng bài toán "cụm chung nằm trong câu hướng dẫn cuối trang". |
| **So khớp mờ với ngưỡng cao** | Anh Bắc cố ý để 0.90 chứ không 0.82, ghi rõ lý do "nợ hàng" vs "nhận hàng" khớp chéo. Đúng bẫy chúng tôi dính với `điện tử` vs `điều chỉnh`. |

Một kỹ thuật **không lấy**: `chuan_hoa()` bên đó chỉ ép ký tự nhầm về chữ số **khi nó bị kẹp giữa hai chữ số**. Với `1C25TAA`, ký tự `1` đứng đầu chuỗi nên không bao giờ được sửa — mà đó đúng là ký tự phân loại. Bản của dự án này ép **theo vị trí** mà Thông tư 78 quy định, và chuỗi ép xong vẫn phải qua kiểm khuôn nên ép sai không sinh kết quả bậy.

Một hạng mục **chưa lấy**: `classify_by_boxes()` nhận trang tiếp diễn qua **bộ ô ký** thay vì tiêu đề — hữu ích khi cần `page_role` thật cho hóa đơn (§8.1).

## 6. Tầng 3 — Gom lô & đối soát (`tools/stage3_resolver.py`)

Tầng thuần dữ liệu, không đụng pixel.
- **Ghép đa trang** theo `scan_index`, `page_role`, tương thích doc_type/system/trường khóa, khoảng cách ≤ 5 trang; trang continuation mồ côi ⇒ `UNRESOLVED_CONTINUATION`.
- **Gom lô chuyến 4 pass:** (1) neo định danh trực tiếp (mã chuyến, số lệnh, luật loại chứng từ); (2) quan hệ qua khóa chung PO/HĐ/PXK có guard xung đột; (3) lan truyền theo hệ thống chỉ khi an toàn (guard G1: chứng từ cùng loại đã có số khác thì không lan; G2: mã chuyến neo dưới ≥ 2 hệ thống không làm ngữ cảnh); (4) còn lại cách ly `UNRESOLVED_*`. Mỗi chứng từ ghi `batch_assignment` giải thích vì sao vào lô.
- **Hồ sơ đơn hàng** bằng Union-Find trên đồ thị PO/HĐ/PXK — chỉ nối khi có bằng chứng quan hệ.
- **Đối soát cấp trường** (`ReconciliationEvidence`: MATCH / PARTIAL / MISMATCH / MISSING_*), không bao giờ dùng "có nhiều chứng từ" làm bằng chứng khớp.
- **Checklist SOP** đối chiếu lô với ma trận chứng từ bắt buộc; tập quy chuẩn rỗng ⇒ `KHONG_CO_QUY_CHUAN`, không kết luận `HOAN_HAO`.

### 6.1 Việc còn thiếu: phân loại QUY TRÌNH theo bộ chứng từ

SOP chia 6 nhóm loại hình → 20 quy trình con (1 · 2.1–2.3 · 3.1–3.11 · 4.1–4.2 · 5.1–5.2 · 6.1–6.2). Phân biệt các quy trình 2.x **không suy được từ một trang**, phải suy từ **tập chứng từ có trong bộ**: `BBBG_HOADON` ⇒ 2.2; `PXKKVCNB` + Loading Plan không dấu hiệu kho ⇒ 2.3; còn lại + kênh `GT` ⇒ 2.1.

Đây không phải việc làm cho đẹp. Hiện `Hoadon2.2__1/2/3` là hóa đơn kênh `GT` nhưng in tên người nhận là siêu thị (`00629-CO.OPFOOD 7 LÊ THỊ HÀ`), nên Tầng 2 gán `MT_COOP` với độ tin cậy **1.00**. Nhìn riêng trang đó thì máy không sai — thông tin để sửa **không nằm trên trang**. Hậu quả: SOP xếp 2.2/2.3 vào kênh NPP (bắt buộc chữ ký Người nhận) trong khi máy gán MT ⇒ **bỏ qua Người nhận** = PASS lỏng. Cả 15 `doc_type` của Tầng 2 khớp 1-1 danh mục Excel nên không phải xây thêm bộ nhận dạng nào, chỉ cần tầng suy luận theo bộ.

## 7. Tầng 3b + Tầng 4 — Vùng ký và kiểm chữ ký/mộc

### 7.1 Vùng ký động (`tools/stage3b_zone_resolver.py`)
Hiện chỉ `LOADING_PLAN`. Thay vì hằng số tọa độ cột (mã hóa bố cục của đúng bộ ảnh demo), hệ thống:
- dò vạch kẻ ngang cuối bảng làm neo (`anchor_y`), phát hiện trang không có khối ký (bảng kéo dài);
- OCR dải nhãn chức danh dưới neo (PSM 6, fallback PSM 4/11/3), khớp mờ với từ điển nhãn trong config, lấy tâm cụm từ, khớp tuyến tính `center(k) = a + b·k` để bù nhãn thiếu (cần ≥ 3 nhãn);
- mép ngoài/mép đáy theo từng cột dựa cụm mực, ranh giới giữa cột giữ không chồng lấn;
- mọi thất bại trả trạng thái ABSTAIN có tên (`COLUMN_DETECTION_FAILED`, `TABLE_ANCHOR_NOT_FOUND`…).

**Vì sao không hardcode cột cho Loading Plan:** bảng hàng hóa co giãn, đo được **y trôi 0.54** và x trôi 0.01–0.06 giữa các tờ. Nhánh đường lui hardcode đã xây (`fallback_columns`) nhưng để `enabled: false`: trên ảnh production nó chạy 0 lần (không lợi gì đo được), còn trên ảnh kém phân giải nó chạy 15 lần và sinh hộp lệch tới 0.019 — vi phạm tính chất an toàn *"sai độ phân giải chỉ được dẫn tới ABSTAIN, không được dẫn tới hộp sai chỗ"*. Bật lên chỉ là sửa một dòng, khi có ảnh THẬT chứng minh cần.

### 7.2 Hai engine kiểm tất định
- **v1 (`stage4_verifier.py`)** — cho hộp tĩnh preset: tách lớp màu HSV (đỏ/tím/xanh) để mộc đè chữ ký không triệt tiêu nhau, lọc connected component loại chữ in sẵn, engine B hình thái cho bản photo đen trắng, modality xác định theo từng trang.
- **ver2 (`stage4_verifier_v2.py`)** — cho zone động: mộc phải qua **3 cổng màu + hình học + diện tích** (độ tròn/HoughCircles cho mộc tròn, minAreaRect cho mộc vuông), cấm fallback chéo giữa engine màu và BW. Engine chữ ký **ngưỡng theo mm** (`px_per_mm = cạnh dài / 297`): ROI là box chặt, chỉ tính mực xanh, nhánh nét tối yêu cầu nét cao ≥ 6 mm (lớn hơn chữ in cao nhất đo được). Ảnh BW ⇒ `review_required`, không tự kết luận.
- **`sig_stroke_ownership.py` — đo theo QUYỀN SỞ HỮU NÉT.** Không cắt ROI từng ô rồi đo (cách đó chặt đứt nét ở biên), mà tách mực xanh cả trang → gom cụm → gán mỗi cụm cho ô chiếm ≥ 50% diện tích; ô nhì chiếm ≥ 25% cụm ⇒ hai chữ ký dính nhau, tách theo pixel. Cách này thay hẳn luật dải-biên-20% của ver2 (nguồn 2/5 lỗi) và đưa Lệnh điều xe từ 6/11 lên **11/11**.

Bài học phương pháp quan trọng nhất ở đây: TN = 0 (mọi ô trống bị chấm "đã ký") **không do cân sáng mà do scale** — ảnh ~850 px được phóng lên H=2200 (×2.6 chiều, ×6.8 diện tích) làm mọi ngưỡng pixel tuyệt đối trở nên dễ dãi. Kết luận được rút ra bằng thí nghiệm tách biến (chỉ cân sáng / chỉ scale / thu nhỏ lại), không suy đoán.

### 7.3 Chiến lược template theo biểu mẫu — trả tiền theo SỐ BIỂU MẪU, không theo số chứng từ

Từ 28/09/2026, thay vì cố xây một engine vạn năng, hệ thống làm **từng biểu mẫu một**:

- **Chế độ A (một lần, offline):** dùng API vision sinh vị trí ô ký/mộc cho một biểu mẫu, người soát tay, chốt vào `config/form_signature_templates.json`.
- **Chế độ B (production):** chạy template + đo mực bằng code tất định — **0đ/tờ**.
- **Chế độ C:** ngoại lệ hiếm mới gọi API.

Chi phí biên của chứng từ thứ 1000 bằng 0. Đo từ số dư thật: **~5,71đ/lần gọi**, và giá **gần như không phụ thuộc kích thước ảnh** (giảm 61% điểm ảnh chỉ bớt 10% token) ⇒ thu nhỏ ảnh không tiết kiệm được gì, **đòn bẩy duy nhất là giảm số lần gọi**. Cache theo `sha256(ảnh)+model+prompt_version+temperature` nên dựng lại kết quả là 0đ.

Ba hạng biểu mẫu, chọn cơ chế theo **hình học**, không theo sở thích:

| Hạng | Đặc điểm | Cơ chế | Ví dụ |
|---|---|---|---|
| A | bố cục cứng, không bảng co giãn | tọa độ cứng trong config | Lệnh điều xe (11/14 ô bắt buộc) |
| B | có bảng co giãn | dò nhãn từng ảnh | Loading Plan |
| — | không có ô ký lẫn mộc | khai báo `KHONG_YEU_CAU` tường minh | Biểu đồ nhiệt độ |

Khai báo tường minh "không có chỗ ký" là bắt buộc, để hệ thống **không báo thiếu oan** — khác hẳn `UNMAPPED` (chưa có preset).

### 7.4 Quy trình lai ghép cho hóa đơn — chia việc theo bản chất, không theo tiện tay

Hóa đơn GTGT chuyển đổi (khuôn FPT IS) dùng quy trình **lai ghép hình học + API**:

| Việc | Ai làm | Vì sao |
|---|---|---|
| Tìm khung `Signature Valid` (mộc chữ ký số của người bán) | **hình học tất định** | Khung là hình chữ nhật có kích thước và vị trí ổn định ⇒ luật tất định làm được, 0đ, tái lập 100% |
| Cắt vùng khối ký | hình học, neo theo khung trên | Thu nhỏ vùng API phải nhìn |
| Đếm chữ ký tay 2 cột + mộc đóng tay | API vision trên **ảnh đã cắt** | Việc thật sự cần nhận thức thị giác |
| Lọc đếm trùng | code | Bỏ mộc chồng ≥ 50% khung đã biết |

**Đây là chỗ P10 ra đời.** Ban đầu giao cả việc cho API kèm prompt cấm tường minh "không được tính khung Signature Valid là mộc đóng tay". API vẫn tính. Ba vòng đổi prompt và một lần đổi sang model đắt hơn đều không sửa được. Lấy việc đó ra khỏi tay API và giao cho hình học thì sửa được ngay. Nguyên tắc rút ra: **với mô-đun không tất định, ranh giới trách nhiệm phải cưỡng chế bằng kiến trúc, không bằng lời**.

Một giả định cũ đã bị bác bỏ bằng đo: `AGENTS.md` §9.8/§9.9 ghi hoãn `HOA_DON` vì "mỗi chi nhánh/kênh cần template riêng". Đo 3 kênh khác nhau (GT 2.1, MT_COOP 3.2, MT_GS25 3.8) cho thấy **cùng một khuôn FPT IS, x của 3 cột ký cố định, chỉ y trôi theo nội dung**. Cái khác theo kênh là **chính sách ai phải ký**, không phải hình học.

### 7.5 Phán quyết
- **Required theo kênh SOP** (`config/stage4_lp_required_policy.json`, trích dẫn từng ô Guideline). Kênh không xác định ⇒ áp chính sách nghiêm nhất + cờ, không đoán.
- Verdict chỉ dựa trên target required; optional chỉ lưu vết. `UNMAPPED` (chưa có preset) ≠ `KHONG_YEU_CAU` (SOP không yêu cầu). Không có target required ⇒ ABSTAIN, không "ĐẠT từ tập rỗng".
- **Hồ sơ đa trang** gộp vai trò ký qua các trang; trang ABSTAIN ⇒ hồ sơ ABSTAIN.
- **Luật ký online**, thêm 29/09: ô `Người lập phiếu` của Loading Plan được ký online — hệ thống in sẵn họ tên, không có mực tay vẫn tính đã ký, bằng chứng riêng `E_SIGNATURE_PRINTED_NAME`. **Chỉ vai trò này**; 4 vai trò kia là chữ ký bên ngoài, áp cho họ là PASS giả. ⚠️ Hệ thống in tên lên **mọi tờ** nên phép kiểm này gần như luôn đúng — nó chỉ bắt được tờ **mất hẳn tên in**, đừng đọc là "đã kiểm chữ ký người lập phiếu".

## 8. Phương pháp đánh giá

- **Ground truth theo tầng:** `output/stage2_gt.json`, `stage3_gt.json`, GT Tầng 4 độc lập v2 (hộp tĩnh), GT zone động v4 (`output/stage4_dynamic_gt_v4/`).
- **Quy trình gán nhãn:** crop phóng to + contact sheet, ≥ 3 annotator mù, cấm chạy detector hay đọc manifest; đo Fleiss κ; nhãn được định nghĩa để không che lỗi (vd `own_signature` — mực tràn từ cột bên **không** tính là có ký).
- **Chỉ số:** Precision/Recall/F1/Accuracy kèm ma trận TP/TN/FP/FN, bóc tách theo vai trò, required/optional, engine, hướng mực tràn. TN luôn được báo — một detector TN = 0 có thể có Recall 100% mà vô dụng.
- **Kiểm độ vững:** leave-one-image-out chọn lại ngưỡng; bất biến scale; độ nhạy từng tham số ×0.5/×2; ablation từng quy tắc; holdout thật khi có.
- **Kiểm thử tổng hợp có khai báo:** vd 62 biến thể xóa mực ô ký trên ảnh thật (cờ `_synthetic`) để đo khả năng bắt thiếu chữ ký bắt buộc khi tập demo không có ca thật.
- **Ca âm cho mọi luật nhận dạng mới:** xóa đúng bằng chứng mà luật dựa vào, rồi chạy lại — luật phải **thôi kết luận**, không được bịa từ chỗ khác. Ví dụ: xóa dòng chữ tiêu đề khỏi 21 trang hóa đơn ⇒ 21/21 thôi kết luận GTGT; xóa 2 chữ ký + mộc khỏi một tờ ⇒ hình học trả `KHONG_THAY_KHUNG` và API trả cả 2 cột không ký.
- **Kiểm thử chống PASS giả:** test hoán vị tên file, test contract verdict, test tái lập, harness bắt cả lỗi runtime và đếm test thực chạy; thiếu GT ⇒ `skipped`, không trả 100%.
- **Ảnh soát cho người:** mỗi tầng có bộ ảnh dán kết quả lên ảnh gốc, kèm **chuỗi/vùng thật** dẫn tới kết luận, để người soát tự kiểm chứ không phải tin con số tổng (`test/`, chỉ mục `test/README.md`). Tầng phân loại: `test/05_phan_loai/` đủ 72 trang.
- **Ghi nhận thực nghiệm thất bại:** mọi hướng đã thử và bị loại (kèm số đo) được ghi lại tại chỗ trong code và trong `AGENTS.md` để không lặp lại.

### 8.1 Ba dạng PASS giả đã gặp, và cách bắt

| Dạng | Ví dụ thật | Cách bắt |
|---|---|---|
| **Mẫu số rỗng** | checklist luôn `HOÀN_HẢO` vì `form_catalog.json` thiếu khóa so khớp ⇒ tập quy chuẩn rỗng | Bắt buộc trạng thái riêng cho tập rỗng (`KHONG_CO_QUY_CHUAN`), cấm kết luận ĐẠT từ tập rỗng |
| **Tổng đúng, thành phần sai** | tờ `Hoadon_3.2__0` đếm ra 5, trùng khít số thật, nhưng thừa một mộc giả và thiếu một mộc thật — hai lỗi bù nhau | So khớp **từng phần tử**, không so tổng |
| **Bằng chứng sai nhưng số đẹp** | luật "tên in = đã ký" đổi đúng 2 ô, đúng vai trò được phép, 4 vai trò kia 0/14 — nhưng chuỗi máy đọc là `Quy đổi Pallct`, nhãn in sẵn của biểu mẫu | **In chuỗi máy dựa vào** (P11) |

Một dạng thứ tư cần cảnh giác là **ground truth không phân biệt**: `page_role` báo khớp 21/21 trên hóa đơn, nhưng cả máy lẫn ground truth đều ghi `HEADER` cho trang 2/2, nên con số đó không chứng minh máy nhận đúng trang tiếp diễn. Muốn biết thật phải dựng ground truth riêng theo footer `trang k/n`.

## 9. Giới hạn đã biết của phương pháp

- Tập demo 72 ảnh trích từ Excel, nén nặng (~45–150 DPI); phần lớn giới hạn recall bắt nguồn từ đây. Production cần scan ≥ 200–300 DPI.
- Engine chữ ký ver2 được thiết kế **sau khi đã xem GT** ⇒ chỉ số trên zone động không phải ước lượng tổng quát hóa; chưa đo chữ ký bút đen và ảnh BW thật.
- **Tập demo chỉ có MỘT loại hóa đơn** (GTGT chuyển đổi, ký hiệu `1C25TAA`). Kết quả 21/21 của Tầng 2b chứng minh máy **nhận đúng GTGT** và **không gán bừa** cho 51 trang khác; nó **không** chứng minh máy phân biệt được GTGT với bán hàng / điều chỉnh / thay thế. Luật cho các loại kia đã viết trong config nhưng **chưa được đo**.
- `config/stage2_keywords.json` hiện **hardcode `1C25TAA`, `1C24TAA`** làm từ khóa nhận hóa đơn — nợ kỹ thuật, sang 2027 mã đổi là hai từ khóa này chết. Chưa gỡ vì gỡ là đụng benchmark.
- Tầng 2b **chưa cắm** vào `tools/stage2_classifier.py`; ngoài ra Tầng 2 chỉ OCR **vùng đầu trang** chứ không cả trang, nên số đo Tầng 2b trên văn bản đầy đủ phải đo lại trên đúng điều kiện production trước khi trích dẫn (P5).
- Danh mục mã chuyến demo suy từ GT; triển khai thật bắt buộc thay bằng danh mục ERP/SAP.
- Gom lô vẫn dựa một phần vào giả định "mỗi hệ thống một chuyến" trong phạm vi dữ liệu; cần Tầng 2 bóc ngày giao / biển số để gỡ.
- **Chưa có tầng phân loại quy trình SOP theo bộ chứng từ** (§6.1) ⇒ còn PASS lỏng ở 3 tờ `Hoadon2.2`.
- Kết quả OCR phụ thuộc nền tảng (Tesseract/leptonica/OpenCV khác phiên bản giữa Windows và Docker Linux cho khác biệt **6/72 trang** ở Tầng 2); mọi chỉ số chính đo trên Windows.
- Template ô ký hiện mới chốt **2/15** biểu mẫu (Lệnh điều xe, Biểu đồ nhiệt độ); Loading Plan chạy cơ chế dò nhãn động; hóa đơn GTGT đang thử nghiệm trên n = 3 tờ. `case/2_tang4_chua_co_template/` còn 50 ảnh chờ.

## 10. Tham chiếu

- Chi tiết kỹ thuật, số liệu, đính chính: `AGENTS.md`
- Kế hoạch sửa: `docs/STAGE3_FIX_PLAN_v3.1.md`, `docs/STAGE4_FIX_PLAN_v2.0.md`, `docs/STAGE3B_COLUMN_FIX_PLAN.md`, `docs/STAGE3B_OVERFLOW_ANALYSIS.md`
- Chiến lược API vision: `docs/VLM_PIPELINE_PLAN.md`
- Ảnh soát template chữ ký: `test/README.md`; ảnh soát tầng phân loại: `test/05_phan_loai/README.md`
- Web local: `web/SPEC.md`, `web/README.md`
- Nguồn nghiệp vụ: `docs/Copy of HUONG DAN CHUNG TU GIAO NHAN.xlsx`
- Tham khảo ngoài: `github.com/vnb-vnb/kido-orc` (§5.3) — ⚠️ repo đó ghi endpoint API **sai** là `platform.beeknoee.com`; đúng phải là `platform-api.beeknoee.com`
