# -*- coding: utf-8 -*-
"""
TANG 3B - ZONE RESOLVER (vung ky dong theo bieu mau)
====================================================
Module loi Tang 3b: sinh bounding box vung ky/vung moc MOT CACH DONG tu cau truc
trang (vach ke bang, kenh phan phoi), thay cho preset tinh cua Tang 3.

Nguon goc: hai ham duoi day truoc day nam trong `tools/kido_pipeline.py`
(`detect_loading_plan_signature_zone` tai dong 63, `detect_invoice_signature_zone`
tai dong 177). Viec tach ra day la tra no kien truc da ghi trong AGENTS.md muc 6
va 11.2 - `kido_pipeline.py` tro ve dung vai orchestrator E2E.

QUAN TRONG (buoc 1/2 - refactor thuan): logic, nguong va hang so hinh hoc duoc
CHEP NGUYEN TRANG, khong sua mot dong nao. Thay doi duy nhat la doan do vach ke
ngang (truoc day bi chep 2 lan, trung ~80%) nay duoc gop thanh helper dung chung
`detect_table_lines()`. Hai ban chep khac nhau o DUNG 2 tham so, va ca hai gia tri
deu duoc giu nguyen bang cach truyen vao helper:

    | Tham so                | LOADING_PLAN | HOA_DON |
    |------------------------|--------------|---------|
    | nguong do dai vach     | w * 0.25     | w * 0.20|
    | dai y xet vach         | 0.05 .. 0.88 | 0.35 .. 0.92 |

Phan con lai (adaptiveThreshold 15/-2, kernel ngang max(20, w*0.10), MORPH_OPEN,
gom cum <= 6px lay median) GIONG HET NHAU giua hai ban.

GIAI DOAN 2 (27/09) - bat bien do phan giai, CHI cho LOADING_PLAN:
  * `detect_loading_plan_signature_zone` (va 2 helper cong khai
    `detect_signature_columns`, `close_ink_group_bottom`) tu dua anh ve
    H=WORK_HEIGHT=2200 truoc moi phep do pixel. Anh H=2200 -> no-op.
  * Phong to dai nhan OCR theo pixel dich (LABEL_OCR_PAGE_HEIGHT), khong he so co dinh.
  * Tam nhan = tam CUM nhan tren dong OCR (PHRASE_GAP_EM), khong phai tam cum tu khop.
  * DEFAULT_SINGLE_PAGE (anchor_y=0.550 doan mo) -> ABSTAIN `TABLE_ANCHOR_NOT_FOUND`.
  * adaptiveThreshold toan trang tinh 1 lan/trang thay vi 1 + 5 lan.
  `detect_invoice_signature_zone` (HOA_DON, dang hoan) KHONG duoc chuan hoa - van
  phu thuoc do phan giai dau vao.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    import pytesseract
    from rapidfuzz import fuzz
    _OCR_IMPORT_ERROR: Optional[str] = None
except Exception as _e:  # pragma: no cover - moi truong thieu thu vien
    pytesseract = None  # type: ignore
    fuzz = None  # type: ignore
    _OCR_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"

if pytesseract is not None:
    for _p in (
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path.home() / r"AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
    ):
        if _p.exists():
            pytesseract.pytesseract.tesseract_cmd = str(_p)
            break

__all__ = [
    "detect_table_lines",
    "load_loading_plan_labels",
    "detect_signature_columns",
    "close_ink_group_bottom",
    "detect_loading_plan_signature_zone",
    "detect_invoice_signature_zone",
    "detect_channel_aware_invoice_zone",
]

# ---------------------------------------------------------------------------
# HANG SO HINH HOC - moi gia tri deu co nguon goc vat ly, KHONG do theo benchmark.
# Bang doi chieu day du: docs/STAGE3B_COLUMN_FIX_PLAN.md muc 6.
# ---------------------------------------------------------------------------
# Dai nhan in san (2 dong: chuc danh + "(Ky va ghi ro ho ten)") ngay duoi day
# bang, do duoc chiem 0.03-0.06 chieu cao trang -> lay 0.10 cho du gap doi.
LABEL_BAND_HEIGHT = 0.10
# [GIAI DOAN 2 - 27/09] CHIEU CAO LAM VIEC CHUAN.
# Moi phep do pixel cua resolver LOADING_PLAN (adaptiveThreshold block 15px,
# kernel ngang, gom cum vach <= 6px, khe muc INK_GROUP_MERGE_GAP, phong to dai
# nhan cho OCR) deu co kich thuoc TUYET DOI. Chay cung mot trang o 850px va 2200px
# cho 14/14 hop khac nhau va ABSTAIN dao chieu (scratch/_audit3b/probe2200.txt).
# Cach sua don gian nhat, de kiem chung nhat: resolver tu dua anh ve H co dinh
# truoc MOI phep do, box_norm tra ve van la toa do chuan hoa nen khong doi hop dong.
# Chon 2200 KHONG theo diem so ma theo contract: Tang 1 `target_long_edge=2200`
# va runner ver2 / E2E deu dua anh A4 H=2200 vao day -> voi dau vao production
# buoc nay la NO-OP (anh H=2200 di qua nguyen ven, ket qua giong het ban cu).
# Noi suy theo quy uoc Tang 1 (`stage1_normalizer.resize_long_edge`): thu nho
# INTER_AREA, phong to INTER_CUBIC.
WORK_HEIGHT = 2200
# Phong to dai nhan truoc khi OCR theo PIXEL DICH, khong theo he so co dinh:
# dai nhan duoc phong sao cho tuong duong trang cao LABEL_OCR_PAGE_HEIGHT px
# (4400px / 11.69in ~ 376 DPI, tren muc ~300 DPI Tesseract khuyen nghi).
# Vi co dinh theo chieu cao trang, co chu nhan (ti le voi trang) cung co dinh
# o pixel dich, bat ke anh vao lon hay nho.
# O WORK_HEIGHT=2200 he so = 2.0, dung bang gia tri cu LABEL_BAND_UPSCALE=2 ->
# khong doi hanh vi tren dau vao production.
LABEL_OCR_PAGE_HEIGHT = 4400
# Khe ngang toi da (don vi em = chieu cao hop tu trung vi cua dong OCR) giua hai
# tu con coi la cung mot cum nhan. Xem ghi chu trong detect_signature_columns.
PHRASE_GAP_EM = 1.0
# [T3B-FIX 27/09] Thu tu cau hinh bo cuc Tesseract cho dai nhan. PSM 6 (mot khoi van
# ban dong nhat) giu la lan doc DAU - dung nhu ban cu. Chi khi PSM 6 khong du nhan moi
# doc tiep: 4 (mot cot van ban, tach theo dong), 11 (van ban thua, KHONG phan tich bo
# cuc - khong bi cum muc ky lam vo dong), 3 (tu dong). Day la danh sach che do, khong
# phai nguong so; thu tu tu co cau truc nhat den it rang buoc bo cuc nhat.
LABEL_OCR_PSM_SEQUENCE = (6, 4, 11, 3)
# Nguong tin cay toi thieu cua Tesseract, chi de bo hop rong/nhieu.
LABEL_MIN_CONF = 10
# Can >= 2 diem de khop duong thang; lay 3 de con 1 bac tu do kiem tra.
# Leave-one-out (n=56) cho thay voi 2 nhan sai so voi len 0.093.
MIN_LABELS_REQUIRED = 3
# 5 cot chia deu mot trang -> buoc danh nghia 1/5 = 0.20, bien +-25%.
COLUMN_PITCH_RANGE = (0.10, 0.25)
# Khe trang toi da con coi la cung mot cum muc: 0.008*H ~ 18px o anh A4 2200px,
# nho hon khoang cach giua hai dong chu in (do duoc >= 0.03*H).
INK_GROUP_MERGE_GAP = 0.008
# Mot dong duoc coi la "co muc" trong dai x cua cot khi so pixel muc vuot
# 2% be rong cot (san nhieu muoi tieu), toi thieu 2 pixel.
INK_ROW_MIN_RATIO = 0.02
# [GIAI DOAN 4 - 27/09] Block-Row Closure (xem _close_signature_block).
# Tran an toan: khoi ky chi duoc noi xuong toi da them 50% chieu cao danh nghia
# (box_h=0.18) - vuot muc do tuc la da di vao noi dung khac cua trang (chu thich
# chan trang, so trang), khong con la khoi ky. KHONG chon theo diem so; so lan
# tran nay "can" duoc bao trong scratch/_phase4/geom/REPORT.md.
BLOCK_GROWTH_CAP = 0.5
# Vach doc dai (vien scan, vien trang) KHONG phai muc ky: loai khoi ho so muc truoc
# khi noi ngang cot bien. Dai >= 5% chieu cao trang (~110px o H=2200) - net chu ky
# khong co doan thang dung lien tuc dai nhu vay.
VERT_LINE_MIN_RATIO = 0.05
# Gioi han noi ngang cot bien: giu trong le an toan cua trang (cung bien voi clamp
# bounds [0.01, 0.99] da co).
SIDE_LIMITS = (0.01, 0.99)
SIDE_INK_MIN_PX = 2

_LABELS_PATH = Path(__file__).resolve().parent.parent / "config" / "stage3b_loading_plan_labels.json"
_LABELS_CACHE: Optional[Dict[str, Any]] = None


class LoadingPlanLabelsError(RuntimeError):
    """Khong nap duoc tu dien nhan chuc danh. KHONG co ban du phong trong Python."""


def load_loading_plan_labels(path: Optional[Path] = None) -> Dict[str, Any]:
    """Nap `config/stage3b_loading_plan_labels.json`.

    Khong co file / file hong -> nem `LoadingPlanLabelsError`. CO Y khong nhung
    tu dien du phong vao Python (AGENTS.md muc 9.7).
    """
    global _LABELS_CACHE
    p = Path(path) if path is not None else _LABELS_PATH
    if path is None and _LABELS_CACHE is not None:
        return _LABELS_CACHE
    if not p.exists():
        raise LoadingPlanLabelsError(f"Thieu tu dien nhan chuc danh Tang 3b: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise LoadingPlanLabelsError(f"Tu dien nhan Tang 3b hong ({p}): {type(e).__name__}: {e}") from e
    cols = data.get("columns")
    if not isinstance(cols, list) or len(cols) < 2:
        raise LoadingPlanLabelsError(f"Tu dien nhan Tang 3b thieu khoa 'columns' hop le: {p}")
    for c in cols:
        for k in ("index", "role", "required", "expected_color", "description", "label_patterns"):
            if k not in c:
                raise LoadingPlanLabelsError(f"Cot {c.get('index')} thieu khoa '{k}' trong {p}")
    data["columns"] = sorted(cols, key=lambda c: c["index"])
    if path is None:
        _LABELS_CACHE = data
    return data


def _to_working_height(img: np.ndarray) -> np.ndarray:
    """Dua anh ve chieu cao WORK_HEIGHT, giu ti le. Anh da dung H thi tra nguyen
    (khong copy, khong noi suy) -> dau vao production H=2200 khong bi dong cham."""
    h, w = img.shape[:2]
    if h == WORK_HEIGHT or h < 1 or w < 1:
        return img
    s = WORK_HEIGHT / float(h)
    nw = max(1, int(round(w * s)))
    interp = cv2.INTER_AREA if s < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(img, (nw, WORK_HEIGHT), interpolation=interp)


def _ink_binary(img: np.ndarray) -> np.ndarray:
    """Anh nhi phan muc dung chung (adaptiveThreshold GAUSSIAN_C, block 15, C=-2
    tren anh xam dao nguoc). Block 15px chi co nghia co dinh khi anh o WORK_HEIGHT."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return cv2.adaptiveThreshold(~gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, 15, -2)


