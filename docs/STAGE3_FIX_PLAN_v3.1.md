# PLAN SỬA TẦNG 3 — OCR KIDO DOCUMENT AUDIT
## Production Hardening v3.1

> **Mục tiêu:** Đóng các lỗi logic đã phát hiện trong `ocr-tang3-batch.ipynb`, giữ lại phần code/visualization đang hoạt động tốt, nhưng sửa lại identity, multi-page stitching, shipment batching, OrderDossier, cross-field reconciliation, checklist semantics và contract cho Tầng 4.
>
> **Phạm vi:** Chỉ sửa Tầng 3 và các artifact/config cần thiết để Tầng 3 nhận đúng output Tầng 2. Không tự ý thay đổi logic Tầng 1/Tầng 2 nếu không có lỗi integration được chứng minh.

---

# 1. BỐI CẢNH VÀ CONTRACT HIỆN TẠI

Pipeline:

```text
Tầng 1
  ↓
Ảnh A4 chuẩn hóa + Stage 1 metadata
  ↓
Tầng 2
  ↓
doc_type
system
page_role
shipment_id
invoice_no
po_no
pxk_no
transfer_order_no
  ↓
TẦNG 3
  ├── Multi-page stitching
  ├── ShipmentBatch
  ├── OrderDossier
  ├── Cross-field reconciliation
  ├── Checklist audit
  └── Stage 4 manifest / signature_targets
```

Dataset demo hiện tại:

```text
72 ảnh đầu vào
→ 65 document entities
→ 7 bộ multi-page
→ 19 batch
→ 57 OrderDossier
```

Các con số trên chỉ là output hiện tại, KHÔNG được coi là Ground Truth accuracy. Sau khi sửa phải chạy benchmark lại.

---

# 2. CÁC LỖI CẦN ĐÓNG

## BUG-01 — CRITICAL
### ShipmentBatch hiện chưa thực sự group theo Shipment ID

Code hiện tại dùng logic tương đương:

```python
batch_key = f"BATCH_{business_code}_{system}"
```

Shipment ID chỉ được gán sau khi batch đã được tạo.

### Vấn đề

Hai shipment khác nhau nhưng cùng system/business code có thể bị gom vào cùng một batch:

```text
Shipment A + COOP
Shipment B + COOP
        ↓
BATCH_x_COOP
```

và `shipment_id` có thể chỉ giữ giá trị đầu tiên.

### Yêu cầu sửa

ShipmentBatch phải được identity theo thứ tự ưu tiên:

```text
1. shipment_id + system/business context
2. transfer_order_no + system/business context
3. business document identity có độ tin cậy đủ cao
4. unresolved batch nếu không đủ identity
```

Không được gom nhiều shipment khác nhau chỉ vì cùng system/business code.

### Nếu thiếu identity

Không tự động gom vào một batch chung.

Tạo trạng thái:

```text
UNRESOLVED
LOW_CONFIDENCE
```

hoặc tương đương, để audit biết rằng identity chưa đủ.

---

# 3. BUG-02 — CRITICAL
## OrderDossier hiện tách PO và Invoice thành các dossier khác nhau

Logic hiện tại ưu tiên một key:

```python
if invoice_no:
    INV_x
elif po_no:
    PO_x
elif transfer_order_no:
    TRANSFER_x
elif pxk_no:
    PXK_x
```

### Vấn đề

Ví dụ:

```text
PO 123
Invoice 456
```

có thể bị tạo thành:

```text
Dossier A = PO 123
Dossier B = Invoice 456
```

Khi đó cross-field reconciliation PO ↔ Invoice không thể thực sự hoạt động trên cùng một dossier.

### Yêu cầu sửa

OrderDossier phải được xây dựng theo QUAN HỆ giữa các chứng từ, không theo một ID duy nhất.

Mô hình mong muốn:

```text
ShipmentBatch
│
├── OrderDossier A
│     ├── PO
│     ├── Invoice
│     ├── Loading Plan
│     ├── PGH
│     └── PXK
│
└── OrderDossier B
      ├── PO
      ├── Invoice
      └── PGH
```

Các chứng từ có thể được liên kết thông qua:

```text
shipment_id
transfer_order_no
po_no
invoice_no
pxk_no
```

### Khuyến nghị implementation

Có thể dùng graph/union-find hoặc equivalent deterministic relationship resolver:

```text
PO_123
   ↕ po_no
Invoice_456
   ↕ shipment_id
Shipment_789
   ↕
LoadingPlan
```

