from __future__ import annotations
import shutil
from pathlib import Path

# Tesseract chỉ dùng cho ĐÚNG MỘT việc: xác định ảnh có bị ngược 180 độ hay không.
# Không dùng để OCR nội dung ở tầng này.
_TESSERACT_CMD = shutil.which("tesseract")
if _TESSERACT_CMD is None:
    _WINDOWS_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if Path(_WINDOWS_TESSERACT).is_file():
        _TESSERACT_CMD = _WINDOWS_TESSERACT

try:
    import pytesseract
    if _TESSERACT_CMD is not None:
        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD
except Exception:
    pass

import cv2
import numpy as np
from pathlib import Path
# KHONG CO SIDE-EFFECT LUC IMPORT (AGENTS.md 9.7).
# Truoc day PROJECT_DIR = Path.cwd(), WORK_DIR.mkdir(), quet PROJECT_DIR.rglob("*.xlsx") va
# nap/trich FORM_CATALOG deu chay ngay khi import; voi ProcessPoolExecutor(6) (Windows 'spawn')
# moi tien trinh con nap lai module nen chung chay x6.
# Nay: PROJECT_DIR suy tu vi tri file (thu muc cha cua tools/) va chi la hang so Path.
# XLSX_PATH / FORM_CATALOG / ORIENTATION_KEYWORDS la LAZY (get_xlsx_path(), get_form_catalog(),
# get_orientation_keywords(), co cache); ten cu van truy cap duoc qua module __getattr__.
PROJECT_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR   = PROJECT_DIR / "docs"
WORK_DIR    = PROJECT_DIR / "output"

"""
TANG 1 - CHUAN HOA ANH CHUNG TU (rule-based, khong train model)
Core module - se duoc tach thanh cac cell trong notebook Kaggle.
"""

import json
import math
import os
import re
import threading
import time
import unicodedata
import zipfile
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ExifTags

STAGE1_VERSION = "1.0.0"
import shutil
from collections import Counter

@dataclass
class Stage1Config:
    # --- I/O ---
    input_dir: str = str(INPUT_DIR)
    output_dir: str = str(WORK_DIR / "stage1_out")
    batch_mode: str = "folder"          # "folder" | "prefix" | "single"
    prefix_sep: str = "__"              # dung khi batch_mode="prefix": BATCH__page1.jpg

    # --- Chat luong dau vao ---
    min_long_edge: int = 900            # duoi nguong nay -> CHUP_LAI
    warn_long_edge: int = 1400          # duoi nguong nay -> CANH_BAO
    blur_reject: float = 35.0           # variance of Laplacian (tren anh chuan hoa 1000px)
    blur_warn: float = 90.0
    glare_reject_pct: float = 6.0       # % diem anh chay sang (V>=250 va S<=25)
    glare_warn_pct: float = 2.0
    dark_reject_mean: float = 55.0      # do sang trung binh qua thap
    # --- Do dong thuan cua GrabCut giua cac seed (do bang paper_mask_consensus) ---
    agreement_reject: float = 0.70     # cac lan chay bat dong manh -> tach giay/nen mo ho
    agreement_warn: float = 0.90
    # --- % net chu bi tu giac cat ra ngoai ---
    ink_outside_reject: float = 0.8    # mat qua 0.5% net chu -> chac chan cat mat noi dung
    ink_outside_warn: float = 0.40
    dpi_reject: float = 100.0          # DPI hieu dung duoi muc nay -> bat chup lai
    dpi_warn: float = 150.0
    min_ink_pct: float = 0.15          # % dien tich la net chu; thap hon => anh trang/chay sang
    warn_ink_pct: float = 0.6

    # --- Phan biet scan / photo ---
    scan_photo_threshold: float = 0.0   # score>0 -> photo, score<0 -> scan

    # --- Dò 4 góc ---
    quad_work_size: int = 1000          # canh dai khi xu ly dò góc
    min_area_ratio_reject: float = 0.12  # giay chiem qua it khung hinh
    min_area_ratio_warn: float = 0.25
    max_area_ratio_warn: float = 0.93   # giay gan trùm khung -> nghi bi cat góc
    corner_margin_reject_pct: float = 0.8   # góc cach mep < 0.8% canh ngan -> coi nhu cham mep
    corner_margin_warn_pct: float = 2.5
    min_corner_angle: float = 50.0
    max_corner_angle: float = 130.0
    aspect_lo_warn: float = 1.15        # A4 = 1.414; ngoài [1.15, 1.85] -> canh bao
    aspect_hi_warn: float = 1.85

    # --- Xoay ---
    use_osd: bool = True
    osd_min_confidence: float = 2.0
    max_fine_skew_deg: float = 15.0

    # --- Chuan hoa dau ra ---
    target_long_edge: int = 2200
    a4_ratio: float = 297.0 / 210.0     # 1.4143
    jpeg_quality: int = 95
    save_debug: bool = True


# Cấu hình dùng cho phần DEMO trong notebook này.
# Ảnh mẫu nhúng trong file Excel đã bị Excel nén xuống ~850px nên phải hạ ngưỡng độ phân giải,
# nếu không mọi ảnh mẫu đều bị loại vì "quá nhỏ". Ảnh scan/chụp thật thường 1700-3000px.
CFG = Stage1Config(
    input_dir=str(INPUT_DIR),
    output_dir=str(WORK_DIR / "stage1_out"),
    batch_mode="folder",
    min_long_edge=500,      # PRODUCTION: để 900
    warn_long_edge=900,     # PRODUCTION: để 1400
)
# Top-level debug print muted for clean module import

MEDIA_DIR = WORK_DIR / "form_samples"
catalog_json_path = Path(WORK_DIR / "form_catalog.json")

# Ghi de tuong minh, vd str(INPUT_DIR / "HUONG DAN CHUNG TU GIAO NHAN.xlsx").
# None -> get_xlsx_path() tu quet PROJECT_DIR.rglob("*.xlsx") o LAN GOI DAU TIEN.
XLSX_PATH_OVERRIDE: Optional[str] = None
_LAZY_UNSET = object()
_XLSX_PATH_CACHE: Any = _LAZY_UNSET
_FORM_CATALOG_CACHE: Any = _LAZY_UNSET


def extract_forms_from_xlsx(xlsx_path: str, out_dir: Path) -> Dict[str, Any]:
    # Trích ảnh biểu mẫu + bản đồ sheet -> loại chứng từ từ file hướng dẫn
    out_dir.mkdir(parents=True, exist_ok=True)
    z = zipfile.ZipFile(xlsx_path)

    # --- (a) sheet nào chứa ảnh nào ---
    wb = z.read("xl/workbook.xml").decode("utf8")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf8")
    relmap = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels))
    sheets = re.findall(r'<sheet name="([^"]+)" sheetId="\d+"[^>]*r:id="([^"]+)"', wb)

    sheet_images: Dict[str, List[str]] = {}
    for name, rid in sheets:
        path = "xl/" + relmap[rid].replace("/xl/", "")
        try:
            sx = z.read(path).decode("utf8")
        except KeyError:
            continue
        m = re.search(r'<drawing r:id="([^"]+)"', sx)
        imgs: List[str] = []
        if m:
            srels = z.read(path.replace("worksheets/", "worksheets/_rels/") + ".rels").decode("utf8")
            srelmap = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"', srels))
            dpath = "xl/" + srelmap[m.group(1)].replace("../", "")
            drels = z.read(dpath.replace("drawings/", "drawings/_rels/") + ".rels").decode("utf8")
            imgs = ["xl/" + t.replace("../", "") for t in re.findall(r'Target="([^"]+)"', drels)]
        sheet_images[name] = imgs

    # --- (b) xuất ảnh ra đĩa, đặt tên theo sheet ---
    saved: Dict[str, List[str]] = {}
    for name, imgs in sheet_images.items():
        safe = re.sub(r"[^0-9A-Za-z._-]+", "_", name).strip("_") or "sheet"
        for i, src in enumerate(imgs):
            try:
                data = z.read(src)
            except KeyError:
                continue
            ext = os.path.splitext(src)[1] or ".png"
            fp = out_dir / f"{safe}__{i}{ext}"
            fp.write_bytes(data)
            saved.setdefault(name, []).append(str(fp))

    # --- (c) đọc sheet Guideline -> bản đồ nghiệp vụ ---
    guideline = []
    try:
        import openpyxl
        ws = openpyxl.load_workbook(xlsx_path, read_only=True)["Guideline"]
        transport = detail = None
        for row in ws.iter_rows(min_row=3, values_only=True):
            row = list(row) + [None] * (9 - len(row))
            if row[1]:
                transport = str(row[1]).strip()
            if row[2]:
                detail = str(row[2]).strip()
            if row[3]:
                link = str(row[7 + 1]).strip() if row[8] else ""
                target = link.split("'!")[0].strip("'") if link else ""
                guideline.append({
                    "transport_type": transport,
                    "order_detail": detail,
                    "doc_type": str(row[3]).strip(),
                    "so_lien_in": row[4],
                    "giao_nvc": row[5],
                    "nvc_mang_ve": row[6],
                    "dien_giai": str(row[7]).strip() if row[7] else "",
                    "form_sheet": target,
                })
    except Exception as e:
        print("Không đọc được sheet Guideline:", e)

    return {"sheet_images": saved, "guideline": guideline,
            "n_images": sum(len(v) for v in saved.values()), "n_sheets": len(saved)}


def get_xlsx_path() -> Optional[str]:
    """Duong dan file Excel huong dan (lazy, cache). rglob chi chay o lan goi dau."""
    global _XLSX_PATH_CACHE
    if XLSX_PATH_OVERRIDE is not None:
        return XLSX_PATH_OVERRIDE
    if _XLSX_PATH_CACHE is _LAZY_UNSET:
        cands = sorted(PROJECT_DIR.rglob("*.xlsx"))
        _XLSX_PATH_CACHE = str(cands[0]) if cands else None
    return _XLSX_PATH_CACHE


def get_form_catalog() -> Dict[str, Any]:
    """FORM_CATALOG (lazy, cache). Doc output/form_catalog.json; neu chua co va tim thay Excel
    thi trich tu Excel roi ghi json — side-effect chi xay ra khi GOI ham nay, khong luc import."""
    global _FORM_CATALOG_CACHE
    if _FORM_CATALOG_CACHE is not _LAZY_UNSET:
        return _FORM_CATALOG_CACHE
    cat: Dict[str, Any] = {}
    if catalog_json_path.exists():
        try:
            cat = json.loads(catalog_json_path.read_text(encoding="utf8"))
        except Exception:
            cat = {}
    else:
        xlsx = get_xlsx_path()
        if xlsx:
            try:
                cat = extract_forms_from_xlsx(xlsx, MEDIA_DIR)
                WORK_DIR.mkdir(parents=True, exist_ok=True)
                catalog_json_path.write_text(
                    json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf8")
            except Exception:
                cat = {}
    _FORM_CATALOG_CACHE = cat
    return cat


def __getattr__(name: str):
    # Tuong thich nguoc (PEP 562): `s1.FORM_CATALOG`, `s1.XLSX_PATH`, `s1.ORIENTATION_KEYWORDS`
    # va `from tools.stage1_normalizer import FORM_CATALOG` van chay — chi tinh khi truy cap.
    if name == "FORM_CATALOG":
        return get_form_catalog()
    if name == "XLSX_PATH":
        return get_xlsx_path()
    if name == "ORIENTATION_KEYWORDS":
        return get_orientation_keywords()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

def imread_unicode(path: str) -> Optional[np.ndarray]:
    """cv2.imread khong doc duoc duong dan unicode tren mot so he thong."""
    try:
        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        return img
    except Exception:
        return None


def imwrite_unicode(path: str, img: np.ndarray, quality: int = 95) -> bool:
    ext = os.path.splitext(path)[1].lower() or ".jpg"
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if ext in (".jpg", ".jpeg") else []
    ok, buf = cv2.imencode(ext, img, params)
    if not ok:
        return False
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    buf.tofile(path)
    return True


def resize_long_edge(img: np.ndarray, long_edge: int, interp=None) -> np.ndarray:
    h, w = img.shape[:2]
    cur = max(h, w)
    if cur == long_edge:
        return img
    s = long_edge / float(cur)
    if interp is None:
        interp = cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC
    return cv2.resize(img, (max(1, int(round(w * s))), max(1, int(round(h * s)))), interpolation=interp)


def read_exif(path: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        with Image.open(path) as im:
            raw = im.getexif()
            if not raw:
                return out
            for tag_id, val in raw.items():
                tag = ExifTags.TAGS.get(tag_id, str(tag_id))
                if isinstance(val, bytes):
                    val = val.decode("utf8", "ignore")
                out[tag] = val
            # IFD phu chua FocalLength / ISO / LensModel
            try:
                for ifd_name in (ExifTags.IFD.Exif, ExifTags.IFD.GPSInfo):
                    try:
                        sub = raw.get_ifd(ifd_name)
                    except Exception:
                        continue
                    for tag_id, val in (sub or {}).items():
                        tag = ExifTags.TAGS.get(tag_id) or ExifTags.GPSTAGS.get(tag_id) or str(tag_id)
                        if isinstance(val, bytes):
                            val = val.decode("utf8", "ignore")
                        out.setdefault(tag, val)
            except Exception:
                pass
    except Exception:
        pass
    return out


def colorfulness(bgr: np.ndarray) -> float:
    """Chi so Hasler-Susstrunk: anh giay scan -> rat thap; nen ban/san -> cao."""
    b, g, r = cv2.split(bgr.astype("float32"))
    rg = np.abs(r - g)
    yb = np.abs(0.5 * (r + g) - b)
    return float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))


def border_ring_mask(h: int, w: int, frac: float = 0.05) -> np.ndarray:
    m = np.zeros((h, w), np.uint8)
    t = max(1, int(round(min(h, w) * frac)))
    m[:t, :] = 255
    m[-t:, :] = 255
    m[:, :t] = 255
    m[:, -t:] = 255
    return m

