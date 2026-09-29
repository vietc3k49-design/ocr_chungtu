# -*- coding: utf-8 -*-
"""
Test suite BAT BIEN cho Tang 3b — vung ky dong LOADING_PLAN.

Cac ca o day khong phu thuoc thuat toan do cot duoc chon. Chung khoa lai
nhung tinh chat ma BAT KY ban cai dat nao cung phai giu, de mot thay doi
hinh hoc ve sau khong am tham pha hop dong hoac pha cac ket qua da dung.

Chay:  .venv/Scripts/python.exe tools/test_stage3b_zone_suite.py
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

GT_FILE = ROOT / "output/stage4_dynamic_gt/gt_labeled.json"
SAMPLES = ROOT / "output/form_samples"

RESULTS = []


def check(name, cond, detail="", known_limit=False):
    """known_limit=True: GIOI HAN DA DO VA DA GIAI THICH (cung quy uoc voi
    test_v2_signature_unit.py). Van in ket qua that; khong lam do suite. Moi ca
    known_limit PHAI di kem mot ca cung (hard) chan tran, de gioi han khong the
    am tham to ra."""
    ok = bool(cond)
    RESULTS.append((name, ok, detail, known_limit))
    tag = "[PASS]" if ok else ("[KNOWN-LIMIT]" if known_limit else "[FAIL]")
    print(f"{tag} {name}" + (f"  -- {detail}" if detail else ""))
    return ok


def load_resolver():
    """Uu tien module tach rieng; chua co thi dung ban trong kido_pipeline."""
    try:
        from tools.stage3b_zone_resolver import detect_loading_plan_signature_zone as f
        return f, "tools.stage3b_zone_resolver"
    except Exception:
        from tools.kido_pipeline import detect_loading_plan_signature_zone as f
        return f, "tools.kido_pipeline (module tach rieng CHUA co)"


def imread_u(p):
    return cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)


REQUIRED_ZONE_KEYS = {"has_signatures", "anchor_y", "status", "description", "targets"}
REQUIRED_TARGET_KEYS = {"role", "box_norm", "required", "expected_color"}


def main():
    detect, src = load_resolver()
    print(f"Nguon ham zone: {src}\n")

    gt = json.loads(GT_FILE.read_text(encoding="utf-8"))
    docs = {}
    for t in gt["targets"]:
        docs.setdefault(t["file_name"], {"page_role": t["page_role"], "targets": []})
        docs[t["file_name"]]["targets"].append(t)

    zones = {}
    for fn, info in sorted(docs.items()):
        img = imread_u(SAMPLES / fn)
        zones[fn] = (img, detect(img, page_role=info["page_role"]))

    # --- CA 1: hop dong tra ve ---------------------------------------------
    bad = [fn for fn, (_, z) in zones.items() if not REQUIRED_ZONE_KEYS <= set(z)]
    check("CA 1: du khoa hop dong cap zone", not bad, f"thieu khoa o: {bad}" if bad else f"{len(zones)} anh OK")

    bad = []
    for fn, (_, z) in zones.items():
        for t in z.get("targets", []):
            if not REQUIRED_TARGET_KEYS <= set(t):
                bad.append((fn, sorted(REQUIRED_TARGET_KEYS - set(t))))
    check("CA 2: du khoa hop dong cap target", not bad, f"thieu: {bad[:3]}" if bad else "OK")

    # --- CA 3: box_norm hop le ---------------------------------------------
    bad = []
    for fn, (_, z) in zones.items():
        for t in z.get("targets", []):
            y1, x1, y2, x2 = t["box_norm"]
            if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
                bad.append((fn, t["role"], t["box_norm"]))
    check("CA 3: box_norm nam trong [0,1] va y1<y2, x1<x2", not bad,
          f"vi pham: {bad[:3]}" if bad else "OK")

    # --- CA 4: cac cot KHONG duoc chong lan nhau ---------------------------
    # Day chinh la loi da do duoc: cot lech trai -> chu ky cot ben canh tran sang.
    OVERLAP_TOL = 0.001
    bad = []
    for fn, (_, z) in zones.items():
        ts = sorted(z.get("targets", []), key=lambda t: t["box_norm"][1])
        for a, b in zip(ts, ts[1:]):
            if a["box_norm"][3] > b["box_norm"][1] + OVERLAP_TOL:
                bad.append(f"{fn}: {a['role'][:14]}.x2={a['box_norm'][3]:.3f} > {b['role'][:14]}.x1={b['box_norm'][1]:.3f}")
    check("CA 4: cac cot lien ke KHONG chong lan", not bad,
          f"{len(bad)} cap chong lan: {bad[:2]}" if bad else "0 cap chong lan")

    # --- CA 5: cac trang khong co khoi ky van duoc nhan dung ---------------
    # [SUA 27/09 - hop dong MOI] `has_signatures == False` nay mang HAI nghia
    # khac han nhau, phai tach ra moi kiem dung duoc:
    #   (a) PAGE_1_NO_SIGNATURES  -> trang that su KHONG CO khoi ky (mien tru
    #       Trang 1 da trang). Day moi la thu CA 5 goc muon do.
    #   (b) ABSTAIN_STATUSES      -> trang CO khoi ky nhung khong DO duoc ranh
    #       gioi cot, nen tra targets=[] de Tang 4 ABSTAIN. Day la hanh vi DUNG
    #       theo thiet ke (docs/STAGE3B_COLUMN_FIX_PLAN.md muc 4), thay cho viec
    #       roi ve bo hang so cu - tuc la thay mot PASS gia bang mot ABSTAIN that.
    # Gop chung hai nhom nhu ban cu se bat test FAIL dung luc he thong cu xu DUNG,
    # hoac (te hon) ep nguoi sua quay lai silent fallback de test xanh.
    ABSTAIN_STATUSES = {"COLUMN_DETECTION_FAILED", "COLUMN_ORDER_VIOLATION",
                        "COLUMN_PITCH_IMPLAUSIBLE", "COLUMN_OCR_UNAVAILABLE",
                        "COLUMN_LABELS_UNAVAILABLE", "TABLE_ANCHOR_NOT_FOUND"}
    exp_none = {fn for fn, i in docs.items()
                if any(t["expected_presence"] == "NO_SIGNATURE_BLOCK" for t in i["targets"])}
    got_none = {fn for fn, (_, z) in zones.items()
                if not z["has_signatures"] and z.get("status") not in ABSTAIN_STATUSES}
    abstained = {fn for fn, (_, z) in zones.items()
                 if not z["has_signatures"] and z.get("status") in ABSTAIN_STATUSES}
    check("CA 5: nhan dung 5 trang khong co khoi ky (khong them, khong bot)",
          exp_none == got_none,
          f"ky vong {sorted(exp_none)} != thuc te {sorted(got_none)}" if exp_none != got_none
          else f"{len(exp_none)}/{len(exp_none)} dung; ngoai ra {len(abstained)} anh ABSTAIN: {sorted(abstained)}")

    # CA 5c: tran so ABSTAIN. ABSTAIN la hanh vi dung khi khong do duoc, nhung
    # neu so anh ABSTAIN tang len thi do la hoi quy do cot, khong duoc lang le
    # chap nhan. Tran = SO DO THAT ngay 27/09 sau giai doan 2 (resolver chay o
    # H=2200 ben trong, nen anh goc va anh production cho CUNG ket qua):
    #   1 anh - Loading_Plan_2.2__0 (OCR chi khop 2/5 nhan: "TRUONG DP", "NGUOI
    #   GIEE/", "THA KHO" duoi nguong fuzz 75). Truoc giai doan 2, o anh goc ca
    #   ABSTAIN la Load_3.5__0, o H=2200 la Loading_Plan_2.2__0 - cung la 1.
    # KHONG nang tran de test xanh. Tran giam duoc thi ha xuong.
    MAX_ABSTAIN = 1
    check(f"CA 5c: so anh ABSTAIN <= {MAX_ABSTAIN} (tran do that, khong noi)",
          len(abstained) <= MAX_ABSTAIN,
          f"{len(abstained)} anh ABSTAIN: {sorted(abstained)}")

    # CA 5b: ABSTAIN phai TUONG MINH - co ma trang thai trong danh sach da cong bo
    # va tuyet doi khong kem theo target nao.
    bad = [(fn, z.get("status")) for fn, (_, z) in zones.items()
           if not z["has_signatures"] and z.get("targets")]
    check("CA 5b: zone khong co chu ky thi targets phai rong", not bad, f"{bad}" if bad else "OK")

    # --- CA 6: tap vai tro khop ground truth --------------------------------
    # Chi ap cho cac anh MA detector KHONG abstain. Anh abstain da duoc CA 5/5b
    # kiem rieng; doi hoi no van tra du 5 vai tro chinh la doi hoi silent fallback.
    bad = []
    for fn, info in docs.items():
        if fn in abstained:
            continue
        gt_roles = {t["role"] for t in info["targets"] if t["role"]}
        new_roles = {t["role"] for t in zones[fn][1].get("targets", [])}
        if gt_roles != new_roles:
            bad.append((fn, sorted(gt_roles ^ new_roles)))
    check("CA 6: tap vai tro trung khop ground truth (tru anh ABSTAIN)", not bad,
          f"lech o {len(bad)} anh: {bad[:2]}" if bad else
          f"OK tren {len(docs) - len(abstained)}/{len(docs)} anh")

    # --- CA 7: tinh xac dinh -------------------------------------------------
    bad = []
    for fn, (img, z1) in zones.items():
        z2 = detect(img.copy(), page_role=docs[fn]["page_role"])
        if json.dumps(z1, sort_keys=True, default=str) != json.dumps(z2, sort_keys=True, default=str):
            bad.append(fn)
    check("CA 7: tinh xac dinh — goi 2 lan cho ket qua giong het", not bad,
          f"khac nhau o: {bad}" if bad else f"{len(zones)} anh on dinh")

    # --- CA 8: khong sua anh dau vao + khong co kenh nhan ten file ----------
    # [SUA 27/09 giai doan 2] Ban cu cua CA 8 goi lai detect() tren cung pixel -
    # TRUNG HOAN TOAN voi CA 7 (tinh xac dinh), khong kiem them dieu gi. Thay bang
    # 2 tinh chat co y nghia:
    #  (a) resolver KHONG sua anh cua caller. Can thiet vi tu giai doan 2, anh H=2200
    #      di qua _to_working_height NGUYEN VEN (cung mot mang) - neu co buoc nao ve
    #      len anh thi se lam ban anh cua Tang 4. Kiem ca anh goc lan anh H=2200.
    #  (b) khong doc ten file la tinh chat CAU TRUC: chu ky ham chi nhan pixel va
    #      page_role, khong co tham so ten/duong dan nao.
    import inspect
    fn0 = sorted(zones)[0]
    img0 = zones[fn0][0]
    s2200 = 2200.0 / img0.shape[0]
    variants = {"goc": img0.copy(),
                "H2200": cv2.resize(img0, (int(img0.shape[1] * s2200), 2200))}
    mutated = []
    for tag, im in variants.items():
        before = im.copy()
        detect(im, page_role=docs[fn0]["page_role"])
        if not np.array_equal(before, im):
            mutated.append(tag)
    params = set(inspect.signature(detect).parameters)
    leaky = sorted(p for p in params if any(k in p.lower() for k in ("file", "path", "name")))
    check("CA 8: khong sua anh dau vao; chu ky ham khong co tham so ten file",
          not mutated and not leaky,
          f"sua anh o {mutated}; tham so nghi van {leaky}" if (mutated or leaky)
          else f"{fn0} (goc + H2200) khong doi pixel; tham so = {sorted(params)}")

    # --- CA 9: dau vao suy bien khong lam sap -------------------------------
    degenerate = [np.zeros((10, 10, 3), np.uint8),
                  np.full((50, 50, 3), 255, np.uint8),
                  np.random.RandomState(0).randint(0, 255, (80, 60, 3), dtype=np.uint8)]
    err = None
    for d in degenerate:
        try:
            r = detect(d, page_role="HEADER")
            if not REQUIRED_ZONE_KEYS <= set(r):
                err = "thieu khoa hop dong tren anh suy bien"
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
    check("CA 9: anh suy bien (den/trang/nhieu) khong crash, van du hop dong", err is None, err or "3 dang OK")

    # --- CA 10: khong co silent fallback ------------------------------------
    # Khi khong do duoc, status phai noi ro; khong duoc tra ve hop mac dinh
    # ma van bao thanh cong. Kiem: moi zone co targets thi status phai khac rong.
    bad = [fn for fn, (_, z) in zones.items()
           if z.get("targets") and not str(z.get("status") or "").strip()]
    check("CA 10: moi zone co target deu mang status tuong minh", not bad,
          f"status rong o: {bad}" if bad else "OK")

    # --- CA 11: BAT BIEN DO PHAN GIAI (giai doan 2) --------------------------
    scale_invariance_cases(detect, docs)

    # --- CA 12-14: cac nhanh ABSTAIN tuong minh ------------------------------
    abstain_edge_cases(detect, zones, docs)

    print()
    real_fail = [n for n, ok, _, kl in RESULTS if not ok and not kl]
    known = [n for n, ok, _, kl in RESULTS if not ok and kl]
    passed = sum(1 for _, ok, _, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"{passed}/{total} PASSED" + (f" | {len(known)} KNOWN-LIMIT" if known else "")
          + (f" | {len(real_fail)} FAIL" if real_fail else ""))
    sys.exit(1 if real_fail else 0)


SCALE_TOL = 0.01


def _scaled_variants(raw):
    """0.5x goc (INTER_AREA), goc, H=2200 va H=3000 (INTER_LINEAR nhu runner ver2)."""
    h, w = raw.shape[:2]
    out = {"x0.5": cv2.resize(raw, (int(w * 0.5), int(h * 0.5)), interpolation=cv2.INTER_AREA),
           "goc": raw}
    for H in (2200, 3000):
        out[f"H{H}"] = cv2.resize(raw, (int(w * H / h), H))
    return out


def scale_invariance_cases(detect, docs):
    """Cung mot trang o 4 ti le -> so voi tham chieu H=2200 (dau vao production).

    SO DO THAT 27/09 (scratch/_phase2/after.json, compare.py), 19 anh LP:
      * Truoc giai doan 2: 14/14 trang co khoi ky cho hop KHAC nhau giua goc va
        H2200 (lech x toi 0.068); ABSTAIN dao chieu Load_3.5__0 / Loading_Plan_2.2__0.
      * Sau: goc & H3000 lech H2200 toi da x 0.004, y1 0.000, y2 0.011.
      * Con 2 lan dao status o H3000 (Load_3.7__0 -> ABSTAIN, Loading_Plan_2.2__0 ->
        do duoc). Nguyen nhan: anh goc ~85 DPI, phong 3000 roi thu 2200 cho pixel
        khac -> Tesseract doc vo ca dong nhan ("(EM IV TRANG MEM"). Khong phai tham
        so pixel; la gioi han OCR tren anh nguon DPI thap. Dao chieu luon la
        ABSTAIN <-> do duoc, KHONG BAO GIO la hop sai cho (CA 11a chan).
      * x0.5 (~425px ~ 36 DPI, duoi nguong dpi_reject 40 cua runner Tang 1):
        14/14 trang co khoi ky ABSTAIN - hanh vi an toan dung, khong phai loi.
    """
    ref_key = "H2200"
    runs = {}
    for fn, info in sorted(docs.items()):
        raw = imread_u(SAMPLES / fn)
        runs[fn] = {k: detect(im, page_role=info["page_role"]) for k, im in _scaled_variants(raw).items()}

    def is_abstain(z):
        return (not z["has_signatures"]) and z["status"] != "PAGE_1_NO_SIGNATURES"

    # 11a (CUNG): o MOI ti le, neu resolver KHONG abstain thi phai cho cung status
    # va hop lech <= SCALE_TOL (x1, x2, y1) so voi tham chieu. Day la tinh chat an
    # toan: sai do phan giai chi duoc phep dan toi ABSTAIN, khong duoc dan toi hop sai.
    bad, worst = [], 0.0
    y2_over = []
    for fn, r in runs.items():
        ref = r[ref_key]
        for k, z in r.items():
            if k == ref_key or is_abstain(z) or is_abstain(ref):
                continue
            if z["status"] != ref["status"] or len(z["targets"]) != len(ref["targets"]):
                bad.append(f"{fn}@{k}: {z['status']} != {ref['status']}")
                continue
            for a, b in zip(z["targets"], ref["targets"]):
                d = max(abs(a["box_norm"][i] - b["box_norm"][i]) for i in (0, 1, 3))
                worst = max(worst, d)
                if d > SCALE_TOL:
                    bad.append(f"{fn}@{k}:{a['role'][:10]} d={d:.3f}")
                d2 = abs(a["box_norm"][2] - b["box_norm"][2])
                if d2 > SCALE_TOL:
                    y2_over.append((fn, k, a["role"][:10], round(d2, 3)))
    check(f"CA 11a: moi ti le khong-ABSTAIN -> cung status, hop (y1,x1,x2) lech <= {SCALE_TOL}",
          not bad, f"{len(bad)} vi pham: {bad[:3]}" if bad else f"lech lon nhat {worst:.3f}")

    # 11b: y2 do Ink-Group Closure quyet dinh - phep NOI roi rac (noi toi day cum
    # muc hoac khong). Mot dong muc sat mep y2 co the lot vao/ra khi noi suy khac
    # -> nhay ca mot cum. Do that: 1 o vuot 0.01 (Load_3.8__0@goc cot 1, +0.011;
    # chi NOI, khong co). Tran cung = 1 o va <= 0.02; bat bien tuyet doi = KNOWN-LIMIT.
    MAX_Y2_OVER, Y2_HARD = 1, 0.02
    check(f"CA 11b: y2 vuot {SCALE_TOL} o <= {MAX_Y2_OVER} o va khong o nao > {Y2_HARD}",
          len(y2_over) <= MAX_Y2_OVER and all(d <= Y2_HARD for *_, d in y2_over),
          f"{y2_over}")
    check(f"CA 11b': y2 bat bien tuyet doi (<= {SCALE_TOL}) o moi ti le", not y2_over,
          f"{y2_over} - Ink-Group Closure roi rac, xem CA 11b", known_limit=True)

    # 11c: dao status giua cac ti le NAM TRONG contract Tang 1 (goc, H2200, H3000).
    flips = [f"{fn}@{k}:{z['status']} vs {r[ref_key]['status']}"
             for fn, r in runs.items() for k, z in r.items()
             if k in ("goc", "H3000") and z["status"] != r[ref_key]["status"]]
    MAX_FLIPS = 2  # do that 27/09, xem docstring. KHONG nang de test xanh.
    check(f"CA 11c: dao status (goc/H3000 vs H2200) <= {MAX_FLIPS} (tran do that)",
          len(flips) <= MAX_FLIPS, f"{len(flips)}: {flips}")
    check("CA 11c': status bat bien tuyet doi giua goc/H2200/H3000", not flips,
          f"{flips} - OCR nhan tren nguon ~85 DPI, xem docstring", known_limit=True)

    # 11d: ti le 0.5x (duoi contract DPI Tang 1) - chi doi hoi an toan (11a da kiem)
    # va trang PAGE_1 van nhan dung. Bao so ABSTAIN de nguoi doc thay.
    n_sig = sum(1 for r in runs.values() if r[ref_key]["status"] != "PAGE_1_NO_SIGNATURES")
    n_abs05 = sum(1 for r in runs.values() if is_abstain(r["x0.5"]))
    p1_bad = [fn for fn, r in runs.items()
              if (r[ref_key]["status"] == "PAGE_1_NO_SIGNATURES") != (r["x0.5"]["status"] == "PAGE_1_NO_SIGNATURES")]
    check("CA 11d: 0.5x (~36 DPI) - PAGE_1 van nhan dung, con lai chi duoc ABSTAIN hoac dung",
          not p1_bad, f"ABSTAIN {n_abs05}/{n_sig} trang co khoi ky; PAGE_1 lech: {p1_bad}")


def abstain_edge_cases(detect, zones, docs):
    import tools.stage3b_zone_resolver as R

    # CA 12: trang HEADER khong co vach bang nao. Truoc day: anchor_y=0.550 doan
    # mo + status DEFAULT_SINGLE_PAGE. Nay phai ABSTAIN TABLE_ANCHOR_NOT_FOUND.
    page = np.full((2200, 1555, 3), 250, np.uint8)
    for i in range(6):  # vai dong chu ngan (khong du dai de thanh vach bang)
        cv2.putText(page, "Nguoi lap phieu", (150 + 250 * (i % 5), 400 + 60 * i),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (30, 30, 30), 2)
    z = detect(page, page_role="HEADER")
    check("CA 12: khong co vach bang (HEADER) -> ABSTAIN TABLE_ANCHOR_NOT_FOUND",
          z["status"] == "TABLE_ANCHOR_NOT_FOUND" and not z["has_signatures"]
          and z["targets"] == [] and z["anchor_y"] is None,
          f"status={z['status']} has={z['has_signatures']} n_targets={len(z['targets'])}")

    # Anh that co khoi ky do duoc, de 2 ca duoi di toi buoc do cot.
    fn_ok = next(fn for fn, (_, zz) in sorted(zones.items()) if zz["has_signatures"])
    img_ok = zones[fn_ok][0]
    role_ok = docs[fn_ok]["page_role"]

    # CA 13: Tesseract sai duong dan -> COLUMN_OCR_UNAVAILABLE (khoi phuc sau).
    old_cmd = R.pytesseract.pytesseract.tesseract_cmd
    try:
        R.pytesseract.pytesseract.tesseract_cmd = r"C:\khong_ton_tai\tesseract.exe"
        z = detect(img_ok, page_role=role_ok)
    finally:
        R.pytesseract.pytesseract.tesseract_cmd = old_cmd
    check("CA 13: tesseract sai duong dan -> ABSTAIN COLUMN_OCR_UNAVAILABLE",
          z["status"] == "COLUMN_OCR_UNAVAILABLE" and not z["has_signatures"] and z["targets"] == [],
          f"{fn_ok}: status={z['status']}")

    # CA 14: thieu tu dien nhan -> COLUMN_LABELS_UNAVAILABLE (khoi phuc sau).
    old_path, old_cache = R._LABELS_PATH, R._LABELS_CACHE
    try:
        R._LABELS_PATH = ROOT / "config" / "__khong_ton_tai__.json"
        R._LABELS_CACHE = None
        z = detect(img_ok, page_role=role_ok)
    finally:
        R._LABELS_PATH, R._LABELS_CACHE = old_path, old_cache
    check("CA 14: thieu config nhan -> ABSTAIN COLUMN_LABELS_UNAVAILABLE",
          z["status"] == "COLUMN_LABELS_UNAVAILABLE" and not z["has_signatures"] and z["targets"] == [],
          f"{fn_ok}: status={z['status']}")
    # sau khi khoi phuc, ket qua phai tro lai nhu cu (khong ro ri trang thai)
    z_back = detect(img_ok, page_role=role_ok)
    check("CA 14b: khoi phuc tesseract/config -> ket qua trung ban dau",
          json.dumps(z_back, sort_keys=True, default=str) == json.dumps(zones[fn_ok][1], sort_keys=True, default=str),
          fn_ok)


if __name__ == "__main__":
    main()
