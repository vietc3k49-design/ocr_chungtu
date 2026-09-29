# Pipeline dùng API vision (beeknoee / `gemini-2.5-flash-lite`) — tối ưu chi phí

> Bản 28/09/2026. Mọi con số dưới đây **đo thật**, nguồn ghi kèm. Chưa đo thì ghi "chưa xác định".

## 1. Số đo nền — quyết định toàn bộ thiết kế

| Hạng mục | Giá trị | Nguồn |
|---|---|---|
| Giá mỗi lần gọi | **~5,3đ** (2 000đ → 1 989,42đ sau 2 lần gọi) | số dư tài khoản beeknoee |
| Token mỗi lần gọi | ~3 100–3 500 prompt + 95–206 output | `usage` trả về |
| Prompt chữ (3 câu) | ~130 token (**4%**) | `run_vlm_sig_scope.PROMPT` |
| Ảnh | ~3 000 token (**96%**) | phần còn lại |
| Độ trễ | 4,9 – 8,0 s/ảnh | đo 28/09 |

### Phát hiện then chốt: giá KHÔNG phụ thuộc kích thước ảnh

| Ảnh gửi | Điểm ảnh | Token prompt |
|---|---|---|
| Cả trang, cạnh 1400 | 1,39 MP | 3 458 |
| Dải ô ký 38%, cạnh 1400 | 1,05 MP | 3 116 (−10%) |
| Dải ô ký 38%, cạnh 1000 | 0,54 MP | 3 545 (+3%) |

Giảm 61% điểm ảnh chỉ bớt 10% token; giảm nữa thì đắt hơn. ⇒ **Gateway tính phí gần như cố định cho mỗi ảnh.**

**Hai hệ quả bắt buộc tuân thủ:**

1. **KHÔNG thu nhỏ ảnh để tiết kiệm.** Nó không tiết kiệm, chỉ làm mất chi tiết nét ký miễn phí.
   Ngược lại: **cắt dải ô ký rồi gửi ở độ phân giải cao nhất** — cùng giá mà model nhìn rõ hơn, đồng thời
   bỏ phần đầu trang chứa tên khách hàng / địa chỉ (giảm dữ liệu nhạy cảm gửi ra ngoài).
2. **Tối ưu = giảm SỐ LẦN GỌI.** Mọi thứ khác là nhiễu.

---

## 2. Ý tưởng trung tâm: trả tiền theo SỐ BIỂU MẪU, không theo số chứng từ

Vị trí ô ký là **thuộc tính của biểu mẫu**, không phải của từng tờ chứng từ. Cột x của
`LOADING_PLAN` ổn định `[.07 .26 .41 .59 .75]` ±0.03 qua mọi mẫu (đo trong `kido-orc`);
phía ta, Tầng 3b đã khai thác đúng tính chất này.

⇒ Không dùng API như một bộ phận của dây chuyền chạy hằng ngày. Dùng nó **một lần, ngoại tuyến,
để SINH template**, rồi production chạy bằng template + đo mực cổ điển với chi phí **0đ**.

```
       CHẾ ĐỘ A — sinh template (một lần, có người soát)
       15 doc_type × 2-3 ảnh mẫu  ≈ 40 lần gọi ≈ 210đ
                     │
                     ▼
            config/vlm_templates.json          ← tài sản dùng mãi
                     │
       CHẾ ĐỘ B — production (hằng ngày)       ← 0đ, tất định
       template + đo mực cổ điển
                     │
                     ▼
       CHẾ ĐỘ C — ngoại lệ (hiếm)
       biểu mẫu lạ / template và đo mực mâu thuẫn → 1 lần gọi
```

Chi phí biên của chứng từ thứ 1 000 = **0đ**. Đây là khác biệt lớn nhất so với cách
repo `kido-orc` làm (gọi VLM cho **mọi** chứng từ, mọi lúc).

---

## 3. Năm cổng lọc trước khi được phép gọi API

Mỗi trang phải qua **hết** các cổng mới được tiêu tiền. Xếp theo thứ tự rẻ trước.

| Cổng | Câu hỏi | Loại bỏ (tập 72 ảnh demo) |
|---|---|---|
| **G0 · Cache** | `sha256(ảnh)+model+prompt` đã có kết quả? | mọi lần chạy lại → **0đ** |
| **G1 · Rulebook** | SOP có yêu cầu kiểm chứng từ này không? "Không cần chứng từ" / "không mang về" → bỏ hẳn | **~13** (18%) — chủ yếu 11 PO |
| **G2 · Cổ điển đã phủ?** | doc_type này engine cổ điển đã đạt chuẩn? `LOADING_PLAN` đang P=R=100% | **19** (26%) |
| **G3 · Trang có ô ký?** | Tầng 1/3b xác định trang không có khối ô ký (trang bảng hàng hoá của phiếu nhiều tờ) | chưa xác định |
| **G4 · Đã có template?** | doc_type × system đã có template từ Chế độ A | tiến tới **~100%** |