Các node có quan hệ chắc chắn phải thuộc cùng dossier.

Không được merge chỉ vì cùng system/business code.

---

# 4. BUG-03 — CRITICAL
## Multi-page stitching vẫn phụ thuộc filename stem

Code hiện tại có logic kiểu:

```python
filename
→ Path(filename).stem
→ stem_groups
→ tìm continuation
```

Điều này mâu thuẫn với mục tiêu filename-leakage-free.

### Vấn đề

Production có thể nhận:

```text
scan_001.jpg
scan_002.jpg
scan_003.jpg
```

hoặc tên file bất kỳ.

Filename không phải business identity.

### Yêu cầu sửa

`CONTINUATION` phải được ghép dựa trên metadata Tầng 2 và các tín hiệu nghiệp vụ:

Ưu tiên:

```text
1. page_role
2. doc_type
3. system
4. shipment_id
5. transfer_order_no
6. po_no
7. invoice_no
8. pxk_no
9. page sequence / continuity
```

Filename chỉ được phép:

```text
- debug
- traceability
- fallback cực kỳ rõ ràng
```

Không được dùng filename làm identity chính.

### Không được làm

Không thay filename stem bằng một regex filename khác rồi tuyên bố filename leakage đã được loại bỏ.

---

# 5. BUG-04 — HIGH
## Multi-page parent selection chưa đủ deterministic

Hiện tại logic có xu hướng:

```text
headers = non-continuation
parent = headers[0]
```

sau đó mới ưu tiên loại tài liệu.

### Yêu cầu

Phải chọn parent bằng business identity + document role.

Quy trình:

```text
CONTINUATION
   ↓
candidate parents
   ↓
filter doc_type/system
   ↓
match business identifiers
   ↓
page continuity
   ↓
deterministic scoring
   ↓
parent
```

Nếu không có parent đủ tin cậy:

```text
UNRESOLVED_CONTINUATION
```

Không ghép bừa.

---

# 6. BUG-05 — HIGH
## Cross-field reconciliation hiện chưa phải reconciliation thực sự

Sau khi sửa OrderDossier, phải xây reconciliation theo từng quan hệ.

Không chỉ xuất:

```text
KHOP_HOAN_TOAN
KHOP_MOT_PHAN
DON_LE
XUNG_DOT
```

mà phải lưu evidence.

Ví dụ schema:

```json
{
  "field": "po_no",
  "source_document": "PO",
  "target_document": "HOA_DON",
  "source_value": "PO123",
  "target_value": "PO123",
  "status": "MATCH"
}
```

### Các quan hệ cần kiểm tra

```text
Shipment
  ↕
Loading Plan
  ↕
PO
  ↕
Invoice
  ↕
PXK
  ↕
PGH
```

Tùy loại chứng từ thực tế, quan hệ không tồn tại thì không đánh dấu lỗi.

### Trạng thái đề xuất

```text
MATCH
PARTIAL_MATCH
MISMATCH
MISSING_SOURCE
MISSING_TARGET
NOT_APPLICABLE
```

Sau đó mới tổng hợp:

```text
KHOP_HOAN_TOAN
KHOP_MOT_PHAN
XUNG_DOT
DON_LE
```

---

# 7. BUG-06 — HIGH
## Signature targets đang fallback sang DEFAULT

Logic hiện tại tương đương:

```python
SIGNATURE_PRESET_MAP.get(doc_type, DEFAULT)
```

### Vấn đề

Một document type mới/chưa mapping vẫn bị gán signature boxes mặc định.

Điều này có thể tạo target sai cho Tầng 4.

### Yêu cầu sửa

Nếu không có preset:

```json
{
  "signature_targets": [],
  "target_mapping_status": "UNMAPPED"
}
```

Không dùng DEFAULT âm thầm.

Chỉ sử dụng DEFAULT nếu có một business rule rõ ràng chứng minh document type đó thực sự dùng cùng layout.

### Thêm metadata

```text
target_mapping_status:
  MAPPED
  UNMAPPED
```

Có thể thêm:

```text
preset_source
preset_version
```

nếu thuận tiện.

---

# 8. BUG-07 — MEDIUM
## Checklist đang trộn document count với copy count

Hiện tại logic có xu hướng:

```python
found_counts[d.doc_type] += 1
```

Trong khi một document có thể:

```text
page_count = 2
```

và nghiệp vụ có thể yêu cầu số liên/copy.

