"""
Module Stage 2: Document Classification & Key Field Extraction (v3.4 Production-Clean)
Hệ thống Kiểm Tra Chứng Từ Giao Nhận KIDO

Tính năng chính (v3.4 Production-Clean):
- Khử sạch 100% hardcode tên file và danh sách mã SAP (Generalization tuyệt đối).
- Tiếp nhận trực tiếp hợp đồng dữ liệu Tầng 1 (status, action, rotation.needs_verification_180).
- Phân tách vai trò trang: page_role ('HEADER' vs 'CONTINUATION') chuẩn bị cho Tầng 3.
- Bóc tách trường khóa sâu: Chuẩn hóa 8 chữ số hóa đơn (NĐ 123), bắt regex PO đa siêu thị, số PXK.
- Tối ưu hiệu năng OCR: Early-exit khi nhận diện chất lượng cao, giảm thiểu số lần gọi Tesseract.
- Đồng thuận đa trang theo NHÓM UPLOAD tường minh (upload_group_id + scan_index), không đọc tên file.
- Two-Zone Scanning có điều kiện (chỉ quét Zone 2 khi thiếu trường bắt buộc).
"""

import os
import re
import time
import json
import unicodedata
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Tuple, Optional, Any
from collections import Counter

import cv2
import numpy as np
import pytesseract
from rapidfuzz import fuzz

# Tự động cấu hình đường dẫn Tesseract trên Windows
tess_candidates = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path.home() / r"AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
]
for p in tess_candidates:
    if p.exists():
        pytesseract.pytesseract.tesseract_cmd = str(p)
        break


# TỪ ĐIỂN TỪ KHÓA + NGƯỠNG PHÂN LOẠI nằm trong config/stage2_keywords.json (dữ liệu, không phải logic).
# Đường dẫn neo theo vị trí module (không theo cwd) để notebook/runner chạy từ thư mục nào cũng nạp đúng.
# CỐ Ý KHÔNG có bản dự phòng hardcode: thiếu file / JSON hỏng / thiếu khóa -> raise ngay tại import.
# Quy tắc chống keyword shadowing (AGENTS.md mục 4.A) được ghi trong khóa "_rules" của file config.
KEYWORDS_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "stage2_keywords.json"

_REQUIRED_THRESHOLDS = (
    "fuzzy_threshold", "conf_pass_threshold", "conf_warn_threshold", "margin_pass_threshold",
    "system_fuzzy_threshold", "fuzzy_min_keyword_len", "exact_len_bonus_divisor",
    "exact_len_bonus_cap", "early_exit_min_hits", "early_exit_min_hits_with_digits",
)


class Stage2ConfigError(RuntimeError):
    """Cấu hình từ điển Tầng 2 thiếu hoặc sai cấu trúc."""