def _norm_ascii(s: str) -> str:
    """NFD tach dau + bo dau + uppercase - cung quy uoc voi Tang 2."""
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").upper()


def detect_table_lines(
    a4_img: np.ndarray,
    line_thresh_ratio: float,
    y_min_ratio: float,
    y_max_ratio: float,
    cluster_gap_px: int = 6,
    bw: Optional[np.ndarray] = None,
) -> List[float]:
    """Do cac vach ke ngang cua bang, tra ve toa do y da chuan hoa (0..1).

    Helper dung chung cho `detect_loading_plan_signature_zone` va
    `detect_invoice_signature_zone`. Thuat toan chep nguyen trang tu hai ban cu:
      1. adaptiveThreshold tren anh xam dao nguoc (GAUSSIAN_C, block 15, C=-2)
      2. MORPH_OPEN bang kernel ngang max(20, int(w * 0.10)) x 1
      3. Giu cac dong co so pixel muc >= int(w * line_thresh_ratio) va nam trong
         dai (int(h * y_min_ratio), int(h * y_max_ratio)]
      4. Gom cum cac dong cach nhau <= cluster_gap_px, lay median moi cum

    Luu y do phan giai: block 15px va cluster_gap_px la PIXEL TUYET DOI. Ham nay
    KHONG tu chuan hoa (HOA_DON van goi truc tiep, chua nam trong pham vi giai
    doan 2); `detect_loading_plan_signature_zone` truyen vao anh da o WORK_HEIGHT.
    `bw` (tuy chon): anh nhi phan `_ink_binary(a4_img)` da tinh san, de khong tinh lai.
    """
    h, w = a4_img.shape[:2]
    if bw is None:
        bw = _ink_binary(a4_img)

    k_w = max(20, int(w * 0.10))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_w, 1))
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel)
    row_sum = np.sum(horiz > 0, axis=1)

    line_thresh = int(w * line_thresh_ratio)
    line_y = [
        y for y in np.where(row_sum >= line_thresh)[0]
        if int(h * y_min_ratio) < y <= int(h * y_max_ratio)
    ]

    table_lines = []
    if line_y:
        curr = [line_y[0]]
        for y in line_y[1:]:
            if y - curr[-1] <= cluster_gap_px:
                curr.append(y)
            else:
                table_lines.append(int(np.median(curr)))
                curr = [y]
        table_lines.append(int(np.median(curr)))

    return [y / float(h) for y in table_lines]