def background_illumination(V: np.ndarray) -> np.ndarray:
    """Uoc luong ban do anh sang nen: morph-close (lay max cuc bo, bo qua net chu) roi lam muot."""
    h, w = V.shape[:2]
    sw, sh = max(32, w // 8), max(32, h // 8)
    small = cv2.resize(V.astype(np.float32), (sw, sh), interpolation=cv2.INTER_AREA)
    k = max(3, (min(sw, sh) // 8) | 1)
    bg = cv2.morphologyEx(small, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.GaussianBlur(bg, (0, 0), max(2.0, k / 3.0))
    return cv2.resize(bg, (w, h), interpolation=cv2.INTER_CUBIC)


def measure_glare(bgr: np.ndarray, roi: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """
    LOA SANG = vung sang HON HAN muc trang cua to giay, khong phai la 'pixel trang'.
    Giay trang trong anh scan co V ~ 250 tren toan bo anh -> illum_range ~ 0 -> KHONG tinh la loa.
    Den flash/den tran roi vao mot goc -> vung do vuot xa muc trang nen -> tinh la loa.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    V = hsv[:, :, 2].astype(np.float32)
    bg = background_illumination(V)
    if roi is None:
        roi = np.ones(V.shape, bool)
    else:
        roi = roi > 0
        if roi.sum() < 0.02 * roi.size:
            roi = np.ones(V.shape, bool)
    inside = bg[roi]
    p5, p50, p95 = (float(np.percentile(inside, q)) for q in (5, 50, 95))
    illum_range = (p95 - p5) / max(p95, 1.0)
    # Loa sang = vung sang VUOT HAN muc trang binh thuong cua chinh to giay VA da bi cat nguong.
    hot = roi & (bg > p50 * 1.08) & (bg >= 246)
    glare_pct = float(hot.sum() / max(roi.sum(), 1) * 100.0)
    if illum_range < 0.08:          # anh sang deu tuyet doi (scan) -> khong the co loa cuc bo
        glare_pct = min(glare_pct, 0.2)
    clipped = float(np.mean(np.all(bgr >= 250, axis=2)[roi]) * 100.0)
    # MAT DO NET CHU: pixel toi ro so voi muc trang cua giay. Dung de phat hien
    # anh trang / chup nham mat sau / chay sang mat het chu.
    ink = float(((V < 0.72 * max(p50, 1.0)) & roi).sum() / max(roi.sum(), 1) * 100.0)
    return {"glare_pct": round(glare_pct, 3), "illum_range": round(float(illum_range), 4),
            "clipped_pct": round(clipped, 3), "paper_white_level": round(p50, 1),
            "ink_pct": round(ink, 3)}


def measure_quality(bgr: np.ndarray, roi_mask: Optional[np.ndarray] = None,
                    min_roi_area: float = 0.0) -> Dict[str, Any]:
    """
    roi_mask = mat na TO GIAY. Chi dung lam vung do khi no CO THE la to giay:
    dien tich >= min_roi_area (process_one truyen cfg.min_area_ratio_reject — cung nguong
    "giay chiem qua it khung hinh" da dung cho tu giac). Mat na nho hon nguong do khong the
    la to giay; do chi la MOT MANG NEN DONG MAU ma GrabCut tach ra (vd o tieu de to mau vang).
    Do mat do net chu CHI trong mang do la do sai vung: THU_HOI_4.2__0 (bieu mau day chu,
    ink toan khung 5.27%) bi mat na 2.43% ngay o o vang chu do -> ink_pct 0.00% -> bi tu choi
    "anh trang". Khi mat na khong hop le -> do tren TOAN KHUNG va ghi ro ly do.
    """
    h, w = bgr.shape[:2]
    small = resize_long_edge(bgr, 1000)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    V = hsv[:, :, 2]
    dark = float(np.mean(V <= 40) * 100.0)
    roi = None
    roi_note = "không có mặt nạ giấy — đo trên toàn khung"
    if roi_mask is not None:
        mask_area = float(np.count_nonzero(roi_mask)) / max(roi_mask.size, 1)
        if mask_area >= min_roi_area:
            roi = cv2.resize(roi_mask, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
        else:
            roi_note = (f"mặt nạ giấy chỉ {mask_area*100:.2f}% khung (< {min_roi_area*100:.0f}%) — "
                        "không thể là tờ giấy, đo trên toàn khung")
    gl = measure_glare(small, roi)

    return {
        "width": int(w),
        "height": int(h),
        "long_edge_px": int(max(h, w)),
        "laplacian_var": round(lap_var, 2),
        "brightness_mean": round(float(V.mean()), 2),
        "brightness_std": round(float(V.std()), 2),
        "ink_pct": gl["ink_pct"],
        "glare_pct": gl["glare_pct"],
        "illum_range": gl["illum_range"],
        "dark_pct": round(dark, 3),
        "colorfulness": round(colorfulness(small), 3),
        # Vung thuc su dung de do ink/glare/illum — luon co mat (schema thong nhat).
        "measure_roi": ({"source": "paper_mask", "reason": None} if roi is not None
                        else {"source": "full_frame", "reason": roi_note}),
    }


def quality_flags(q: Dict[str, Any], cfg: Stage1Config) -> Tuple[List[str], List[str]]:
    rejects, warns = [], []
    if q["long_edge_px"] < cfg.min_long_edge:
        rejects.append(f"Ảnh quá nhỏ ({q['long_edge_px']}px < {cfg.min_long_edge}px) — chụp lại ở độ phân giải cao hơn")
    elif q["long_edge_px"] < cfg.warn_long_edge:
        warns.append(f"Độ phân giải thấp ({q['long_edge_px']}px) — OCR có thể kém chính xác")

    if q["laplacian_var"] < cfg.blur_reject:
        rejects.append(f"Ảnh quá mờ (độ nét {q['laplacian_var']:.0f} < {cfg.blur_reject:.0f}) — giữ máy ổn định và chụp lại")
    elif q["laplacian_var"] < cfg.blur_warn:
        warns.append(f"Ảnh hơi mờ (độ nét {q['laplacian_var']:.0f})")

    if q["glare_pct"] > cfg.glare_reject_pct:
        rejects.append(f"Lóa sáng {q['glare_pct']:.1f}% diện tích — tránh đèn chiếu trực tiếp, chụp lại")
    elif q["glare_pct"] > cfg.glare_warn_pct:
        warns.append(f"Có vùng lóa sáng {q['glare_pct']:.1f}%")

    if q["brightness_mean"] < cfg.dark_reject_mean:
        rejects.append(f"Ảnh quá tối (độ sáng TB {q['brightness_mean']:.0f}) — chụp lại nơi đủ sáng")
    if q["ink_pct"] < cfg.min_ink_pct:
        rejects.append(f"Gần như không thấy nét chữ nào ({q['ink_pct']:.2f}% diện tích) — "
                       f"ảnh trắng, chụp nhầm mặt sau hoặc cháy sáng hoàn toàn")
    elif q["ink_pct"] < cfg.warn_ink_pct:
        warns.append(f"Mật độ nét chữ rất thấp ({q['ink_pct']:.2f}%) — kiểm tra có đúng mặt trước chứng từ không")
    return rejects, warns

def ring_vs_document(bgr: np.ndarray, center_frac: float = 0.45) -> Dict[str, Any]:
    """
    Vanh ngoai cua khung anh co phai la GIAY khong?
      - Anh SCAN: to giay trum kin mat kinh -> vanh ngoai chinh la giay -> giong ruot chung tu.
      - Anh CHUP: vanh ngoai la mat ban / san / tay nguoi -> khac han nen giay.
    So sanh trung vi mau Lab cua vanh ngoai voi nen giay o VUNG GIUA anh
    (chi lay pixel sang = nen giay, bo qua net chu), tinh theo don vi sigma.
    """
    h, w = bgr.shape[:2]
    lab = cv2.cvtColor(cv2.GaussianBlur(flatten_illumination(bgr, 1.0), (0, 0), 1.5),
                       cv2.COLOR_BGR2LAB).astype(np.float32)
    cy, cx = int(h * (1 - center_frac) / 2), int(w * (1 - center_frac) / 2)
    core = lab[cy:h - cy, cx:w - cx].reshape(-1, 3)
    if len(core) < 200:
        return {"separable": False, "distance": 0.0, "reason": "ảnh quá nhỏ"}
    paper = core[core[:, 0] >= np.percentile(core[:, 0], 65)]      # pixel sang = nen giay
    mu = np.median(paper, axis=0)
    mad = np.median(np.abs(paper - mu), axis=0) * 1.4826
    sigma = np.clip(mad, [2.0, 1.0, 1.0], [10.0, 5.0, 5.0])

    ring = lab[border_ring_mask(h, w, 0.03) > 0].reshape(-1, 3)
    ring_mu = np.median(ring, axis=0)
    dist = float(np.sqrt((((ring_mu - mu) / sigma) ** 2).sum()))

    # NGOAI LE: LE TRANG CUA MAY SCAN.
    # Bieu mau carbon vang/hong cho ruot chung tu co mau (vi du Lab a=116, b=173) trong khi
    # le giay trang quanh no trung tinh (a=b=128). Khi do ring KHAC ruot that, nhung do KHONG
    # phai "nen ban" - do la le trang cua ban scan. Dau hieu nhan biet: vanh ngoai SANG BANG
    # HOAC HON ruot VA gan nhu khong co mau. Nen ban/san thi hoac toi hon, hoac co mau.
    # Phai thoa CA BA dieu kien, neu khong thi anh chup tren ban trang cung bi nham la scan:
    #   (1) vanh ngoai sang bang hoac hon ruot giay
    #   (2) vanh ngoai gan nhu khong co mau
    #   (3) anh sang toan anh rat deu  -> chi den scan moi cho duoc, den phong thi khong
    V = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[:, :, 2].astype(np.float32)
    bgV = background_illumination(V)
    illum_range = float((np.percentile(bgV, 95) - np.percentile(bgV, 5)) / max(np.percentile(bgV, 95), 1.0))
    ring_chroma = float(np.hypot(ring_mu[1] - 128.0, ring_mu[2] - 128.0))
    scanner_margin = (ring_mu[0] >= mu[0] - 3.0) and (ring_chroma < 12.0) and (illum_range < 0.12)
    if scanner_margin:
        return {"separable": False, "distance": round(dist, 2), "scanner_white_margin": True,
                "illum_range": round(illum_range, 4),
                "note": "vành ngoài sáng và không màu -> lề trắng của máy scan, không phải nền bàn",
                "paper_lab": [round(float(x), 1) for x in mu],
                "ring_lab": [round(float(x), 1) for x in ring_mu]}

    return {"separable": dist > 4.0, "distance": round(dist, 2), "scanner_white_margin": False,
            "illum_range": round(illum_range, 4),
            "paper_lab": [round(float(x), 1) for x in mu],
            "ring_lab": [round(float(x), 1) for x in ring_mu]}


PHONE_MAKE_HINTS = ("apple", "samsung", "xiaomi", "oppo", "vivo", "huawei", "realme",
                    "oneplus", "google", "nokia", "asus", "sony", "motorola", "honor", "redmi", "iphone")
SCAN_SOFTWARE_HINTS = ("scan", "canoscan", "epson", "hp scan", "brother", "ricoh", "xerox",
                       "camscanner", "adobe scan", "office lens", "genius scan", "docscan", "kyocera", "canon ir")


def detect_source_type(bgr: np.ndarray, exif: Dict[str, Any], quad_info: Optional[Dict[str, Any]],
                       cfg: Stage1Config, paper_mask: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """
    Tra ve {'type': 'scan'|'photo', 'score': float, 'confidence': float, 'evidence': [...]}
    score > 0  -> nghieng ve ANH CHUP DIEN THOAI
    score < 0  -> nghieng ve ANH SCAN
    Hoan toan rule-based, khong train.
    """
    ev: List[Dict[str, Any]] = []

    def vote(name: str, v: float, weight: float, detail: str):
        ev.append({"feature": name, "vote": round(float(v), 3), "weight": weight,
                   "contribution": round(float(v) * weight, 3), "detail": detail})

    # --- (1) EXIF: bang chung manh nhat ---
    make = str(exif.get("Make", "")).lower()
    model = str(exif.get("Model", "")).lower()
    software = str(exif.get("Software", "")).lower()
    has_cam_params = any(k in exif for k in ("FocalLength", "ExposureTime", "ISOSpeedRatings", "FNumber", "LensModel"))
    has_gps = "GPSLatitude" in exif or "GPSInfo" in exif

    if any(hint in make or hint in model for hint in PHONE_MAKE_HINTS):
        vote("exif_camera_make", 1.0, 3.0, f"EXIF Make/Model = '{exif.get('Make','')} {exif.get('Model','')}' -> may dien thoai")
    elif any(hint in software for hint in SCAN_SOFTWARE_HINTS):
        vote("exif_scan_software", -1.0, 3.0, f"EXIF Software = '{exif.get('Software','')}' -> phan mem scan")
    elif has_cam_params or has_gps:
        vote("exif_camera_params", 0.7, 2.0, "EXIF co thong so chup (khau do/ISO/GPS) -> anh chup")
    else:
        vote("exif_missing", -0.15, 1.0, "Khong co EXIF (anh scan, anh da xu ly hoac anh chup da bi strip metadata)")

    # --- (2) Vien anh: scan thi vien la giay/nen may dong nhat, chup thi lo nen ban ---
    small = resize_long_edge(bgr, 800)
    h, w = small.shape[:2]
    ring = border_ring_mask(h, w, 0.05)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    ring_px = hsv[ring > 0]
    sat_mean = float(ring_px[:, 1].mean())
    val_std = float(ring_px[:, 2].std())
    ring_colorful = colorfulness(cv2.bitwise_and(small, small, mask=ring))

    if sat_mean > 45:
        vote("border_saturation", 1.0, 2.0, f"Vien anh co mau bao hoa cao (S={sat_mean:.0f}) -> lo nen ban/san")
    elif sat_mean > 22:
        vote("border_saturation", 0.5, 2.0, f"Vien anh hoi co mau (S={sat_mean:.0f})")
    else:
        vote("border_saturation", -0.8, 2.0, f"Vien anh gan nhu khong mau (S={sat_mean:.0f}) -> nen giay/scan")

    if val_std > 55:
        vote("border_texture", 0.9, 1.5, f"Vien anh nhieu ket cau/do tuong phan (std={val_std:.0f}) -> nen ngoai giay")
    elif val_std < 22:
        vote("border_texture", -0.8, 1.5, f"Vien anh phang (std={val_std:.0f}) -> dac trung scan")
    else:
        vote("border_texture", 0.1, 1.5, f"Vien anh trung tinh (std={val_std:.0f})")

    # --- (3) Do dong deu anh sang toan anh ---
    V = hsv[:, :, 2].astype(np.float32)
    bg = cv2.GaussianBlur(cv2.resize(V, (64, 64), interpolation=cv2.INTER_AREA), (0, 0), 6)
    p5, p95 = np.percentile(bg, 5), np.percentile(bg, 95)
    illum_range = float((p95 - p5) / max(p95, 1.0))
    if illum_range > 0.35:
        vote("illumination_gradient", 1.0, 2.0, f"Anh sang khong deu (chenh {illum_range*100:.0f}%) -> anh chup")
    elif illum_range > 0.18:
        vote("illumination_gradient", 0.4, 2.0, f"Anh sang hoi lech (chenh {illum_range*100:.0f}%)")
    else:
        vote("illumination_gradient", -0.9, 2.0, f"Anh sang rat deu (chenh {illum_range*100:.0f}%) -> den scan")

    # --- (3b) Tach duoc to giay khoi NEN hay khong: dac trung manh nhat sau EXIF ---
    if paper_mask is None:
        vote("paper_background_separable", -1.0, 3.0,
             "Khong ton tai 'nen' quanh to giay (giay trum kin khung) -> dac trung anh scan")
    else:
        pa = float((paper_mask > 0).mean())
        if pa > 0.93:
            vote("paper_background_separable", -0.8, 3.0,
                 f"To giay chiem {pa*100:.0f}% khung, khong con vien nen -> anh scan hoac anh da crop")
        elif pa < 0.10:
            vote("paper_background_separable", -0.3, 3.0,
                 f"Vung tach duoc qua nho ({pa*100:.0f}%) - khong ket luan duoc")
        else:
            vote("paper_background_separable", 1.0, 3.0,
                 f"Tach duoc to giay ({pa*100:.0f}% khung) khoi nen xung quanh -> anh chup")

    # --- (4) Tu giac giay nam han trong khung ---
    if quad_info and quad_info.get("found"):
        ar = quad_info.get("area_ratio", 1.0)
        margin = quad_info.get("min_corner_margin_pct", 0.0)
        if ar < 0.88 and margin > 2.0:
            vote("paper_quad_inside_frame", min(1.0, margin / 6.0), 2.0,
                 f"To giay nam gon trong khung (chiem {ar*100:.0f}% dien tich, le {margin:.1f}%) -> anh chup")
        else:
            vote("paper_quad_inside_frame", -0.5, 2.0,
                 f"To giay trum gan het khung (chiem {ar*100:.0f}%) -> dac trung scan/anh da crop")
    else:
        vote("paper_quad_inside_frame", -0.5, 2.0, "Khong do duoc tu giac to giay -> giay trum khung (scan)")

    # --- (4b) DAC TRUNG QUYET DINH: vanh ngoai anh co CUNG CHAT LIEU voi ruot chung tu khong? ---
    ring_test = ring_vs_document(small)
    if ring_test.get("scanner_white_margin"):
        vote("scanner_white_margin", -1.0, 6.0,
             "Vành ngoài sáng, không màu VÀ ánh sáng rất đều -> lề trắng của bàn scan, "
             "không phải nền bàn -> ảnh scan")
    elif ring_test["separable"]:
        vote("background_ring_differs", 1.0, 4.0,
             f"Vanh ngoai khung KHAC HAN nen giay ben trong (lech {ring_test['distance']:.1f} sigma) "
             f"-> co nen ban/san quanh to giay -> anh chup")
    else:
        vote("background_ring_differs", -1.0, 4.0,
             f"Vanh ngoai khung CUNG chat lieu voi nen giay (lech {ring_test['distance']:.1f} sigma) "
             f"-> to giay trum kin khung -> anh scan")

    # --- (5) Ti le khung hinh ---
    H0, W0 = bgr.shape[:2]
    ar_img = max(H0, W0) / max(1.0, min(H0, W0))
    if abs(ar_img - 4 / 3) < 0.04 or abs(ar_img - 16 / 9) < 0.06:
        vote("frame_aspect", 0.8, 1.0, f"Ti le khung {ar_img:.2f} dung chuan cam bien dien thoai (4:3 hoac 16:9)")
    elif 1.35 <= ar_img <= 1.48:
        vote("frame_aspect", -0.6, 1.0, f"Ti le khung {ar_img:.2f} ~ A4 (1.41) -> scan nguyen trang")
    else:
        vote("frame_aspect", 0.0, 1.0, f"Ti le khung {ar_img:.2f} khong ket luan")

    # --- (6) Nhieu cam bien o vung phang ---
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    med = cv2.medianBlur(gray, 3)
    flat = cv2.absdiff(gray, med)
    flat_mask = (cv2.Laplacian(med, cv2.CV_64F).__abs__() < 5)
    noise = float(flat[flat_mask].mean()) if flat_mask.any() else 0.0
    if noise > 2.2:
        vote("sensor_noise", 0.7, 1.0, f"Nhieu vung phang cao ({noise:.2f}) -> cam bien dien thoai")
    else:
        vote("sensor_noise", -0.4, 1.0, f"Vung phang sach ({noise:.2f}) -> scan")

    total_w = sum(e["weight"] for e in ev)
    score = sum(e["contribution"] for e in ev) / max(total_w, 1e-6)
    stype = "photo" if score > cfg.scan_photo_threshold else "scan"
    confidence = min(1.0, abs(score) / 0.45)
    ev_sorted = sorted(ev, key=lambda e: -abs(e["contribution"]))
    return {
        "type": stype,
        "score": round(float(score), 4),
        "confidence": round(float(confidence), 3),
        "evidence": ev_sorted,
        "ring_test": ring_test,
        "top_reasons": [e["detail"] for e in ev_sorted[:3]],
    }

def order_quad(pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    d = (pts[:, 0] - pts[:, 1])
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmax(d)]
    bl = pts[np.argmin(d)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def quad_metrics(quad: np.ndarray, W: int, H: int) -> Dict[str, Any]:
    q = order_quad(quad)
    area = abs(cv2.contourArea(q.astype(np.float32)))
    area_ratio = area / float(W * H)
    margins = [min(x, y, W - 1 - x, H - 1 - y) for (x, y) in q]
    min_margin_pct = 100.0 * float(min(margins)) / float(min(W, H))
    n_touch = sum(1 for m in margins if 100.0 * m / min(W, H) < 0.8)

    wt = np.linalg.norm(q[0] - q[1]); wb = np.linalg.norm(q[3] - q[2])
    hl = np.linalg.norm(q[0] - q[3]); hr = np.linalg.norm(q[1] - q[2])
    wq, hq = (wt + wb) / 2.0, (hl + hr) / 2.0
    aspect = max(wq, hq) / max(1e-6, min(wq, hq))

    angles = []
    for i in range(4):
        p0, p1, p2 = q[(i - 1) % 4], q[i], q[(i + 1) % 4]
        v1, v2 = p0 - p1, p2 - p1
        c = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-6))
        angles.append(float(np.degrees(np.arccos(np.clip(c, -1, 1)))))

    # do lech so voi hinh chu nhat: chenh lech canh doi dien
    side_skew = max(abs(wt - wb) / max(wt, wb, 1e-6), abs(hl - hr) / max(hl, hr, 1e-6))

    return {
        "points": [[round(float(x), 1), round(float(y), 1)] for x, y in q],
        "area_ratio": round(float(area_ratio), 4),
        "min_corner_margin_pct": round(float(min_margin_pct), 2),
        "n_corners_touching_edge": int(n_touch),
        "aspect": round(float(aspect), 3),
        "corner_angles": [round(a, 1) for a in angles],
        "side_skew": round(float(side_skew), 3),
        "warp_w": int(round(wq)),
        "warp_h": int(round(hq)),
    }


def quad_from_contour(c: np.ndarray) -> Optional[np.ndarray]:
    """
    SUA 1 - Ep contour ve DUNG 4 dinh bang do nhi phan tren epsilon.
    Truoc day code roi xuong minAreaRect khi approxPolyDP khong ra 4 diem,
    ma hinh chu nhat bao chi dung khi to giay song song mat phang camera.
    """
    hull = cv2.convexHull(c)                 # to giay luon loi -> bo nhieu rang cua
    peri = cv2.arcLength(hull, True)
    lo, hi = 0.001, 0.20
    for _ in range(24):
        mid = (lo + hi) / 2.0
        ap = cv2.approxPolyDP(hull, mid * peri, True)
        if len(ap) > 4:
            lo = mid                          # con nhieu dinh -> noi epsilon
        elif len(ap) < 4:
            hi = mid                          # gop qua tay -> siet lai
        else:
            q = ap.reshape(4, 2).astype(np.float32)
            return q if cv2.isContourConvex(ap) else None
    return None


def quad_extreme_points(c: np.ndarray) -> Optional[np.ndarray]:
    """Du phong: 4 goc = cuc tri cua (x+y) va (x-y). Dung khi giay xoay duoi ~40 do."""
    p = c.reshape(-1, 2).astype(np.float32)
    if len(p) < 4:
        return None
    ssum, sdif = p.sum(1), p[:, 0] - p[:, 1]
    q = np.array([p[np.argmin(ssum)], p[np.argmax(sdif)],
                  p[np.argmax(ssum)], p[np.argmin(sdif)]], np.float32)
    dmin = min(float(np.linalg.norm(q[i] - q[j])) for i in range(4) for j in range(i + 1, 4))
    return q if dmin > 10 else None


def contour_to_quad(c: np.ndarray) -> Optional[np.ndarray]:
    """3 lop: do nhi phan epsilon -> cuc tri toa do -> minAreaRect (chi khi thuc su chu nhat)."""
    q = quad_from_contour(c)
    if q is not None:
        return q
    q = quad_extreme_points(c)
    if q is not None:
        return q
    box = cv2.boxPoints(cv2.minAreaRect(c))
    # chi chap nhan hinh chu nhat bao khi contour LAP DAY no > 92%
    if cv2.contourArea(c) / max(cv2.contourArea(box), 1.0) > 0.92:
        return box.astype(np.float32)
    return None


def quad_mask_iou(quad: np.ndarray, mask: np.ndarray) -> float:
    """
    SUA 2 - Cau hoi TRUC TIEP: tu giac nay co trung voi to giay khong?
    Cac tieu chi cu (ti le canh, goc vuong, dien tich) deu gian tiep nen
    ung vien bam vao KHUNG IN tren giay van dat diem cao.
    """
    m = np.zeros(mask.shape[:2], np.uint8)
    cv2.fillConvexPoly(m, np.round(quad).astype(np.int32), 255)
    a, b = m > 0, mask > 0
    union = int(np.count_nonzero(a | b))
    return float(np.count_nonzero(a & b)) / max(union, 1)


def boundary_iou(mask_a: np.ndarray, mask_b: np.ndarray, d_frac: float = 0.02) -> float:
    """
    IoU tinh RIENG TREN DAI BIEN (co mat na vao d px roi lay phan vanh).
    IoU thuong do DIEN TICH chong lap nen mat mot dai hep o ria chi lam giam rat it.
    Chi so nay nhay gap nhieu lan voi sai lech o biên - dung chinh cho ca "mat mot cot ben phai".
    """
    d = max(1, int(round(d_frac * min(mask_a.shape[:2]))))
    k = np.ones((2 * d + 1, 2 * d + 1), np.uint8)
    ba = cv2.subtract(mask_a, cv2.erode(mask_a, k)) > 0
    bb = cv2.subtract(mask_b, cv2.erode(mask_b, k)) > 0
    union = int(np.count_nonzero(ba | bb))
    return float(np.count_nonzero(ba & bb)) / max(union, 1)


def ink_outside_quad(bgr: np.ndarray, quad_pts, paper_mask: Optional[np.ndarray]) -> Dict[str, Any]:
    """
    CHI SO QUAN TRONG NHAT: tu giac co dang CAT MAT CHU khong?

    Cac chi so hinh hoc (IoU, ti le canh, goc vuong) deu gian tiep. Cau hoi nghiep vu
    that su la "co mat chu khong". Dem % pixel NET CHU nam TRONG to giay nhung
    NGOAI tu giac. Mot dai hep bi cat o ria lam IoU giam rat it nhung so chu mat
    thi dem duoc ngay - ma dai ria do lai chinh la cho dat chu ky va moc.
    """
    small = resize_long_edge(bgr, 800)
    H, W = small.shape[:2]
    sc = W / float(bgr.shape[1])
    txt = _text_mask(small, max(H, W)) > 0

    qm = np.zeros((H, W), np.uint8)
    cv2.fillConvexPoly(qm, np.round(np.asarray(quad_pts, np.float32) * sc).astype(np.int32), 255)
    inside_quad = qm > 0

    if paper_mask is not None:
        pm = cv2.resize(paper_mask, (W, H), interpolation=cv2.INTER_NEAREST) > 0
    else:
        pm = np.ones((H, W), bool)

    ink_on_paper = txt & pm
    n_ink = int(np.count_nonzero(ink_on_paper))
    if n_ink < 200:
        return {"available": False, "reason": "quá ít nét chữ để đo"}
    lost = int(np.count_nonzero(ink_on_paper & ~inside_quad))
    return {"available": True,
            "ink_outside_pct": round(100.0 * lost / n_ink, 3),
            "n_ink_px": n_ink}


def _quad_from_contours(gray: np.ndarray) -> List[np.ndarray]:
    H, W = gray.shape[:2]
    cands = []
    blur = cv2.bilateralFilter(gray, 9, 60, 60)
    v = float(np.median(blur))
    for sigma in (0.25, 0.45, 0.65):
        lo = int(max(0, (1.0 - sigma) * v))
        hi = int(min(255, (1.0 + sigma) * v))
        edges = cv2.Canny(blur, lo, hi)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
        edges = cv2.erode(edges, np.ones((3, 3), np.uint8), iterations=1)
        cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:8]
        for c in cnts:
            if cv2.contourArea(c) < 0.08 * W * H:
                continue
            q = contour_to_quad(c)
            if q is not None:
                cands.append(q)
    return cands


# KHOA TOAN CUC CHO GRABCUT: cv2.setRNGSeed() dat seed len bo sinh so ngau nhien
# TOAN CUC cua OpenCV (dung chung cho ca tien trinh), KHONG phai bien cuc bo cua tung luong.
# Runner Tang 1 chay ThreadPoolExecutor(max_workers=6), neu khong khoa thi luong B co the
# goi setRNGSeed() xen giua cap setRNGSeed()/grabCut() cua luong A -> grabCut cua A chay
# voi seed cua B, pha vo tinh TAI LAP ma thiet ke 3-seed (paper_mask_consensus) co dat.
# Chi bao quanh dung cap setRNGSeed + grabCut (khong bao ca ham) de giu duoc song song.
_GRABCUT_RNG_LOCK = threading.Lock()


def paper_mask_from_background(bgr: np.ndarray, inset: float = 0.04, iters: int = 4,
                               work: int = 400, allow_touch_border: bool = False,
                               base_mask: Optional[np.ndarray] = None,
                               rng_seed: int = 20250913) -> Optional[np.ndarray]:
    """
    Tach to giay khoi nen bang GrabCut (thuat toan do thi cua OpenCV - KHONG phai model hoc may,
    khong can du lieu huan luyen).

    LAN 1 (mac dinh): khoi tao bang hinh chu nhat, vanh ngoai `inset` coi la NEN.
        -> mat na sach nhung KHONG BAO GIO cham mep anh.
    LAN 2 (allow_touch_border=True): khoi tao bang chinh mat na lan 1, vanh ngoai chi la
        "co the la nen" -> vung giay duoc phep no ra toi mep anh NEU no thuc su la giay.
        Nho vay moi biet duoc to giay co bi khung anh cat hay khong.

    `base_mask`: mat na lan 1 da tinh san -> bo qua lan 1, tiet kiem thoi gian.
    """
    h, w = bgr.shape[:2]
    sc = work / float(max(h, w))
    sm = cv2.resize(bgr, (max(8, int(w * sc)), max(8, int(h * sc))), interpolation=cv2.INTER_AREA)
    H, W = sm.shape[:2]
    k = np.ones((5, 5), np.uint8)

    if base_mask is not None:
        m = cv2.resize(base_mask, (W, H), interpolation=cv2.INTER_NEAREST)
        if m.mean() < 5:
            return None
        if not allow_touch_border:
            return cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
    else:
        gc = np.zeros((H, W), np.uint8)
        dx, dy = max(1, int(W * inset)), max(1, int(H * inset))
        try:
            # TAI LAP: grabCut khoi tao GMM bang k-means lay seed tu RNG toan cuc cua OpenCV.
            # Khong co dong duoi day thi CUNG MOT ANH cho KET QUA KHAC NHAU moi lan chay
            # (da do: dien tich mat na dao dong 0.27-0.39 tren cung mot file).
            with _GRABCUT_RNG_LOCK:
                cv2.setRNGSeed(rng_seed)
                cv2.grabCut(sm, gc, (dx, dy, W - 2 * dx, H - 2 * dy),
                            np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64),
                            iters, cv2.GC_INIT_WITH_RECT)
        except Exception:
            return None
        m = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
        if m.mean() < 5:
            return None

        # GrabCut hay "an" luon vung BONG DO quanh to giay. Loc lai: trong vung GrabCut chon,
        # chi giu phan SANG (giay) bang nguong Otsu tren kenh L cua anh da lam phang anh sang.
        try:
            Lc = cv2.cvtColor(flatten_illumination(sm, 1.0), cv2.COLOR_BGR2LAB)[:, :, 0]
            vals = Lc[m > 0]
            if vals.size > 200:
                thr, _ = cv2.threshold(vals.reshape(-1, 1), 0, 255,
                                       cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                refined = cv2.bitwise_and(m, (Lc >= thr).astype(np.uint8) * 255)
                if refined.mean() > 0.60 * m.mean():
                    m = refined
        except Exception:
            pass

        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k, iterations=1)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k, iterations=3)
        n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
        if n > 1:
            m = np.where(lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA])), 255, 0).astype(np.uint8)
        ff = m.copy()
        cv2.floodFill(ff, np.zeros((H + 2, W + 2), np.uint8), (0, 0), 255)
        m = m | cv2.bitwise_not(ff)
        if not allow_touch_border:
            return cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)

    # --- LAN 2: cho phep mat na cham mep anh ---
    try:
        gc2 = np.full((H, W), cv2.GC_PR_BGD, np.uint8)
        gc2[m > 0] = cv2.GC_PR_FGD
        gc2[cv2.erode(m, np.ones((7, 7), np.uint8), iterations=2) > 0] = cv2.GC_FGD
        gc2[cv2.dilate(m, np.ones((9, 9), np.uint8), iterations=4) == 0] = cv2.GC_BGD
        if (gc2 == cv2.GC_BGD).sum() > 100 and (gc2 == cv2.GC_FGD).sum() > 100:
            with _GRABCUT_RNG_LOCK:
                cv2.setRNGSeed(rng_seed + 1)
                cv2.grabCut(sm, gc2, None, np.zeros((1, 65), np.float64),
                            np.zeros((1, 65), np.float64), 2, cv2.GC_INIT_WITH_MASK)
            m2 = np.where((gc2 == cv2.GC_FGD) | (gc2 == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
            m2 = cv2.morphologyEx(m2, cv2.MORPH_CLOSE, k, iterations=2)
            n2, lab2, st2, _ = cv2.connectedComponentsWithStats(m2, 8)
            if n2 > 1:
                m2 = np.where(lab2 == 1 + int(np.argmax(st2[1:, cv2.CC_STAT_AREA])), 255, 0).astype(np.uint8)
            if 0.8 * m.mean() < m2.mean() < 1.8 * m.mean() + 20:
                m = m2
    except Exception:
        pass
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)


def paper_mask_consensus(bgr: np.ndarray, inset: float = 0.04,
                         seeds: Tuple[int, ...] = (20250913, 424242, 777),
                         ) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
    """
    Chay GrabCut NHIEU LAN voi cac seed CO DINH khac nhau roi lay DONG THUAN theo pixel.

    Vi sao can: co dinh seed chi lam ket qua TAI LAP (cung anh -> cung ket qua),
    KHONG lam no ON DINH. Do thuc te tren mot anh: doi seed thi dien tich mat na
    nhay tu 0.24 den 0.39 - lech 60%. Nghia la viec tach giay/nen o anh do von da
    mo ho, mot lan chay chi la mot lan boc tham.

    Lay da so 2/3 pixel -> triet tieu nhieu ngau nhien.
    Do IoU doi mot giua cac lan -> DO DONG THUAN. Dong thuan thap = tach giay/nen
    that su mo ho = tin hieu that, dang canh bao cho nguoi kiem tra.
    """
    masks = []
    for sd in seeds:
        m = paper_mask_from_background(bgr, inset=inset, rng_seed=sd)
        if m is not None:
            masks.append(m > 0)
    if not masks:
        return None, {"n_runs": 0, "agreement": None, "reason": "không tách được tờ giấy khỏi nền"}
    if len(masks) == 1:
        return (masks[0].astype(np.uint8) * 255,
                {"n_runs": 1, "agreement": None, "area": round(float(masks[0].mean()), 4)})

    vote = np.sum(np.stack(masks), axis=0)
    cons = (vote >= max(2, (len(masks) + 1) // 2)).astype(np.uint8) * 255

    ious = []
    for i in range(len(masks)):
        for j in range(i + 1, len(masks)):
            inter = np.count_nonzero(masks[i] & masks[j])
            union = np.count_nonzero(masks[i] | masks[j])
            ious.append(inter / max(union, 1))
    agree = float(min(ious))
    if cons.mean() < 5:
        return None, {"n_runs": len(masks), "agreement": round(agree, 3),
                      "reason": "các lần chạy không đồng thuận đủ để giữ vùng nào"}
    return cons, {"n_runs": len(masks),
                  "agreement": round(agree, 3),
                  "agreement_mean": round(float(np.mean(ious)), 3),
                  "area": round(float((cons > 0).mean()), 4),
                  "areas_per_run": [round(float(m.mean()), 4) for m in masks]}


def border_contact(bgr: np.ndarray, inset: float = 0.04, tol_px: int = 3,
                   mask: Optional[np.ndarray] = None,
                   base_mask: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """
    KIEM TRA "DU 4 GOC" - do TRUC TIEP tren mat na to giay.

    Cach lam: GrabCut duoc khoi tao voi vanh ngoai `inset` (4%) la NEN, nen mat na to giay
    khong bao gio vuot qua duong bien 4% do. Vi vay:
      - Neu to giay NAM GON trong khung  -> bien cua mat na la MEP GIAY THAT, nam vao ben trong.
      - Neu to giay BI CAT boi khung anh -> mat na se ap sat duong bien 4% do tren mot
        DOAN LIEN TUC DAI (vi giay con chay tiep ra ngoai).
    Ta do ti le doan lien tuc dai nhat ap sat duong bien tren tung canh.
    Khong phu thuoc anh sang, khong phu thuoc mau nen.
    """
    mask = paper_mask_from_background(resize_long_edge(bgr, 800), inset=inset,
                                      allow_touch_border=True, base_mask=base_mask)
    if mask is None:
        return {"available": False, "reason": "không tách được tờ giấy khỏi nền (nền và giấy quá giống nhau)"}
    H, W = mask.shape[:2]
    on = mask > 0
    if on.mean() < 0.05:
        return {"available": False, "reason": "vùng giấy quá nhỏ"}

    dx = dy = max(2, int(round(0.012 * min(W, H))))     # coi la "cham mep" khi cach mep < 1.2%

    def longest_run(b: np.ndarray) -> float:
        best = cur = 0
        for v in b:
            cur = cur + 1 if v else 0
            if cur > best:
                best = cur
        return best / max(len(b), 1)

    cols = np.arange(W)[None, :]
    rows = np.arange(H)[:, None]
    big = 10 ** 6
    first_row = np.where(on.any(axis=0), np.argmax(on, axis=0), big)                  # theo tung cot
    last_row = np.where(on.any(axis=0), H - 1 - np.argmax(on[::-1], axis=0), -big)
    first_col = np.where(on.any(axis=1), np.argmax(on, axis=1), big)                  # theo tung hang
    last_col = np.where(on.any(axis=1), W - 1 - np.argmax(on[:, ::-1], axis=1), -big)

    sides = {
        "trên": longest_run(first_row <= dy + tol_px),
        "dưới": longest_run(last_row >= H - 1 - dy - tol_px),
        "trái": longest_run(first_col <= dx + tol_px),
        "phải": longest_run(last_col >= W - 1 - dx - tol_px),
    }
    sides = {k: round(float(v), 3) for k, v in sides.items()}
    cut = [k for k, v in sides.items() if v > 0.20]
    near = [k for k, v in sides.items() if 0.08 < v <= 0.20]
    return {"available": True,
            "sides_edge_run": sides,
            "max_side": round(max(sides.values()), 3),
            "paper_area_ratio": round(float(on.mean()), 4),
            "cut_sides": cut,
            "near_edge_sides": near,
            "looks_precropped": len(cut) == 4}


def _quad_from_background(bgr: np.ndarray, pmask: Optional[np.ndarray] = None) -> List[np.ndarray]:
    H, W = bgr.shape[:2]
    mask = (cv2.resize(pmask, (W, H), interpolation=cv2.INTER_NEAREST) if pmask is not None
            else paper_mask_from_background(bgr))
    if mask is None:
        return []
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:3]:
        if cv2.contourArea(c) < 0.08 * W * H:
            continue
        q = contour_to_quad(c)
        if q is not None:
            out.append(q)
    return out


def _quad_from_lines(gray: np.ndarray) -> List[np.ndarray]:
    """Giao diem cua 2 duong ngang + 2 duong doc ngoai cung."""
    H, W = gray.shape[:2]
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, threshold=int(0.25 * min(H, W)),
                            minLineLength=int(0.35 * min(H, W)), maxLineGap=int(0.05 * min(H, W)))
    if lines is None:
        return []
    hor, ver = [], []
    for x1, y1, x2, y2 in lines[:, 0]:
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
        if ang < 25 or ang > 155:
            hor.append((x1, y1, x2, y2))
        elif 65 < ang < 115:
            ver.append((x1, y1, x2, y2))
    if len(hor) < 2 or len(ver) < 2:
        return []
    hor.sort(key=lambda l: (l[1] + l[3]) / 2)
    ver.sort(key=lambda l: (l[0] + l[2]) / 2)
    top, bot, left, right = hor[0], hor[-1], ver[0], ver[-1]

    def inter(l1, l2):
        x1, y1, x2, y2 = l1; x3, y3, x4, y4 = l2
        d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(d) < 1e-6:
            return None
        px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / d
        py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / d
        return [px, py]

    pts = [inter(top, left), inter(top, right), inter(bot, right), inter(bot, left)]
    if any(p is None for p in pts):
        return []
    pts = np.array(pts, np.float32)
    if not (( -0.15 * W <= pts[:, 0]).all() and (pts[:, 0] <= 1.15 * W).all()
            and (-0.15 * H <= pts[:, 1]).all() and (pts[:, 1] <= 1.15 * H).all()):
        return []
    return [pts]


def _score_candidate(m: Dict[str, Any], iou: Optional[float] = None) -> float:
    s = 0.0
    ar = m["area_ratio"]
    s += 2.0 * (1.0 if 0.3 <= ar <= 0.92 else max(0.0, 1.0 - abs(ar - 0.6) * 2))
    a = m["aspect"]
    s += 1.5 * math.exp(-((a - 1.414) ** 2) / (2 * 0.35 ** 2))
    ang_pen = sum(abs(x - 90.0) for x in m["corner_angles"]) / 4.0
    s += 1.5 * math.exp(-(ang_pen ** 2) / (2 * 12.0 ** 2))
    s += 1.0 * math.exp(-(m["side_skew"] ** 2) / (2 * 0.15 ** 2))
    # uu tien tu giac nam gon trong khung (ung vien trung khop ca khung anh thuong la rac)
    s += 1.0 * (0.35 ** m["n_corners_touching_edge"])
    if iou is not None:
        s += 3.0 * iou          # SUA 2: tieu chi TRUC TIEP, trong so nang nhat
    return s


def detect_paper_quad(bgr: np.ndarray, cfg: Stage1Config,
                      pmask: Optional[np.ndarray] = None) -> Dict[str, Any]:
    H0, W0 = bgr.shape[:2]
    work = resize_long_edge(bgr, cfg.quad_work_size)
    Hw, Ww = work.shape[:2]
    scale = max(H0, W0) / float(max(Hw, Ww))
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)

    strategies = [("contour", _quad_from_contours(gray)),
                  ("background", _quad_from_background(work, pmask)),
                  ("hough_lines", _quad_from_lines(gray))]

    # mat na to giay o CUNG TI LE voi anh work, de tinh IoU
    mask_w = None
    if pmask is not None:
        mask_w = cv2.resize(pmask, (Ww, Hw), interpolation=cv2.INTER_NEAREST)

    best, best_score, best_method, best_iou = None, -1.0, None, None
    tried = []
    for name, cands in strategies:
        for q in cands:
            m = quad_metrics(q, Ww, Hw)
            if m["area_ratio"] < 0.05:
                continue
            iou = quad_mask_iou(order_quad(q), mask_w) if mask_w is not None else None
            # SUA 2: luat loai thang - tu giac khong khop to giay thi bo han,
            # khong cho vao vong cham diem (chinh la ung vien bam vao khung in).
            if iou is not None and iou < 0.60:
                tried.append({"method": name, "iou": round(iou, 3), "loai": "IoU < 0.60"})
                continue
            sc = _score_candidate(m, iou)
            tried.append({"method": name, "score": round(sc, 3), "iou": None if iou is None else round(iou, 3),
                          "area_ratio": m["area_ratio"], "aspect": m["aspect"]})
            if sc > best_score:
                best, best_score, best_method, best_iou = q, sc, name, iou

    if best is None:
        return {"found": False, "method": None, "candidates_tried": tried[:10],
                "points": None, "area_ratio": None, "min_corner_margin_pct": None,
                "iou_with_mask": None}

    m = quad_metrics(best * scale, W0, H0)
    b_iou = None
    if mask_w is not None:
        qm = np.zeros((Hw, Ww), np.uint8)
        cv2.fillConvexPoly(qm, np.round(order_quad(best)).astype(np.int32), 255)
        b_iou = round(boundary_iou(qm, (mask_w > 0).astype(np.uint8) * 255), 3)
    m.update({"found": True, "method": best_method, "fit_score": round(best_score, 3),
              "iou_with_mask": None if best_iou is None else round(best_iou, 3),
              "boundary_iou": b_iou,
              # CANH BAO DIEN GIAI: chien luoc 'background' SINH tu giac TU CHINH mat na nay,
              # nen IoU khi do la "tu giac khop voi thu de ra no" - gan 1 theo dinh nghia.
              # Chi so nay CHI co gia tri khi chien luoc thang la contour hoac hough_lines.
              "iou_is_self_referential": best_method == "background",
              "candidates_tried": tried[:10]})
    return m

PASS, WARN, RETAKE = "DAT", "CANH_BAO", "CHUP_LAI"


def gate_four_corners(quad: Dict[str, Any], contact: Dict[str, Any], source_type: str,
                      cfg: Stage1Config, pminfo: Optional[Dict[str, Any]] = None,
                      ink_out: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Anh SCAN: khong bat buoc du 4 goc (to giay trum mat kinh may scan la binh thuong).
    Anh CHUP DIEN THOAI: BAT BUOC nhin thay tron ven 4 goc va 4 canh.
    """
    rejects: List[str] = []
    warns: List[str] = []

    if source_type == "scan":
        if not quad.get("found"):
            warns.append("Ảnh scan: không tách được biên tờ giấy, sẽ cắt viền trắng theo nội dung")
        return {"status": PASS if not rejects else RETAKE, "rejects": rejects, "warns": warns}

    # --- Kiem tra canh bi tran ra ngoai khung (doc lap voi viec fit tu giac) ---
    if contact.get("available"):
        if contact.get("looks_precropped"):
            warns.append("Ảnh đã được cắt sát 4 cạnh (giống ảnh scan) — không còn lề nền để kiểm tra đủ 4 góc")
        elif contact["cut_sides"]:
            rejects.append("Cạnh " + "/".join(contact["cut_sides"]) +
                           " của tờ giấy tràn ra ngoài khung ảnh — lùi máy ra xa và chụp lại trọn 4 góc")
        elif contact["near_edge_sides"]:
            warns.append("Cạnh " + "/".join(contact["near_edge_sides"]) +
                         " gần sát mép ảnh — nên chừa thêm lề quanh tờ giấy")

    if not quad.get("found"):
        rejects.append("Không tìm thấy đủ 4 góc tờ giấy — đặt giấy lên nền tương phản (bàn tối màu) và chụp lại")
        return {"status": RETAKE, "rejects": rejects, "warns": warns}

    ar = quad["area_ratio"]
    margin = quad["min_corner_margin_pct"]
    n_touch = quad["n_corners_touching_edge"]
    angles = quad["corner_angles"]
    aspect = quad["aspect"]

    if n_touch >= 2:
        rejects.append(f"{n_touch} góc chạm/vượt mép ảnh — tờ giấy bị cắt, lùi ra xa và chụp lại toàn bộ tờ")
    elif n_touch == 1:
        if ar > cfg.max_area_ratio_warn:
            rejects.append("1 góc chạm mép và tờ giấy trùm gần hết khung — khả năng mất nội dung, chụp lại")
        else:
            warns.append("1 góc sát mép ảnh — nên chừa lề rộng hơn quanh tờ giấy")

    if margin is not None and margin < 0:
        warns.append(f"Có góc tờ giấy ước lượng nằm NGOÀI khung ảnh ({margin:.1f}%) — kiểm tra lại ảnh")
    elif margin is not None and margin < cfg.corner_margin_reject_pct and n_touch == 0:
        warns.append(f"Góc gần nhất chỉ cách mép {margin:.1f}% — rất sát, dễ mất nét")
    elif margin is not None and margin < cfg.corner_margin_warn_pct:
        warns.append(f"Lề quanh tờ giấy hẹp ({max(margin, 0.0):.1f}%)")

    if ar < cfg.min_area_ratio_reject:
        rejects.append(f"Tờ giấy chỉ chiếm {ar*100:.0f}% khung hình — lại gần hơn và chụp lại")
    elif ar < cfg.min_area_ratio_warn:
        warns.append(f"Tờ giấy chỉ chiếm {ar*100:.0f}% khung hình — độ phân giải chữ sẽ thấp")

    bad_ang = [a for a in angles if a < cfg.min_corner_angle or a > cfg.max_corner_angle]
    if bad_ang:
        rejects.append(f"Góc tờ giấy biến dạng mạnh ({', '.join(f'{a:.0f}°' for a in bad_ang)}) — chụp vuông góc với mặt giấy")

    if not (cfg.aspect_lo_warn <= aspect <= cfg.aspect_hi_warn):
        warns.append(f"Tỉ lệ cạnh {aspect:.2f} lệch so với khổ A4 (1.41) — kiểm tra có chụp thiếu phần nào không")

    # SUA 5 - KHONG dung ti le canh lam luat loai.
    # Ti le do duoi phoi canh khong dang tin: anh chup nghieng HOP LE (con du 4 goc)
    # van cho aspect ~1.08 do canh xa bi thu ngan. Luat "canh bi cat" o tren da do
    # truc tiep bang hinh hoc roi, nen ti le canh chi con la CANH BAO.
    # --- Tin hieu 1: % NET CHU bi tu giac cat ra ngoai (chi so quan trong nhat) ---
    if ink_out and ink_out.get("available"):
        pct = ink_out["ink_outside_pct"]
        if pct > cfg.ink_outside_reject:
            rejects.append(f"Tứ giác cắt mất {pct:.2f}% nét chữ trên tờ giấy — "
                           "ảnh nắn ra sẽ thiếu nội dung, chụp lại trọn tờ")
        elif pct > cfg.ink_outside_warn:
            warns.append(f"Tứ giác cắt mất {pct:.2f}% nét chữ — kiểm tra ảnh ra bằng mắt")

    # --- Tin hieu 2: cac lan GrabCut co dong thuan khong ---
    if pminfo and pminfo.get("agreement") is not None:
        ag = pminfo["agreement"]
        if ag < cfg.agreement_reject:
            rejects.append(f"Ba lần tách giấy khỏi nền cho kết quả lệch nhau nhiều "
                           f"(đồng thuận {ag:.2f}) — nền và giấy quá giống nhau, "
                           "đặt giấy lên nền tối màu và chụp lại")
        elif ag < cfg.agreement_warn:
            warns.append(f"Tách giấy khỏi nền chưa chắc chắn (đồng thuận {ag:.2f}) — "
                         "ảnh nắn ra nên được kiểm tra bằng mắt")

    if quad.get("iou_with_mask") is not None and quad["iou_with_mask"] < 0.85:
        warns.append(f"Tứ giác chỉ khớp {quad['iou_with_mask']*100:.0f}% với vùng giấy "
                     "— ảnh nắn ra có thể lệch, nên kiểm tra bằng mắt")

    if quad.get("side_skew", 0) > 0.35:
        warns.append(f"Phối cảnh lệch mạnh (chênh cạnh đối diện {quad['side_skew']*100:.0f}%) — chụp cao hơn và vuông góc hơn")

    status = RETAKE if rejects else (WARN if warns else PASS)
    return {"status": status, "rejects": rejects, "warns": warns}

def warp_to_a4(bgr: np.ndarray, quad: Dict[str, Any], cfg: Stage1Config) -> Tuple[np.ndarray, Dict[str, Any]]:
    q = np.array(quad["points"], dtype=np.float32)
    q = order_quad(q)
    wq, hq = float(quad["warp_w"]), float(quad["warp_h"])
    if wq <= 1 or hq <= 1:
        return bgr, {"applied": False, "reason": "kích thước tứ giác không hợp lệ"}

    # ep ve ti le A4 theo huong canh dai de sua meo phoi canh con lai
    if hq >= wq:
        out_h = max(hq, wq * cfg.a4_ratio)
        out_w = out_h / cfg.a4_ratio
    else:
        out_w = max(wq, hq * cfg.a4_ratio)
        out_h = out_w / cfg.a4_ratio
    out_w, out_h = int(round(out_w)), int(round(out_h))

    dst = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], np.float32)
    M = cv2.getPerspectiveTransform(q, dst)
    warped = cv2.warpPerspective(bgr, M, (out_w, out_h), flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_REPLICATE)
    return warped, {"applied": True, "out_size": [out_w, out_h], "forced_a4": True}

_OSD_AVAILABLE: Optional[bool] = None


def _osd_available() -> bool:
    global _OSD_AVAILABLE
    if _OSD_AVAILABLE is None:
        try:
            import pytesseract  # noqa
            pytesseract.get_tesseract_version()
            _OSD_AVAILABLE = True
        except Exception:
            _OSD_AVAILABLE = False
    return _OSD_AVAILABLE


def _text_mask(bgr: np.ndarray, long_edge: int = 1200) -> np.ndarray:
    """Mat na NET CHU, da loai bo duong ke bang (chung tu KIDO co rat nhieu duong ke)."""
    g = cv2.cvtColor(resize_long_edge(bgr, long_edge), cv2.COLOR_BGR2GRAY)
    th = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (41, 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 41))
    lines = cv2.bitwise_or(cv2.morphologyEx(th, cv2.MORPH_OPEN, hk),
                           cv2.morphologyEx(th, cv2.MORPH_OPEN, vk))
    return (cv2.subtract(th, lines) > 0).astype(np.float32)


def text_axis(bgr: np.ndarray) -> Dict[str, Any]:
    """
    Chu nam NGANG hay DOC? Dong chu tao dao dong manh theo truc vuong goc voi huong dong.
    Rat on dinh voi chung tu nhieu chu (da do tren 14 bieu mau KIDO: dung 14/14).
    """
    txt = _text_mask(bgr)
    r = txt.sum(axis=1) / max(txt.shape[1], 1)
    c = txt.sum(axis=0) / max(txt.shape[0], 1)
    ratio = float(np.var(r) / max(np.var(c), 1e-6))
    horizontal = ratio > 1.0
    conf = min(1.0, abs(math.log10(max(ratio, 1e-6))) / 0.7)
    return {"text_horizontal": horizontal, "ratio": round(ratio, 3), "confidence": round(conf, 3)}


def flip_score(bgr: np.ndarray) -> Dict[str, Any]:
    """
    Chu co bi LAT NGUOC 180 do khong?
    Chu Latin + dau tieng Viet co phan vuon LEN (b, d, h, l, chu hoa, dau sac/huyen/nga/mu)
    nhieu hon phan thong XUONG (g, p, q, y). So khoi muc phia tren vs phia duoi than chu.
    Do tin cay trung binh (~75%) nen chi dung khi khong co Tesseract OSD.
    """
    txt = _text_mask(bgr, 1400)
    prof = txt.sum(axis=1)
    H = len(prof)
    if prof.max() < 1:
        return {"score": 0.0, "n_bands": 0}
    thr = prof.max() * 0.08
    bands, inb, st = [], False, 0
    for i, v in enumerate(prof):
        if v > thr and not inb:
            st, inb = i, True
        elif v <= thr and inb:
            if i - st >= 10:
                bands.append((st, i))
            inb = False
    if inb and H - st >= 10:
        bands.append((st, H))
    above = below = 0.0
    used = 0
    for a, b in bands:
        pr = prof[a:b]
        h = len(pr)
        if h < 12 or h > 120:
            continue
        core = np.where(pr >= 0.55 * pr.max())[0]
        if len(core) == 0:
            continue
        above += pr[:core[0]].sum()
        below += pr[core[-1] + 1:].sum()
        used += 1
    if above + below < 1:
        return {"score": 0.0, "n_bands": used}
    return {"score": round(float((above - below) / (above + below)), 3), "n_bands": used}


def _osd(bgr: np.ndarray) -> Optional[Dict[str, Any]]:
    if not _osd_available():
        return None
    try:
        import pytesseract
        probe = resize_long_edge(bgr, 1600)
        gray = cv2.cvtColor(probe, cv2.COLOR_BGR2GRAY)
        gray = cv2.copyMakeBorder(gray, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)
        txt = pytesseract.image_to_osd(gray, config="--psm 0 -c min_characters_to_try=20")
        return {"deg": int(re.search(r"Rotate: (\d+)", txt).group(1)) % 360,
                "confidence": float(re.search(r"Orientation confidence: ([\d.]+)", txt).group(1)),
                "script": (re.search(r"Script: (\w+)", txt) or [None, "?"])[1]}
    except Exception:
        return None


def rotate_cw(img: np.ndarray, deg: int) -> np.ndarray:
    """Xoay THEO CHIEU KIM DONG HO deg do (0/90/180/270) - dung quy uoc cua Tesseract OSD:
    truong 'Rotate: N' nghia la 'xoay anh N do theo chieu kim dong ho thi chu se dung'."""
    deg = int(deg) % 360
    if deg == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if deg == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if deg == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


# Tu khoa cho OCR Lexical Guard (xac nhan huong 0/180) nam o CONFIG, khong hardcode:
# config/stage1_orientation_keywords.json. Thieu file / loi doc / danh sach rong -> guard TAT,
# nhung KHONG tat am tham: warnings.warn (1 lan / tien trinh) va moi trang ghi truong
# `lexical_guard = {"enabled": False, ...}` vao JSON ket qua (xem process_one).
# KHONG co ban du phong hardcode trong Python — co y (doi khach hang thi doi file config).
ORIENTATION_KEYWORDS_PATH = PROJECT_DIR / "config" / "stage1_orientation_keywords.json"
_ORIENT_KW_CACHE: Any = _LAZY_UNSET
_ORIENT_KW_ERROR: Optional[str] = None


def _normalize_orientation_text(text: str) -> str:
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^A-Z0-9\s]', ' ', text.upper())


def get_orientation_keywords() -> List[str]:
    """Nap (lazy, cache) danh sach tu khoa. Tra [] neu thieu/loi -> lexical guard TAT."""
    global _ORIENT_KW_CACHE, _ORIENT_KW_ERROR
    if _ORIENT_KW_CACHE is not _LAZY_UNSET:
        return _ORIENT_KW_CACHE
    kws: List[str] = []
    err: Optional[str] = None
    try:
        data = json.loads(Path(ORIENTATION_KEYWORDS_PATH).read_text(encoding="utf8"))
        raw = data.get("keywords") if isinstance(data, dict) else None
        if not isinstance(raw, list) or not all(isinstance(k, str) for k in raw):
            err = "khóa 'keywords' thiếu hoặc không phải list[str]"
        else:
            # Chuan hoa giong van ban OCR (bo dau, upper); tu khoa ASCII hoa giu nguyen.
            kws = [k for k in (_normalize_orientation_text(x).strip() for x in raw) if k]
            if not kws:
                err = "danh sách 'keywords' rỗng"
    except FileNotFoundError:
        err = "không tìm thấy file"
    except Exception as e:
        err = f"lỗi đọc file: {type(e).__name__}: {e}"
    if err is not None:
        kws = []
        _ORIENT_KW_ERROR = f"{ORIENTATION_KEYWORDS_PATH}: {err}"
        import warnings
        warnings.warn(f"[stage1] OCR Lexical Guard TẮT — {_ORIENT_KW_ERROR}. "
                      "Xoay 0/180 chỉ còn dựa vào OSD + flip_score.", RuntimeWarning, stacklevel=2)
    _ORIENT_KW_CACHE = kws
    return kws


def lexical_guard_status() -> Dict[str, Any]:
    kws = get_orientation_keywords()
    return {"enabled": bool(kws), "n_keywords": len(kws),
            "source": str(ORIENTATION_KEYWORDS_PATH), "error": _ORIENT_KW_ERROR}


def _count_orientation_keywords(crop_bgr: np.ndarray) -> int:
    kws = get_orientation_keywords()
    if not kws:
        return 0      # guard TAT — da canh bao tuong minh trong get_orientation_keywords()
    try:
        import pytesseract
        txt = pytesseract.image_to_string(crop_bgr, lang='vie+eng', config='--psm 6')
        norm = _normalize_orientation_text(txt)
        return sum(1 for kw in kws if kw in norm)
    except Exception:
        return 0


def coarse_orientation(bgr: np.ndarray, cfg: Stage1Config) -> Dict[str, Any]:
    """
    Tra ve so do can xoay THEO CHIEU KIM DONG HO de dua chu ve dung huong (0/90/180/270).

    Chien luoc 3 lop, ket hop OCR Lexical Guard:
      LOP 1 - TRUC CHU (ngang hay doc): hinh chieu net chu. Neu do tin cay thap (< 0.15),
               kiem tra huong tu nhien truoc bang tu khoa de tranh xoay nham bang ngang.
      LOP 2 - TESSERACT OSD: chi tin tuong khi confidence >= 2.0 va script la 'Latin'.
      LOP 3 - LEXICAL GUARD & FLIP HEURISTIC:
               - Neu huong 0 do da chua tu khoa tieng Viet/nghiep vu KIDO hop le -> GIU NGUYEN 0 DO.
               - Neu chi huong 180 do moi doc duoc tu khoa -> LAT 180 DO.
               - Fallback: chi dung flip_score khi ca 2 huong deu khong co tu khoa.
    """
    ax = text_axis(bgr)
    base = 0 if ax["text_horizontal"] else 90

    # Neu do tin cay cua text_axis qua yeu (< 0.15), kiem tra huong tu nhien (0) truoc
    if ax.get("confidence", 0) < 0.15:
        h, w = bgr.shape[:2]
        kw_0 = _count_orientation_keywords(bgr[:int(h * 0.35), :])
        probe_90 = rotate_cw(bgr, 90)
        h90, w90 = probe_90.shape[:2]
        kw_90 = _count_orientation_keywords(probe_90[:int(h90 * 0.35), :])
        if kw_0 >= kw_90 and kw_0 > 0:
            base = 0
        elif kw_90 > kw_0:
            base = 90
        else:
            base = 0

    probe = rotate_cw(bgr, base)

    # 1. Kiem tra Tesseract OSD voi do tin cay cao va script Latin
    osd = _osd(probe) if cfg.use_osd else None
    if osd and osd["deg"] in (0, 180) and osd["confidence"] >= cfg.osd_min_confidence and osd.get("script") == "Latin":
        return {
            "deg": (base + osd["deg"]) % 360,
            "method": "text_axis+osd_flip",
            "confidence": round(min(1.0, osd["confidence"] / 3.0), 3),
            "osd_confidence": osd["confidence"],
            "script": osd.get("script"),
            "axis": ax
        }

    # 2. LEXICAL GUARD: Neu huong hien tai (0 do) da co tu khoa hop le -> GIU NGUYEN 0 DO
    hp, wp = probe.shape[:2]
    kw_top = _count_orientation_keywords(probe[:int(hp * 0.35), :])
    if kw_top > 0:
        return {
            "deg": base % 360,
            "method": "lexical_guard_upright",
            "confidence": 0.95,
            "axis": ax,
            "kw_hits": kw_top,
            "note": "Xac nhan thuan chieu qua tu khoa nghiep vu"
        }

    # 3. Neu 0 do khong co tu khoa, kiem tra huong 180 do
    probe_180 = rotate_cw(probe, 180)
    kw_180 = _count_orientation_keywords(probe_180[:int(hp * 0.35), :])
    if kw_180 > kw_top:
        return {
            "deg": (base + 180) % 360,
            "method": "lexical_guard_flip180",
            "confidence": 0.90,
            "axis": ax,
            "kw_hits_180": kw_180,
            "note": "Phat hien nguoc chieu qua tu khoa nghiep vu"
        }

    # 4. Fallback ve flip_score chi khi khong tim thay tu khoa o ca 2 huong
    fs = flip_score(probe)
    flip = fs["score"] < -0.40  # Nguong chat che hon (truoc day la -0.15)
    deg = (base + (180 if flip else 0)) % 360
    return {
        "deg": deg,
        "method": "text_axis+flip_heuristic",
        "confidence": 0.45,
        "axis": ax,
        "flip": fs,
        "osd_raw": osd,
        "note": "Khong co ket qua OSD hoac tu khoa du tin cay - huong 180 do chi o muc tin cay trung binh"
    }


def fine_skew_angle(bgr: np.ndarray, cfg: Stage1Config,
                    max_deg: Optional[float] = None) -> Dict[str, Any]:
    """Chung tu KIDO co nhieu duong ke bang -> Hough tren duong ngang rat on dinh."""
    lim = cfg.max_fine_skew_deg if max_deg is None else max_deg
    gray = cv2.cvtColor(resize_long_edge(bgr, 1400), cv2.COLOR_BGR2GRAY)
    H, W = gray.shape[:2]
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 1440, threshold=int(0.12 * W),
                            minLineLength=int(0.25 * W), maxLineGap=int(0.02 * W))
    angs = []
    if lines is not None:
        for x1, y1, x2, y2 in lines[:, 0]:
            a = math.degrees(math.atan2(y2 - y1, x2 - x1))
            if abs(a) <= lim:
                angs.append(a)
            elif abs(abs(a) - 90) <= lim:
                angs.append(a - 90 if a > 0 else a + 90)
    if len(angs) < 4:
        # fallback: minAreaRect tren khoi chu
        th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3)))
        pts = cv2.findNonZero(th)
        if pts is None:
            return {"deg": 0.0, "method": "none", "n_lines": 0}
        a = cv2.minAreaRect(pts)[-1]
        a = a - 90 if a > 45 else a
        a = max(-lim, min(lim, a))
        return {"deg": round(float(a), 3), "method": "min_area_rect", "n_lines": 0}

    angs = np.array(angs, np.float32)
    # SUA 3 - hai chot an toan: THA KHONG XOAY CON HON XOAY SAI.
    # Anh lech 1 do thi OCR van doc duoc; anh bi xoay nham 7 do thi hong han.
    if len(angs) < 6:
        return {"deg": 0.0, "method": "skipped_few_lines", "n_lines": int(len(angs))}
    med = float(np.median(angs))
    keep = angs[np.abs(angs - med) < 2.0]
    if len(keep) < 3 or float(np.std(keep)) > 3.0:
        return {"deg": 0.0, "method": "skipped_inconsistent", "n_lines": int(len(angs))}
    ang = float(np.clip(np.median(keep), -lim, lim))
    return {"deg": round(ang, 3), "method": "hough_lines", "n_lines": int(len(angs)),
            "limit_deg": lim}