### Yêu cầu

Tách rõ:

```text
document_count
page_count
copy_count
```

Không dùng một biến `found` cho cả ba semantics.

### Checklist output nên phân biệt

```json
{
  "document_type": "PO",
  "document_count": 1,
  "page_count": 2,
  "copy_count": 1
}
```

Nếu dữ liệu nguồn không đủ để xác định copy_count thì:

```text
copy_count = null
copy_count_status = UNKNOWN
```

Không tự suy diễn.

---

# 9. BUG-08 — MEDIUM
## CANONICAL_MAP còn phụ thuộc thứ tự regex

Các mapping kiểu:

```python
(r"PO|đơn đặt hàng|Don dat hang", "PO")
```

có `break` khi match đầu tiên.

### Vấn đề

Thứ tự rule có thể thay đổi kết quả.

### Yêu cầu

Ưu tiên nguồn canonical chính:

```text
form_catalog.json
→ doc_type
→ explicit canonical mapping
```

Regex chỉ là fallback.

Nếu vẫn cần regex:

```text
- rule phải có priority
- rule phải deterministic
- conflict phải được log
```

Ví dụ:

```json
{
  "pattern": "...",
  "canonical_type": "PO",
  "priority": 100
}
```

---

# 10. BUG-09 — MEDIUM
## business-code mapping đang hardcode trong logic

Các rule như:

```python
if system == "COOP":
    ...
```

không nhất thiết sai vì đây là business rule, nhưng cần tách khỏi core grouping engine.

### Yêu cầu

Tạo business configuration/rule layer.

Ví dụ:

```text
config/
  stage3_business_rules.json
```

hoặc cấu trúc tương đương.

Core engine chỉ đọc rule.

Mục tiêu:

```text
CLASSIFICATION LOGIC
≠
BUSINESS RULE
```

Không cần over-engineer nếu notebook hiện tại chưa cần module hóa toàn bộ.

---

# 11. BUG-10 — MEDIUM
## Tuyên bố "100% được gán Bounding Box" dễ gây hiểu nhầm

Nếu tất cả 65 document entities đều có signature target nhờ preset thì chỉ được báo:

```text
65/65 document entities được gán signature targets
```

Không được suy ra:

```text
100% target boxes chính xác
```

### Nên thêm:

```text
preset_assigned_count
unmapped_count
verified_count
```

Nếu chưa có verification Ground Truth thì không được gọi là accuracy.

---

# 12. BỔ SUNG — STAGE 3 GROUND TRUTH

Hiện tại các con số:

```text
72 images
65 documents
19 batches
57 dossiers
7 multi-page groups
```

là output của thuật toán, chưa phải independent Ground Truth.

### Yêu cầu tạo benchmark độc lập

Tạo:

```text
output/stage3_gt.json
```

hoặc location phù hợp với cấu trúc project.

Tối thiểu cần:

```json
{
  "document_id": "...",
  "parent_document_id": "...",
  "continuation_pages": [],
  "shipment_id": "...",
  "order_dossier_id": "...",
  "expected_relationships": [],
  "expected_checklist": {}
}
```

### Metrics đề xuất

```text
Multi-page:
  precision
  recall
  F1

Shipment grouping:
  purity
  completeness

Order dossier:
  purity
  completeness

Cross-field:
  field-level match accuracy

Checklist:
  rule-level accuracy
```

Không tự tạo Ground Truth từ output của chính algorithm.

Nếu chưa đủ dữ liệu để tạo GT độc lập, ghi rõ:

```text
Ground Truth chưa hoàn chỉnh
```

và không báo accuracy giả.

---

# 13. KIẾN TRÚC SAU KHI SỬA

Mục tiêu:

```text
STAGE 2
   │
   ▼
Document Entities
   │
   ▼
Multi-page Resolver
   │
   ├── Header
   └── Continuation
   │
   ▼
Complete Documents
   │
   ▼
Shipment Identity Resolver
   │
   ▼
ShipmentBatch
   │
   ▼
Relationship Resolver / Document Graph
   │
   ▼
OrderDossier
   │
   ▼
Cross-field Reconciliation
   │
   ▼
Checklist Audit
   │
   ▼
Stage 3 Manifest
   │
   ├── Stage 4 signature_targets
   └── audit metadata
```

---

# 14. SHIPMENT IDENTITY RULE

Implement deterministic priority:

