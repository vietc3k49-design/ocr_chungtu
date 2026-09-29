# -*- coding: utf-8 -*-
"""
GT production v4 cho LOADING_PLAN — gan nhan tren BOX PRODUCTION MOI (resolver per-column, Giai doan 4).

KHONG gan nhan moi bang may. Chi GHEP nhan nguoi da co vao box production hien tai:

  * own_signature (nhan CHINH): "CHINH vai tro nay da ky chua" — nhan theo VAI TRO, doc lap box.
      - 13 trang cu: lay tu GT v3 (output/stage4_dynamic_gt_v3/gt_labeled.json), ghep theo (file_name, role).
      - Load_3.5__0 (5 target moi): lay tu gt_load35.json (3 annotator mu A/B/C, nhat tri 100% own_signature),
        nguon scratch/_phase4/geom/new_targets/gt_load35.json, CHEP vao output/stage4_dynamic_gt_v4/.
  * presence / overflow / sig_cut / frame_quality: PHU THUOC BOX. Chung duoc gan tren box CU (box v3, hoac box
    shared-bottom cua ban sao resolver voi Load_3.5__0), KHONG phai box moi. Moi target ghi ro
    `box_dependent_labels_from` + `label_box_norm` + `box_changed` (so box nhan vs box production, lam tron 4 chu so).
    Khong gia vo la gan tren box moi — bench chi dung cac nhan nay tren o box_changed=false.
  * Nhan trang: has_signature_block lay tu v3; Load_3.5__0 = YES (3/3 annotator).

Assert (that, khong noi): moi target production co own_signature; khong target GT thua; moi target v3 va gt_load35
deu duoc dung (khong mat nhan am tham); box GT (box_norm) == box production.

Chay:  .venv/Scripts/python.exe tools/build_lp_prod_gt_v4.py
Ghi:   output/stage4_dynamic_gt_v4/gt_labeled.json (+ gt_load35.json nguon)
"""
import datetime as _dt
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import lp_production_path as lpp  # noqa: E402

GT_V3 = ROOT / "output/stage4_dynamic_gt_v3/gt_labeled.json"
LOAD35_SRC = ROOT / "scratch/_phase4/geom/new_targets/gt_load35.json"
OUT_DIR = ROOT / "output/stage4_dynamic_gt_v4"
LOAD35_DST = OUT_DIR / "gt_load35.json"
OUT = OUT_DIR / "gt_labeled.json"
LOAD35_FILE = "Load_3.5__0.png"
BOX_DEP = ("presence", "overflow", "sig_cut", "frame_quality")


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def rbox(b):
    return [round(float(v), 4) for v in b]


