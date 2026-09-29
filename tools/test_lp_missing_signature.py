# -*- coding: utf-8 -*-
"""
BO TEST TONG HOP (SYNTHETIC) — "THIEU CHU KY BAT BUOC" cho LOADING_PLAN.

VI SAO: trong GT production v4 (output/stage4_dynamic_gt_v4/gt_labeled.json) ca 32/32 o
BAT BUOC (config/stage4_lp_required_policy.json) deu da ky => tap demo KHONG kiem duoc viec
he thong bat THIEU chu ky bat buoc (engine hong bao-moi-o-da-ky cung ra DAT 14/14).
AGENTS.md 9.12.A / 9.12.F.2.

DU LIEU O DAY LA TONG HOP, KHONG PHAI ANH THAT. Anh bien the duoc tao bang cach XOA muc xanh
(chu ky) trong box cua o duoc chon tren anh Tang 1 that roi to nen. Ket qua o day chi chung
minh logic phat hien thieu + verdict + ho so tren dung kieu xoa nay — KHONG thay the anh that
thieu chu ky (van la viec mo 9.12.F.2). Moi artifact ghi `_synthetic: true`.

Cach xoa (chi trong box cua o, box = zone Tang 3b production tren anh goc):
  1. NET BUT = thanh phan lien thong cua (pixel toi | pixel xanh RONG H80-160) co >= 25% pixel
     "xanh-nhat" (xanh HSV hoac toi co B-R >= 8). Chu in den / duong ke ~0% xanh => KHONG phai but.
     (Loi net but xanh toi thuong co S~0 nen KHONG the xoa chi theo mau — ban dau lam vay va
     inpaint keo lai mau xanh, engine van thay 18-47 mm2; da bo.) Khong dung nguong engine.
  2. gom net but thanh cum (gian 1.5 mm) tren TOAN anh; cum co >= 50% net nam trong box => muc
     cua o (xoa phan trong box); cum < 50% trong box => muc TRAN tu cot ben, GIU NGUYEN;
  3. gian mask 2 px (khu vien rang cua) nhung khong an vao pixel toi KHONG thuoc net cua o;
     trong thanh phan but chi xoa pixel xanh-nhat + pixel toi cach no <= 2 px (loi but); chu in
     dinh vao net but tai diem cat duoc giu (ban dau bao ve qua it => inpaint boi nhoe chu in
     "(Ky va ghi ro ho ten)" thanh vet toi cao 6.3 mm, engine nhanh net toi bat => FN GIA; da sua);
  4. TO NEN chi tren mask bang nen giay uoc luong (loc max 9x9 roi median 41x41 cua anh goc). Da thu cv2.inpaint
     TELEA truoc: keo mau toi cua chu in vao vung xoa => vet toi cao 6.3 mm, engine bat nhu net
     tay (FN GIA do cach xoa, khong phai do engine) — da bo. Ngoai box: khong doi 1 pixel (assert).
  Phan chu ky CUA O nam ngoai box (vat qua ranh gioi cot) KHONG bi xoa — dung hop dong "chi trong box".

Nhom bien the:
  REQ1  — xoa dung 1 o required da ky (own_signature YES)          => ky vong trang/ho so KHONG DAT
  REQ2  — xoa 2 o required da ky tren cung trang                     => KHONG DAT
  REQALL— xoa moi o required (trang co 3 required: NPP / KHO_NOIBO)  => CHUA_KY_DONG_DAU
  OPT1  — xoa 1 o KHONG required da ky                               => trang/ho so VAN DAT
  (+ baseline khong xoa: phai tai lap manifest v2 chinh thuc)

Kiem (assert that, test FAIL neu sai):
  * baseline: moi trang tai lap doc_status + detected tung o cua manifest v2;
  * ngoai box xoa anh khong doi (max diff 0);
  * ver2: o bi xoa detected=False;
  * trang: REQ* != DAT (REQ1/REQ2-con-o => THIEU_MOT_SO_CHU_KY; het required => CHUA_KY_DONG_DAU);
    OPT1 => van DAT_CHUAN_GOC;
  * ho so (tools.stage4_required_policy.evaluate_lp_dossier_verdicts — ham Cell 3b generator dung):
    REQ* != DAT, OPT1 == DAT.
  Ghi so, KHONG assert: v1 tren cung bien the; o KHONG bi xoa co doi detected khong (side-effect);
  box Tang 3b tren bien the co doi khong (zone chay lai tren anh bien the, dung production).

Kenh cua trang lay tu artifact Tang 2 (output/stage2_out/stage2_classified_results.json) qua
duong production (tools/lp_production_path.load_production_page).

Xac dinh: khong co ngau nhien trong thuat toan; seed co dinh (np.random.seed) de phong; manifest
ghi md5 tung anh, chay lai phai trung (--check-determinism so voi manifest cu tren dia).

Chay:  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tools/test_lp_missing_signature.py
Ghi:   output/stage4_synthetic_missing/{images/<variant_id>/<file>.png, previews/, manifest.json, results.json}
"""
import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import lp_production_path as lpp  # noqa: E402
from tools.stage4_verifier_v2 import (  # noqa: E402
    verify_single_target as v2_verify, evaluate_document_verdict_v2, SIG_CFG)
