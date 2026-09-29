# -*- coding: utf-8 -*-
"""
Sinh bo lieu GAN NHAN THU CONG cho zone dong LOADING_PLAN tren DUNG DUONG PRODUCTION
(anh Tang 1, resize H=2200, resolver Tang 3b — xem tools/lp_production_path.py).

KHONG chay detector Tang 4, KHONG ghi bat ky ket qua detector nao vao skeleton / crop / ten file.
Truoc khi ghi, doi chieu box voi manifest v2 chinh thuc: lech => dung (exit 1), khong ghi gi.

Xuat (thu muc moi, KHONG dung toi output/stage4_dynamic_gt/ cu):
  output/stage4_dynamic_gt_v3/skeleton.json
  output/stage4_dynamic_gt_v3/crops/<target_id>.png   crop phong to, vien mo rong ~15%, khung that ve mau xanh la
  output/stage4_dynamic_gt_v3/pages/<doc>.png         overlay toan trang (khung danh so)
  output/stage4_dynamic_gt_v3/sheets/<doc>.png        contact sheet cac crop cua 1 trang

Chay:  .venv/Scripts/python.exe tools/build_lp_prod_crops.py
"""
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import lp_production_path as lpp  # noqa: E402

OUT = ROOT / "output" / "stage4_dynamic_gt_v3"
CONTEXT_MARGIN = 0.15      # vien mo rong moi phia, theo ty le kich thuoc khung
CROP_TARGET_H = 720        # chieu cao crop sau phong to (px)
FRAME_COLOR = (0, 200, 0)  # xanh la: khong trung mau muc xanh / moc do
FRAME_THICK = 3


def slug(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d").replace("Đ", "D")
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:40]


def imwrite_u(p: Path, img):
    cv2.imencode(".png", img)[1].tofile(str(p))