def rotate_fine(bgr: np.ndarray, deg: float) -> np.ndarray:
    if abs(deg) < 0.15:
        return bgr
    h, w = bgr.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), deg, 1.0)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    M[0, 2] += nw / 2.0 - w / 2.0
    M[1, 2] += nh / 2.0 - h / 2.0
    return cv2.warpAffine(bgr, M, (nw, nh), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)

def flatten_illumination(bgr: np.ndarray, strength: float = 1.0) -> np.ndarray:
    """
    Lam phang anh sang TREN KENH V cua HSV, giu nguyen H va S.
    => bong do, den vang bi trung hoa nhung mau moc do / muc xanh khong doi.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    V = hsv[:, :, 2]
    bg = background_illumination(V)
    target = float(np.percentile(bg, 90))
    flat = V / np.maximum(bg, 1.0) * target
    out = V * (1 - strength) + flat * strength
    hsv[:, :, 2] = np.clip(out, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def white_balance_on_paper(bgr: np.ndarray) -> np.ndarray:
    """Can bang trang dua tren pixel nen giay (sang nhat), khong dung gray-world
    de tranh lam nhat moc do tren chung tu nhieu muc do."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    thr = np.percentile(gray, 85)
    mask = gray >= thr
    if mask.sum() < 500:
        return bgr
    means = [float(bgr[:, :, c][mask].mean()) for c in range(3)]
    target = float(np.mean(means))
    out = bgr.astype(np.float32)
    for c in range(3):
        gain = target / max(means[c], 1.0)
        gain = float(np.clip(gain, 0.75, 1.35))   # chan gain de khong doi mau muc
        out[:, :, c] *= gain
    return np.clip(out, 0, 255).astype(np.uint8)