```text
if shipment_id is valid:
    identity = shipment_id + system/context

elif transfer_order_no is valid:
    identity = transfer_order_no + system/context

elif strong business document key exists:
    identity = strongest valid key + system/context

else:
    identity = UNRESOLVED
```

### Không được:

```text
business_code + system
```

làm shipment identity khi có khả năng nhiều shipment cùng business/system.

---

# 15. ORDER DOSSIER RESOLUTION

Tạo document nodes:

```text
PO
INVOICE
LOADING_PLAN
PGH
PXK
TRANSFER_ORDER
...
```

Mỗi node chứa:

```text
doc_id
doc_type
shipment_id
transfer_order_no
po_no
invoice_no
pxk_no
system
business_code
```

Tạo edges khi field liên kết chắc chắn:

```text
same shipment_id
same transfer_order_no
same po_no
same invoice_no
same pxk_no
```

Không merge khi chỉ có:

```text
same system
same business_code
same filename
```

Trừ khi có rule nghiệp vụ cụ thể và được ghi log.

---

# 16. CONFIDENCE / AUDITABILITY

Mọi quyết định grouping quan trọng nên có:

```json
{
  "decision": "MERGED",
  "reason": "same shipment_id",
  "confidence": "HIGH"
}
```

Ví dụ:

```text
HIGH
same shipment_id

MEDIUM
same transfer_order_no + system

LOW
weak business key
```

Nếu unresolved:

```text
decision = "UNRESOLVED"
```

Điều này rất quan trọng cho audit và debug.

---

# 17. KHÔNG PHÁ VỠ TẦNG 1 / TẦNG 2

Không thay đổi các logic đã ổn của Tầng 1/Tầng 2 chỉ để làm Tầng 3 dễ hơn.

Tầng 3 phải tương thích với:

```text
stage2_classified_results.json
```

và các field:

```text
doc_type
system
page_role
shipment_id
invoice_no
po_no
pxk_no
transfer_order_no
```

Nếu field thiếu hoặc null:

```text
handle gracefully
```

Không crash.

---

# 18. GIỮ LẠI NHỮNG PHẦN ĐANG TỐT

Không cần viết lại toàn bộ notebook.

Giữ nếu không bị ảnh hưởng:

```text
- Visualization
- Stitching Inspector
- Batch Distribution
- Checklist Heatmap
- Dossier Gallery
- Manifest export
- Performance optimizations
- Existing data structures nếu có thể tái sử dụng
```

Chỉ refactor phần logic identity/grouping/reconciliation/target mapping cần thiết.

---

# 19. TEST CASE BẮT BUỘC SAU KHI SỬA

## Test 1 — Hai shipment cùng system

```text
COOP + Shipment A
COOP + Shipment B
```

Expected:

```text
2 ShipmentBatch
```

Không được:

```text
1 ShipmentBatch
```

---

## Test 2 — PO + Invoice cùng order

```text
PO123
Invoice456
same shipment
```

Expected:

```text
1 OrderDossier
```

---

## Test 3 — PO + Invoice khác order

```text
PO123 + Invoice456
PO789 + Invoice999
```

Expected:

```text
2 OrderDossier
```

---

## Test 4 — Multi-page không phụ thuộc filename

Đổi:

```text
PO_3.1__0.png
PO_3.1__1.png
```

thành tên random:

```text
IMG_0001.jpg
IMG_9843.jpg
```

Nếu Stage 2 metadata giữ nguyên, kết quả stitching phải giữ nguyên.

---

## Test 5 — Continuation không có parent

Expected:

```text
UNRESOLVED_CONTINUATION
```

Không tự ghép vào document bất kỳ.

---

## Test 6 — Unknown doc_type

Expected:

```text
signature_targets = []
target_mapping_status = UNMAPPED
```

Không dùng DEFAULT.

---

## Test 7 — Multi-page checklist

Ví dụ PO 2 trang:

```text
document_count = 1
page_count = 2
```

Không được:

```text
document_count = 2
```

---

# 20. REGRESSION CHECK

Sau khi sửa phải chạy toàn bộ notebook trên bộ 72 ảnh.

Bắt buộc ghi:

```text
input_images
document_entities
multi_page_groups
shipment_batches
order_dossiers
reconciliation_results
checklist_results
unresolved_items
```

So sánh trước/sau.

Không cố ép kết quả mới phải bằng:

```text
65 / 19 / 57
```

Nếu logic đúng làm số batch/dossier thay đổi thì chấp nhận thay đổi và giải thích nguyên nhân.

---

