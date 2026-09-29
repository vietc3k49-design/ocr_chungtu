# -*- coding: utf-8 -*-
"""Kiểm đường lui hardcode cho ranh giới cột LOADING_PLAN (Tầng 3b).

Đường lui CHỈ chạy khi dò nhãn chức danh thất bại. Trên 19 ảnh demo nhánh chính
chưa hụt lần nào, nên không thể kiểm nó bằng cách chạy bình thường — phải ÉP hỏng.

5 ca:
  1. Bình thường: nhánh chính chạy, KHÔNG được dùng đường lui.
  2. Ép dò cột hỏng: phải ra đủ 5 target, column_source = FALLBACK_HARDCODE,
     mọi target mang review_required=True.
  3. Ép hỏng + tắt đường lui trong config: phải ABSTAIN như hành vi cũ.
  4. Ép hỏng khi KHÔNG có vạch kẻ bảng (không có anchor_y): vẫn phải ABSTAIN —
     đường lui không được đoán vị trí khi thiếu mốc neo.
  5. Hộp đường lui phải nằm trong trang và đúng thứ tự trái→phải.
"""
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import stage3b_zone_resolver as R                      # noqa: E402

ANH = ROOT / "output/stage1_out/images/form_samples/Load3.3__0.png"
CFG = ROOT / "config/stage3b_loading_plan_labels.json"
n_pass = n_fail = 0


def check(ten, dieu_kien, chi_tiet=""):
    global n_pass, n_fail
    if dieu_kien:
        n_pass += 1
        print(f"  [PASS] {ten}")
    else:
        n_fail += 1
        print(f"  [FAIL] {ten}  {chi_tiet}")


def ep_hong(status="COLUMN_DETECTION_FAILED"):
    """Thay detect_signature_columns bằng bản luôn báo hỏng."""
    goc = R.detect_signature_columns
    R.detect_signature_columns = lambda img, y: {
        "ok": False, "status": status, "centers": None, "bounds": None,
        "pitch": None, "label_hits": {}, "sources": None, "ocr_psm_passes": [],
    }
    return goc


def dat_co(bat):
    """Bật/tắt đường lui trong config (mặc định trên đĩa là TẮT)."""
    c = json.loads(CFG.read_text(encoding="utf-8"))
    c["fallback_columns"]["enabled"] = bat
    CFG.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    R._LABELS_CACHE = None


def main():
    img = cv2.imread(str(ANH))
    assert img is not None, f"không đọc được {ANH}"
    goc_cfg_toan_cuc = CFG.read_text(encoding="utf-8")
    fb = json.loads(goc_cfg_toan_cuc)["fallback_columns"]
    dat_co(True)          # CA 1/2/5 cần đường lui BẬT; CA 3 tự tắt lại

    print("CA 1 — bình thường, KHÔNG được dùng đường lui")
    z = R.detect_loading_plan_signature_zone(img, page_role="HEADER")
    check("nhánh chính chạy được", z.get("has_signatures") is True, z.get("status"))
    check("không dùng đường lui", z.get("column_fallback") is None)
    check("5 target", len(z.get("targets") or []) == 5)
    check("nguồn cột là OCR/nội suy",
          all(t["column_source"] in ("OCR_LABEL", "INTERPOLATED") for t in z["targets"]))
    check("không target nào bị gắn review_required",
          all("review_required" not in t for t in z["targets"]))
    box_chinh = [t["box_norm"] for t in z["targets"]]

    print("\nCA 2 — ép dò cột hỏng, đường lui phải gánh")
    goc = ep_hong()
    try:
        z2 = R.detect_loading_plan_signature_zone(img, page_role="HEADER")
    finally:
        R.detect_signature_columns = goc
    check("vẫn dựng được khối ký", z2.get("has_signatures") is True, z2.get("status"))
    check("column_status = COLUMN_FALLBACK_HARDCODE",
          z2.get("column_status") == "COLUMN_FALLBACK_HARDCODE", z2.get("column_status"))
    check("ghi vết lý do gốc",
          (z2.get("column_fallback") or {}).get("ly_do") == "COLUMN_DETECTION_FAILED")
    check("đủ 5 target", len(z2.get("targets") or []) == 5)
    check("mọi target mang review_required=True",
          all(t.get("review_required") is True for t in z2.get("targets") or []))
    check("nguồn cột = FALLBACK_HARDCODE",
          all(t["column_source"] == "FALLBACK_HARDCODE" for t in z2.get("targets") or []))

    print("\nCA 5 — hình học hộp đường lui")
    tg = z2.get("targets") or []
    xs = [t["box_norm"][1] for t in tg] + [tg[-1]["box_norm"][3]] if tg else []
    check("x tăng dần trái→phải", all(xs[i] < xs[i + 1] for i in range(len(xs) - 1)), xs)
    check("mọi toạ độ trong [0,1]",
          all(0.0 <= v <= 1.0 for t in tg for v in t["box_norm"]))
    # Ranh gioi GIUA cac cot phai khop config tuyet doi; MEP NGOAI (cot dau/cuoi)
    # duoc _close_signature_block noi ra khi chu ky tran qua mep bang -> cho sai so 0.02.
    got = [round(t["box_norm"][1], 3) for t in tg]
    mong = [round(v, 3) for v in fb["bounds"][:-1]]
    check("ranh giới GIỮA các cột khớp config tuyệt đối", got[1:] == mong[1:], (got, mong))
    check("mép ngoài trái lệch <= 0.02 (block closure được nới)",
          abs(got[0] - mong[0]) <= 0.02, (got[0], mong[0]))
    # đường lui KHÔNG được trùng khít nhánh chính (nếu trùng thì test vô nghĩa)
    check("hộp đường lui khác hộp nhánh chính (test có ý nghĩa)",
          box_chinh != [t["box_norm"] for t in tg])

    print("\nCA 3 — ép hỏng + tắt đường lui trong config ⇒ ABSTAIN như cũ")
    goc_cfg = CFG.read_text(encoding="utf-8")
    c = json.loads(goc_cfg)
    c["fallback_columns"]["enabled"] = False
    CFG.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    R._LABELS_CACHE = None          # cache la bien module, khong phai lru_cache
    goc = ep_hong()
    try:
        z3 = R.detect_loading_plan_signature_zone(img, page_role="HEADER")
    finally:
        R.detect_signature_columns = goc
        CFG.write_text(goc_cfg, encoding="utf-8")
        R._LABELS_CACHE = None          # cache la bien module, khong phai lru_cache
    check("ABSTAIN khi tắt", z3.get("has_signatures") is False and not z3.get("targets"),
          z3.get("status"))

    print("\nCA 4 — ép hỏng trên ảnh KHÔNG có vạch bảng ⇒ vẫn ABSTAIN")
    import numpy as np
    trang = np.full_like(img, 255)
    goc = ep_hong()
    try:
        z4 = R.detect_loading_plan_signature_zone(trang, page_role="HEADER")
    finally:
        R.detect_signature_columns = goc
    check("không có mốc neo thì không đoán",
          z4.get("has_signatures") is False and not z4.get("targets"), z4.get("status"))

    CFG.write_text(goc_cfg_toan_cuc, encoding="utf-8")   # tra config ve nguyen trang
    R._LABELS_CACHE = None
    print(f"\n==> {n_pass} PASS / {n_fail} FAIL")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