def _load_keywords_config(path: Path = KEYWORDS_CONFIG_PATH) -> dict:
    if not path.exists():
        raise Stage2ConfigError(
            f"Không tìm thấy từ điển Tầng 2: {path}. File này là BẮT BUỘC "
            f"(không có dự phòng hardcode trong stage2_classifier.py)."
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise Stage2ConfigError(f"JSON hỏng trong {path}: {exc}") from exc

    def _rule_list(key: str, id_key: str) -> list:
        items = data.get(key)
        if not isinstance(items, list) or not items:
            raise Stage2ConfigError(f"{path}: khóa '{key}' phải là danh sách không rỗng.")
        out = []
        for i, it in enumerate(items):
            if (not isinstance(it, dict) or not isinstance(it.get(id_key), str)
                    or not isinstance(it.get("keywords"), list)
                    or not all(isinstance(k, str) for k in it["keywords"])):
                raise Stage2ConfigError(
                    f"{path}: '{key}[{i}]' phải có dạng {{\"{id_key}\": str, \"keywords\": [str, ...]}}."
                )
            out.append((it[id_key], list(it["keywords"])))
        ids = [o[0] for o in out]
        if len(set(ids)) != len(ids):
            raise Stage2ConfigError(f"{path}: '{key}' có {id_key} trùng lặp: {ids}.")
        return out

    thresholds = data.get("thresholds")
    if not isinstance(thresholds, dict):
        raise Stage2ConfigError(f"{path}: thiếu khóa 'thresholds'.")
    missing = [k for k in _REQUIRED_THRESHOLDS if not isinstance(thresholds.get(k), (int, float))
               or isinstance(thresholds.get(k), bool)]
    if missing:
        raise Stage2ConfigError(f"{path}: 'thresholds' thiếu hoặc sai kiểu số: {missing}.")

    return {
        "doc_rules": _rule_list("doc_rules", "doc_type"),
        "system_rules": _rule_list("system_rules", "system"),
        "internal_subtype_markers": _rule_list("internal_subtype_markers", "subtype"),
        "thresholds": {k: thresholds[k] for k in _REQUIRED_THRESHOLDS},
    }


_KEYWORDS_CFG = _load_keywords_config()
THRESHOLDS = _KEYWORDS_CFG["thresholds"]


@dataclass
class Stage2Config:
    # Thư mục dữ liệu
    base_dir: Path = Path(".")
    samples_dir: Path = Path("output/form_samples")
    form_catalog_path: Path = Path("output/form_catalog.json")
    stage1_pages_dir: Path = Path("output/stage1_out/pages/form_samples")
    stage1_images_dir: Path = Path("output/stage1_out/images/form_samples")
    output_dir: Path = Path("output/stage2_out")
    gt_path: Path = Path("output/stage2_gt.json")
    
    # Tỷ lệ cắt Header
    crop_ratio_portrait: float = 0.35      # Vùng 1: 35% chiều cao ảnh dọc
    crop_ratio_landscape: float = 0.45     # Vùng 1: 45% chiều cao ảnh ngang
    crop_ratio_zone2: float = 0.60         # Vùng 2: quét tới 60% chiều cao khi thiếu trường khóa
    # Vùng 2 CỐ Ý quét lại từ đầu ảnh (0.0), KHÔNG phải lãng phí như nhìn thoáng qua:
    # crop lớn hơn -> tỷ lệ resize về 1600px khác -> Tesseract cho kết quả KHÁC. Đây thực
    # chất là lần đọc thứ hai ở độ phân giải khác, và nó cứu được các trường mà Zone 1
    # đọc trượt. Thực nghiệm cắt dải 0.30->0.60 làm po_no Recall tụt 83.3% -> 58.3%
    # và pxk_no 100% -> 75%. Giữ 0.0.
    crop_zone2_start: float = 0.0
    write_rotated_back: bool = False       # Ghi đè ảnh đã xoay 180 lên đĩa (side-effect, mặc định TẮT)
    target_ocr_width: int = 1600           # Chiều rộng 1600px bảo toàn nét chữ thanh mảnh
    
    # Cấu hình Tesseract
    ocr_lang: str = "vie+eng"
    primary_psm: int = 6
    fallback_psm: int = 3
    
    # Ngưỡng phân loại & Gác cổng — giá trị mặc định nạp từ config/stage2_keywords.json ("thresholds")
    fuzzy_threshold: float = THRESHOLDS["fuzzy_threshold"]
    conf_pass_threshold: float = THRESHOLDS["conf_pass_threshold"]
    conf_warn_threshold: float = THRESHOLDS["conf_warn_threshold"]
    margin_pass_threshold: float = THRESHOLDS["margin_pass_threshold"]
    system_fuzzy_threshold: float = THRESHOLDS["system_fuzzy_threshold"]
    fuzzy_min_keyword_len: int = THRESHOLDS["fuzzy_min_keyword_len"]
    exact_len_bonus_divisor: float = THRESHOLDS["exact_len_bonus_divisor"]
    exact_len_bonus_cap: float = THRESHOLDS["exact_len_bonus_cap"]
    early_exit_min_hits: int = THRESHOLDS["early_exit_min_hits"]
    early_exit_min_hits_with_digits: int = THRESHOLDS["early_exit_min_hits_with_digits"]


def normalize_text(text: str) -> str:
    """Chuẩn hóa văn bản: Bỏ dấu tiếng Việt, chuyển sang uppercase ASCII sạch sẽ."""
    if not text:
        return ""
    text = unicodedata.normalize("NFD", str(text))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.upper().replace("Đ", "D")
    text = re.sub(r"[^A-Z0-9\s:/._#-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# 15 NHÓM CHỨNG TỪ QUY CHUẨN KIDO — dữ liệu nằm ở config/stage2_keywords.json ("doc_rules").
# Giữ nguyên tên + dạng list[(doc_type, [keyword, ...])] để tương thích caller
# (tools/generate_nb2.py, ocr-tang2-classify.ipynb). THỨ TỰ trong file config có ý nghĩa.
RAW_DOC_RULES = _KEYWORDS_CFG["doc_rules"]

# 12 HỆ THỐNG ĐỐI TÁC QUY CHUẨN THEO TAXONOMY KIDO — config/stage2_keywords.json ("system_rules").
RAW_SYSTEM_RULES = _KEYWORDS_CFG["system_rules"]

# PHÂN LOẠI CON CỦA NHÓM CHUYỂN KHO (INTERNAL_TRANSFER) — theo SOP KIDO, sheet mục 5:
#   5.1 "Hàng chuyển kho thuê CLK/AJ/Lotte/Anpha"            -> INTERNAL_KHO_THUE
#   5.2 "Hàng trung chuyển kho Nội Bộ (Kho Quảng Nam/ Bắc Ninh)" -> INTERNAL_KHO_NOIBO
# Dấu hiệu là TÊN ĐƠN VỊ / ĐỊA DANH KHO do chính SOP liệt kê, không phải mã chuyến hay tên file.
# Các cụm "NOI BO", "DIEU DONG" KHÔNG phải dấu hiệu phân biệt: chúng nằm sẵn trong mẫu in
# của CẢ HAI loại (tiêu đề "PXK KIÊM VẬN CHUYỂN NỘI BỘ", "vận chuyển hàng nội bộ các Kho" của
# BBBG hàng hóa) -> chỉ xác định được HỌ chuyển kho, không xác định được loại kho.
# Không có dấu hiệu, hoặc có dấu hiệu của CẢ HAI loại -> GIỮ INTERNAL_TRANSFER, không đoán.
# "LOTTE" cố ý KHÔNG đưa vào: trùng từ khóa MT_LOTTE (keyword shadowing, mục 4.A AGENTS.md).
# Dữ liệu: config/stage2_keywords.json ("internal_subtype_markers").
RAW_INTERNAL_SUBTYPE_MARKERS = _KEYWORDS_CFG["internal_subtype_markers"]
INTERNAL_SUBTYPE_PATTERNS = [
    (sub_id, [(normalize_text(kw), re.compile(r"\b" + re.escape(normalize_text(kw)) + r"\b")) for kw in kws])
    for sub_id, kws in RAW_INTERNAL_SUBTYPE_MARKERS
]


def refine_internal_transfer(norm_text: str) -> Tuple[str, str]:
    """Tách INTERNAL_TRANSFER thành kho thuê / kho nội bộ khi và chỉ khi có dấu hiệu MỘT phía.

    Trả về (system_id, marker). Không đủ tín hiệu hoặc tín hiệu mâu thuẫn -> ("INTERNAL_TRANSFER", "").
    """
    hits = {}
    for sub_id, pats in INTERNAL_SUBTYPE_PATTERNS:
        for kw, pat in pats:
            if pat.search(norm_text):
                hits.setdefault(sub_id, kw)
                break
    if len(hits) == 1:
        sub_id, kw = next(iter(hits.items()))
        return sub_id, kw
    return "INTERNAL_TRANSFER", ""


DOC_RULES = [
    (doc_type, [normalize_text(kw) for kw in kws if kw.strip()])
    for doc_type, kws in RAW_DOC_RULES
]

SYSTEM_RULES = [
    (sys_id, [normalize_text(kw) for kw in kws if kw.strip()])
    for sys_id, kws in RAW_SYSTEM_RULES
]


SHIPMENT_REFERENCE_PATH = Path("config/stage2_shipment_reference.json")


def _load_shipment_reference(path: Path = SHIPMENT_REFERENCE_PATH) -> dict:
    """Nap danh muc ma chuyen tham chieu (ERP master data) neu co.

    Thiet ke co chu dich: du lieu khach hang nam TRONG FILE CAU HINH, khong nam trong code.
    Khong co file -> tra ve rong -> he thong chay o che do TRUNG THUC, khong hieu chinh gi.
    """
    try:
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data.get("enabled", False):
            return {}
        return {str(k): str(v) for k, v in (data.get("ocr_corrections") or {}).items()}
    except Exception as exc:
        print(f"[WARN] Khong doc duoc danh muc ma chuyen tham chieu {path}: {exc}")
        return {}


SHIPMENT_OCR_CORRECTIONS = _load_shipment_reference()


def disambiguate_shipment_id(cand: Optional[str]) -> Optional[str]:
    """Hieu chinh ma chuyen bi nhieu OCR tren anh scan nen 45-150 DPI.

    Gom hai tang, tach bach ro rang:
      1. Quy tac TONG QUAT ve hinh dang ky tu (I/L bi doc thay cho chu so 1) - luon bat.
      2. Doi chieu DANH MUC THAM CHIEU tu config/stage2_shipment_reference.json - chi bat khi
         co file. OCR tren anh 45-150 DPI nham lan co he thong cac cap chu so (1<->7, 3<->7,
         2<->5); KHONG the phuc hoi ma dung neu khong co mot danh muc that de doi chieu.

    Truoc day bang hieu chinh nay bi nhet cung trong ma nguon. Hau qua: benchmark dat 100% mot
    cach gia tao, khong the thay khi doi khach hang, va che giau nang luc that cua he thong.
    Nay no la du lieu tham chieu thay the duoc. Khong co file -> khong hieu chinh -> chi so do
    duoc phan anh dung nang luc OCR thuc te.
    """
    if not cand:
        return None
    cand = str(cand).strip()
    if cand.startswith(("I", "L")) and cand[1:].isdigit():
        cand = "1" + cand[1:]
    return SHIPMENT_OCR_CORRECTIONS.get(cand, cand)


class Stage2DocumentClassifier:
    """Bộ phân loại chứng từ giao nhận KIDO (v3.3 Production)."""
    
    def __init__(self, config: Optional[Stage2Config] = None):
        self.cfg = config or Stage2Config()
        
    def crop_header_adaptive(self, img_bgr: np.ndarray, zone: int = 1) -> Tuple[np.ndarray, float]:
        """Cắt vùng Header theo tỷ lệ thích ứng."""
        h, w = img_bgr.shape[:2]
        is_landscape = w > h
        if zone == 1:
            ratio = self.cfg.crop_ratio_landscape if is_landscape else self.cfg.crop_ratio_portrait
        else:
            ratio = self.cfg.crop_ratio_zone2
        crop_h = max(int(h * ratio), 100)
        if zone == 1:
            return img_bgr[0:crop_h, 0:w].copy(), ratio

        # VUNG 2 LA MOT DAI, KHONG PHAI MOT VUNG BAO TRUM.
        # Truoc day vung 2 cat 0 -> 60%, tuc bao trum tron ven vung 1 (0 -> 35%) va OCR lai y
        # nguyen phan da doc. Cat tu 30% giup giam manh chi phi OCR thua ma van giu mot dai
        # chong lan nho (30-35%) de khong cat ngang dong chu nam dung ranh gioi.
        start_y = min(int(h * self.cfg.crop_zone2_start), max(crop_h - 100, 0))
        return img_bgr[start_y:crop_h, 0:w].copy(), ratio

    def preprocess_for_ocr(self, header_bgr: np.ndarray, target_w: int = 1600, use_clahe: bool = True) -> np.ndarray:
        """Tiền xử lý ảnh: Giữ độ phân giải sắc nét, CLAHE tương phản cục bộ."""
        h, w = header_bgr.shape[:2]
        if w < target_w:
            target_h = int(h * (target_w / float(w)))
            resized = cv2.resize(header_bgr, (target_w, target_h), interpolation=cv2.INTER_CUBIC)
        else:
            resized = header_bgr
            
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        if use_clahe:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            return clahe.apply(gray)
        return gray

    def run_header_ocr_multipass(self, gray_img: np.ndarray) -> Tuple[str, int]:
        """OCR đa tầng thông minh: Thử PSM 6 -> Fallback PSM 3 nếu thiếu nét."""
        cfg_p6 = f"-l {self.cfg.ocr_lang} --psm {self.cfg.primary_psm} --oem 3"
        txt_p6 = pytesseract.image_to_string(gray_img, config=cfg_p6).strip()
        
        norm_p6 = normalize_text(txt_p6)
        kw_hits_p6 = sum(1 for _, kws in DOC_RULES for kw in kws if kw in norm_p6)
        has_digits_p6 = bool(re.search(r"\b\d{5,8}\b", norm_p6))
        
        if ((kw_hits_p6 >= self.cfg.early_exit_min_hits_with_digits and has_digits_p6)
                or kw_hits_p6 >= self.cfg.early_exit_min_hits):
            return txt_p6, self.cfg.primary_psm
            
        cfg_p3 = f"-l {self.cfg.ocr_lang} --psm {self.cfg.fallback_psm} --oem 3"
        txt_p3 = pytesseract.image_to_string(gray_img, config=cfg_p3).strip()
        norm_p3 = normalize_text(txt_p3)
        kw_hits_p3 = sum(1 for _, kws in DOC_RULES for kw in kws if kw in norm_p3)
        has_digits_p3 = bool(re.search(r"\b\d{5,8}\b", norm_p3))
        
        if (kw_hits_p3 > kw_hits_p6) or (not has_digits_p6 and has_digits_p3):
            return txt_p3, self.cfg.fallback_psm
        # GHI CHÚ THỰC NGHIỆM (27/09) — ĐÃ THỬ VÀ KHÔNG ÁP DỤNG (log: scratch/_nb/t2/exp_tiebreak.log):
        # Luật hòa "cả 2 pass 0 keyword-hit, không số -> chọn pass mà match_document_type != UNKNOWN".
        # Chỉ đổi đúng 1/72 trang (PO_3.11__0, ~40 DPI, trang "2/2" của PO): UNKNOWN -> PO/CONTINUATION
        # nhờ một từ tên sản phẩm (CELANO) ở PSM 3, doc_type 70 -> 71/72, trạng thái CANH_BAO.
        # Nhưng page_role 72 -> 71/72 (GT ghi HEADER) và Tầng 3 FAIL (multi-page P 7/8, F1 93.33%):
        # trang được ghép với PO_3.11__1 qua po_no mà chính nó KHÔNG đọc được — po_no đến từ
        # apply_stem_consistency_voting (gom theo TÊN FILE). Không đưa vào khi chưa gỡ phụ thuộc đó.
        # (27/09 tối: phụ thuộc tên file ĐÃ GỠ — nay là apply_upload_group_voting, cụm tương thích không
        #  nhận trang UNKNOWN. Luật hòa này CHƯA được đo lại trên cơ chế mới; muốn bật phải đo lại.)
        return txt_p6, self.cfg.primary_psm

    def match_document_type(self, norm_text: str) -> Tuple[str, float, float, str]:
        """Phân loại Loại chứng từ với Candidate Scoring & Anti-Keyword Shadowing."""
        # 1. Bảo vệ tuyệt đối PXKKVCNB
        is_pxk = ("XUAT KHO KIEM VAN CHUYEN" in norm_text or 
                  "PXKKVCNB" in norm_text or 
                  "KIEM VAN CHUYEN NOI BO" in norm_text or 
                  "PHIEU XUAT KHO KIEM" in norm_text)
        if is_pxk:
            return "PXKKVCNB", 1.0, 0.40, "PHIEU XUAT KHO KIEM VAN CHUYEN NOI BO"

        # 2. Nhận diện trang bảng kê tiếp nối (TABLE_CONTINUATION)
        has_po_title = any(kw in norm_text for kw in ["DON DAT HANG", "PURCHASE ORDER", "STORE ORDER", "BON DAT HANG", "QUY CACH DAT HANG"])
        is_continuation = (
            not has_po_title and (
                "TRANG 2" in norm_text or 
                ("MA VACH" in norm_text and "DON GIA" in norm_text) or
                ("BARCODE" in norm_text and "DON GIA" in norm_text) or
                ("LAYOUT" in norm_text and "STT" in norm_text and "DON DAT HANG" not in norm_text and "PO" not in norm_text) or
                (("MA SAN PHAM" in norm_text or "MA SP" in norm_text) and any(w in norm_text for w in ["CELANO", "MERINO", "KEM"]) and "HOA DON GIA TRI GIA TANG" not in norm_text)
            )
        )
        if is_continuation:
            return "TABLE_CONTINUATION", 0.90, 0.40, "Bang hang hoa (Trang tiep)"

        # 3. Ưu tiên nhận diện BB_NO_HANG khi có điều khoản áp dụng nợ hàng
        if any(w in norm_text for w in ["TRUONG HOP NO HANG", "TRUONG HOP NO HONG", "AP DUNG CHO CAC TRUONG HOP NO", "AP DUNG CHO COC TRUONG HOP NO"]):
            return "BB_NO_HANG", 1.0, 0.40, "BIEN BAN NO HANG"

        # Lọc bỏ cụm từ tham chiếu trong câu ghi chú đơn hàng để tránh false positive HOA_DON
        clean_text = re.sub(r"(?:KEM\s*THEO|GIAO\s*HANG\s*KEM\s*THEO)[^.\n]{0,40}HOA\s*DON\s*GTGT", "", norm_text)

        candidates = []
        for doc_type, kws in DOC_RULES:
            best_kw_score = 0.0
            best_kw = ""
            best_is_exact = False
            for kw in kws:
                if kw in clean_text:
                    score = 1.0 + min(len(kw) / self.cfg.exact_len_bonus_divisor, self.cfg.exact_len_bonus_cap)
                    if score > best_kw_score:
                        best_kw_score = score
                        best_kw = kw
                        best_is_exact = True
                elif len(kw) >= self.cfg.fuzzy_min_keyword_len:
                    ratio = fuzz.partial_ratio(kw, clean_text) / 100.0
                    if ratio >= self.cfg.fuzzy_threshold and ratio > best_kw_score:
                        best_kw_score = ratio
                        best_kw = kw
                        best_is_exact = False
            if best_kw_score > 0:
                clamped_score = min(best_kw_score, 1.0)
                candidates.append((doc_type, clamped_score, best_kw, len(best_kw), best_is_exact))

        candidates.sort(key=lambda x: (x[1], x[3]), reverse=True)
        if candidates:
            top1 = candidates[0]
            top1_kw, top1_exact = top1[2], top1[4]

            # MARGIN CHỈ TÍNH VỚI ỨNG VIÊN THỰC SỰ CẠNH TRANH.
            # Hai trường hợp KHÔNG phải nhập nhằng, phải loại khỏi phép tính margin:
            #   (a) Bao hàm từ khóa (subsumption): từ khóa của ứng viên là chuỗi con của từ khóa
            #       thắng cuộc -> cả hai khớp CÙNG một đoạn văn bản, chỉ khác mức độ đặc hiệu.
            #       VD: "PHIEU GIAO NHAN PALLET" (BBBG_PALLET) vs "PHIEU GIAO NHAN"
            #       (PHIEU_GIAO_HANG) -> không hề mâu thuẫn, bản dài hơn đặc hiệu hơn.
            #   (b) Lệch bậc bằng chứng (exact vs fuzzy): khi top1 khớp CHÍNH XÁC thì ứng viên chỉ
            #       khớp MỜ không được coi là đối thủ. Các mã biểu mẫu SOP anh em luôn đạt
            #       partial_ratio rất cao với nhau dù không hề xuất hiện trong văn bản.
            #       VD: "LG/GN/OP/01-01" đạt fuzzy 0.93 trên trang chỉ chứa "LG/GN/OP/01-05".
            rivals = []
            for cand in candidates[1:]:
                if cand[2] and cand[2] in top1_kw:
                    continue
                if top1_exact and not cand[4]:
                    continue
                rivals.append(cand)

            second_score = rivals[0][1] if rivals else 0.0
            margin = round(top1[1] - second_score, 2)
            return top1[0], top1[1], margin, top1[2]

        # 3. Fallback Heuristic
        if re.search(r"-\d{1,2}\.\d", norm_text) or "DUNG XE" in norm_text or "XE DANG CHAY" in norm_text or "DATALOGGER" in norm_text:
            return "BIEU_DO_NHIET_DO", 0.90, 0.30, "GPS/Datalogger log"
        if ("PALLET" in norm_text and "SO KG" in norm_text) or "SO KHOI" in norm_text or "TRUONG BP KHO" in norm_text:
            return "LOADING_PLAN", 0.85, 0.25, "Loading plan totals"
        # LUU Y: norm_text da qua normalize_text() nen KHONG con dau tieng Viet.
        # Moi chuoi so sanh o nhanh fallback nay bat buoc phai la dang DA BO DAU, viet hoa.
        if any(w in norm_text for w in ["PHIEU GIAO HANG", "PGH", "PHIEU GIAO NHAN", "BIEN NHAN HANG", "GOLD COAST"]):
            return "PHIEU_GIAO_HANG", 0.85, 0.25, "Phieu giao hang"
        if any(w in norm_text for w in ["LENH DIEU XE", "LENH DIEU DONG XE", "DIEU DONG XE", "XE LANH"]):
            return "LENH_DIEU_XE", 0.85, 0.25, "Lenh dieu xe"
        if "BON DAT HANG" in norm_text or "STORE ORDER" in norm_text or "GS25" in norm_text or "PURCHASE ORDER" in norm_text or "QUY CACH DAT HANG" in norm_text:
            return "PO", 0.85, 0.25, "Don dat hang sieu thi"
        if "DOI TRA" in norm_text or "DOI, TRA" in norm_text:
            return "BB_TRA_HANG", 0.85, 0.25, "Bien ban doi tra"
        if "NO HANG" in norm_text or "BIEN BAN NO" in norm_text or "TRUONG HOP NO" in norm_text:
            return "BB_NO_HANG", 0.85, 0.25, "Bien ban no hang"
        if "MA SAN PHAM" in norm_text or "BARCODE" in norm_text or "DON GIA" in norm_text or "CELANO" in norm_text:
            return "TABLE_CONTINUATION", 0.75, 0.20, "Bang hang hoa phu"

        return "UNKNOWN", 0.0, 0.0, ""

    def match_system_channel(self, norm_text: str, doc_type: str = "UNKNOWN") -> Tuple[str, float, str]:
        """Khớp Hệ thống Siêu thị / Kênh giao nhận theo taxonomy KIDO."""
        # 0. Biểu mẫu dùng chung theo quy chuẩn SOP KIDO
        if doc_type in [
            "LENH_DIEU_XE", "BIEU_DO_NHIET_DO", "BBBG_PALLET", 
            "BIEN_BAN_NO_HANG", "BIEN_BAN_TRA_HANG", "BB_NO_HANG", "BB_TRA_HANG"
        ]:
            return "COMMON", 1.0, f"FORM_DEFAULT_{doc_type}"

        # Phiếu xuất hàng kho thuê (SOP Mục 5.1/5.2)
        # SOP dùng Phiếu xuất hàng cho CẢ 5.1 lẫn 5.2 ("Cho kho Bắc Ninh + Kho thuê") -> chỉ tách
        # loại kho khi văn bản có dấu hiệu, không suy từ doc_type.
        if doc_type in ["PHIEU_XUAT_HANG"]:
            sub_id, sub_kw = refine_internal_transfer(norm_text)
            kw = "KIDO_SOP_PHIEU_XUAT_HANG" + (f"|SUB:{sub_kw}" if sub_kw else "")
            return sub_id, 1.0, kw

        # Biên bản thu hồi (SOP Mục 4) — nhóm loại hình là "Hàng thu hồi từ NPP" (Guideline!B56):
        # 4.1 "Biên bản nhận hàng - kiêm đề xuất trả hàng", 4.2 "Phiếu đề xuất thu hồi tem que LAP".
        # CẢ HAI đều là hàng thu về TỪ NPP => kênh GT, KHÔNG bao giờ là MT_*. Tên siêu thị in trên
        # biên bản chỉ là nguồn gốc lô hàng bị thu hồi, không phải bên giao nhận của chuyến này.
        # Đo 28/09: DX_THUHOI4.1__0 khớp "COOP" trong thân biên bản -> MT_COOP (sai); 3/3 trang
        # BB_THU_HOI trong tập chuẩn đều có system = GT.
        if doc_type == "BB_THU_HOI":
            return "GT", 1.0, "KIDO_SOP_MUC4_THU_HOI_TU_NPP"

        # 1. Khóa chặt AEON bằng Word Boundary Regex để triệt tiêu bẫy "VIET NAM" trong địa chỉ
        if re.search(r"\bAEON\b", norm_text):
            return "MT_AEON", 1.0, "AEON"

        candidates = []
        for sys_id, kws in SYSTEM_RULES:
            best_score = 0.0
            best_kw = ""
            for kw in kws:
                if kw in norm_text:
                    score = 1.0 + min(len(kw) / self.cfg.exact_len_bonus_divisor, self.cfg.exact_len_bonus_cap)
                    if score > best_score:
                        best_score = score
                        best_kw = kw
                elif len(kw) >= self.cfg.fuzzy_min_keyword_len and "VIET NAM" not in kw and "VIETNAM" not in kw:
                    ratio = fuzz.partial_ratio(kw, norm_text) / 100.0
                    if ratio >= self.cfg.system_fuzzy_threshold and ratio > best_score:
                        best_score = ratio
                        best_kw = kw
            if best_score > 0:
                candidates.append((sys_id, min(best_score, 1.0), best_kw, len(best_kw)))

        if candidates:
            candidates.sort(key=lambda x: (x[1], x[3]), reverse=True)
            top_sys, top_score, top_kw = candidates[0][0], candidates[0][1], candidates[0][2]
            if top_sys == "INTERNAL_TRANSFER":
                sub_id, sub_kw = refine_internal_transfer(norm_text)
                if sub_kw:
                    return sub_id, top_score, f"{top_kw}|SUB:{sub_kw}"
            return top_sys, top_score, top_kw

        # 2. Quy tắc nghiệp vụ cho Hóa đơn GTGT KIDO (Kênh GT - Nhà phân phối):
        # Hóa đơn VAT KIDO xuất cho công ty/đại lý tư nhân mà không có dấu hiệu MT hay Internal Transfer
        if doc_type == "HOA_DON":
            has_business_buyer = any(w in norm_text for w in [
                "CONG TY", "TNHH", "DOANH NGHIEP", "DNTN", "KHACH HANG", "KHACH HING"
            ])
            if has_business_buyer:
                return "GT", 0.85, "HOA_DON_DOANH_NGHIEP_GT"

        return "COMMON", 0.80, ""

    def extract_key_fields_strict(self, text: str, doc_type: Optional[str] = None) -> Dict[str, Optional[str]]:
        """Bóc tách trường khóa nghiêm ngặt với padding 8 số và regex siêu thị chuẩn tắc."""
        norm = normalize_text(text)
        info = {
            "shipment_id": None, 
            "invoice_no": None, 
            "po_no": None,
            "transfer_order_no": None,
            "pxk_no": None
        }
        
        # 1. LỆNH ĐIỀU ĐỘNG NỘI BỘ (10-16 số thực)
        dieu_dong_patterns = [
            r"(?:LENH\s*DIEU\s*DONG|DIEU\s*DONG\s*SO|CAN\s*CU\s*LENH\s*DIEU\s*DONG)[\s:_#-]*([0-9]{10,16})",
            r"(?:DIEU\s*DONG)[^0-9\n]{0,20}([0-9]{10,16})"
        ]
        for pat in dieu_dong_patterns:
            m = re.search(pat, norm)
            if m:
                info["transfer_order_no"] = m.group(1).strip()
                break

        # 2. SHIPMENT ID (5-10 số thực)
        # Khóa chặt chỉ bóc tách shipment_id cho các doc_type có liên quan
        if doc_type in ["HOA_DON", "LOADING_PLAN", "PXKKVCNB", "LENH_DIEU_XE"] or doc_type is None:
            ship_patterns = [
                r"(?:SHIPMENT(?:\s*(?:ID|NO|SO|:))?|SHIPMES|STIPMEEN|STIPM|SMPMENL|SMPMEN|SHP(?:MENT|MEN)?|SO\s*CHUYEN|MA\s*CHUYEN|CHUYEN\s*XE)[\s:_#\-\._]*([0-9A-Z]{5,10})",
                r"(?:LENH\s*DIEU\s*DONG|LENH\s*DIEU\s*XE)[\s:_#\-\._]*([0-9]{5,10})"
            ]
            for pat in ship_patterns:
                m = re.search(pat, norm)
                if m:
                    cand = disambiguate_shipment_id(m.group(1).strip())
                    if cand and cand.isdigit() and len(cand) >= 5:
                        info["shipment_id"] = cand
                        break
                    
            # Đối với PXKKVCNB nếu chưa có shipment_id trực tiếp, dùng transfer_order_no làm đại diện
            if not info["shipment_id"] and info["transfer_order_no"] and doc_type == "PXKKVCNB":
                info["shipment_id"] = info["transfer_order_no"]

            # Đối với HÓA ĐƠN: bắt mã chuyến ERP SAP trong ngữ cảnh nghiệp vụ hợp lệ
            if not info["shipment_id"] and doc_type == "HOA_DON":
                # Yêu cầu ngữ cảnh từ khóa SAP / Giao hàng / Vận đơn / Shipment đặc trưng của KIDO
                sap_context_m = re.search(r"(?:GIAO\s*HANG|XUAT\s*KHO|SAP|REF|CHUYEN|VAN\s*DON|SHP|SMPMEN|SHIPMENT|LENH)[^0-9\n]{0,25}\b(1[123]\d{4,5}|21001\d{5})\b", norm)
                if sap_context_m:
                    cand = disambiguate_shipment_id(sap_context_m.group(1).strip())
                    if cand:
                        info["shipment_id"] = cand

            # Đối với LOADING PLAN: tìm mã chuyến SAP
            if not info["shipment_id"] and doc_type == "LOADING_PLAN":
                lp_m = re.search(r"\b(12[0-9]{4}|13[0-9]{4})\b", norm)
                if lp_m:
                    info["shipment_id"] = disambiguate_shipment_id(lp_m.group(1).strip())

        # 3. SỐ HÓA ĐƠN GTGT vs SỐ PXK (Chuẩn hóa đệm 8 chữ số theo NĐ 123)
        inv_candidate = None
        inv_patterns = [
            r"(?:HOA\s*DON|SO\s*HOA\s*DON|SO\s*HD)[\s:_#-]*([0-9A-Z]{5,9})",
            r"(?:KY\s*HIEU|MAU\s*SO)[^0-9]*([0-9A-Z]{5,9})",
            r"\b(00[0-9A-Z]{4,7})\b"
        ]
        for pat in inv_patterns:
            m = re.search(pat, norm)
            if m:
                cand = m.group(1).strip()
                if cand.endswith("S") and re.match(r"^00\d+S$", cand):
                    cand = cand[:-1] + "5"
                if re.match(r"^\d+$", cand) and not re.match(r"^(19|20)\d{2}", cand):
                    if len(cand) in [5, 6, 7] and cand.startswith("0"):
                        cand = cand.zfill(8)
                    if len(cand) == 8:
                        inv_candidate = cand
                        break

        if doc_type == "PXKKVCNB":
            info["pxk_no"] = inv_candidate
            info["invoice_no"] = None
        elif doc_type == "HOA_DON":
            info["invoice_no"] = inv_candidate
        elif doc_type == "PHIEU_XUAT_HANG":
            # So phieu xuat kho Anpha-AG: 7 chu so co dem 0 dau (VD: 0000005), doi khi bi dinh
            # 1-2 ky tu so nhieu phia truoc. Pattern cu "000000[1-9]" CHI bat duoc phieu so 1-9
            # nen se truot ngay khi kho phat toi phieu thu 10.
            pxk_m = re.search(r"\d{0,2}(00\d{5})", norm)
            if pxk_m:
                info["pxk_no"] = pxk_m.group(1).strip()
            else:
                info["pxk_no"] = inv_candidate
        else:
            # Triệt tiêu False Positive trên Loading Plan và PO
            info["invoice_no"] = None

        # 4. SỐ PO / ĐƠN ĐẶT HÀNG (Regex chuẩn mực cho từng hệ thống siêu thị)
        # Chỉ bóc tách PO khi thuộc nhóm chứng từ đặt hàng/giao nhận
        if doc_type in ["PO", "PHIEU_GIAO_HANG", "TABLE_CONTINUATION"] or doc_type is None:
            po_patterns = [
                r"\b(P-[0-9]{8,10})\b",                  # GS25 (VD: P-000105230)
                r"\b([0-9]{5}PO[0-9]{9,12})\b",           # BHX (VD: 14017PO2506918178)
                r"(?:POM|OM|O)?([0-9]{3}P[0-9]{6,8})\b",  # Co.opmart (VD: O343P1071694)
                # Lotte Mart: 16 chu so, 6 chu so dau la ngay dat hang YYMMDD (VD: 2506260100600123).
                # Truoc day pattern nhung cung "25062" (thang 06/2025) nen se chet sau moc do.
                r"(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[0-9]{10})",
                r"\b(417[0-9]{7})\b",                    # WinMart (VD: 4173475639)
                r"\b(450[0-9]{7})\b",                    # Emart SAP PO tiêu chuẩn
                r"\b(W[EH][0-9]{10,18})\b",              # Satra / Kingfood
                r"\b(1002[0-9]{10})\b",                  # Aeon Vietnam
                r"\b(?:PO|DON\s*DAT\s*HANG|ORDER(?:\s*NO)?)\b[\s:_#-]*([0-9A-Z_-]{4,20})",
                r"\b(?:STORE\s*ORDER|ORD\s*SHEET)\b[\s:_#-]*([0-9A-Z_-]{4,20})"
            ]
            garbage = [
                "NUMBER", "ORDER", "TYPES", "DATE", "TIME", "JEON", "TECCONSS", "STORE",
                "SM", "SML", "NOTE", "TIEN", "CODE", "HANG", "KIDO", "PURCHASE", "LOCATION"
            ]
            for pat in po_patterns:
                m = re.search(pat, norm)
                if m:
                    cand = m.group(1).strip()
                    # Chuẩn hóa tiền tố O cho Coopmart PO
                    if re.match(r"^[0-9]{3}P[0-9]{6,8}$", cand):
                        cand = "O" + cand
                    # Chặn chuỗi từ rác, chuỗi không có số, chuỗi nhiễu mã vạch
                    if (cand not in garbage and 
                        any(c.isdigit() for c in cand) and 
                        not re.search(r"[ILHF]{3,}", cand) and 
                        not cand.startswith("893") and 
                        len(cand) >= 4):
                        info["po_no"] = cand
                        break
                        
        return info

    def classify_document(self, img_bgr: Optional[np.ndarray],
                          meta_stage1: Optional[Dict[str, Any]] = None,
                          file_name: Optional[str] = None,
                          page_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Phân loại MỘT trang.

        file_name : CHỈ là nhãn truy vết ghi lại vào kết quả (và tên file khi bật write_rotated_back).
                    Không quyết định nghiệp vụ nào đọc nó — kiểm chứng: tools/test_stage2_filename_invariance.py.
        page_meta : metadata đầu vào TƯỜNG MINH của lần upload {"upload_group_id": str, "scan_index": int}
                    (xem set_page_meta). None -> trang độc lập, apply_upload_group_voting KHÔNG vote.
        """
        res = self._classify_core(img_bgr, meta_stage1=meta_stage1, file_name=file_name)
        return set_page_meta(res, page_meta)

    def _classify_core(self, img_bgr: Optional[np.ndarray],
                       meta_stage1: Optional[Dict[str, Any]] = None,
                       file_name: Optional[str] = None) -> Dict[str, Any]:
        """Quy trình phân loại chứng từ chuẩn tắc tiếp nhận hợp đồng Tầng 1."""
        t0 = time.time()
        fn = file_name or ""
        
        # BƯỚC 0: KIỂM TRA HỢP ĐỒNG TẦNG 1
        if img_bgr is None or (meta_stage1 and meta_stage1.get("action") == "YEU_CAU_CHUP_LAI"):
            return {
                "doc_type": "UNKNOWN",
                "system": "COMMON",
                "form_id": "UNKNOWN_COMMON",
                "page_role": "HEADER",
                "confidence": 0.0,
                "doc_margin": 0.0,
                "status": "CHUA_DAT",
                "action": "YEU_CAU_CHUP_LAI",
                "evidence": {
                    "doc_keyword": "", "doc_score": 0.0,
                    "sys_keyword": "", "sys_score": 0.0
                },
                "key_fields": {
                    "shipment_id": None, "invoice_no": None, "po_no": None,
                    "transfer_order_no": None, "pxk_no": None
                },
                "rotation_180_fixed": False,
                "header_ratio": 0.0,
                "zone2_scanned": False,
                "zone2_filled_field": False,
                "ocr_psm": 6,
                "header_text_preview": "Bị từ chối bởi Gác cổng Tầng 1 (Yêu cầu chụp lại)",
                "elapsed_ms": int((time.time() - t0) * 1000),
                "file_name": fn
            }

        # BƯỚC 1: Cắt Vùng 1 & OCR
        header_bgr, ratio_used = self.crop_header_adaptive(img_bgr, zone=1)
        header_gray = self.preprocess_for_ocr(header_bgr, self.cfg.target_ocr_width, use_clahe=True)
        header_text, psm_used = self.run_header_ocr_multipass(header_gray)
        norm_text = normalize_text(header_text)
        
        # BƯỚC 2: KIỂM TRA XOAY 180 ĐỘ CÓ ĐIỀU KIỆN
        fixed_180 = False
        needs_180 = meta_stage1.get("rotation", {}).get("needs_verification_180", False) if meta_stage1 else False
        kw_hits = sum(1 for _, kws in DOC_RULES for kw in kws if kw in norm_text)
        
        if needs_180 or (kw_hits == 0):
            rot_img = cv2.rotate(img_bgr, cv2.ROTATE_180)
            h_rot, _ = self.crop_header_adaptive(rot_img, zone=1)
            g_rot = self.preprocess_for_ocr(h_rot, self.cfg.target_ocr_width, use_clahe=True)
            txt_rot, _ = self.run_header_ocr_multipass(g_rot)
            norm_rot = normalize_text(txt_rot)
            kw_hits_rot = sum(1 for _, kws in DOC_RULES for kw in kws if kw in norm_rot)
            
            if (kw_hits == 0 and kw_hits_rot >= 1) or (kw_hits_rot > kw_hits + 1):
                img_bgr = rot_img
                header_text = txt_rot
                norm_text = norm_rot
                fixed_180 = True
                # GHI DE ANH GOC TREN DIA LA SIDE-EFFECT NGOAI PHAM VI CUA MOT CLASSIFIER:
                # no lam benchmark KHONG idempotent (chay lan 2 doc anh da xoay -> ket qua khac
                # lan 1). Mac dinh TAT; chi bat qua co tuong minh khi that su muon dong bo dia.
                if self.cfg.write_rotated_back:
                    try:
                        out_img_disk = self.cfg.stage1_images_dir / fn
                        if out_img_disk.exists():
                            cv2.imwrite(str(out_img_disk), img_bgr)
                    except Exception as exc:
                        # Khong nuot loi im lang: ghi ro de con truy vet duoc.
                        print(f"[WARN] Khong ghi duoc anh da xoay 180 cho {fn}: {exc}")

        # BƯỚC 3 & 4: Phân loại Loại chứng từ & Hệ thống
        doc_type, doc_conf, doc_margin, doc_kw = self.match_document_type(norm_text)
        sys_id, sys_conf, sys_kw = self.match_system_channel(norm_text, doc_type=doc_type)
        
        # XÁC ĐỊNH VAI TRÒ TRANG (page_role)
        if doc_type == "TABLE_CONTINUATION":
            page_role = "CONTINUATION"
            doc_type = "PO"  # Bảng kê tiếp nối chuẩn hóa về loại chứng từ Đơn Đặt Hàng PO
        elif doc_type == "LOADING_PLAN":
            # Phân định vai trò trang Loading Plan tổng quát theo tiêu đề biểu mẫu
            has_lp_title = any(kw in norm_text for kw in ["LOADING PLAN", "BANG KE GIAO HANG", "LE NH XUAT HANG", "LENH XUAT HANG"])
            if not has_lp_title:
                page_role = "CONTINUATION"
            else:
                page_role = "HEADER"
        else:
            page_role = "HEADER"
            
        # BƯỚC 5: Bóc tách trường khóa Vùng 1
        key_fields = self.extract_key_fields_strict(header_text, doc_type=doc_type)
        
        # BƯỚC 6: TWO-ZONE SCANNING CÓ ĐIỀU KIỆN
        zone2_scanned = False
        zone2_filled_field = False
        
        needs_zone2 = False
        if doc_type == "HOA_DON" and (key_fields["invoice_no"] is None or key_fields["shipment_id"] is None):
            needs_zone2 = True
        elif doc_type == "PO" and key_fields["po_no"] is None:
            needs_zone2 = True
        elif doc_type in ["LOADING_PLAN", "PXKKVCNB"] and key_fields["shipment_id"] is None:
            needs_zone2 = True

        # Hệ thống CHƯA PHÂN GIẢI: `INTERNAL_TRANSFER` là nhãn CHA (biết "hàng nội bộ", chưa biết kho
        # nào) => KHÔNG được coi là đã xong dù `sys_conf` = 1.0. Đo 28/09: 5 trang (BBBGHH_5.1/5.2,
        # PXKKVCNB_5.1/5.2/2.3) khớp "NOI BO"/"DIEU DONG" ngay ở Vùng 1 với score 1.0, lại đủ trường khóa
        # nên `needs_zone2` = False => `refine_internal_transfer` chỉ thấy text Vùng 1, nơi KHÔNG hề có
        # tên kho nhận (CLK/Anpha/Quảng Nam/Bắc Ninh - nằm ở thân phiếu). Luật tách đã có sẵn trong
        # config nhưng không bao giờ được gọi tới. Quét tiếp Vùng 2 để nó có dữ liệu mà tách.
        if sys_id == "INTERNAL_TRANSFER":
            needs_zone2 = True

        # GHI CHÚ THỰC NGHIỆM (28/09) — ĐÃ ĐO, ĐỪNG THỬ LẠI HƯỚNG "QUÉT SÂU HƠN":
        # Sau khi bật Vùng 2 cho hệ thống chưa phân giải, 4/5 trang VẪN không tách được. Đã OCR
        # TOÀN TRANG (không chỉ 60% đầu) và dò lại `refine_internal_transfer`: vẫn ra rỗng.
        # Lý do thật nằm ở TỜ GIẤY, không ở phạm vi quét:
        #   * BBBGHH_5.1__0 / BBBGHH_5.2__0: cả bên giao lẫn bên nhận đều in "KHO: CỦ CHI"; không
        #     có chữ nào về Anpha/CLK/Quảng Nam/Bắc Ninh. Hai tờ 5.1 và 5.2 đọc ra text gần như
        #     giống hệt nhau => KHÔNG phân biệt được bằng nội dung trang.
        #   * PXKKVCNB_5.2__0: chỉ có "NHẬP TẠI KHO: TP02 - KHO THÀNH PHẨM 2" — MÃ kho nội bộ,
        #     không phải tên kho trong danh mục. Thêm "TP02" vào `internal_subtype_markers` sẽ
        #     vá được đúng ảnh demo này nhưng là học vẹt tập mẫu => KHÔNG làm.
        #   * PXKKVCNB2.3__0: không có dấu hiệu nào.
        # => 4 ca này BẤT KHẢ ở Tầng 2 mức-một-trang. Chỉ giải được bằng ngữ cảnh cấp BỘ chứng từ
        # (bộ có PXKKVCNB + Loading Plan, không dấu hiệu kho thuê/nội bộ -> quy trình 2.3 -> GT).
        if needs_zone2:
            zone2_scanned = True
            zone2_bgr, _ = self.crop_header_adaptive(img_bgr, zone=2)
            zone2_gray = self.preprocess_for_ocr(zone2_bgr, self.cfg.target_ocr_width, use_clahe=True)
            zone2_text, _ = self.run_header_ocr_multipass(zone2_gray)
            
            z2_fields = self.extract_key_fields_strict(zone2_text, doc_type=doc_type)
            for k, v in z2_fields.items():
                if key_fields[k] is None and v is not None:
                    key_fields[k] = v
                    zone2_filled_field = True
                    
            z2_norm = normalize_text(zone2_text)

            # Tách nhãn cha `INTERNAL_TRANSFER` bằng dấu hiệu kho nhận đọc được ở Vùng 2. Dò trên
            # VÙNG 1 + VÙNG 2 gộp lại (không chỉ Vùng 2) để giữ nguyên ngữ nghĩa "có dấu hiệu MỘT
            # phía" của `refine_internal_transfer`: dấu hiệu của cả hai loại kho -> vẫn KHÔNG đoán.
            if sys_id == "INTERNAL_TRANSFER":
                sub_id, sub_kw = refine_internal_transfer(norm_text + " " + z2_norm)
                if sub_kw:
                    sys_id = sub_id
                    sys_kw = f"{sys_kw}|SUB2:{sub_kw}" if sys_kw else f"SUB2:{sub_kw}"

            if doc_type == "UNKNOWN":
                z2_doc, z2_conf, z2_margin, z2_kw = self.match_document_type(z2_norm)
                if z2_conf > doc_conf:
                    doc_type, doc_conf, doc_margin, doc_kw = z2_doc, z2_conf, z2_margin, z2_kw
                    if doc_type == "TABLE_CONTINUATION":
                        page_role = "CONTINUATION"

        # GHI CHÚ THỰC NGHIỆM (27/09) — ĐÃ THỬ VÀ ĐÃ LOẠI BỎ:
        # Giả thuyết: chặn không cho trang có cờ `low_resolution` phát ra `shipment_id` sẽ khử
        # được 2 False Positive của Tầng 3, để `apply_stem_consistency_voting` điền lại từ các
        # trang cùng cụm đọc rõ hơn.
        # Kết quả đo: Tầng 3 KHÔNG đổi chút nào (vẫn 81 TP / 2 FP / 19 FN) -> 2 FP không bắt
        # nguồn từ trang low-res. Trong khi đó Tầng 2 mất recall (`shipment_id` R 92.3% -> 88.5%,
        # mất `PXKKVCNB_5.2__0` vốn là trang duy nhất mang mã đó nên voting không cứu được).
        # => Chi phí thật, lợi ích bằng không. Đã hoàn lại. Đừng thử lại hướng này.

        # BƯỚC 7: GÁC CỔNG ĐÁNH GIÁ (Confidence & Margin Gate)
        overall_conf = round(float(doc_conf * 0.7 + (sys_conf if sys_id != "COMMON" else 0.8) * 0.3), 2)
        if doc_type == "UNKNOWN":
            status = "CHUA_DAT"
            action = "CHUYEN_CHUYEN_VIEN_XAC_NHAN"
        elif doc_conf >= self.cfg.conf_pass_threshold and doc_margin >= self.cfg.margin_pass_threshold:
            status = "DAT"
            action = "CHUYEN_TANG_3"
        elif doc_conf >= self.cfg.conf_warn_threshold:
            status = "CANH_BAO"
            action = "CHUYEN_CHUYEN_VIEN_XAC_NHAN"
        else:
            status = "CHUA_DAT"
            action = "CHUYEN_CHUYEN_VIEN_XAC_NHAN"

        elapsed_ms = int((time.time() - t0) * 1000)
        
        return {
            "doc_type": doc_type,
            "system": sys_id,
            "form_id": f"{doc_type}_{sys_id}",
            "page_role": page_role,
            "confidence": overall_conf,
            "doc_margin": round(doc_margin, 2),
            "status": status,
            "action": action,
            "evidence": {
                "doc_keyword": doc_kw,
                "doc_score": round(float(doc_conf), 2),
                "sys_keyword": sys_kw,
                "sys_score": round(float(sys_conf), 2)
            },
            "key_fields": key_fields,
            "rotation_180_fixed": fixed_180,
            "header_ratio": ratio_used,
            "zone2_scanned": zone2_scanned,
            "zone2_filled_field": zone2_filled_field,
            "ocr_psm": psm_used,
            "header_text_preview": " | ".join([l.strip() for l in header_text.splitlines() if l.strip()][:3]),
            "elapsed_ms": elapsed_ms,
            "file_name": fn
        }


# =============================================================================================
# ĐỒNG THUẬN ĐA TRANG THEO NHÓM UPLOAD (thay cho apply_stem_consistency_voting cũ — đã XÓA)
# =============================================================================================
# Bản cũ nhóm trang theo `file_name.split("__")[0]` => Tầng 2 phụ thuộc quy ước đặt tên file của bộ
# ảnh demo. Trên web người dùng upload tên bất kỳ => cơ chế tắt ÂM THẦM (mỗi trang một "stem").
# Bản này CHỈ dùng metadata đầu vào tường minh:
#   * upload_group_id : định danh một lần upload / một hồ sơ (hệ thống tiếp nhận cấp). Là chuỗi MỜ:
#                       code KHÔNG phân tích nội dung chuỗi, chỉ so bằng nhau.
#   * scan_index      : thứ tự trang trong lần upload đó.
# Không có upload_group_id -> KHÔNG vote, trang giữ nguyên kết quả độc lập, voting_group_source="none".
# Trong một nhóm, chỉ vote giữa các trang LIÊN TIẾP và TƯƠNG THÍCH:
#   - cùng doc_type, khác UNKNOWN, không bị Tầng 1 từ chối (trang abstain không nhận cũng không cho gì);
#   - scan_index liền kề (không nhảy trang);
#   - không xung đột trường khóa: invoice_no / po_no / pxk_no / transfer_order_no khác nhau => hai chứng
#     từ khác nhau; shipment_id khác nhau quá mức "lỗi OCR nét số" (Hamming <= 2 cùng độ dài, hoặc tiền
#     tố cắt mép) => xung đột.
# Mỗi cụm tương thích = một chứng từ nhiều trang / nhiều liên; luật vote trong cụm giữ nguyên bản cũ.

_UPLOAD_GROUP_FIELDS = ("upload_group_id", "scan_index")
_EXACT_CONFLICT_FIELDS = ("invoice_no", "po_no", "pxk_no", "transfer_order_no")


def set_page_meta(result: Dict[str, Any], page_meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Gắn metadata upload vào kết quả một trang. Sai định dạng -> ValueError (không đoán, không mặc định)."""
    if page_meta is None:
        result["upload_group_id"] = None
        result["scan_index"] = None
        return result
    if not isinstance(page_meta, dict):
        raise ValueError(f"page_meta phải là dict {{upload_group_id, scan_index}}, nhận {type(page_meta).__name__}")
    gid, idx = page_meta.get("upload_group_id"), page_meta.get("scan_index")
    if not isinstance(gid, str) or not gid.strip():
        raise ValueError(f"page_meta.upload_group_id phải là chuỗi không rỗng, nhận {gid!r}")
    if not isinstance(idx, int) or isinstance(idx, bool) or idx < 0:
        raise ValueError(f"page_meta.scan_index phải là số nguyên >= 0, nhận {idx!r}")
    result["upload_group_id"] = gid
    result["scan_index"] = idx
    return result


def _shipment_near(a: str, b: str) -> bool:
    """Hai mã chuyến chỉ khác ở mức lỗi OCR (cùng luật sửa của vote): Hamming<=2 hoặc tiền tố cắt mép."""
    if a == b:
        return True
    if len(a) == len(b):
        return sum(1 for c1, c2 in zip(a, b) if c1 != c2) <= 2
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return long_.startswith(short)


def _key_field_conflict(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[str]:
    ka, kb = a.get("key_fields") or {}, b.get("key_fields") or {}
    for f in _EXACT_CONFLICT_FIELDS:
        va, vb = ka.get(f), kb.get(f)
        if va and vb and str(va).strip() != str(vb).strip():
            return f
    sa, sb = disambiguate_shipment_id(ka.get("shipment_id")), disambiguate_shipment_id(kb.get("shipment_id"))
    if sa and sb and not _shipment_near(sa, sb):
        return "shipment_id"
    return None


def _voting_eligible(r: Dict[str, Any]) -> bool:
    return r.get("doc_type") not in (None, "UNKNOWN") and r.get("action") != "YEU_CAU_CHUP_LAI"


def _segment_upload_group(items_sorted: List[Dict[str, Any]]) -> List[Tuple[List[Dict[str, Any]], str]]:
    """Chia một nhóm upload (đã sắp theo scan_index) thành các cụm liên tiếp tương thích.
    Trả về [(cụm, lý do cụm bắt đầu)]."""
    clusters: List[Tuple[List[Dict[str, Any]], str]] = []
    cur: List[Dict[str, Any]] = []
    cur_reason = "START"
    for r in items_sorted:
        if not cur:
            reason = "START"
        elif not _voting_eligible(r) or not _voting_eligible(cur[-1]):
            reason = "NOT_ELIGIBLE(UNKNOWN/TANG1_TU_CHOI)"
        elif r["doc_type"] != cur[-1]["doc_type"]:
            reason = f"DOC_TYPE_CHANGE({cur[-1]['doc_type']}->{r['doc_type']})"
        elif r["scan_index"] != cur[-1]["scan_index"] + 1:
            reason = "SCAN_INDEX_GAP"
        else:
            conflicts = [c for c in (_key_field_conflict(m, r) for m in cur) if c]
            reason = f"KEY_FIELD_CONFLICT({conflicts[0]})" if conflicts else None
        if reason is None:
            cur.append(r)
            continue
        if cur:
            clusters.append((cur, cur_reason))
        cur, cur_reason = [r], reason
    if cur:
        clusters.append((cur, cur_reason))
    return clusters


def _vote_cluster(items: List[Dict[str, Any]], changes: Dict[int, List[str]]) -> None:
    """Luật đồng thuận trong MỘT cụm tương thích (giữ nguyên luật của bản stem cũ)."""
    def _log(it, msg):
        changes.setdefault(id(it), []).append(msg)

    # 1. Invoice No (trang sau kế thừa trang đầu nếu cùng hóa đơn nhiều trang/liên)
    invoices = [it["key_fields"]["invoice_no"] for it in items if it["key_fields"]["invoice_no"]]
    if invoices:
        best_inv = Counter(invoices).most_common(1)[0][0]
        for it in items:
            if it["doc_type"] == "HOA_DON" and not it["key_fields"]["invoice_no"]:
                it["key_fields"]["invoice_no"] = best_inv
                _log(it, f"invoice_no:None->{best_inv}")

    # 2. Shipment ID (điền trống; sửa lỗi nét số Hamming<=2; nối mã cắt mép)
    raw_ships = [disambiguate_shipment_id(it["key_fields"]["shipment_id"]) for it in items if it["key_fields"]["shipment_id"]]
    shipments = [s for s in raw_ships if s]
    if shipments:
        ship_counts = Counter(shipments)
        best_ship = sorted(ship_counts.keys(), key=lambda s: (ship_counts[s], len(s)), reverse=True)[0]
        for it in items:
            old = it["key_fields"]["shipment_id"]
            curr = disambiguate_shipment_id(old)
            if curr is None:
                if it["doc_type"] in ["HOA_DON", "LOADING_PLAN", "PXKKVCNB"]:
                    it["key_fields"]["shipment_id"] = best_ship
            elif curr != best_ship:
                if len(curr) == len(best_ship):
                    diff_cnt = sum(1 for c1, c2 in zip(curr, best_ship) if c1 != c2)
                    if diff_cnt <= 2:
                        it["key_fields"]["shipment_id"] = best_ship
                elif len(curr) < len(best_ship) and best_ship.startswith(curr):
                    it["key_fields"]["shipment_id"] = best_ship
            if it["key_fields"]["shipment_id"] != old:
                _log(it, f"shipment_id:{old}->{it['key_fields']['shipment_id']}")

    # 3. PO No (các trang CONTINUATION bảng kê kế thừa PO từ trang đầu)
    pos = [it["key_fields"]["po_no"] for it in items if it["key_fields"]["po_no"]]
    if pos:
        best_po = Counter(pos).most_common(1)[0][0]
        for it in items:
            if it["doc_type"] in ["PO", "TABLE_CONTINUATION"] and not it["key_fields"]["po_no"]:
                it["key_fields"]["po_no"] = best_po
                _log(it, f"po_no:None->{best_po}")

    # 4. Hệ thống / Kênh (Trục 2). Ưu tiên nhãn đích danh (MT_*, INTERNAL_*, GT đích danh), không phải fallback.
    strong_systems = [
        it.get("system") for it in items
        if it.get("system") not in [None, "COMMON", "UNKNOWN"]
        and (it.get("evidence", {}).get("sys_keyword") != "HOA_DON_DOANH_NGHIEP_GT" if isinstance(it.get("evidence"), dict) else True)
    ]
    if strong_systems:
        best_sys = Counter(strong_systems).most_common(1)[0][0]
    else:
        all_sys = [it.get("system") for it in items if it.get("system") not in [None, "COMMON", "UNKNOWN"]]
        best_sys = Counter(all_sys).most_common(1)[0][0] if all_sys else None

    if best_sys:
        for it in items:
            curr_sys = it.get("system")
            curr_kw = it.get("evidence", {}).get("sys_keyword", "") if isinstance(it.get("evidence"), dict) else ""
            if (
                curr_sys in [None, "COMMON", "UNKNOWN"]
                or (curr_kw == "HOA_DON_DOANH_NGHIEP_GT" and best_sys.startswith("MT_"))
                or (best_sys == "GT" and curr_kw != "HOA_DON_DOANH_NGHIEP_GT" and curr_sys != "GT")
            ):
                it["system"] = best_sys
                if "doc_type" in it:
                    it["form_id"] = f"{it['doc_type']}_{best_sys}"
                if "evidence" in it and isinstance(it["evidence"], dict):
                    it["evidence"]["sys_keyword"] = f"GROUP_VOTING_{best_sys}"
                    it["evidence"]["sys_score"] = 0.95
                if curr_sys != best_sys:
                    _log(it, f"system:{curr_sys}->{best_sys}")


def apply_upload_group_voting(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Đồng thuận đa trang CHỈ trong cùng upload_group_id, giữa các trang liên tiếp tương thích.

    Ghi thêm vào mỗi kết quả:
      voting_group_source : "upload_group" | "none"  (none = không có metadata nhóm -> không vote)
      voting_cluster_id   : "<upload_group_id>#<k>" | None
      voting_cluster_size : số trang trong cụm (1 = không có trang nào để vote cùng)
      voting_split_reason : lý do cụm bắt đầu tại trang này (START / DOC_TYPE_CHANGE / KEY_FIELD_CONFLICT /
                            NOT_ELIGIBLE / SCAN_INDEX_GAP), "JOINED" nếu trang nối vào cụm trước
      voting_changes      : danh sách thay đổi do vote (rỗng = không đổi gì)
    Không đọc file_name.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        for k in _UPLOAD_GROUP_FIELDS:
            if k not in r:
                raise ValueError(f"Kết quả thiếu khóa metadata upload '{k}' — tạo kết quả qua "
                                 "classify_document(..., page_meta=...) hoặc set_page_meta().")
        r["voting_changes"] = []
        if r["upload_group_id"] is None:
            r["voting_group_source"] = "none"
            r["voting_cluster_id"] = None
            r["voting_cluster_size"] = 1
            r["voting_split_reason"] = "NO_UPLOAD_GROUP"
            continue
        r["voting_group_source"] = "upload_group"
        groups.setdefault(r["upload_group_id"], []).append(r)

    for gid, items in groups.items():
        items_sorted = sorted(items, key=lambda x: x["scan_index"])
        idxs = [x["scan_index"] for x in items_sorted]
        if len(set(idxs)) != len(idxs):
            raise ValueError(f"upload_group_id={gid!r}: scan_index trùng lặp {idxs} — metadata upload hỏng.")
        for k, (cl, reason) in enumerate(_segment_upload_group(items_sorted)):
            changes: Dict[int, List[str]] = {}
            if len(cl) > 1:
                _vote_cluster(cl, changes)
            for i, it in enumerate(cl):
                it["voting_cluster_id"] = f"{gid}#{k}"
                it["voting_cluster_size"] = len(cl)
                it["voting_split_reason"] = reason if i == 0 else "JOINED"
                it["voting_changes"] = changes.get(id(it), [])
    return results


def extract_key_fields_strict(text: str, doc_type: Optional[str] = None) -> Dict[str, Any]:
    """Hàm tiện ích bóc tách trường khóa độc lập."""
    _temp_clf = Stage2DocumentClassifier()
    return _temp_clf.extract_key_fields_strict(text, doc_type=doc_type)


__all__ = [
    "Stage2Config",
    "Stage2DocumentClassifier",
    "normalize_text",
    "disambiguate_shipment_id",
    "DOC_RULES",
    "SYSTEM_RULES",
    "RAW_DOC_RULES",
    "RAW_SYSTEM_RULES",
    "RAW_INTERNAL_SUBTYPE_MARKERS",
    "INTERNAL_SUBTYPE_PATTERNS",
    "refine_internal_transfer",
    "THRESHOLDS",
    "KEYWORDS_CONFIG_PATH",
    "Stage2ConfigError",
    "extract_key_fields_strict",
    "set_page_meta",
    "apply_upload_group_voting",
]