def _label_hits_one_pass(up: np.ndarray, psm: int, columns: List[Dict[str, Any]],
                         fuzz_min: float) -> Dict[int, List[float]]:
    """MOT lan OCR dai nhan (da phong to + Otsu) voi `--psm {psm}` -> {cot: [tam nhan
    chuan hoa theo be rong dai]}. Logic khop/gom cum CHEP NGUYEN TRANG tu ban 1 lan OCR
    truoc day (PSM 6) - chi tach ra ham de goi lai voi PSM khac. Loi Tesseract -> nem ra
    cho caller xu ly."""
    data = pytesseract.image_to_data(up, lang="vie", config=f"--psm {int(psm)}",
                                     output_type=pytesseract.Output.DICT)
    band_w = float(up.shape[1])
    all_words = []   # moi tu khong rong - dung de do BE RONG CUM NHAN
    words = []       # tu du tin cay - dung de KHOP mau nhan
    for i in range(len(data["text"])):
        txt = (data["text"][i] or "").strip()
        if not txt:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            continue
        wd = {
            "t": _norm_ascii(txt),
            "x0": data["left"][i],
            "x1": data["left"][i] + data["width"][i],
            "hgt": data["height"][i],
            "ln": (data["block_num"][i], data["par_num"][i], data["line_num"][i]),
        }
        all_words.append(wd)
        if conf > LABEL_MIN_CONF:
            words.append(wd)

    # [GIAI DOAN 2 - 27/09] TAM NHAN = TAM CA CUM NHAN, khong phai tam cum tu khop.
    # Do duoc (scratch/_phase2/diag_hits.py): nhan cot 5 "NGUOI GIAO / THU KHO" dai
    # ~0.13W; khop "NGUOI GIAO" cho tam ~0.81, khop "THU KHO" cho ~0.87, khop ca hai
    # cho median ~0.84. Mau nao OCR doc duoc thay doi theo noi suy/ti le anh -> tam
    # cot 5 nhay 0.80..0.88 giua cac ban resize cua CUNG mot trang, keo theo pitch va
    # moi cot noi suy. Cot 1 "NGUOI LAP PHIEU" bi cung loi (0.139 / 0.168).
    # Sua: gom cac tu tren cung dong OCR thanh CUM, tach cum khi khe ngang > 1 em
    # (em ~ chieu cao hop tu trung vi cua dong). Ly le typo: khoang cach giua hai tu
    # ~0.25-0.35 em; khoang trang giua hai nhan cot >> 1 em. Tam nhan = tam cum chua
    # tu khop. An toan: neu cum chua tu khop cua cot KHAC (hai nhan dinh sat nhau) thi
    # KHONG mo rong, dung lai tam cum tu khop nhu cu.
    phrase_of: Dict[int, int] = {}
    phrase_span: List[Tuple[float, float]] = []
    by_line: Dict[Any, List[Dict[str, Any]]] = {}
    for wd in all_words:
        by_line.setdefault(wd["ln"], []).append(wd)
    for ln_words in by_line.values():
        ln_words.sort(key=lambda x: x["x0"])
        em = float(np.median([x["hgt"] for x in ln_words])) if ln_words else 0.0
        cur = None
        for wd in ln_words:
            if cur is None or wd["x0"] - phrase_span[cur][1] > PHRASE_GAP_EM * em:
                phrase_span.append((wd["x0"], wd["x1"]))
                cur = len(phrase_span) - 1
            else:
                phrase_span[cur] = (phrase_span[cur][0], max(phrase_span[cur][1], wd["x1"]))
            phrase_of[id(wd)] = cur

    raw_hits = []  # (cot, cum, tam cum tu khop)
    for col in columns:
        k = int(col["index"])
        for pat in col["label_patterns"]:
            n = len(pat)
            if n < 1:
                continue
            for i in range(len(words) - n + 1):
                chunk = words[i:i + n]
                if len({x["ln"] for x in chunk}) != 1:
                    continue  # phai cung mot dong OCR
                if min(fuzz.ratio(chunk[j]["t"], pat[j]) for j in range(n)) >= fuzz_min:
                    raw_hits.append((k, phrase_of.get(id(chunk[0])),
                                     (chunk[0]["x0"] + chunk[-1]["x1"]) / 2.0))

    cols_in_phrase: Dict[Any, set] = {}
    for k, ph, _ in raw_hits:
        cols_in_phrase.setdefault(ph, set()).add(k)
    hits: Dict[int, List[float]] = {}
    for k, ph, c_chunk in raw_hits:
        if ph is not None and cols_in_phrase.get(ph) == {k}:
            x0p, x1p = phrase_span[ph]
            c = (x0p + x1p) / 2.0
        else:
            c = c_chunk
        hits.setdefault(k, []).append(c / band_w)

    return hits