def stretch_paper_contrast(bgr: np.ndarray, white_pct: float = 97.0, black_pct: float = 2.0) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    V = hsv[:, :, 2]
    lo, hi = np.percentile(V, black_pct), np.percentile(V, white_pct)
    if hi - lo < 20:
        return bgr
    V = np.clip((V - lo) * (245.0 / (hi - lo)) + 5.0, 0, 255)
    hsv[:, :, 2] = V
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def trim_white_border(bgr: np.ndarray, pad_frac: float = 0.012) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Cat vien trang thua (chu yeu cho anh scan)."""
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(resize_long_edge(bgr, 1000), cv2.COLOR_BGR2GRAY)
    sh, sw = gray.shape[:2]
    th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    pts = cv2.findNonZero(th)
    if pts is None:
        return bgr, {"applied": False}
    x, y, bw, bh = cv2.boundingRect(pts)
    if bw * bh < 0.25 * sw * sh:
        return bgr, {"applied": False, "reason": "vùng nội dung quá nhỏ, bỏ qua để an toàn"}
    sx, sy = w / float(sw), h / float(sh)
    pad = int(round(pad_frac * max(w, h)))
    x0 = max(0, int(x * sx) - pad); y0 = max(0, int(y * sy) - pad)
    x1 = min(w, int((x + bw) * sx) + pad); y1 = min(h, int((y + bh) * sy) + pad)
    if (x1 - x0) < 0.4 * w or (y1 - y0) < 0.4 * h:
        return bgr, {"applied": False, "reason": "cắt quá nhiều, bỏ qua"}
    return bgr[y0:y1, x0:x1], {"applied": True, "crop_box": [x0, y0, x1, y1],
                               "removed_pct": round(100.0 * (1 - ((x1 - x0) * (y1 - y0)) / (w * h)), 2)}


def ink_stats(bgr: np.ndarray) -> Dict[str, Any]:
    """Do luong muc xanh / moc do con lai sau chuan hoa - de kiem chung khong lam mat chu ky."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0].astype(np.int16), hsv[:, :, 1], hsv[:, :, 2]
    red = (((H <= 12) | (H >= 168)) & (S >= 60) & (V >= 50))
    blue = ((H >= 95) & (H <= 135) & (S >= 55) & (V >= 40))
    return {"red_pixel_pct": round(float(red.mean() * 100), 4),
            "blue_pixel_pct": round(float(blue.mean() * 100), 4)}