def rel(p):
    return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    assert GT_V3.exists(), f"thieu GT v3: {GT_V3}"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not LOAD35_DST.exists():
        assert LOAD35_SRC.exists(), f"thieu nguon GT Load_3.5__0: {LOAD35_SRC}"
        shutil.copy2(LOAD35_SRC, LOAD35_DST)
    elif LOAD35_SRC.exists():
        assert md5(LOAD35_SRC) == md5(LOAD35_DST), "gt_load35.json trong v4 khac nguon scratch — kiem tra tay"
    v3 = json.loads(GT_V3.read_text(encoding="utf-8"))
    l35 = json.loads(LOAD35_DST.read_text(encoding="utf-8"))

    v3_by_key = {}
    for t in v3["targets"]:
        k = (t["file_name"], t["role"])
        assert k not in v3_by_key, f"GT v3 trung (file, role): {k}"
        v3_by_key[k] = t
    l35_by_role = {}
    for t in l35["targets"]:
        assert t["file_name"] == LOAD35_FILE, t["file_name"]
        assert t["role"] not in l35_by_role, f"gt_load35 trung role {t['role']}"
        l35_by_role[t["role"]] = t
    assert not any(k[0] == LOAD35_FILE for k in v3_by_key), "GT v3 da co target Load_3.5__0 — khong ro nguon nao dung"

    # Duong production (chep 1-1 Cell 1+3) + doi chieu manifest v2 chinh thuc
    pages, _ = lpp.load_all_loading_plan_pages()
    box_check = lpp.assert_boxes_match_manifest(pages)

    targets, used_v3, used_l35, missing = [], set(), set(), []
    for p in pages:
        if lpp.page_kind(p) != "TARGETS":
            continue
        fn = p["file_name"]
        for i, t in enumerate(p["zone"]["targets"]):
            tid = lpp.target_id(fn, i)
            new_box = rbox(t["box_norm"])
            if fn == LOAD35_FILE:
                src = l35_by_role.get(t["role"])
                src_name, box_from = "gt_load35.json (3 annotator mu, majority)", "load35_shared_bottom_box"
                if src is not None:
                    used_l35.add(t["role"])
                votes = {"own_signature": src.get("votes_own_signature")} if src else None
            else:
                src = v3_by_key.get((fn, t["role"]))
                src_name, box_from = "gt_v3", "v3_box"
                if src is not None:
                    used_v3.add((fn, t["role"]))
                votes = src.get("votes") if src else None
            if src is None or src.get("own_signature") not in ("YES", "NO", "AMBIGUOUS"):
                missing.append(tid)
                continue
            label_box = rbox(src["box_norm"])
            rec = {
                "target_id": tid, "page_id": lpp.page_id(fn), "file_name": fn, "doc_type": p["doc_type"],
                "page_role": p["page_role"], "zone_status": p["zone"].get("status"), "role_index": i,
                "role": t["role"], "required": bool(t["required"]), "expected_color": t.get("expected_color"),
                "box_norm": new_box,                         # box PRODUCTION hien tai
                "own_signature": src["own_signature"],       # nhan CHINH, doc lap box
                "own_signature_source": src_name,
                "box_dependent_labels_from": box_from,
                "label_box_norm": label_box,
                "box_changed": label_box != new_box,
                "votes": votes,
            }
            for k in BOX_DEP:
                rec[k] = src.get(k)
            if src.get("notes"):
                rec["notes"] = src["notes"]
            targets.append(rec)

    assert not missing, f"{len(missing)} target production KHONG co own_signature: {missing}"
    unused_v3 = sorted(set(v3_by_key) - used_v3)
    unused_l35 = sorted(set(l35_by_role) - used_l35)
    assert not unused_v3, f"{len(unused_v3)} nhan GT v3 khong khop target production nao (vai tro/trang doi?): {unused_v3}"
    assert not unused_l35, f"nhan gt_load35 khong dung: {unused_l35}"
    n_prod = sum(len(p["zone"]["targets"]) for p in pages if lpp.page_kind(p) == "TARGETS")
    assert len(targets) == n_prod, f"so target GT {len(targets)} != production {n_prod}"
    assert len({t["target_id"] for t in targets}) == len(targets), "target_id trung"

    # Nhan trang
    v3_pages = {pg["page_id"]: pg for pg in v3.get("pages", [])}
    out_pages = []
    for p in pages:
        pid = lpp.page_id(p["file_name"])
        old = v3_pages.get(pid, {})
        pg = {"page_id": pid, "file_name": p["file_name"], "page_role": p["page_role"],
              "zone_status": (p["zone"] or {}).get("status") if p["zone"] else None,
              "page_kind": lpp.page_kind(p),
              "n_targets": len((p["zone"] or {}).get("targets") or []) if lpp.page_kind(p) == "TARGETS" else 0}
        if p["file_name"] == LOAD35_FILE:
            pg["has_signature_block"] = l35["page"]["has_signature_block"]
            pg["has_signature_block_votes"] = l35["page"].get("votes")
            pg["page_label_source"] = "gt_load35.json"
        elif old.get("has_signature_block") is not None:
            pg["has_signature_block"] = old["has_signature_block"]
            pg["page_label_source"] = "gt_v3"
        out_pages.append(pg)
    assert next(pg for pg in out_pages if pg["file_name"] == LOAD35_FILE).get("has_signature_block") == "YES"

    res_path = ROOT / "tools/stage3b_zone_resolver.py"
    doc = {
        "dataset_name": "KIDO LOADING_PLAN Dynamic Zone GT v4 — DUONG PRODUCTION, box per-column (Giai doan 4)",
        "version": "4.0.0",
        "built_by": "tools/build_lp_prod_gt_v4.py",
        "built_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "method": ("GHEP nhan nguoi co san vao box production moi — KHONG gan nhan moi. own_signature theo VAI TRO "
                   "(doc lap box) ghep theo (file_name, role). presence/overflow/sig_cut/frame_quality la nhan tren "
                   "box CU (xem box_dependent_labels_from/label_box_norm/box_changed), chi dung tren o box_changed=false."),
        "sources": {
            "gt_v3": {"path": rel(GT_V3), "md5": md5(GT_V3), "stage3b_resolver_mtime": v3.get("stage3b_resolver_mtime"),
                      "annotation_method": v3.get("annotation_method")},
            "gt_load35": {"path": rel(LOAD35_DST), "copied_from": rel(LOAD35_SRC) if LOAD35_SRC.exists() else None,
                          "md5": md5(LOAD35_DST), "note": l35.get("note"),
                          "disagreements": l35.get("disagreements")},
        },
        "image_source": v3.get("image_source"),
        "zone_source": "tools.kido_pipeline.detect_loading_plan_signature_zone (-> tools/stage3b_zone_resolver.py)",
        "stage3b_resolver_path": rel(res_path),
        "stage3b_resolver_mtime": lpp.resolver_mtime(),
        "stage3b_resolver_md5": md5(res_path),
        "labels_config_md5": md5(ROOT / "config/stage3b_loading_plan_labels.json"),
        "manifest_box_check": box_check,
        "annotation_method": v3.get("annotation_method"),
        "annotators": v3.get("annotators"),
        "agreement": {"gt_v3": v3.get("agreement"),
                      "gt_load35_own_signature": "3/3 nhat tri tren 5/5 target"},
        "primary_label": "own_signature",
        "total_pages": len(out_pages),
        "total_targets": len(targets),
        "page_kind_distribution": dict(Counter(pg["page_kind"] for pg in out_pages)),
        "targets_by_role": dict(Counter(t["role"] for t in targets)),
        "targets_by_required": {str(k): v for k, v in Counter(t["required"] for t in targets).items()},
        "own_signature_distribution": dict(Counter(t["own_signature"] for t in targets)),
        "own_signature_source_distribution": dict(Counter(t["own_signature_source"] for t in targets)),
        "box_changed_distribution": {str(k): v for k, v in Counter(t["box_changed"] for t in targets).items()},
        "box_changed_by_source": {f"{s}|{c}": n for (s, c), n in
                                  Counter((t["box_dependent_labels_from"], t["box_changed"]) for t in targets).items()},
        "presence_distribution_box_unchanged": dict(Counter(t["presence"] for t in targets if not t["box_changed"])),
        "page_label_distribution": dict(Counter(pg.get("has_signature_block") for pg in out_pages
                                                if pg.get("has_signature_block") is not None)),
        "pages": out_pages,
        "targets": targets,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    for k in ("total_pages", "total_targets", "page_kind_distribution", "own_signature_distribution",
              "own_signature_source_distribution", "box_changed_distribution", "box_changed_by_source",
              "presence_distribution_box_unchanged", "page_label_distribution", "stage3b_resolver_mtime",
              "manifest_box_check"):
        print(f"{k}: {doc[k]}")
    print("box_changed targets:", [t["target_id"] for t in targets if t["box_changed"]])
    print(f"-> {rel(OUT)}")


if __name__ == "__main__":
    main()