def detect_signature_columns(a4_img: np.ndarray, anchor_y: float) -> Dict[str, Any]:
    """Do ranh gioi 5 cot khoi ky tu vi tri NHAN CHUC DANH in san.

    Vi sao khong dung vach ke: khao sat 14 anh cho thay khoi ky LOADING_PLAN la
    vung TRANG KHONG KE (0/14 anh co vach phan cach cot ben trong) va hinh chieu
    muc doc cung khong tach duoc 5 cot (0/14). Xem docs/STAGE3B_COLUMN_FIX_PLAN.md
    muc 1.

    Tra:
      {'ok', 'status', 'centers', 'bounds', 'pitch', 'label_hits', 'sources'}
    `sources[i]` in {'OCR_LABEL', 'INTERPOLATED'}.
    Khi that bai: ok=False, status la mot trong
      COLUMN_OCR_UNAVAILABLE / COLUMN_DETECTION_FAILED /
      COLUMN_ORDER_VIOLATION / COLUMN_PITCH_IMPLAUSIBLE
    va centers/bounds = None. **Khong co fallback ve hang so cu.**
    """
    labels = load_loading_plan_labels()
    columns = labels["columns"]
    n_cols = len(columns)
    fuzz_min = float(labels.get("fuzz_min_score", 75))

    passes: List[int] = []
    fail = lambda st: {  # noqa: E731
        "ok": False, "status": st, "centers": None, "bounds": None,
        "pitch": None, "label_hits": {}, "sources": None,
        "ocr_psm_passes": list(passes),
    }

    if pytesseract is None or fuzz is None:
        return fail("COLUMN_OCR_UNAVAILABLE")

    a4_img = _to_working_height(a4_img)  # no-op khi goi tu resolver (da chuan hoa)
    h, w = a4_img.shape[:2]
    y0 = int(max(0.0, anchor_y) * h)
    y1 = min(h, int((anchor_y + LABEL_BAND_HEIGHT) * h))
    if y1 - y0 < 4 or w < 8:
        return fail("COLUMN_DETECTION_FAILED")

    try:
        band = a4_img[y0:y1, :]
        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY) if band.ndim == 3 else band
        f_up = LABEL_OCR_PAGE_HEIGHT / float(h)  # = 2.0 tai WORK_HEIGHT
        up = cv2.resize(gray, None, fx=f_up, fy=f_up, interpolation=cv2.INTER_CUBIC)
        up = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    except Exception:  # noqa: BLE001
        return fail("COLUMN_OCR_UNAVAILABLE")

    # [T3B-FIX 27/09] OCR NHIEU CAU HINH, CHI KHI PSM 6 KHONG DU NHAN.
    # Do duoc (scratch/_nb/t3bfix/diag1.log, diag2.log): xoa 1 chu ky ben DUOI nhan
    # (dai nhan van sach) lam PSM 6 doc 0-1/5 nhan - phan tich bo cuc cua Tesseract
    # coi dai la mot khoi van ban, muc ky phia duoi lam vo phan dong ("moi chu mot
    # dong"). Cung dai do, PSM 4/11/3 van doc duoc cac nhan o cung toa do (phan lon
    # lech <= 0.003W; cot 1 lech toi ~0.03W khi mot lan doc chi khop "LAP PHIEU" thay
    # vi ca cum - cung hien tuong da co trong PSM 6) -> pixel nhan khong doi, chi buoc
    # phan tich bo cuc la gion.
    # Cach sua: lan luot them cac lan doc voi PSM khac, GOP bang chung vi tri nhan
    # (median moi cot tren moi lan doc), dung o lan dau du MIN_LABELS_REQUIRED nhan.
    # Ket qua gop VAN PHAI qua nguyen cac rang buoc san co (thu tu, pitch, bien) - bang
    # chung mau thuan => ABSTAIN nhu cu, khong doc tiep de "chon" ket qua dep.
    # Khong them nguong moi. PSM 6 du nhan => KHONG chay them lan nao => ket qua va
    # chi phi giong het ban cu (14/14 trang production di nhanh nay).
    hits: Dict[int, List[float]] = {}
    for psm in LABEL_OCR_PSM_SEQUENCE:
        try:
            ph = _label_hits_one_pass(up, psm, columns, fuzz_min)
        except Exception:  # noqa: BLE001 - Tesseract vang mat / sai cau hinh / loi runtime
            if not passes:
                return fail("COLUMN_OCR_UNAVAILABLE")
            break
        passes.append(int(psm))
        for k, v in ph.items():
            hits.setdefault(k, []).extend(v)
        if len(hits) >= MIN_LABELS_REQUIRED:
            break

    measured = {k: float(np.median(v)) for k, v in hits.items()}
    if len(measured) < MIN_LABELS_REQUIRED:
        return fail("COLUMN_DETECTION_FAILED")

    ks = sorted(measured)
    if any(measured[a] >= measured[b] for a, b in zip(ks, ks[1:])):
        return fail("COLUMN_ORDER_VIOLATION")

    # Khop tuyen tinh center(k) = a + b*k tren cac cot do duoc, suy ra cot thieu.
    b, a = np.polyfit(np.array(ks, dtype=float),
                      np.array([measured[k] for k in ks], dtype=float), 1)
    pitch = float(b)
    if not (COLUMN_PITCH_RANGE[0] <= pitch <= COLUMN_PITCH_RANGE[1]):
        return fail("COLUMN_PITCH_IMPLAUSIBLE")

    centers = [measured[k] if k in measured else float(a + pitch * k) for k in range(n_cols)]
    sources = ["OCR_LABEL" if k in measured else "INTERPOLATED" for k in range(n_cols)]
    if any(centers[i] >= centers[i + 1] for i in range(n_cols - 1)):
        return fail("COLUMN_ORDER_VIOLATION")

    bounds = [centers[0] - pitch / 2.0]
    bounds += [(centers[i] + centers[i + 1]) / 2.0 for i in range(n_cols - 1)]
    bounds.append(centers[-1] + pitch / 2.0)
    bounds = [float(min(0.99, max(0.01, v))) for v in bounds]
    if any(bounds[i] >= bounds[i + 1] for i in range(len(bounds) - 1)):
        return fail("COLUMN_ORDER_VIOLATION")

    return {
        "ok": True,
        "status": "COLUMNS_FROM_LABELS",
        "centers": [round(c, 4) for c in centers],
        "bounds": [round(v, 4) for v in bounds],
        "pitch": round(pitch, 4),
        "label_hits": {int(k): round(v, 4) for k, v in sorted(measured.items())},
        "sources": sources,
        "ocr_psm_passes": list(passes),
    }


def close_ink_group_bottom(a4_img: np.ndarray, x0: float, x1: float, y2: float,
                           y_start: float = 0.0) -> float:
    """Ink-Group Closure: neu `y2` roi vao GIUA mot cum muc cua chinh cot nay thi
    keo xuong day cum do; roi vao vung trang thi giu nguyen.

    Chi NOI, khong bao gio CO => khong the lam mat Recall. Dung dung tai day cum
    dang bi cat, khong nhay sang cum ke tiep.

    Ham cong khai: tu chuan hoa ve WORK_HEIGHT. Resolver goi ban noi bo
    `_close_ink_group_bottom_bw` voi anh nhi phan tinh MOT lan cho ca trang
    (truoc day adaptiveThreshold toan trang bi tinh lai cho moi cot, 5 lan/trang).
    """
    a4_img = _to_working_height(a4_img)
    if a4_img.shape[0] < 8:
        return y2
    return _close_ink_group_bottom_bw(_ink_binary(a4_img), x0, x1, y2)


def _close_ink_group_bottom_bw(bw: np.ndarray, x0: float, x1: float, y2: float) -> float:
    """Loi cua Ink-Group Closure tren anh nhi phan `_ink_binary` da tinh san."""
    h, w = bw.shape[:2]
    cx0 = int(max(0.0, min(1.0, x0)) * w)
    cx1 = int(max(0.0, min(1.0, x1)) * w)
    if cx1 - cx0 < 3 or h < 8:
        return y2
    row = int(round(y2 * h))
    if row <= 0 or row >= h - 1:
        return y2

    col = bw[:, cx0:cx1]
    thr = max(2, int((cx1 - cx0) * INK_ROW_MIN_RATIO))
    prof = (np.sum(col > 0, axis=1) >= thr)

    gap = max(1, int(h * INK_GROUP_MERGE_GAP))
    # y2 nam trong vung trang (ke ca khe <= gap giua 2 dong cung cum)? -> giu nguyen.
    lo = max(0, row - gap)
    if not prof[lo:row + 1].any():
        return y2

    # Di xuong toi khi gap khe trang > gap pixel lien tiep => day cum.
    y = row
    blank = 0
    last_ink = row
    limit = h - 1
    while y < limit:
        y += 1
        if prof[y]:
            last_ink = y
            blank = 0
        else:
            blank += 1
            if blank > gap:
                break
    return float(min(0.99, max(y2, (last_ink + 1) / float(h))))