def normalize_appearance(bgr: np.ndarray, source_type: str, cfg: Stage1Config) -> Tuple[np.ndarray, Dict[str, Any]]:
    steps = []
    out = bgr
    if source_type == "photo":
        out = flatten_illumination(out, strength=1.0); steps.append("flatten_illumination(V)")
        out = white_balance_on_paper(out); steps.append("white_balance_on_paper")
    else:
        out = flatten_illumination(out, strength=0.6); steps.append("flatten_illumination(V, 0.6)")
    out = stretch_paper_contrast(out); steps.append("stretch_paper_contrast")
    out = cv2.fastNlMeansDenoisingColored(out, None, 3, 3, 7, 21) if source_type == "photo" else out
    if source_type == "photo":
        steps.append("denoise_light")
    out = resize_long_edge(out, cfg.target_long_edge); steps.append(f"resize_long_edge({cfg.target_long_edge})")
    return out, {"steps": steps}

def _merge_status(*statuses: str) -> str:
    if RETAKE in statuses:
        return RETAKE
    if WARN in statuses:
        return WARN
    return PASS


# ---------------------------------------------------------------------------
# CONTRACT JSON TRANG: moi trang (DAT / CANH_BAO / CHUP_LAI, ke ca khong doc duoc anh)
# co CUNG MOT TAP KHOA. Buoc nao khong chay (trang bi tu choi som) -> gia tri null TUONG MINH,
# ten buoc nam trong `skipped_steps`, ly do nam trong `skipped_reason` (= rejects).
# Truoc day trang bi tu choi som thieu perspective/rotation/trim_border/normalize/ink_check/
# quality_output, va output chi co {"image": None} (thieu width/height).
# ---------------------------------------------------------------------------
PAGE_KEYS: Tuple[str, ...] = (
    "stage1_version", "source_file", "file_name", "batch_id", "page_index",
    "status", "rejects", "warns",
    "paper_mask", "quad", "ink_outside_quad", "quality_input",
    "source_type", "source_type_confidence", "source_type_score", "source_type_reasons",
    "source_type_evidence", "exif_summary", "frame_has_background", "ring_test",
    "border_contact", "gate_four_corners",
    "perspective", "lexical_guard", "rotation", "trim_border", "normalize", "ink_check",
    "quality_output", "low_resolution",
    "output", "skipped_steps", "skipped_reason", "action", "elapsed_ms",
)
_PAGE_META_KEYS = {"stage1_version", "source_file", "file_name", "batch_id", "page_index",
                   "status", "rejects", "warns", "output", "skipped_steps", "skipped_reason",
                   "action", "elapsed_ms", "low_resolution", "lexical_guard"}


