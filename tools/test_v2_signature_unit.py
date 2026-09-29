# -*- coding: utf-8 -*-
"""
Unit test doc lap cho `verify_signature` trong tools/stage4_verifier_v2.py.

Khong dung ground truth, khong doc anh that: moi ROI duoc sinh tong hop bang
numpy/cv2 nen hanh vi mong doi suy ra tu DINH NGHIA NGHIEP VU, khong phai tu
diem so benchmark.

Chay:  .venv/Scripts/python.exe tools/test_v2_signature_unit.py
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.stage4_verifier_v2 import verify_signature  # noqa: E402  [module that cua du an]

RESULTS = []


def check(name, cond, detail="", known_limit=False):
    """known_limit=True: ca ghi nhan GIOI HAN DA BIET cua engine dang chay.
    Van in ket qua that, nhung KHONG lam do suite — vi do la hanh vi da duoc
    do, duoc giai thich va duoc chap nhan co y thuc, khong phai hoi quy moi."""
    ok = bool(cond)
    RESULTS.append((name, ok, detail, known_limit))
    tag = "[PASS]" if ok else ("[KNOWN-LIMIT]" if known_limit else "[FAIL]")
    print(f"{tag} {name}" + (f"  -- {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Helper sinh ROI tong hop. Kich thuoc mac dinh xap xi ROI tham chieu 464x714.
# ---------------------------------------------------------------------------
def blank(h=464, w=714, val=245):
    """Nen giay trang (hoi xam nhu giay scan that)."""
    return np.full((h, w, 3), val, dtype=np.uint8)


def add_printed_text(img, font_h_px=12, n_lines=3):
    """Chu in san nho, vi du '(Ky, ghi ro ho ten)'."""
    scale = font_h_px / 22.0  # FONT_HERSHEY_SIMPLEX cao ~22px o scale 1.0
    for i in range(n_lines):
        y = int(img.shape[0] * 0.25) + i * int(font_h_px * 2.2)
        cv2.putText(img, "(Ky, ghi ro ho ten)", (int(img.shape[1] * 0.1), y),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, (60, 60, 60), 1, cv2.LINE_AA)
    return img


def add_signature_strokes(img, thickness_frac=0.012):
    """Net ky viet tay to: polyline day, keo dai ngang ROI."""
    h, w = img.shape[:2]
    th = max(2, int(round(min(h, w) * thickness_frac)))
    pts = np.array([
        [0.15, 0.70], [0.22, 0.35], [0.30, 0.72], [0.38, 0.30],
        [0.47, 0.68], [0.56, 0.32], [0.66, 0.66], [0.78, 0.40],
    ])
    pts = (pts * np.array([w, h])).astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(img, [pts], False, (30, 30, 30), th, cv2.LINE_AA)
    return img


def add_blue_ink(img):
    h, w = img.shape[:2]
    th = max(2, int(round(min(h, w) * 0.012)))
    pts = np.array([[0.2, 0.6], [0.35, 0.35], [0.5, 0.65], [0.65, 0.38]])
    pts = (pts * np.array([w, h])).astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(img, [pts], False, (200, 40, 20), th, cv2.LINE_AA)  # BGR xanh duong
    return img


def add_hline(img, thickness=2):
    h, w = img.shape[:2]
    y = h // 2
    cv2.line(img, (0, y), (w - 1, y), (40, 40, 40), thickness)
    return img


def add_vline(img, thickness=2):
    h, w = img.shape[:2]
    x = w // 2
    cv2.line(img, (x, 0), (x, h - 1), (40, 40, 40), thickness)
    return img


def add_salt_pepper(img, amount=0.004, seed=20250927):
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    n = int(h * w * amount)
    ys = rng.integers(0, h, n)
    xs = rng.integers(0, w, n)
    img[ys, xs] = 20
    return img


# ---------------------------------------------------------------------------
# CA 1 - ROI trang hoan toan -> detected = False
# ---------------------------------------------------------------------------
r = verify_signature(blank())
check("CA 1: ROI trang hoan toan -> detected=False",
      r["detected"] is False and r["evidence"] == "NO_SIGNATURE_DETECTED",
      f"detected={r['detected']} evidence={r['evidence']}")

# ---------------------------------------------------------------------------
# CA 2 - Chi co chu in nho (~12px) -> detected = False
# ---------------------------------------------------------------------------
r = verify_signature(add_printed_text(blank(), font_h_px=12, n_lines=3))
check("CA 2: chi co chu in nho ~12px -> detected=False",
      r["detected"] is False and r["evidence"] == "NO_SIGNATURE_DETECTED",
      f"detected={r['detected']}")

# ---------------------------------------------------------------------------
# CA 3 - Mot duong ke NGANG manh xuyen suot -> detected = False
# ---------------------------------------------------------------------------
r = verify_signature(add_hline(blank(), thickness=2))
check("CA 3: duong ke ngang manh xuyen suot -> detected=False",
      r["detected"] is False and r["evidence"] == "NO_SIGNATURE_DETECTED",
      f"detected={r['detected']}")

# ---------------------------------------------------------------------------
# CA 4 - Mot duong ke DOC manh xuyen suot -> detected = False
# ---------------------------------------------------------------------------
r = verify_signature(add_vline(blank(), thickness=2))
check("CA 4: duong ke doc manh xuyen suot -> detected=False",
      r["detected"] is False and r["evidence"] == "NO_SIGNATURE_DETECTED",
      f"detected={r['detected']}")

# ---------------------------------------------------------------------------
# CA 5 - Net chu ky viet tay to -> detected = True / HANDWRITING_STROKE_DETECTED
# ---------------------------------------------------------------------------
r = verify_signature(add_signature_strokes(blank()))
check("CA 5: net chu ky viet tay to -> detected=True + HANDWRITING_STROKE_DETECTED",
      r["detected"] is True and r["evidence"] == "HANDWRITING_STROKE_DETECTED",
      f"detected={r['detected']} evidence={r['evidence']}")

# ---------------------------------------------------------------------------
# CA 6 - Muc xanh -> detected = True / BLUE_SIGNATURE_DETECTED
# ---------------------------------------------------------------------------
r = verify_signature(add_blue_ink(blank()))
check("CA 6: muc xanh -> detected=True + BLUE_SIGNATURE_DETECTED",
      r["detected"] is True and r["evidence"] == "BLUE_SIGNATURE_DETECTED"
      and r["ink_type"] == "blue_ink",
      f"detected={r['detected']} evidence={r['evidence']}")

# ---------------------------------------------------------------------------
# CA 7 - Nhieu muoi tieu nhe tren nen trang -> detected = False (bat bien nhieu)
# ---------------------------------------------------------------------------
r = verify_signature(add_salt_pepper(blank()))
check("CA 7: nhieu muoi tieu nhe -> detected=False (bat bien nhieu)",
      r["detected"] is False and r["evidence"] == "NO_SIGNATURE_DETECTED",
      f"detected={r['detected']}")

# ---------------------------------------------------------------------------
# CA 8 - BAT BIEN KICH THUOC (ca quan trong nhat)
#        Cung noi dung chu ky, 2 kich thuoc ROI khac nhau -> CUNG detected.
#        Kiem ca 2 chieu: co chu ky (True) va chi co chu in (False).
# ---------------------------------------------------------------------------
small_sig = verify_signature(add_signature_strokes(blank(200, 400)))
large_sig = verify_signature(add_signature_strokes(blank(400, 800)))
check("CA 8a: chu ky o 200x400 va 400x800 -> CUNG detected (=True)",
      small_sig["detected"] == large_sig["detected"] is True,
      f"200x400={small_sig['detected']} 400x800={large_sig['detected']}")

small_txt = verify_signature(add_printed_text(blank(200, 400), font_h_px=10, n_lines=2))
large_txt = verify_signature(add_printed_text(blank(400, 800), font_h_px=20, n_lines=2))
check("CA 8b: chu in scale 200x400 va 400x800 -> CUNG detected (=False)",
      small_txt["detected"] == large_txt["detected"] is False,
      f"200x400={small_txt['detected']} 400x800={large_txt['detected']}")

# ---------------------------------------------------------------------------
# CA 9 - Tinh xac dinh: goi 2 lan tren cung input -> ket qua giong het
# ---------------------------------------------------------------------------
img_det = add_signature_strokes(blank())
a = verify_signature(img_det.copy())
b = verify_signature(img_det.copy())
same = (a["detected"] == b["detected"] and a["evidence"] == b["evidence"]
        and abs(a["confidence"] - b["confidence"]) < 1e-12
        and a["reason"] == b["reason"] and a["ink_type"] == b["ink_type"])
check("CA 9: tinh xac dinh - 2 lan goi cho ket qua giong het", same,
      f"conf={a['confidence']} vs {b['confidence']}")

# ---------------------------------------------------------------------------
# CA 10 - ROI cuc nho / rong -> khong crash
# ---------------------------------------------------------------------------
ok10 = True
detail10 = []
for label, roi in [
    ("None", None),
    ("0x0x3", np.zeros((0, 0, 3), dtype=np.uint8)),
    ("1x1x3", np.zeros((1, 1, 3), dtype=np.uint8)),
    ("2x5x3", np.full((2, 5, 3), 250, dtype=np.uint8)),
    ("3x3x3", np.full((3, 3, 3), 250, dtype=np.uint8)),
    ("4x4x3", np.full((4, 4, 3), 250, dtype=np.uint8)),
]:
    try:
        rr = verify_signature(roi)
        need = {"detected", "confidence", "ink_type", "reason", "evidence", "mask"}
        if not need.issubset(rr.keys()):
            ok10 = False
            detail10.append(f"{label}: thieu khoa")
    except Exception as exc:  # noqa: BLE001
        ok10 = False
        detail10.append(f"{label}: {type(exc).__name__}: {exc}")
check("CA 10: ROI cuc nho / rong -> khong crash, du khoa tra ve", ok10,
      "; ".join(detail10))

# ---------------------------------------------------------------------------
# CA 11 - SWEEP KICH THUOC (chung minh nguong da scale, khong chi 2 diem)
#   Quet ROI tu 0.5x den 3.0x kich thuoc tham chieu 464x714, noi dung scale theo.
#   Ky vong: chu in san -> False o MOI scale; chu ky -> True o MOI scale.
#   Day chinh la cho ban CU (nguong pixel tuyet doi) hong: da do duoc, o 3.0x
#   (1392x2142) ban cu cham mot dong chu in san la HANDWRITING_STROKE_DETECTED
#   vi dien tich tuyet doi vuot 300 px; ban moi tra False o moi scale.
#
#   GIA DINH: gioi han duoi cua sweep dat o 0.5x. Duoi ~0.3x (ROI < 140 px cao)
#   chu in bi merge thanh mot blob duy nhat va moi phuong phap dua tren
#   connected-component deu mat kha nang phan biet; day la vung nam NGOAI
#   contract (khong signature zone that nao nho nhu vay).
# ---------------------------------------------------------------------------
SCALES = [0.5, 1.0, 1.5, 2.0, 3.0]

bad_txt = []
for s in SCALES:
    hh, ww = int(464 * s), int(714 * s)
    rr = verify_signature(add_printed_text(blank(hh, ww), font_h_px=12 * s, n_lines=3))
    if rr["detected"]:
        bad_txt.append(f"{s}x({hh}x{ww})")
# GIOI HAN DA BIET, KHONG PHAI HOI QUY:
# Nguong cua engine san xuat la PIXEL TUYET DOI, do do o scale >= 3x mot dong
# chu in san vuot `area > 300` va bi cham la net ky. Da thu sua bang ink-mask +
# nguong ti le (bat CA nay) nhung DO THAT tren du lieu that thi Precision tut
# 79.63% -> 62.86% => da hoan lai. Xem ghi chu dai trong stage4_verifier_v2.py
# ngay tren `verify_signature`, va output/stage4_out/stage4_v2_signature_ab.json.
# Contract hien tai co dinh anh A4 H=2200 nen scale 3x KHONG xay ra trong san
# xuat. Neu contract resize thay doi, ca nay phai duoc nang lai thanh FAIL that.
check("CA 11a: sweep 0.5x-3.0x, chu in san -> False o moi scale",
      not bad_txt, ("FP tai: " + ", ".join(bad_txt)) if bad_txt else "0 FP",
      known_limit=False)  # [BAN SAO engine moi] nang thanh PASS/FAIL THAT: nguong mm, bat bien ti le

bad_sig = []
for s in SCALES:
    hh, ww = int(464 * s), int(714 * s)
    rr = verify_signature(add_signature_strokes(blank(hh, ww)))
    if not rr["detected"]:
        bad_sig.append(f"{s}x({hh}x{ww})")
check("CA 11b: sweep 0.5x-3.0x, chu ky that -> True o moi scale",
      not bad_sig, ("FN tai: " + ", ".join(bad_sig)) if bad_sig else "0 FN")

# ---------------------------------------------------------------------------
print()
passed = sum(1 for _, ok, _, _ in RESULTS if ok)
total = len(RESULTS)
known = [n for n, ok, _, kl in RESULTS if not ok and kl]
real_fail = [n for n, ok, _, kl in RESULTS if not ok and not kl]
print(f"{passed}/{total} PASSED"
      + (f"  |  {len(known)} GIOI HAN DA BIET (khong lam do suite)" if known else "")
      + (f"  |  {len(real_fail)} FAIL" if real_fail else ""))
for n in known:
    print(f"  [known-limit] {n}")
sys.exit(1 if real_fail else 0)