def _ink_group_bottom_fixed(bw: np.ndarray, x0: float, x1: float, y2: float) -> float:
    """Nhu `_close_ink_group_bottom_bw` nhung KHONG 'bo' 1 pixel: ban goc khoi tao
    last_ink = row nen khi y2 nam trong khe (khong cham muc) no van tra row+1 -> goi lap
    se truot xuong tung pixel toi het khe. Day dung cho vong lap diem bat dong; ham cong
    khai/ban cu giu nguyen hanh vi."""
    h, w = bw.shape[:2]
    cx0 = int(max(0.0, min(1.0, x0)) * w)
    cx1 = int(max(0.0, min(1.0, x1)) * w)
    if cx1 - cx0 < 3 or h < 8:
        return y2
    row = int(round(y2 * h))
    if row <= 0 or row >= h - 1:
        return y2
    thr = max(2, int((cx1 - cx0) * INK_ROW_MIN_RATIO))
    prof = (np.sum(bw[:, cx0:cx1] > 0, axis=1) >= thr)
    gap = max(1, int(h * INK_GROUP_MERGE_GAP))
    lo = max(0, row - gap)
    hit = np.where(prof[lo:row + 1])[0]
    if hit.size == 0:
        return y2
    last = lo + int(hit[-1])
    y, blank = last, 0
    while y < h - 1:
        y += 1
        if prof[y]:
            last, blank = y, 0
        else:
            blank += 1
            if blank > gap:
                break
    return float(min(0.99, max(y2, (last + 1) / float(h))))


def _close_side_bw(ink: np.ndarray, y1: float, y2: float, x_edge: float,
                   direction: int, limit: float) -> float:
    """Noi NGANG mep ngoai cua cot bien (cot dau: direction=-1 sang trai; cot cuoi:
    +1 sang phai). Cung nguyen ly Ink-Group Closure: neu mep cat ngang mot cum muc
    (co muc trong `gap` pixel phia TRONG mep) thi day mep ra toi het cum, dung khi
    gap khe trang > gap pixel lien tiep. Chi NOI, khong bao gio CO.

    Chi ap cho mep NGOAI cua cot dau/cuoi: phia ngoai khong con cot hang xom nao, nen
    noi o day khong the nuot muc cua vai tro khac (khac voi ranh gioi giua hai cot)."""
    h, w = ink.shape[:2]
    ry0, ry1 = int(max(0.0, y1) * h), int(min(1.0, y2) * h)
    if ry1 - ry0 < 3:
        return x_edge
    band = ink[ry0:ry1, :]
    # Nguong theo COT pixel: mot net but cat ngang mot cot chi dong gop ~do day net
    # (2-4px o H=2200), KHONG ti le voi chieu cao khoi. Dung san toi thieu 2px da co
    # (INK_ROW_MIN_RATIO ti le theo be rong cot chi hop cho ho so HANG). Do nhay:
    # 2/3/4px cho mep ngoai lech <= 0.003 (REPORT giai doan 4).
    prof = (np.sum(band > 0, axis=0) >= SIDE_INK_MIN_PX)
    gap = max(1, int(h * INK_GROUP_MERGE_GAP))
    col = int(round(x_edge * w))
    lim = int(round(limit * w))
    col = max(0, min(w - 1, col))
    if direction > 0:
        lo = max(0, col - gap)
        hit = np.where(prof[lo:col + 1])[0]
        if hit.size == 0:
            return x_edge
        last = lo + int(hit[-1])      # net muc ngoai cung THAT phia trong mep (khong 'bo' pixel)
    else:
        hit = np.where(prof[col:min(w, col + gap + 1)])[0]
        if hit.size == 0:
            return x_edge
        last = col + int(hit[0])
    x, blank = last, 0
    while (x < lim if direction > 0 else x > lim):
        x += direction
        if prof[x]:
            last, blank = x, 0
        else:
            blank += 1
            if blank > gap:
                break
    new = (last + 1) / float(w) if direction > 0 else last / float(w)
    return float(max(x_edge, new) if direction > 0 else min(x_edge, new))


def _close_signature_block(bw: np.ndarray, bounds: List[float], y1: float, y2_base: float,
                           box_h: float) -> Tuple[List[float], List[float], Dict[str, Any]]:
    """[GIAI DOAN 4b - 27/09] Column Closure, mep day RIENG tung cot.

    Bien the "mep day CHUNG ca hang" (ban shared) bi loai theo quyet dinh coordinator:
    no nhan mot su kien roi rac cua Ink-Group Closure (vd Load_3.8 anh goc +0.011) ra
    ca 5 o -> vi pham CA 11b (<= 1 o). Nay moi cot mot y2 rieng:
      1. Xuat phat = y2 CU cua chinh cot do (Ink-Group Closure tren `bw` goc) -> hop moi
         chua hop cu (don dieu, khong mat Recall do hinh hoc).
      2. Noi lap toi diem bat dong bang `_ink_group_bottom_fixed` (khong 'bo' pixel):
         mot cum muc cham y2 thi keo xuong day cum; cum tiep theo cach <= gap cung duoc noi.
      3. Mep ngoai cot dau/cuoi noi ngang theo `_close_side_bw` tren dai y cua CHINH cot do.
      Tran: y2 <= min(0.98, y2_base + BLOCK_GROWTH_CAP * box_h). Chi NOI, khong co.
    Vach doc dai (vien scan) bi loai khoi anh muc truoc khi do."""
    h, w = bw.shape[:2]
    k = max(3, int(h * VERT_LINE_MIN_RATIO))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, k)))
    ink = cv2.subtract(bw, vert)
    cap = float(min(0.98, y2_base + BLOCK_GROWTH_CAP * box_h))
    b = list(bounds)
    n = len(b) - 1
    y2s = [max(y2_base, _close_ink_group_bottom_bw(bw, b[i], b[i + 1], y2_base)) for i in range(n)]
    y2_old = list(y2s)
    capped = [False] * n
    n_iter = 0
    for n_iter in range(1, 11):
        changed = False
        for i in range(n):
            v = _ink_group_bottom_fixed(ink, b[i], b[i + 1], y2s[i])
            if v > cap:
                v, capped[i] = cap, True
            v = max(y2s[i], v)
            if v != y2s[i]:
                y2s[i], changed = v, True
        nb0 = _close_side_bw(ink, y1, y2s[0], b[0], -1, SIDE_LIMITS[0])
        nb1 = _close_side_bw(ink, y1, y2s[-1], b[-1], +1, SIDE_LIMITS[1])
        if nb0 != b[0] or nb1 != b[-1]:
            changed = True
        b[0], b[-1] = nb0, nb1
        if not changed:
            break
    info = {"mode": "PER_COLUMN", "y2_base": round(y2_base, 3),
            "y2_old": [round(v, 3) for v in y2_old], "y2_new": [round(v, 3) for v in y2s],
            "y2_capped": capped,
            "x_outer_before": [round(bounds[0], 3), round(bounds[-1], 3)],
            "x_outer_after": [round(b[0], 3), round(b[-1], 3)], "iterations": n_iter}
    return b, y2s, info