from tools.stage4_verifier import verify_single_target as v1_verify  # noqa: E402  (chi minh hoa)
from tools.stage4_required_policy import (  # noqa: E402
    load_lp_required_policy, evaluate_lp_dossier_verdicts)

SEED = 20250927
OUT_DIR = ROOT / "output/stage4_synthetic_missing"
GT_PATH = ROOT / "output/stage4_dynamic_gt_v4/gt_labeled.json"
S3_PATH = ROOT / "output/stage3_out/stage3_batched_manifest.json"
MODES = ("FIXED_BOX", "RERUN_ZONE")

ERASE_CFG = {
    # Nhan dien NET BUT (khong dung dinh nghia mau cua engine):
    "blue_hsv_lo": (80, 30, 30),       # mau xanh RONG hon engine (90,40,40)-(145,255,255)
    "blue_hsv_hi": (160, 255, 255),
    "dark_delta": 40,                  # pixel toi hon nen giay (p90 cua box) >= 40 muc
    "bluish_b_minus_r": 8,             # pixel toi co B-R >= 8: loi net but xanh (loi but toi S~0 van hay gap)
    "pen_cc_min_bluish_frac": 0.25,    # thanh phan (toi|xanh) co >= 25% pixel xanh-nhat => net but;
                                       # chu in / duong ke: ~0% (do tren Load3.3: B-R median 0, S median 0)
    "cluster_link_mm": 1.5,            # gom net but thanh chu ky
    "own_cluster_min_inside_frac": 0.50,  # cum co < 50% net trong box => muc TRAN tu cot ben, GIU
    "halo_dilate_px": 2,               # phu vien khu rang cua quanh net
    "pen_core_px": 2,                  # pixel toi cach pixel xanh-nhat <= 2 px = loi net but; xa hon = chu in/ke
    "bg_max_ksize": 9,                 # to nen: loc MAX 9x9 (xoa net manh hon 9 px) ...
    "bg_median_ksize": 41,             # ... roi median 41x41 (~5.5 mm) => mau nen giay dia phuong
}


def md5_arr(a):
    return hashlib.md5(np.ascontiguousarray(a).tobytes()).hexdigest()


def box_px(box_norm, shape):
    h, w = shape[:2]
    y0, x0, y1, x1 = box_norm
    return (max(0, int(round(y0 * h))), max(0, int(round(x0 * w))),
            min(h, int(round(y1 * h))), min(w, int(round(x1 * w))))