def header(img, lines, bg=(40, 40, 40)):
    """Them dai tieu de ASCII phia tren anh (khong ve de len noi dung)."""
    lh = 34
    bar = np.full((lh * len(lines) + 10, img.shape[1], 3), bg, np.uint8)
    for k, t in enumerate(lines):
        cv2.putText(bar, t, (8, 28 + k * lh), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    return np.vstack([bar, img])


def make_crop(a4, box_norm):
    """Crop co vien mo rong; khung that ve NGOAI mep khung (khong de len pixel ben trong)."""
    h, w = a4.shape[:2]
    y1, x1, y2, x2 = box_norm
    bh, bw = (y2 - y1) * h, (x2 - x1) * w
    fy1, fx1, fy2, fx2 = int(round(y1 * h)), int(round(x1 * w)), int(round(y2 * h)), int(round(x2 * w))
    cy1 = max(0, int(fy1 - CONTEXT_MARGIN * bh)); cy2 = min(h, int(fy2 + CONTEXT_MARGIN * bh))
    cx1 = max(0, int(fx1 - CONTEXT_MARGIN * bw)); cx2 = min(w, int(fx2 + CONTEXT_MARGIN * bw))
    crop = a4[cy1:cy2, cx1:cx2].copy()
    sc = max(1.0, CROP_TARGET_H / max(1, crop.shape[0]))
    big = cv2.resize(crop, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)
    # toa do khung that trong crop phong to; dich ra ngoai FRAME_THICK px
    p1 = (int((fx1 - cx1) * sc) - FRAME_THICK, int((fy1 - cy1) * sc) - FRAME_THICK)
    p2 = (int((fx2 - cx1) * sc) + FRAME_THICK - 1, int((fy2 - cy1) * sc) + FRAME_THICK - 1)
    # lam mo nhe phan vien mo rong de annotator phan biet trong/ngoai khung
    mask = np.zeros(big.shape[:2], np.uint8)
    cv2.rectangle(mask, (p1[0] + FRAME_THICK, p1[1] + FRAME_THICK),
                  (p2[0] - FRAME_THICK + 1, p2[1] - FRAME_THICK + 1), 255, -1)
    faded = cv2.addWeighted(big, 0.55, np.full_like(big, 255), 0.45, 0)
    big = np.where(mask[..., None] == 255, big, faded)
    cv2.rectangle(big, p1, p2, FRAME_COLOR, FRAME_THICK)
    return big


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    pages, _ = lpp.load_all_loading_plan_pages()
    try:
        check = lpp.assert_boxes_match_manifest(pages)
    except AssertionError as e:
        print(str(e))
        sys.exit(1)
    print(f"Box khop manifest v2: {check}")

    for sub in ("crops", "pages", "sheets"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)

    skel = {
        "dataset_name": "KIDO LOADING_PLAN Dynamic Zone GT v3 — DUONG PRODUCTION",
        "version": "3.0.0-skeleton",
        "image_source": "output/stage1_out/images/form_samples (fallback output/form_samples), resize H=2200 "
                        "— chep 1-1 generate_nb4_ver2.py Cell 1+3 qua tools/lp_production_path.py",
        "zone_source": "tools.kido_pipeline.detect_loading_plan_signature_zone (-> stage3b_zone_resolver)",
        "stage3b_resolver_mtime": lpp.resolver_mtime(),
        "manifest_box_check": check,
        "crop_context_margin": CONTEXT_MARGIN,
        "note": "Chua gan nhan. Khong chua ket qua detector. Xem ANNOTATOR_GUIDE.md.",
        "pages": [],
        "targets": [],
    }

    for p in pages:
        fn, doc = p["file_name"], Path(p["file_name"]).stem
        kind = lpp.page_kind(p)
        z = p["zone"] or {}
        skel["pages"].append({
            "page_id": lpp.page_id(fn), "file_name": fn, "image_path": str(Path(p["image_path"]).relative_to(ROOT)).replace("\\", "/") if p["image_path"] else None,
            "page_role": p["page_role"], "zone_status": z.get("status") or p["read_error"],
            "page_kind": kind, "n_targets": len(z.get("targets") or []) if kind == "TARGETS" else 0,
            "needs_page_label": kind in ("PAGE_1_NO_SIGNATURES", "ZONE_ABSTAIN"),
            "page_image": f"output/stage4_dynamic_gt_v3/pages/{doc}.png",
        })
        if kind == "READ_ERROR":
            print(f"  !! {fn}: {p['read_error']}")
            continue
        a4 = p["image"]
        h, w = a4.shape[:2]
        ov = a4.copy()
        crops = []
        if kind == "TARGETS":
            for i, t in enumerate(z["targets"]):
                tid = lpp.target_id(fn, i)
                y1, x1, y2, x2 = t["box_norm"]
                cv2.rectangle(ov, (int(x1 * w), int(y1 * h)), (int(x2 * w), int(y2 * h)), FRAME_COLOR, 4)
                cv2.putText(ov, f"T{i:02d}", (int(x1 * w) + 8, int(y1 * h) + 44),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 0, 255), 4, cv2.LINE_AA)
                c = make_crop(a4, t["box_norm"])
                imwrite_u(OUT / "crops" / f"{tid}.png", header(c, [tid, slug(t["role"])]))
                crops.append((tid, t["role"], c))
                skel["targets"].append({
                    "target_id": tid, "page_id": lpp.page_id(fn), "file_name": fn,
                    "doc_type": "LOADING_PLAN", "page_role": p["page_role"], "zone_status": z.get("status"),
                    "role_index": i, "role": t["role"], "required": bool(t["required"]),
                    "expected_color": t["expected_color"], "box_norm": t["box_norm"],
                    "crop_file": f"output/stage4_dynamic_gt_v3/crops/{tid}.png",
                })
            title = [f"{doc}  page_role={p['page_role']}  {len(crops)} khung (T00..)"]
        else:
            # Khong in zone_status len anh: annotator tu xac nhan co/khong khoi ky.
            title = [f"{doc}  page_role={p['page_role']}  -> XAC NHAN: trang co khoi ky khong? (has_signature_block)"]
        imwrite_u(OUT / "pages" / f"{doc}.png", header(ov, title))

        if crops:
            hh = 520
            tiles = []
            for tid, role, c in crops:
                sc = hh / c.shape[0]
                tiles.append(header(cv2.resize(c, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA),
                                    [tid.split("__")[-1], slug(role)[:22]]))
            gap = np.full((tiles[0].shape[0], 12, 3), 255, np.uint8)
            row = tiles[0]
            for tl in tiles[1:]:
                row = np.hstack([row, gap, tl])
            imwrite_u(OUT / "sheets" / f"{doc}.png", header(row, [doc]))

    skel["total_pages"] = len(skel["pages"])
    skel["total_targets"] = len(skel["targets"])
    skel["page_kind_distribution"] = dict(Counter(pg["page_kind"] for pg in skel["pages"]))
    skel["targets_by_role"] = dict(Counter(t["role"] for t in skel["targets"]))
    skel["targets_by_required"] = {str(k): v for k, v in Counter(t["required"] for t in skel["targets"]).items()}
    (OUT / "skeleton.json").write_text(json.dumps(skel, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"pages={skel['total_pages']} {skel['page_kind_distribution']}")
    print(f"targets={skel['total_targets']} required={skel['targets_by_required']}")
    for r, n in skel["targets_by_role"].items():
        print(f"   {r}: {n}")
    print(f"-> {OUT / 'skeleton.json'}")


if __name__ == "__main__":
    main()