def detect_loading_plan_signature_zone(a4_img: np.ndarray, page_role: str = "HEADER") -> Dict[str, Any]:
    """
    Thuật toán Giải Pháp 1 (Dossier Lifecycle + Dynamic Table Bottom Detection):
    - Nhận diện Trang 1 hồ sơ đa trang: Bảng hàng hóa dài phủ kín (>70% trang) -> Miễn trừ chữ ký (targets = [])
    - Nhận diện Trang 2 (Continuation) & Đơn Trang: Dò đáy bảng thực tế (Table Bottom Grid)
      kết hợp dò từ khóa để neo chính xác 5 Bounding Box ngay dưới hàng kết thúc bảng.
    """
    # 0. [GIAI DOAN 2 - 27/09] Chuan hoa do phan giai: MOI phep do ben duoi chay
    #    tren anh H=WORK_HEIGHT. Dau vao H=2200 (production) -> no-op.
    a4_img = _to_working_height(a4_img)
    h, w = a4_img.shape[:2]
    # Anh nhi phan muc tinh MOT lan, dung chung cho do vach bang va Ink-Group Closure.
    bw = _ink_binary(a4_img)

    # 1. Trich xuat cac vach ke ngang cua bang bang morphology.
    #    [TACH MODULE 27/09] Doan nay truoc day duoc chep 2 lan (LOADING_PLAN va HOA_DON);
    #    nay dung chung helper detect_table_lines(). Tham so duoc truyen vao DUNG BANG
    #    gia tri cu cua LOADING_PLAN: nguong 25% chieu rong trang, dai y tu 5% den 88%.
    norm_lines = detect_table_lines(
        a4_img,
        line_thresh_ratio=0.25,
        y_min_ratio=0.05,
        y_max_ratio=0.88,
        bw=bw,
    )
    
    # 2. Xử lý Vòng đời Đa trang (Dossier Lifecycle):
    # Nếu là Trang 1 (HEADER) và có hơn 18 dòng kẻ bảng kéo dài xuống quá 70% trang
    # -> Đây là Trang 1 của lô nhiều mặt hàng, KHÔNG CÓ KHỐI CHỮ KÝ!
    if page_role == "HEADER" and len(norm_lines) >= 18 and (norm_lines[-1] > 0.70):
        return {
            "has_signatures": False,
            "anchor_y": None,
            "status": "PAGE_1_NO_SIGNATURES",
            "description": "Trang 1/2: Bảng hàng hóa dài phủ kín trang, khối ký nằm ở Trang 2",
            "targets": []
        }
        
    # 3. Với Trang 2 (Continuation) hoặc Đơn Trang (Single Page):
    # Tìm đáy bảng (vạch kẻ ngang cuối cùng của bảng)
    if norm_lines:
        last_table_line = norm_lines[-1]
        anchor_y = round(last_table_line + 0.015, 3)
        status = "TABLE_BOTTOM_DETECTED"
    else:
        # Trường hợp không có vạch bảng (Trang 2 chỉ có chữ ký ở đỉnh):
        if page_role == "CONTINUATION":
            anchor_y = 0.080 # Bắt đầu ngay trên đỉnh trang
            status = "TOP_SIGNATURES_DETECTED"
        else:
            # [GIAI DOAN 2 - 27/09] Truoc day: anchor_y = 0.550, status
            # "DEFAULT_SINGLE_PAGE" roi van dung hop tai do. Day la DOAN VI TRI - 0.550
            # khong do tu anh nao, chi la "giua trang". Khong co vach bang thi khong
            # co moc neo khoi ky; OCR nhan tai mot Y doan mo co the trung chu bat ky
            # va sinh 5 hop dung la sai cho. Nay ABSTAIN tuong minh: Tang 4 phai
            # tra ve nguoi kiem tra thay vi cham diem tren hop doan.
            return {
                "has_signatures": False,
                "anchor_y": None,
                "status": "TABLE_ANCHOR_NOT_FOUND",
                "description": (
                    "Khong do duoc vach ke bang nao (trang khong phai CONTINUATION) -> "
                    "khong co moc neo khoi ky; Tang 4 phai ABSTAIN, khong doan vi tri"
                ),
                "targets": [],
            }

    # 4. Ranh gioi cot: DO TREN TUNG ANH tu nhan chuc danh in san.
    #    [SUA 27/09] Bo hoan toan bo hang so 0.02/0.20/0.36/0.54/0.72/0.98 - do
    #    duoc la lech trai 0.03-0.05 (20-30% be rong cot) nen chu ky cot ben trai
    #    tran sang o ben phai (nguon 9/10 FP o cot 2 va cot 4).
    #    Do that bai -> ABSTAIN tuong minh, TUYET DOI khong roi ve hang so cu.
    try:
        col = detect_signature_columns(a4_img, anchor_y)
    except LoadingPlanLabelsError as e:
        return {
            "has_signatures": False,
            "anchor_y": anchor_y,
            "status": "COLUMN_LABELS_UNAVAILABLE",
            "description": f"Khong nap duoc tu dien nhan chuc danh: {e}",
            "targets": [],
        }
    fallback_used = None
    col_status_goc = col["status"]
    if not col["ok"]:
        # [29/09] DUONG LUI HARDCODE — chi thay DUNG BUOC 4 (ranh gioi cot).
        # Buoc 1-3 (vach ke bang, nhan trang 1 da trang, anchor_y) va buoc 5
        # (dong day khoi ky) deu chay bang OpenCV va VAN DUNG khi OCR chet.
        # Vut ca trang di chi vi thieu ranh gioi cot la lang phi ba buoc con dung.
        # RANG BUOC: bat buoc da co anchor_y tu vach ke bang; moi target sinh ra
        # deu mang review_required=True; KHONG BAO GIO ra phan quyet DAT thang.
        # CHI ap dung cho that bai TREN TUNG ANH. COLUMN_OCR_UNAVAILABLE la LOI CAI DAT
        # (thieu tesseract/rapidfuzz) -> phai ABSTAIN de lo ra, khong duoc lay hang so
        # che di: OCR chet thi MOI chung tu se chay bang hang so ma khong ai biet.
        fb = load_loading_plan_labels().get("fallback_columns") or {}
        ap_dung = set(fb.get("chi_ap_dung_cho") or ())
        if not (fb.get("enabled") and fb.get("bounds") and col_status_goc in ap_dung
                and len(fb["bounds"]) == len(load_loading_plan_labels()["columns"]) + 1):
            return {
                "has_signatures": False,
                "anchor_y": anchor_y,
                "status": col["status"],
                "description": (
                    f"Khong do duoc ranh gioi cot khoi ky tai Y={anchor_y:.3f} "
                    f"({col['status']}); duong lui hardcode TAT -> Tang 4 phai ABSTAIN"
                ),
                "targets": [],
            }
        col = {
            "ok": True,
            "status": "COLUMN_FALLBACK_HARDCODE",
            "bounds": list(fb["bounds"]),
            "centers": [round((fb["bounds"][i] + fb["bounds"][i + 1]) / 2, 3)
                        for i in range(len(fb["bounds"]) - 1)],
            "pitch": None,
            "label_hits": {},
            "sources": ["FALLBACK_HARDCODE"] * (len(fb["bounds"]) - 1),
        }
        fallback_used = {
            "ly_do": col_status_goc,
            "version": fb.get("version"),
            "nguon": fb.get("_nguon"),
            "delta_x0_max": fb.get("delta_x0_max"),
        }

    columns = load_loading_plan_labels()["columns"]

    # 5. Mep tren giu nguyen cong thuc cu. Mep duoi + mep ngoai cot bien:
    #    [GIAI DOAN 4b - 27/09] Column Closure (_close_signature_block): mep duoi RIENG
    #    tung cot, noi toi diem bat dong; mep ngoai cot dau/cuoi noi ngang
    #    khi chu ky tran qua mep bang. Chi NOI, khong co. Ranh gioi GIUA cac cot KHONG doi
    #    (xem REPORT giai doan 4: tam nhan + mep bang khop mo hinh o deu, sai so <1%).
    box_h = 0.18
    y1 = round(max(0.04, anchor_y - 0.01), 3)
    y2_base = round(min(0.98, anchor_y + box_h), 3)
    bounds, y2_cols, block_info = _close_signature_block(bw, col["bounds"], y1, y2_base, box_h)

    targets = []
    for i, c in enumerate(columns):
        x0, x1 = bounds[i], bounds[i + 1]
        t = {
            "role": c["role"],
            "box_norm": [y1, round(x0, 3), round(y2_cols[i], 3), round(x1, 3)],
            "required": bool(c["required"]),
            "expected_color": c["expected_color"],
            "description": c["description"],
            "column_source": col["sources"][i],
            "column_center": col["centers"][i],
        }
        if fallback_used:
            # Cot KHONG do tu anh nay ma lay tu hang so -> khong duoc tu dong duyet.
            t["review_required"] = True
            t["review_reason"] = "COLUMN_FALLBACK_HARDCODE"
        targets.append(t)

    return {
        "has_signatures": True,
        "anchor_y": anchor_y,
        "status": status,
        "column_status": col["status"],
        "column_fallback": fallback_used,
        "column_pitch": col["pitch"],
        "column_bounds": [round(v, 3) for v in bounds],
        "block_closure": block_info,
        "description": (
            f"Dò đáy bảng tại Y={anchor_y:.2f}; cột đo từ "
            f"{sum(1 for s in col['sources'] if s == 'OCR_LABEL')}/{len(columns)} nhãn OCR"
        ),
        "targets": targets
    }