def _finalize_page_schema(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Dien null tuong minh cho moi khoa con thieu va sap theo PAGE_KEYS. KHONG doi status/action."""
    skipped = [k for k in PAGE_KEYS if k not in _PAGE_META_KEYS and k not in rec]
    for k in skipped:
        rec[k] = None
    rec.setdefault("low_resolution", False)
    rec.setdefault("lexical_guard", lexical_guard_status())
    out = rec.get("output") or {}
    rec["output"] = {"image": out.get("image"), "width": out.get("width"), "height": out.get("height")}
    rec["skipped_steps"] = skipped
    rec["skipped_reason"] = (("Tầng 1 dừng trước các bước này: " + " | ".join(rec.get("rejects") or []))
                             if skipped else None)
    extra = [k for k in rec if k not in PAGE_KEYS]          # khoa ngoai contract: giu, dat cuoi
    return {**{k: rec[k] for k in PAGE_KEYS}, **{k: rec[k] for k in extra}}


def process_one(path: str, cfg: Stage1Config, batch_id: str = "", page_index: int = 0,
                save: bool = True) -> Tuple[Dict[str, Any], Optional[np.ndarray]]:
    """Tra ve (metadata_dict, anh_da_chuan_hoa | None)."""
    t0 = time.time()
    rec: Dict[str, Any] = {
        "stage1_version": STAGE1_VERSION,
        "source_file": str(path),
        "file_name": os.path.basename(path),
        "batch_id": batch_id,
        "page_index": page_index,
        "status": PASS,
        "rejects": [],
        "warns": [],
    }

    bgr = imread_unicode(path)
    if bgr is None:
        rec.update({"status": RETAKE, "rejects": ["Không đọc được file ảnh (định dạng không hỗ trợ hoặc file hỏng)"],
                    "action": "YEU_CAU_CHUP_LAI", "elapsed_ms": int((time.time() - t0) * 1000)})
        return _finalize_page_schema(rec), None

    # 1.3 mat na to giay - TINH MOT LAN DUY NHAT roi dung lai cho moi buoc sau
    #     (GrabCut la phan ton thoi gian nhat cua tang 1)
    pmask, pminfo = paper_mask_consensus(resize_long_edge(bgr, 800), inset=0.04)
    rec["paper_mask"] = pminfo
    quad = detect_paper_quad(bgr, cfg, pmask)
    rec["quad"] = quad
    rec["ink_outside_quad"] = (ink_outside_quad(bgr, quad["points"], pmask)
                               if quad.get("found") else {"available": False,
                                                          "reason": "không đo được tứ giác"})

    # 1.1 chat luong tho - CHI DO TRONG VUNG TO GIAY, khong tinh nen ban/san
    q = measure_quality(bgr, roi_mask=pmask, min_roi_area=cfg.min_area_ratio_reject)
    rec["quality_input"] = q
    rj, wn = quality_flags(q, cfg)

    # 1.2 scan hay chup
    exif = read_exif(path)
    src = detect_source_type(bgr, exif, quad, cfg, pmask)
    rec["source_type"] = src["type"]
    rec["source_type_confidence"] = src["confidence"]
    rec["source_type_score"] = src["score"]
    rec["source_type_reasons"] = src["top_reasons"]
    rec["source_type_evidence"] = src["evidence"]
    rec["exif_summary"] = {k: str(exif.get(k)) for k in ("Make", "Model", "Software", "DateTime") if k in exif}

    # Quyet dinh XU LY dua tren HINH HOC, khong phu thuoc hoan toan vao nhan scan/photo:
    # neu quanh to giay con mot vanh nen => phai nan phoi canh VA phai kiem tra du 4 goc.
    ring_sep = bool(src.get("ring_test", {}).get("separable"))
    has_border = bool((src["type"] == "photo" or ring_sep)
                      and quad.get("found") and quad.get("area_ratio", 1.0) < 0.90
                      and (quad.get("min_corner_margin_pct") or 0) > 0.5)
    rec["frame_has_background"] = has_border
    rec["ring_test"] = src.get("ring_test")
    apply_corner_rule = (src["type"] == "photo") or ring_sep

    # 1.4 gac cong 4 goc
    contact = (border_contact(bgr, base_mask=pmask) if apply_corner_rule
               else {"available": False, "reason": "tờ giấy trùm kín khung (ảnh scan) — không áp dụng luật đủ 4 góc"})
    rec["border_contact"] = contact
    gate = gate_four_corners(quad, contact, "photo" if apply_corner_rule else "scan", cfg,
                             pminfo=pminfo, ink_out=rec["ink_outside_quad"])
    rj += gate["rejects"]; wn += gate["warns"]
    rec["gate_four_corners"] = gate["status"]

    rec["rejects"] = rj
    rec["warns"] = wn
    rec["status"] = RETAKE if rj else (WARN if wn else PASS)

    if rec["status"] == RETAKE:
        rec["output"] = {"image": None, "width": None, "height": None}
        rec["elapsed_ms"] = int((time.time() - t0) * 1000)
        rec["action"] = "YEU_CAU_CHUP_LAI"
        return _finalize_page_schema(rec), None

    # 1.5 nan phoi canh (chi khi la anh chup va co tu giac tot)
    work = bgr
    if has_border and quad.get("found"):
        work, winfo = warp_to_a4(bgr, quad, cfg)
        rec["perspective"] = winfo
    else:
        rec["perspective"] = {"applied": False, "reason": "tờ giấy trùm kín khung (không có nền để nắn) hoặc không đo được tứ giác"}

    # 1.6 xoay tho + khu nghieng tinh
    co = coarse_orientation(work, cfg)
    # Lexical guard bi TAT (thieu/loi config tu khoa) -> ghi TUONG MINH vao JSON trang.
    # Nay ghi CA KHI guard bat (enabled=True) de moi trang co cung tap khoa.
    rec["lexical_guard"] = lexical_guard_status()   # luon ghi (bat hay tat), xem PAGE_KEYS
    work = rotate_cw(work, co["deg"])
    # SUA 3: da nan phoi canh thi anh von da thang -> khong cho xoay them qua 2 do
    fs = fine_skew_angle(work, cfg,
                         max_deg=2.0 if rec["perspective"].get("applied") else None)
    work = rotate_fine(work, fs["deg"])
    rec["rotation"] = {"coarse_deg": co["deg"], "coarse_method": co["method"],
                       "coarse_confidence": co.get("confidence"),
                       "osd_confidence": co.get("osd_confidence"),
                       "fine_skew_deg": fs["deg"], "fine_method": fs["method"],
                       # Huong 0 vs 180 la phan kho nhat: quy tac thuan tuy khong the chac 100%.
                       # Tang 2 (OCR) se xac nhan lai: neu doc ra rac thi lat 180 va doc lai.
                       "needs_verification_180": bool(co.get("confidence", 0) < 0.5)}

    # cat vien trang cho anh scan
    if src["type"] == "scan":
        work, tinfo = trim_white_border(work)
        rec["trim_border"] = tinfo
    else:
        rec["trim_border"] = {"applied": False}

    # 1.7 chuan hoa mau/sang
    before_ink = ink_stats(resize_long_edge(work, 900))
    work, ninfo = normalize_appearance(work, src["type"], cfg)
    after_ink = ink_stats(resize_long_edge(work, 900))
    rec["normalize"] = ninfo
    rec["ink_check"] = {"before": before_ink, "after": after_ink}
    # Kiem tra CA HAI CHIEU. Ban truoc chi bat chieu GIAM nen bo lot ca anh scan bi
    # xoay/bien dang lam pixel xanh TANG 36 lan (0.199 -> 7.135) ma van xep "GIU DUOC".
    for mau, key in (("đỏ", "red_pixel_pct"), ("xanh", "blue_pixel_pct")):
        b, a = before_ink[key], after_ink[key]
        if b > 0.05 and a < 0.35 * b:
            rec["warns"].append(f"Chuẩn hoá làm giảm mạnh pixel màu {mau} "
                                f"({b:.3f}% → {a:.3f}%) — kiểm tra lại mộc/chữ ký")
            rec["status"] = _merge_status(rec["status"], WARN)
        elif b > 0.02 and a > 8.0 * b and a > 1.0:
            rec["warns"].append(f"Pixel màu {mau} TĂNG bất thường ({b:.3f}% → {a:.3f}%) — "
                                "dấu hiệu ảnh bị biến dạng hoặc lệch màu nặng")
            rec["status"] = _merge_status(rec["status"], WARN)

    # do do phan giai cuoi
    qh, qw = work.shape[:2]
    # SUA 4 - DPI HIEU DUNG: do tren vung giay trong ANH GOC.
    # Cach cu lay canh dai cua file output (luon resize len 2200px) nen LUON ra ~188 DPI,
    # ke ca khi to giay trong anh goc chi cao 600px. Phong to khong them thong tin.
    src_long = (max(quad.get("warp_w") or 0, quad.get("warp_h") or 0)
                if quad.get("found") else max(bgr.shape[:2]))
    src_long = max(src_long, 1)
    effective_dpi = round(src_long / 11.69, 1)        # kho A4 dai 11.69 inch
    nominal_dpi = round(max(qh, qw) / 11.69, 1)
    rec["quality_output"] = {
        "width": int(qw), "height": int(qh),
        "effective_dpi": effective_dpi,               # <- con so THAT
        "nominal_dpi_a4": nominal_dpi,                # <- chi de doi chieu
        "paper_long_edge_src_px": int(src_long),
        "upscaled": bool(cfg.target_long_edge > src_long),
        "laplacian_var": round(float(cv2.Laplacian(cv2.cvtColor(resize_long_edge(work, 1000), cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()), 2)}
    if effective_dpi < cfg.dpi_reject:
        # DO PHAN GIAI THAP LA RUI RO, KHONG PHAI "KHONG DUNG DUOC".
        # Truoc day DPI thap MOT MINH da du de gan CHUP_LAI. Thuc nghiem cho thay dieu do sai:
        # 8 trang bi loai chi vi DPI (27-40) van duoc Tang 2 phan loai DUNG doc_type va van boc
        # tach duoc shipment_id / po_no / invoice_no. Te hon, loai mot trang con LAM GAY CA BO
        # HO SO DA TRANG cua trang con lai von hoan toan tot (Load_3.2, PO_3.1 -> multi-page
        # Recall tut 100% xuong 71%).
        # Vi vay: chi TU CHOI khi DPI thap DI KEM mot loi chat luong khac (mo, loa, mat net chu,
        # thieu goc...). Neu moi tieu chi khac deu dat thi ha xuong CANH_BAO kem co
        # `low_resolution` de nguoi kiem tra biet, va van cho trang di tiep xuong Tang 2.
        has_other_reject = len(rec["rejects"]) > 0
        msg = (f"Độ phân giải thực chỉ ~{effective_dpi:.0f} DPI — "
               "tờ giấy quá nhỏ trong khung, lại gần hơn và chụp lại")
        if has_other_reject:
            rec["rejects"].append(msg)
            rec["status"] = RETAKE
        else:
            rec["warns"].append(msg + " (vẫn chuyển tiếp: các tiêu chí chất lượng khác đều đạt)")
            rec["low_resolution"] = True
            rec["status"] = _merge_status(rec["status"], WARN)
    elif effective_dpi < cfg.dpi_warn:
        rec["warns"].append(f"Độ phân giải thực ~{effective_dpi:.0f} DPI — OCR chữ nhỏ "
                            "(số hoá đơn, mã SP) dễ sai")
        rec["status"] = _merge_status(rec["status"], WARN)

    if save:
        stem = Path(path).stem
        sub = batch_id or "_no_batch"
        name = stem if re.match(r"^\d{2}[_-]", stem) else f"{page_index:02d}_{stem}"
        out_path = os.path.join(cfg.output_dir, "images", sub, f"{name}.jpg")
        imwrite_unicode(out_path, work, cfg.jpeg_quality)
        rec["output"] = {"image": out_path, "width": int(qw), "height": int(qh)}
    else:
        rec["output"] = {"image": None, "width": int(qw), "height": int(qh)}

    rec["action"] = "CHUYEN_TANG_2" if rec["status"] in (PASS, WARN) else "YEU_CAU_CHUP_LAI"
    rec["elapsed_ms"] = int((time.time() - t0) * 1000)
    return _finalize_page_schema(rec), work

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def collect_batches(input_dir: str, cfg: Stage1Config) -> Dict[str, List[str]]:
    files = [str(p) for p in Path(input_dir).rglob("*") if p.suffix.lower() in IMG_EXT]
    files.sort(key=natural_key)
    batches: Dict[str, List[str]] = {}
    for f in files:
        if cfg.batch_mode == "folder":
            bid = Path(f).parent.name
        elif cfg.batch_mode == "prefix":
            name = Path(f).stem
            bid = name.split(cfg.prefix_sep)[0] if cfg.prefix_sep in name else name
        else:
            bid = "batch_001"
        batches.setdefault(bid, []).append(f)
    for k in batches:
        batches[k].sort(key=natural_key)
    return batches


def process_batches(input_dir: str, cfg: Stage1Config, limit_per_batch: Optional[int] = None,
                    verbose: bool = True) -> Dict[str, Any]:
    # Chạy Tầng 1 cho toàn bộ thư mục, xuất ảnh + JSON + manifest theo lô
    batches = collect_batches(input_dir, cfg)
    all_batches, n_pages = [], 0
    t_all = time.time()

    for bid, files in batches.items():
        if limit_per_batch:
            files = files[:limit_per_batch]
        pages, statuses = [], []
        for i, f in enumerate(files):
            rec, _img = process_one(f, cfg, batch_id=bid, page_index=i, save=True)
            pages.append(rec)
            statuses.append(rec["status"])
            n_pages += 1
            jp = Path(cfg.output_dir) / "pages" / bid / f"{i:02d}_{Path(f).stem}.json"
            jp.parent.mkdir(parents=True, exist_ok=True)
            jp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf8")

        batch_status = _merge_status(*statuses) if statuses else RETAKE
        manifest = {
            "batch_id": bid,
            "stage1_version": STAGE1_VERSION,
            "n_pages": len(pages),
            "status": batch_status,
            "action": "CHUYEN_TANG_2" if batch_status in (PASS, WARN) else "YEU_CAU_CHUP_LAI",
            "pages_need_retake": [p["file_name"] for p in pages if p["status"] == RETAKE],
            "pages": [{"page_index": p["page_index"], "file_name": p["file_name"],
                       "status": p["status"], "source_type": p["source_type"],
                       "output": (p.get("output") or {}).get("image"),
                       "rejects": p["rejects"], "warns": p["warns"]} for p in pages],
        }
        mp = Path(cfg.output_dir) / "manifests" / f"{bid}.json"
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf8")
        all_batches.append(manifest)
        if verbose:
            icon = {"DAT": "[OK]", "CANH_BAO": "[!]", "CHUP_LAI": "[X]"}[batch_status]
            print(f"{icon} lô {bid}: {len(pages)} trang -> {batch_status}")

    summary = {
        "stage1_version": STAGE1_VERSION,
        "input_dir": input_dir,
        "n_batches": len(all_batches),
        "n_pages": n_pages,
        "elapsed_sec": round(time.time() - t_all, 1),
        "by_status": dict(Counter(b["status"] for b in all_batches)),
        "batches": all_batches,
    }
    Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)
    (Path(cfg.output_dir) / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf8")
    return summary

_rng = np.random.default_rng(7)


def _bg_texture(h, w, kind):
    if kind == "wood":
        base = np.zeros((h, w, 3), np.uint8); base[:] = (60, 95, 140)
        for _ in range(60):
            y = _rng.integers(0, h)
            cv2.line(base, (0, int(y)), (w, int(y + _rng.integers(-20, 20))),
                     tuple(int(c) for c in (_rng.integers(40, 80), _rng.integers(75, 115),
                                            _rng.integers(120, 165))), int(_rng.integers(2, 9)))
        return cv2.GaussianBlur(base, (0, 0), 3)
    if kind == "dark_desk":
        base = np.full((h, w, 3), (48, 46, 44), np.uint8)
        return np.clip(base + _rng.normal(0, 9, (h, w, 3)), 0, 255).astype(np.uint8)
    base = np.full((h, w, 3), 150, np.uint8)                      # sàn gạch
    step = max(40, h // 6)
    for y in range(0, h, step):
        cv2.line(base, (0, y), (w, y), (120, 122, 125), 3)
    for x in range(0, w, step):
        cv2.line(base, (x, 0), (x, h), (120, 122, 125), 3)
    return cv2.GaussianBlur(base, (0, 0), 2)


def _vignette_and_light(img, strength=0.18):
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w * _rng.uniform(0.3, 0.7), h * _rng.uniform(0.3, 0.7)
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2); d /= d.max()
    m = 1.0 - strength * d ** 1.6
    sx, sy = w * _rng.uniform(0.1, 0.9), h * _rng.uniform(0.1, 0.9)
    ds = np.sqrt((xx - sx) ** 2 + (yy - sy) ** 2) / (0.45 * max(h, w))
    m = m * (1.0 + 0.16 * np.exp(-ds ** 2))
    return np.clip(img.astype(np.float32) * m[:, :, None], 0, 255).astype(np.uint8)


def synth_photo(scan_bgr, out_size=(1663, 2218), mode="ok", bg="wood", seed=0):
    global _rng
    _rng = np.random.default_rng(seed)
    W, H = out_size
    canvas = _bg_texture(H, W, bg)
    doc = scan_bgr.copy(); dh, dw = doc.shape[:2]

    occ = (_rng.uniform(0.20, 0.28) if mode == "far"
           else _rng.uniform(0.72, 0.80) if mode == "missing_corner"
           else _rng.uniform(0.48, 0.62))
    th_ = int(math.sqrt(occ * W * H * (dh / dw))); tw_ = int(th_ * dw / dh)
    tw_, th_ = min(tw_, int(W * 0.96)), min(th_, int(H * 0.96))
    doc = cv2.resize(doc, (tw_, th_), interpolation=cv2.INTER_AREA)
    doc = np.clip(doc.astype(np.float32) * 0.86, 0, 255).astype(np.uint8)  # giấy dưới đèn phòng ~215

    x0 = (W - tw_) // 2 + int(_rng.integers(-W // 40, W // 40))
    y0 = (H - th_) // 2 + int(_rng.integers(-H // 40, H // 40))
    src = np.float32([[0, 0], [tw_, 0], [tw_, th_], [0, th_]])
    j = 0.09 if mode == "tilted" else 0.02
    dst = np.float32([[x0 + _rng.normal(0, tw_ * j), y0 + _rng.normal(0, th_ * j)],
                      [x0 + tw_ + _rng.normal(0, tw_ * j), y0 + _rng.normal(0, th_ * j)],
                      [x0 + tw_ + _rng.normal(0, tw_ * j), y0 + th_ + _rng.normal(0, th_ * j)],
                      [x0 + _rng.normal(0, tw_ * j), y0 + th_ + _rng.normal(0, th_ * j)]])
    if mode == "missing_corner":
        dst[1] += [W * 0.22, -H * 0.14]; dst[2] += [W * 0.22, H * 0.16]; dst[3] += [0, H * 0.16]

    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(doc, M, (W, H), borderValue=(0, 0, 0))
    mask = cv2.warpPerspective(np.full((th_, tw_), 255, np.uint8), M, (W, H))
    sh = cv2.GaussianBlur(mask, (0, 0), 25).astype(np.float32) / 255.0
    canvas = np.clip(canvas.astype(np.float32) * (1 - 0.35 * sh[:, :, None]), 0, 255).astype(np.uint8)
    out = np.where(mask[:, :, None] > 0, warped, canvas)
    out = _vignette_and_light(out)

    if mode == "glare":
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        d = np.sqrt((xx - W * 0.55) ** 2 + (yy - H * 0.35) ** 2) / (0.16 * max(H, W))
        out = np.clip(out.astype(np.float32) + (np.exp(-d ** 2) * 140)[:, :, None], 0, 255).astype(np.uint8)
    if mode == "blurry":
        out = cv2.GaussianBlur(out, (0, 0), 5.5)
    out = np.clip(out.astype(np.float32) + _rng.normal(0, 4.0, out.shape), 0, 255).astype(np.uint8)
    if mode == "rot90":
        out = cv2.rotate(out, cv2.ROTATE_90_CLOCKWISE)
    elif mode == "rot180":
        out = cv2.rotate(out, cv2.ROTATE_180)
    return out


def run_demo():
    SYNTH_DIR = WORK_DIR / "demo_input" / "LO_MO_PHONG_001"
    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    samples = sorted(MEDIA_DIR.glob("*.png")) if MEDIA_DIR.exists() else []
    MODES = [("ok", "wood"), ("tilted", "dark_desk"), ("missing_corner", "wood"), ("far", "tile"),
             ("rot90", "dark_desk"), ("rot180", "wood"), ("glare", "wood"), ("blurry", "dark_desk")]

    if samples:
        for i, (mode, bg) in enumerate(MODES):
            img = imread_unicode(str(samples[(i * 7) % len(samples)]))
            if img is None:
                continue
            o = synth_photo(img, (1663, 2218), mode=mode, bg=bg, seed=i + 1)
            imwrite_unicode(str(SYNTH_DIR / f"{i:02d}_{mode}.jpg"), o, 88)
        print("Đã sinh", len(list(SYNTH_DIR.glob('*.jpg'))), "ảnh chụp mô phỏng ->", SYNTH_DIR)

    SCAN_DIR = WORK_DIR / "demo_input" / "LO_SCAN_MAU"
    SCAN_DIR.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(sorted(MEDIA_DIR.glob("*.png"))[:8] if MEDIA_DIR.exists() else []):
        shutil.copy(p, SCAN_DIR / f"{i:02d}_{p.name}")

    RUN_DIR = str(WORK_DIR / "demo_input")
    summary = process_batches(RUN_DIR, CFG)
    print(f"\n{summary['n_batches']} lô / {summary['n_pages']} trang trong {summary['elapsed_sec']}s")

if __name__ == "__main__":
    run_demo()