def pen_mask(img, cfg):
    """Mask net but (0/1) tren toan anh: thanh phan lien thong cua (toi | xanh) co ty le pixel
    xanh-nhat >= pen_cc_min_bluish_frac. Chu in den / duong ke ~0% xanh => bi loai."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    paper = float(np.percentile(gray, 90))
    blue = cv2.inRange(hsv, np.array(cfg["blue_hsv_lo"]), np.array(cfg["blue_hsv_hi"])) > 0
    dark = gray.astype(np.int16) < paper - cfg["dark_delta"]
    bmr = img[..., 0].astype(np.int16) - img[..., 2].astype(np.int16)
    bluish = blue | (dark & (bmr >= cfg["bluish_b_minus_r"]))
    cand = (dark | blue).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    tot = np.bincount(lab.ravel(), minlength=n)
    blu = np.bincount(lab.ravel(), weights=bluish.ravel().astype(np.float64), minlength=n)
    keep = np.zeros(n, np.uint8)
    frac = np.divide(blu, np.maximum(tot, 1))
    keep[1:] = (frac[1:] >= cfg["pen_cc_min_bluish_frac"]).astype(np.uint8)
    pen = keep[lab]
    # Trong thanh phan but, CHI giu la net but: pixel xanh-nhat + pixel toi cach pixel xanh-nhat
    # <= pen_core_px (loi net but toi S~0). Pixel toi xa hon (chu in / duong ke dinh vao net but
    # tai diem cat) KHONG thuoc net but => khong bi xoa.
    cp = cfg["pen_core_px"]
    near_blue = cv2.dilate(bluish.astype(np.uint8), np.ones((2 * cp + 1, 2 * cp + 1), np.uint8)) > 0
    core = bluish | (dark & near_blue)
    protect = (pen > 0) & ~core
    pen[protect] = 0
    return pen, int(protect.sum()), blue


def erase_boxes(img, boxes):
    """Xoa net but cua o trong tung box (giu muc tran tu cot ben, chu in, duong ke). Tra
    (anh moi, thong ke tung box, max diff ngoai box)."""
    cfg = ERASE_CFG
    h, w = img.shape[:2]
    ppm = max(h, w) / SIG_CFG["a4_long_edge_mm"]
    pen, n_protect_all, _ = pen_mask(img, cfg)
    k = max(1, int(round(cfg["cluster_link_mm"] * ppm)))
    grown = cv2.dilate(pen, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    _, lab = cv2.connectedComponents(grown, connectivity=8)
    lab = lab * pen
    gtot = np.bincount(lab.ravel())
    stats = []
    full_mask = np.zeros((h, w), np.uint8)
    inside_any = np.zeros((h, w), bool)
    for bn in boxes:
        y0, x0, y1, x1 = box_px(bn, img.shape)
        inside_any[y0:y1, x0:x1] = True
        sub = lab[y0:y1, x0:x1]
        ids, cnt_in = np.unique(sub[sub > 0], return_counts=True)
        own_ids, kept_px, own_px = [], 0, 0
        for cid, ci in zip(ids, cnt_in):
            if ci / gtot[cid] >= cfg["own_cluster_min_inside_frac"]:
                own_ids.append(int(cid))
                own_px += int(ci)
            else:
                kept_px += int(ci)
        sel = np.isin(sub, own_ids).astype(np.uint8) if own_ids else np.zeros_like(sub, np.uint8)
        d = cfg["halo_dilate_px"]
        if d > 0 and sel.any():
            sel = cv2.dilate(sel, cv2.getStructuringElement(cv2.MORPH_RECT, (2 * d + 1, 2 * d + 1)))
            # vien gian khong duoc an vao net KHONG phai cua o (chu in toi / muc tran giu lai)
            g = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
            paper = float(np.percentile(g, 90))
            not_own_dark = (g.astype(np.int16) < paper - cfg["dark_delta"]) & ~np.isin(sub, own_ids)
            sel[not_own_dark] = 0
        full_mask[y0:y1, x0:x1] |= sel
        stats.append({"box_px": [y0, x0, y1, x1], "own_pen_groups": len(own_ids),
                      "own_pen_px_erased": own_px, "neighbor_pen_px_kept_in_box": kept_px,
                      "mask_px": int(sel.sum())})
    out = img.copy()
    if full_mask.any():
        # TO NEN: nen giay uoc luong bang median lon (net but/chu in mong << nua cua so) — KHONG dung
        # cv2.inpaint vi TELEA keo mau toi cua chu in ke ben vao vung xoa (vet nhoe gia net tay).
        mk = cfg["bg_max_ksize"]
        bg = cv2.medianBlur(cv2.dilate(img, np.ones((mk, mk), np.uint8)), cfg["bg_median_ksize"])
        out = img.copy()
        out[full_mask.astype(bool)] = bg[full_mask.astype(bool)]
        m = ~full_mask.astype(bool)
        out[m] = img[m]  # chi doi pixel trong mask
    diff_out = int(np.abs(out.astype(np.int16) - img.astype(np.int16))[~inside_any].max()) if (~inside_any).any() else 0
    hsv2 = cv2.cvtColor(out, cv2.COLOR_BGR2HSV)
    eng = cv2.inRange(hsv2, np.array(SIG_CFG["blue_hsv_lo"]), np.array(SIG_CFG["blue_hsv_hi"])) > 0
    for s in stats:
        y0, x0, y1, x1 = s["box_px"]
        s["residual_blue_px_engine_range"] = int(eng[y0:y1, x0:x1].sum())
        s["original_blue_px_engine_range"] = int((cv2.inRange(cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV),
                                                              np.array(SIG_CFG["blue_hsv_lo"]),
                                                              np.array(SIG_CFG["blue_hsv_hi"])) > 0).sum())
    return out, stats, diff_out



def run_page(fn, s2_map, image_dir=None, fixed_page=None):
    """Chay 1 trang theo duong production (lpp.load_production_page), anh lay tu image_dir neu co.
    fixed_page (che do FIXED_BOX): KHONG chay lai zone Tang 3b — dung nguyen zone/targets (da ap
    chinh sach kenh) cua trang goc, chi thay anh + do lai modality. Tra ban ghi trang theo schema
    Cell 3 ver2 (+ v1 de minh hoa)."""
    if fixed_page is None:
        old = lpp.STAGE1_DIR
        try:
            if image_dir is not None:
                lpp.STAGE1_DIR = Path(image_dir)
                assert (lpp.STAGE1_DIR / fn).exists(), f"thieu anh bien the {image_dir}/{fn}"
            p = lpp.load_production_page(fn, s2_map)
        finally:
            lpp.STAGE1_DIR = old
        if image_dir is not None:
            assert Path(p["image_path"]).parent == Path(image_dir), "doc nham anh goc thay vi bien the"
    else:
        raw = cv2.imread(str(Path(image_dir) / fn))
        scale = float(lpp.TARGET_H) / raw.shape[0]
        a4 = cv2.resize(raw, (int(raw.shape[1] * scale), lpp.TARGET_H))   # nhu Cell 3
        p = dict(fixed_page, image=a4, image_path=str(Path(image_dir) / fn))
        if lpp.page_kind(p) == "TARGETS":
            mod = lpp.detect_document_modality(a4)["modality"]
            p["modality"], p["is_color"] = mod, (mod == "TRUE_COLOR")
    rec = {"file_name": fn, "doc_type": p["doc_type"], "system": p["system"], "page_role": p["page_role"],
           "zone_status": (p["zone"] or {}).get("status"), "modality": p["modality"], "targets": [],
           "doc_status": None, "action": None, "reason": None, "v1_detected": []}
    kind = lpp.page_kind(p)
    if kind == "PAGE_1_NO_SIGNATURES":
        rec.update(doc_status="TRANG_1_CHUA_KY", action="HOP_LE", modality="N/A")
        return rec, p
    if kind != "TARGETS":
        rec.update(doc_status="CHUA_CHUAN_HOA_VUNG_KY", action="ABSTAIN", modality="N/A")
        return rec, p
    for t in p["zone"]["targets"]:
        r2 = v2_verify(p["image"], lpp.prepare_v2_target(t), is_color=p["is_color"])
        r1 = v1_verify(p["image"], lpp.prepare_v1_target(t), is_color=p["is_color"])
        rec["targets"].append({
            "role": t["role"], "required": t["required"], "required_source": t.get("required_source"),
            "policy_channel": t.get("policy_channel"), "box_norm": [round(float(v), 4) for v in t["box_norm"]],
            "expected_color": t.get("expected_color"), "detected": bool(r2.get("detected")),
            "evidence": r2.get("evidence"), "reason": r2.get("reason"),
            "review_required": bool(r2.get("review_required", False)),
            "blue_own_mm2": r2.get("blue_own_mm2"), "blue_edge_mm2": r2.get("blue_edge_mm2"),
            "dark_stroke_mm2": r2.get("dark_stroke_mm2")})
        rec["v1_detected"].append(bool(r1.get("detected")))
    st, act, why = evaluate_document_verdict_v2(rec["targets"], is_color=p["is_color"])
    rec.update(doc_status=st, action=act, reason=why)
    return rec, p



def dossier_of(page_records, s3, pol, fn):
    res = evaluate_lp_dossier_verdicts(page_records, s3, evaluate_document_verdict_v2, pol)
    for d in res["dossiers"]:
        if fn in d["pages"]:
            return d
    raise AssertionError(f"khong tim thay ho so chua {fn}")


def preview(orig, var, boxes, path):
    """Anh so sanh (goc | bien the) vung khoi ky de soi bang mat."""
    ys = [box_px(b, orig.shape) for b in boxes]
    y0 = max(0, min(b[0] for b in ys) - 60)
    y1 = min(orig.shape[0], max(b[2] for b in ys) + 60)
    x0 = max(0, min(b[1] for b in ys) - 300)
    x1 = min(orig.shape[1], max(b[3] for b in ys) + 300)
    a, b = orig[y0:y1, x0:x1].copy(), var[y0:y1, x0:x1].copy()
    for (by0, bx0, by1, bx1) in ys:
        cv2.rectangle(b, (bx0 - x0, by0 - y0), (bx1 - x0 - 1, by1 - y0 - 1), (0, 0, 255), 1)
    sep = np.full((a.shape[0], 8, 3), 255, np.uint8)
    cv2.imwrite(str(path), np.hstack([a, sep, b]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-determinism", action="store_true",
                    help="so md5 anh sinh ra voi manifest.json dang co tren dia (phai trung)")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    np.random.seed(SEED)
    t0 = time.time()
    old_manifest = None
    if args.check_determinism:
        mp = OUT_DIR / "manifest.json"
        assert mp.exists(), "--check-determinism can manifest.json cu"
        old_manifest = json.loads(mp.read_text(encoding="utf-8"))

    s2_map = lpp.load_stage2_map()
    pol = load_lp_required_policy()
    s3 = json.loads(S3_PATH.read_text(encoding="utf-8"))
    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))
    gt_by = {(t["file_name"], t["role"]): t for t in gt["targets"]}
    manifest_v2 = lpp.load_manifest_v2()
    mdocs = {d["file_name"]: d for d in manifest_v2["documents"] if d.get("doc_type") == "LOADING_PLAN"}

    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)
        return cond

    # ---------------- baseline ----------------
    files = lpp.list_loading_plan_files(s2_map)
    base, base_pages = {}, {}
    for fn in files:
        rec, p = run_page(fn, s2_map)
        base[fn], base_pages[fn] = rec, p
    lpp.assert_boxes_match_manifest(list(base_pages.values()), manifest_v2)
    for fn in files:
        md = mdocs[fn]
        check(base[fn]["doc_status"] == md["doc_status"],
              f"BASELINE {fn}: doc_status {base[fn]['doc_status']} != manifest {md['doc_status']}")
        for i, (a, b) in enumerate(zip(base[fn]["targets"], md.get("targets", []))):
            check(a["detected"] == bool(b["detected"]), f"BASELINE {fn} T{i:02d}: detected lech manifest")
    sig_pages = [fn for fn in files if base[fn]["targets"]]
    print(f"Baseline: {len(files)} trang LP, {len(sig_pages)} trang co khoi ky; "
          f"doc_status {dict(Counter(base[f]['doc_status'] for f in files))}")

    # ---------------- chon o ----------------
    cells = []  # (fn, idx, role, required, own_signature, overflow, channel)
    for fn in sig_pages:
        for i, t in enumerate(base[fn]["targets"]):
            g = gt_by.get((fn, t["role"]))
            check(g is not None, f"GT thieu o {fn}/{t['role']}")
            cells.append({"file_name": fn, "idx": i, "role": t["role"], "required": t["required"],
                          "own_signature": g["own_signature"] if g else None,
                          "overflow_gt": g.get("overflow") if g else None,
                          "box_changed_gt": g.get("box_changed") if g else None,
                          "channel": t["policy_channel"], "system": base[fn]["system"],
                          "base_detected": t["detected"]})
    req_yes = [c for c in cells if c["required"] and c["own_signature"] == "YES"]
    req_no = [c for c in cells if c["required"] and c["own_signature"] != "YES"]
    opt_yes = [c for c in cells if (not c["required"]) and c["own_signature"] == "YES"]
    print(f"O ky: {len(cells)} | required YES {len(req_yes)} / required khac YES {len(req_no)} | "
          f"optional YES {len(opt_yes)}")

    variants = []
    for c in req_yes:
        variants.append(("REQ1", c["file_name"], [c["idx"]]))
    by_page_req = defaultdict(list)
    for c in req_yes:
        by_page_req[c["file_name"]].append(c["idx"])
    for fn in sorted(by_page_req):
        idxs = sorted(by_page_req[fn])
        n_req_page = sum(1 for t in base[fn]["targets"] if t["required"])
        if len(idxs) >= 2 and n_req_page > 2:
            variants.append(("REQ2", fn, idxs[:2]))
        if len(idxs) >= 2 and len(idxs) == n_req_page:
            variants.append(("REQALL", fn, idxs))
    for c in opt_yes:
        variants.append(("OPT1", c["file_name"], [c["idx"]]))

    img_root = OUT_DIR / "images"
    prev_root = OUT_DIR / "previews"
    img_root.mkdir(parents=True, exist_ok=True)
    prev_root.mkdir(parents=True, exist_ok=True)
    base_list = [base[f] for f in files]

    man_variants, results = [], []
    DAT = ("DAT_CHUAN_GOC", "DAT_CHUAN_PHOTO")
    for kind, fn, idxs in variants:
        vid = f"{kind}__{Path(fn).stem}__" + "_".join(f"T{i:02d}" for i in idxs)
        orig = base_pages[fn]["image"]
        src = cv2.imread(base_pages[fn]["image_path"])
        check(src.shape == orig.shape, f"{vid}: anh Tang 1 khong phai H=2200 nhu gia dinh")
        boxes = [base[fn]["targets"][i]["box_norm"] for i in idxs]
        var, estats, diff_out = erase_boxes(src, boxes)
        check(diff_out == 0, f"{vid}: anh bi doi ngoai box (max diff {diff_out})")
        vdir = img_root / vid
        vdir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(vdir / fn), var)
        reread = cv2.imread(str(vdir / fn))
        check(np.array_equal(reread, var), f"{vid}: PNG ghi/doc khong lossless")
        preview(src, var, boxes, prev_root / f"{vid}.png")
        man_variants.append({"variant_id": vid, "kind": kind, "file_name": fn, "source_image": str(
            Path(base_pages[fn]["image_path"]).relative_to(ROOT)).replace("\\", "/"),
            "image": str((vdir / fn).relative_to(ROOT)).replace("\\", "/"), "md5": md5_arr(var),
            "erased_targets": [{"idx": i, "role": base[fn]["targets"][i]["role"],
                                "required": base[fn]["targets"][i]["required"],
                                "box_norm": base[fn]["targets"][i]["box_norm"], **st}
                               for i, st in zip(idxs, estats)]})

        n_req_left = sum(1 for i, t in enumerate(base[fn]["targets"]) if t["required"] and i not in idxs)
        if kind == "OPT1":
            exp_page, exp_dossier_dat = "DAT_CHUAN_GOC", True
        elif n_req_left == 0:
            exp_page, exp_dossier_dat = "CHUA_KY_DONG_DAU", False
        else:
            exp_page, exp_dossier_dat = "THIEU_MOT_SO_CHU_KY", False

        for mode in MODES:
            rec, p = run_page(fn, s2_map, image_dir=vdir,
                              fixed_page=base_pages[fn] if mode == "FIXED_BOX" else None)
            boxes_same = (len(rec["targets"]) == len(base[fn]["targets"]) and all(
                a["box_norm"] == b["box_norm"] for a, b in zip(rec["targets"], base[fn]["targets"])))
            pages_for_dossier = [rec if r["file_name"] == fn else r for r in base_list]
            dv = dossier_of(pages_for_dossier, s3, pol, fn)
            erased = []
            for i in idxs:
                t = rec["targets"][i] if i < len(rec["targets"]) else None
                c = next(c for c in cells if c["file_name"] == fn and c["idx"] == i)
                erased.append({"idx": i, "role": c["role"], "required": c["required"], "channel": c["channel"],
                               "overflow_gt": c["overflow_gt"],
                               "box_norm_eval": None if t is None else t["box_norm"],
                               "v2_detected": None if t is None else t["detected"],
                               "v2_evidence": None if t is None else t["evidence"],
                               "v2_reason": None if t is None else t["reason"],
                               "v1_detected": None if t is None else rec["v1_detected"][i]})
            others_changed = [f"T{i:02d}:{b['detected']}->{a['detected']}" for i, (a, b) in
                              enumerate(zip(rec["targets"], base[fn]["targets"])) if i not in idxs
                              and a["detected"] != b["detected"]] if boxes_same else []
            v1_targets = [dict(t, detected=d1, review_required=False)
                          for t, d1 in zip(rec["targets"], rec["v1_detected"])]
            v1_status = evaluate_document_verdict_v2(v1_targets, is_color=True)[0] if v1_targets else None
            tag = f"[{mode}] {vid}"
            if mode == "FIXED_BOX":
                # Tang 4 + verdict + ho so, hinh hoc co dinh: kiem CHAT
                check(all(e["v2_detected"] is False for e in erased),
                      f"{tag}: ver2 van bao da ky o bi xoa: "
                      + ", ".join(f"{e['role']}[{e['v2_evidence']}]" for e in erased if e["v2_detected"] is not False))
                check(rec["doc_status"] == exp_page, f"{tag}: trang {rec['doc_status']} != ky vong {exp_page}")
                check((dv["doc_status"] in DAT) == exp_dossier_dat,
                      f"{tag}: ho so {dv['doc_status']} (ky vong {'DAT' if exp_dossier_dat else 'KHONG DAT'})")
                check(not others_changed, f"{tag}: o KHONG bi xoa doi detected {others_changed}")
            else:
                # Duong production day du (zone chay lai tren anh bien the): thieu required
                # KHONG BAO GIO duoc ra DAT (ABSTAIN chap nhan duoc — an toan, dem rieng).
                if kind != "OPT1":
                    check(rec["doc_status"] not in DAT, f"{tag}: trang {rec['doc_status']} — thieu required ma DAT")
                    check(dv["doc_status"] not in DAT, f"{tag}: ho so {dv['doc_status']} — thieu required ma DAT")
            results.append({"mode": mode, "variant_id": vid, "kind": kind, "file_name": fn,
                            "system": rec["system"], "channel": erased[0]["channel"],
                            "boxes_unchanged_after_erase": boxes_same, "zone_status": rec["zone_status"],
                            "erased": erased, "page_status": rec["doc_status"], "page_reason": rec["reason"],
                            "expected_page_status": exp_page,
                            "dossier_id": dv["dossier_id"], "dossier_pages": dv["pages"],
                            "dossier_status": dv["doc_status"], "dossier_reason": dv["reason"],
                            "expected_dossier_dat": exp_dossier_dat,
                            "v2_other_cells_changed": others_changed,
                            "v1_page_status_illustrative": v1_status})
            good = (rec["doc_status"] == exp_page and dv["doc_status"] not in DAT) if kind != "OPT1" else \
                (rec["doc_status"] in DAT and dv["doc_status"] in DAT)
            lbl = "OK " if good else ("ABS" if rec["doc_status"] == "CHUA_CHUAN_HOA_VUNG_KY" else "ERR")
            print(f"[{lbl}] {mode:10s} {vid:44s} {rec['system']:18s} trang={rec['doc_status']:22s} "
                  f"ho_so={dv['doc_status']:22s} v2_xoa={[e['v2_detected'] for e in erased]} "
                  f"v1_xoa={[e['v1_detected'] for e in erased]}" + ("" if boxes_same else "  [BOX DOI]")
                  + (f"  [o khac doi {others_changed}]" if others_changed else ""))

    # ---------------- tong hop ----------------
    summ = {"n_variants": len(man_variants), "by_kind": dict(Counter(v["kind"] for v in man_variants)),
            "required_cells_not_YES_in_gt": len(req_no)}
    for mode in MODES:
        R = [r for r in results if r["mode"] == mode]
        S = {}
        req_rows = [(r, e) for r in R if r["kind"] != "OPT1" for e in r["erased"]]
        opt_rows = [(r, e) for r in R if r["kind"] == "OPT1" for e in r["erased"]]
        for eng in ("v2", "v1"):
            by_role, by_ch, tot = defaultdict(Counter), defaultdict(Counter), Counter()
            for r, e in req_rows:
                d = e[f"{eng}_detected"]
                tg = "TP_missing_detected" if d is False else ("NO_CELL_zone_abstain_or_box_lost" if d is None
                                                               else "FN_still_signed")
                by_role[e["role"]][tg] += 1
                by_ch[e["channel"]][tg] += 1
                tot[tg] += 1
            S[f"{eng}_erased_required_cells_total"] = dict(tot)
            S[f"{eng}_erased_required_cells_by_role"] = {k: dict(v) for k, v in by_role.items()}
            S[f"{eng}_erased_required_cells_by_channel"] = {k: dict(v) for k, v in by_ch.items()}
            S[f"{eng}_erased_optional_cells"] = dict(Counter(
                "not_detected" if e[f"{eng}_detected"] is False else
                ("no_cell" if e[f"{eng}_detected"] is None else "still_detected") for _, e in opt_rows))
        S["page_status_by_kind"] = {k: dict(Counter(r["page_status"] for r in R if r["kind"] == k))
                                    for k in summ["by_kind"]}
        S["dossier_status_by_kind"] = {k: dict(Counter(r["dossier_status"] for r in R if r["kind"] == k))
                                       for k in summ["by_kind"]}
        S["v1_page_status_illustrative_by_kind"] = {
            k: dict(Counter(str(r["v1_page_status_illustrative"]) for r in R if r["kind"] == k))
            for k in summ["by_kind"]}
        S["variants_box_changed_after_erase"] = [r["variant_id"] for r in R if not r["boxes_unchanged_after_erase"]]
        S["variants_zone_abstain"] = [r["variant_id"] for r in R if r["page_status"] == "CHUA_CHUAN_HOA_VUNG_KY"]
        S["v2_other_cells_changed"] = {r["variant_id"]: r["v2_other_cells_changed"]
                                       for r in R if r["v2_other_cells_changed"]}
        S["v2_still_signed_cells"] = [{"variant_id": r["variant_id"], **e} for r, e in req_rows + opt_rows
                                      if e["v2_detected"] is True]
        S["required_missing_but_page_DAT"] = [r["variant_id"] for r in R if r["kind"] != "OPT1"
                                              and r["page_status"] in DAT]
        S["required_missing_but_dossier_DAT"] = [r["variant_id"] for r in R if r["kind"] != "OPT1"
                                                 and r["dossier_status"] in DAT]
        summ[mode] = S

    manifest = {
        "_synthetic": True,
        "_warning": ("DU LIEU TONG HOP: anh bien the tao bang cach xoa muc xanh trong box o ky tren anh Tang 1 that. "
                     "KHONG phai anh that thieu chu ky; khong dung lam GT do chinh xac tong quat."),
        "generator": "tools/test_lp_missing_signature.py", "seed": SEED, "erase_cfg": ERASE_CFG,
        "source_gt": str(GT_PATH.relative_to(ROOT)).replace("\\", "/"),
        "source_stage2": str(lpp.STAGE2_PATH.relative_to(ROOT)).replace("\\", "/"),
        "source_stage3": str(S3_PATH.relative_to(ROOT)).replace("\\", "/"),
        "n_variants": len(man_variants), "variants": man_variants,
    }
    if old_manifest is not None:
        old = {v["variant_id"]: v["md5"] for v in old_manifest["variants"]}
        new = {v["variant_id"]: v["md5"] for v in man_variants}
        diff = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
        check(not diff, f"DETERMINISM: {len(diff)} bien the md5 khac lan truoc: {diff[:5]}")
        print(f"Determinism: {len(new)} bien the, {len(diff)} khac md5 so voi manifest cu")
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "results.json").write_text(json.dumps({"_synthetic": True, "summary": summ, "variants": results},
                                                     ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== TONG HOP (DU LIEU TONG HOP) ===")
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    print(f"\nThoi gian {time.time() - t0:.1f}s")
    if failures:
        print(f"\nFAIL: {len(failures)} kiem tra")
        for f in failures:
            print("  - " + f)
        return 1
    print(f"\nPASS: tat ca kiem tra dat ({len(man_variants)} bien the x {len(MODES)} che do = {len(results)} lan danh gia)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