# 21. ACCEPTANCE CRITERIA

Tầng 3 chỉ được coi là hoàn thành khi:

### Identity

- [ ] ShipmentBatch không còn group chỉ bằng `business_code + system`.
- [ ] Hai shipment khác nhau không thể bị gom chung chỉ vì cùng system.
- [ ] Có trạng thái unresolved khi thiếu identity.

### Multi-page

- [ ] Không dùng filename stem làm identity chính.
- [ ] Continuation được resolve bằng Stage 2 metadata/business fields.
- [ ] Không có parent phù hợp → unresolved, không merge bừa.
- [ ] Randomize filename vẫn cho kết quả stitching tương đương.

### Dossier

- [ ] PO + Invoice cùng order có thể nằm trong cùng dossier.
- [ ] Các order khác nhau không bị merge.
- [ ] Graph/relationship resolution deterministic.

### Reconciliation

- [ ] Có field-level evidence.
- [ ] Có MATCH / PARTIAL / MISMATCH / MISSING / N/A.
- [ ] Có summary status.

### Checklist

- [ ] Tách document_count/page_count/copy_count.
- [ ] Không tự suy diễn copy count nếu nguồn không đủ.

### Stage 4

- [ ] Không có silent DEFAULT signature preset.
- [ ] Unknown mapping → UNMAPPED.
- [ ] Signature target có traceability.

### Benchmark

- [ ] Có regression run trên 72 ảnh.
- [ ] Không báo accuracy nếu chưa có independent Ground Truth.
- [ ] Ghi rõ trước/sau nếu số lượng batch/dossier thay đổi.

---

# 22. OUTPUT MONG MUỐN

Stage 3 manifest phải chứa tối thiểu:

```json
{
  "batch_id": "...",
  "shipment_id": "...",
  "batch_confidence": "...",
  "documents": [],
  "order_dossiers": [],
  "reconciliation": [],
  "checklist": {},
  "audit_flags": []
}
```

Document item nên có:

```json
{
  "doc_id": "...",
  "doc_type": "...",
  "page_count": 1,
  "is_multi_page": false,
  "shipment_id": "...",
  "invoice_no": "...",
  "po_no": "...",
  "pxk_no": "...",
  "transfer_order_no": "...",
  "signature_targets": [],
  "target_mapping_status": "MAPPED"
}
```

---

# 23. NGUYÊN TẮC QUAN TRỌNG CHO AGENT

1. Không rewrite toàn bộ notebook nếu không cần.
2. Không sửa Tầng 1/Tầng 2 nếu không có lỗi integration cụ thể.
3. Không dùng filename làm business identity.
4. Không group shipment chỉ bằng system/business code.
5. Không tách PO và Invoice thành dossier riêng khi có evidence chúng thuộc cùng order.
6. Không tạo reconciliation giả chỉ bằng summary label.
7. Không dùng DEFAULT signature target âm thầm.
8. Không gọi output của algorithm là Ground Truth.
9. Không ép số lượng batch/dossier về kết quả cũ nếu logic mới cho kết quả khác.
10. Mọi thay đổi phải có regression test.
11. Ưu tiên deterministic behavior và auditability.
12. Giữ visualization/output structure hiện tại nếu tương thích.

---

# 24. THỨ TỰ IMPLEMENTATION

## Phase 1
Multi-page Resolver

## Phase 2
Shipment Identity Resolver + ShipmentBatch

## Phase 3
Document Graph + OrderDossier

## Phase 4
Field-level Cross-field Reconciliation

## Phase 5
Checklist semantics

## Phase 6
Signature target mapping / Stage 4 contract

## Phase 7
Regression benchmark + Stage 3 GT

## Phase 8
Update visualization/report outputs

Không chuyển sang Phase tiếp theo nếu Phase trước chưa pass các test bắt buộc.

---

# 25. KẾT QUẢ CUỐI CÙNG CẦN BÁO CÁO

Sau khi hoàn thành, Agent phải báo:

```text
1. Files changed
2. Functions changed
3. Bugs fixed
4. Tests added
5. Regression results
6. Before/after:
   - document entities
   - multi-page groups
   - shipment batches
   - order dossiers
7. Number of unresolved items
8. Reconciliation summary
9. Checklist summary
10. Signature target mapping coverage
11. Any remaining known limitations
```

Không được chỉ báo:

```text
"Notebook chạy thành công"
```

mà phải chứng minh các lỗi logic ở trên đã được đóng.