Còn lại mới gọi — **1 lần/trang**, không gọi lại.

**G2 phải chặn theo `doc_type`, KHÔNG theo "độ tự tin của engine cổ điển".**
Repo `kido-orc` chỉ ra đúng một cái bẫy: nếu lấy phán đoán của engine cổ điển làm điều kiện
kích hoạt, thì lúc nó **sai một cách tự tin** sẽ không phát tín hiệu nào và lỗi đi thẳng vào kết quả.
"doc_type này đã được benchmark với GT" là **sự kiện đo được**, không phải tự đánh giá — nên dùng
làm cổng thì an toàn.

---

## 4. Phân công: API định vị, đo mực kết luận

| Việc | Ai làm | Lý do |
|---|---|---|
| Vị trí ô ký trên biểu mẫu lạ | **API** (Chế độ A) | cổ điển không có bộ dò cho biểu mẫu chưa gặp |
| **Đã ký / trống** | **đo mực cổ điển** | con số ra phán quyết phải tất định. Đo 28/09 trên GT v4: cổ điển 44/25/0/0 (P=R=100%) vs Gemini gọi thẳng Google 43/24/1/1 |
| Mộc | đo mực + hình học | chưa đo API trên mộc — **chưa xác định** |
| Cờ mâu thuẫn | so vị trí API ↔ đo mực | lệch → đẩy người soát, không tự quyết |

Giữ nguyên nguyên tắc: **API chỉ ghi vào trường `vlm_*`, không bao giờ ghi đè kết quả cổ điển.**
Tắt `VLM_ENABLED` thì hệ thống chạy y như hiện tại.

---

## 5. Ước tính chi phí

| Giai đoạn | Số lần gọi | Tiền |
|---|---|---|
| Chế độ A — sinh template 15 doc_type × 2-3 ảnh | ~40 | **~210đ** |
| Soát tay + gọi lại chỗ hỏng | ~15 | ~80đ |
| Chế độ C — ngoại lệ, ước 5% của 1 000 chứng từ/tháng | ~50/tháng | ~265đ/tháng |
| **Production thường ngày** | **0** | **0đ** |

Số dư hiện tại **1 989đ** thừa cho toàn bộ Chế độ A và còn dư nhiều lượt chạy lại.

So với cách gọi API cho mọi chứng từ: 1 000 chứng từ/tháng × 5,3đ = **5 300đ/tháng**, tức
**gấp ~20 lần**. Và mỗi chứng từ lại là một lần gửi dữ liệu khách ra ngoài.

---

## 6. Ràng buộc kỹ thuật đã chốt

- **Cache là bắt buộc**, khóa `sha256(bytes ảnh) + model + version prompt + temperature`.
  Khóa tính trên **ảnh gốc người dùng nộp**, KHÔNG phải ảnh sau Tầng 1 — ảnh T1 trên Linux
  lệch pixel 35/72 so Windows, khóa theo nó sẽ cache miss trên Docker và sinh thêm nguồn lệch.
- `temperature = 0`, nằm trong khóa cache.
- Gọi hỏng → trả lỗi, **không** âm thầm đổi model, **không** ghi cache.
- Prompt có `PROMPT_VERSION`; đổi prompt là đổi khóa cache — cố ý, để không lẫn kết quả hai đời prompt.
- Kết quả API **không** ghi vào artifact Tầng 1–4; nằm riêng ở `output/vlm_*`.

## 7. Việc chưa đo — không được phát biểu như đã biết

- Độ chính xác của `gemini-2.5-flash-lite` trên **53 ảnh ngoài `LOADING_PLAN`** — đây chính là
  phần API sinh ra để phục vụ. Mới chạy 3 ảnh LP (TP3/TN4/FP0/FN3), quá ít để kết luận.
- Model nào đáng tiền: gateway có 187 model. Chưa so.
- API phát hiện **mộc** tốt đến đâu.
- `reasoning_effort: "none"` (Smartlog dùng) có cắt được output token không.

## 8. Bản đồ mã nguồn

| File | Việc |
|---|---|
| `tools/vlm_gateway.py` | client + cache + thu nhỏ ảnh |
| `tools/run_vlm_sig_scope.py` | chạy theo bộ (`--bo lp` có GT chấm điểm / `--bo abstain`) |
| `output/vlm_cache/<model>/<sha>.json` | cache — chạy lại 0đ |
| `output/vlm_sig_scope/<model>/<bo>/` | kết quả + `_eval.json` |
| `.env` | `VLM_API_KEY`, `VLM_API`, `VLM_MODEL`, `VLM_MAX_EDGE` |