def detect_invoice_signature_zone(a4_img: np.ndarray, page_role: str = "HEADER", system: str = "COMMON") -> Dict[str, Any]:
    """
    Thuật toán Giải Pháp 2 (Channel-Aware Invoice Signature Zone Resolver v2.5):
    - Dò vạch kẻ ngang cuối cùng của bảng hóa đơn (last_table_line).
    - Phân định cấu trúc Dual-Mode với biên bảo vệ mép giấy x=[0.08, 0.44] và x=[0.54, 0.92]:
      + Bảng ngắn (last_table_line <= 0.72): Khối ký nổi ngay dưới bảng (floating bottom) y=[last_line+0.055, min(0.850, y1+0.125)].
      + Bảng dài (last_table_line > 0.72): Khối ký ép sát chân trang (docked bottom) y=[0.780, 0.950].
    - Phân hóa targets theo 10 Kênh/Hệ thống chuẩn SOP KIDO (Guideline):
      + MT_COOP, MT_GS25, MT_SATRA, MT_BIGC: Bắt buộc Người mua ký + Mộc vuông tiếp nhận ST.
      + MT_WINMART: Miễn trừ Người mua (Vin xác nhận trên PGH theo SOP KIDO Row 33).
      + MT_AEON, MT_LOTTE, MT_EMART: Người mua ký nhận.
      + GT: NPP ký nhận chuyển đổi hóa đơn.
      + MT_BHX: Khổ rộng ghép đôi (Biên bản DC BHX + Hóa đơn KIDO).
    """
    h, w = a4_img.shape[:2]

    # [TACH MODULE 27/09] dung chung helper detect_table_lines().
    # Tham so DUNG BANG gia tri cu cua HOA_DON: nguong 20% chieu rong trang,
    # bang hoa don thuong ket thuc trong khoang 35% den 92% chieu cao trang.
    norm_lines = detect_table_lines(
        a4_img,
        line_thresh_ratio=0.20,
        y_min_ratio=0.35,
        y_max_ratio=0.92,
    )
    last_table_line = norm_lines[-1] if norm_lines else 0.750
    
    sys_upper = system.upper()
    
    if "BHX" in sys_upper:
        # Trường hợp Bách Hóa Xanh: Ảnh scan khổ rộng đôi (Biên bản DC BHX bên trái + Hóa đơn KIDO bên phải)
        layout_mode = "DUAL_PANEL_BHX"
        targets = [
            {
                "role": "Người mua hàng (Hóa đơn)",
                "box_norm": [0.700, 0.50, 0.950, 0.72],
                "required": False,
                "expected_color": "blue_ink",
                "description": "Chữ ký người mua trên Hóa đơn KIDO"
            },
            {
                "role": "Thủ kho DC BHX",
                "box_norm": [0.700, 0.10, 0.950, 0.45],
                "required": True,
                "expected_color": "blue_ink",
                "description": "Chữ ký xác nhận nhận hàng của DC Bách Hóa Xanh (Biên bản bên trái)"
            },
            {
                "role": "Người bán KIDO",
                "box_norm": [0.700, 0.73, 0.950, 0.98],
                "required": True,
                "expected_color": "blue_ink",
                "description": "Chữ ký điện tử / Người bán KIDO"
            }
        ]
    elif "AEON" in sys_upper and last_table_line <= 0.72:
        # Trường hợp Aeon bảng ngắn (như Hoadon_3.5__0): Khối ký nằm trong khung bảng ở y=[0.60, 0.68]
        layout_mode = "AEON_IN_TABLE_BLOCK"
        targets = [
            {
                "role": "Người mua hàng (Aeon)",
                "box_norm": [0.600, 0.08, 0.680, 0.44],
                "required": True,
                "expected_color": "blue_ink",
                "description": "Chữ ký người nhận hàng siêu thị Aeon"
            },
            {
                "role": "Thủ trưởng đơn vị / Người bán",
                "box_norm": [0.600, 0.54, 0.680, 0.92],
                "required": True,
                "expected_color": "blue_ink",
                "description": "Khối chữ ký số điện tử KIDO"
            },
            {
                "role": "Con dấu mộc đỏ",
                "box_norm": [0.590, 0.52, 0.680, 0.90],
                "required": True,
                "expected_color": "red_stamp",
                "description": "Mộc đỏ KIDO hoặc khung ký số FPT"
            }
        ]
    else:
        # Các hệ thống còn lại: Phân định Dual-Mode
        if last_table_line <= 0.72:
            y1 = round(last_table_line + 0.055, 3)
            y2 = round(min(0.850, y1 + 0.125), 3)
            stamp_y1 = round(last_table_line + 0.035, 3)
            stamp_y2 = round(min(0.850, stamp_y1 + 0.145), 3)
            layout_mode = "FLOATING_BELOW_TABLE"
        else:
            y1 = 0.780
            y2 = 0.950
            stamp_y1 = 0.700
            stamp_y2 = 0.920
            layout_mode = "DOCKED_BOTTOM"
            
        if "WINMART" in sys_upper or "VIN" in sys_upper:
            # WinMart: Miễn trừ ký trên Hóa đơn theo SOP KIDO Row 33
            targets = [
                {
                    "role": "Người mua hàng",
                    "box_norm": [y1, 0.08, y2, 0.44],
                    "required": False,
                    "expected_color": "blue_ink",
                    "description": "Miễn trừ theo SOP KIDO: Siêu thị WinMart không ký hóa đơn (xác nhận trên PGH)"
                },
                {
                    "role": "Thủ trưởng đơn vị / Người bán",
                    "box_norm": [y1, 0.54, y2, 0.92],
                    "required": True,
                    "expected_color": "blue_ink",
                    "description": "Chữ ký người bán / Chữ ký số KIDO"
                },
                {
                    "role": "Con dấu mộc đỏ",
                    "box_norm": [stamp_y1, 0.52, stamp_y2, 0.90],
                    "required": True,
                    "expected_color": "red_stamp",
                    "description": "Mộc đỏ KIDO hoặc khung chữ ký số điện tử"
                }
            ]
        elif any(k in sys_upper for k in ["COOP", "GS25", "SATRA", "BIGC"]):
            # Các chuỗi siêu thị bắt buộc ký và có mộc tiếp nhận vuông
            store_name = "Co.opmart" if "COOP" in sys_upper else ("GS25" if "GS25" in sys_upper else ("Satra" if "SATRA" in sys_upper else "Big C"))
            targets = [
                {
                    "role": f"Người mua hàng ({store_name})",
                    "box_norm": [y1, 0.08, y2, 0.44],
                    "required": True,
                    "expected_color": "blue_ink",
                    "description": f"Chữ ký nhận hàng của đại diện {store_name}"
                },
                {
                    "role": f"Mộc tiếp nhận {store_name}",
                    "box_norm": [stamp_y1, 0.08, stamp_y2, 0.46],
                    "required": True,
                    "expected_color": "any_stamp",
                    "description": f"Dấu vuông tiếp nhận hàng của siêu thị {store_name} (mực xanh, tím hoặc đỏ)"
                },
                {
                    "role": "Thủ trưởng đơn vị / Người bán",
                    "box_norm": [y1, 0.54, y2, 0.92],
                    "required": True,
                    "expected_color": "blue_ink",
                    "description": "Chữ ký người bán / Kế toán KIDO"
                },
                {
                    "role": "Con dấu mộc đỏ",
                    "box_norm": [stamp_y1, 0.52, stamp_y2, 0.90],
                    "required": True,
                    "expected_color": "red_stamp",
                    "description": "Mộc đỏ KIDO hoặc khung chữ ký số"
                }
            ]
        elif "GT" in sys_upper:
            # Kênh NPP: Đại diện NPP ký nhận chuyển đổi
            targets = [
                {
                    "role": "Đại diện Nhà Phân Phối",
                    "box_norm": [y1, 0.08, y2, 0.44],
                    "required": True,
                    "expected_color": "blue_ink",
                    "description": "Chữ ký nhận của NPP trên HĐ chuyển đổi"
                },
                {
                    "role": "Người bán / Chữ ký số KIDO",
                    "box_norm": [y1, 0.54, y2, 0.92],
                    "required": True,
                    "expected_color": "blue_ink",
                    "description": "Khung chữ ký số điện tử KIDO"
                },
                {
                    "role": "Con dấu mộc đỏ",
                    "box_norm": [stamp_y1, 0.52, stamp_y2, 0.90],
                    "required": True,
                    "expected_color": "red_stamp",
                    "description": "Mộc đỏ KIDO hoặc khung ký số FPT"
                }
            ]
        else:
            # Chung hoặc Aeon dài, Lotte, Emart
            targets = [
                {
                    "role": "Người mua / nhận hàng",
                    "box_norm": [y1, 0.08, y2, 0.44],
                    "required": True,
                    "expected_color": "blue_ink",
                    "description": "Chữ ký và họ tên người nhận hàng tại điểm giao"
                },
                {
                    "role": "Thủ trưởng đơn vị / Người bán",
                    "box_norm": [y1, 0.54, y2, 0.92],
                    "required": True,
                    "expected_color": "blue_ink",
                    "description": "Chữ ký người bán / KIDO"
                },
                {
                    "role": "Con dấu mộc đỏ",
                    "box_norm": [stamp_y1, 0.52, stamp_y2, 0.90],
                    "required": True,
                    "expected_color": "red_stamp",
                    "description": "Mộc đỏ KIDO hoặc khung chữ ký số điện tử"
                }
            ]
            
    return {
        "has_signatures": True,
        "anchor_y": round(last_table_line, 3),
        "status": "TABLE_BOTTOM_DETECTED" if norm_lines else "DEFAULT_INVOICE_BOTTOM",
        "layout_mode": layout_mode,
        "description": f"Dò đáy bảng tại Y={last_table_line:.3f} ({layout_mode}) | Hệ thống: {system}",
        "targets": targets
    }


# Bí danh tương thích
detect_channel_aware_invoice_zone = detect_invoice_signature_zone
