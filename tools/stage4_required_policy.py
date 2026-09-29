"""
TẦNG 4 — CHÍNH SÁCH VAI TRÒ KÝ BẮT BUỘC `LOADING_PLAN` THEO KÊNH + PHÁN QUYẾT HỒ SƠ ĐA TRANG
============================================================================================

Nguồn luật: `config/stage4_lp_required_policy.json` (trích nguyên văn SOP sheet Guideline của
`docs/Copy of HUONG DAN CHUNG TU GIAO NHAN.xlsx`, người dùng đã duyệt 27/09). Module này KHÔNG
chứa luật nghiệp vụ nào: thiếu / hỏng config ⇒ `Stage4PolicyError`, không có dự phòng hardcode.

Hai việc:
  1. `apply_lp_required_policy(targets, system)` — gán lại `required` của từng ô ký theo kênh
     (ánh xạ `system` Tầng 2 → kênh nằm trong config). Kênh không xác định ⇒ chính sách
     NGHIÊM NHẤT + `policy_channel_unresolved=True`, không đoán.
  2. `evaluate_lp_dossier_verdicts(page_results, stage3_manifest)` — gộp phán quyết các trang
     của CÙNG MỘT chứng từ `LOADING_PLAN` theo nhóm đa trang của Tầng 3 (`documents[].page_files`),
     KHÔNG ghép theo tên file.

Ghép vai trò target ↔ policy theo TÊN role do config nhãn Tầng 3b in ra (`label_role`), đối chiếu
`label_index` lúc nạp; không theo vị trí cột cứng.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_POLICY_PATH = ROOT / "config" / "stage4_lp_required_policy.json"

UNRESOLVED_CHANNEL = "UNRESOLVED"

# Trạng thái hồ sơ (contract manifest v2) — tên trạng thái, không phải luật nghiệp vụ.
DOSSIER_NO_BLOCK_STATUS = "KHONG_TIM_THAY_KHOI_KY"
DOSSIER_ABSTAIN_STATUS = "CHUA_CHUAN_HOA_VUNG_KY"

__all__ = [
    "Stage4PolicyError",
    "DEFAULT_POLICY_PATH",
    "UNRESOLVED_CHANNEL",
    "DOSSIER_NO_BLOCK_STATUS",
    "DOSSIER_ABSTAIN_STATUS",
    "load_lp_required_policy",
    "resolve_lp_channel",
    "apply_lp_required_policy",
    "policy_summary",
    "evaluate_lp_dossier_verdicts",
]


class Stage4PolicyError(RuntimeError):
    """Config chính sách thiếu / hỏng / mâu thuẫn với config nhãn Tầng 3b."""


_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _labels_columns(labels_path: Path) -> List[Dict[str, Any]]:
    if not labels_path.exists():
        raise Stage4PolicyError(f"Thiếu config nhãn Tầng 3b mà policy tham chiếu: {labels_path}")
    try:
        cols = json.loads(labels_path.read_text(encoding="utf-8"))["columns"]
    except Exception as exc:  # noqa: BLE001
        raise Stage4PolicyError(f"Config nhãn Tầng 3b hỏng ({labels_path}): {exc}") from exc
    return cols


def load_lp_required_policy(path: Optional[os.PathLike] = None) -> Dict[str, Any]:
    """Nạp + kiểm tính nhất quán của config. Lỗi nào cũng ném Stage4PolicyError."""
    p = Path(path) if path is not None else DEFAULT_POLICY_PATH
    if not p.exists():
        raise Stage4PolicyError(
            f"Thiếu config chính sách chữ ký bắt buộc LOADING_PLAN: {p} — không có dự phòng hardcode.")
    mtime = p.stat().st_mtime
    key = str(p.resolve())
    if key in _CACHE and _CACHE[key][0] == mtime:
        return _CACHE[key][1]
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise Stage4PolicyError(f"Config chính sách hỏng ({p}): {exc}") from exc

    for k in ("doc_type", "roles", "always_optional_roles", "system_to_channel", "channels", "labels_config"):
        if k not in cfg:
            raise Stage4PolicyError(f"Config chính sách thiếu khóa '{k}' ({p})")
    roles = cfg["roles"]
    chans = cfg["channels"]
    if UNRESOLVED_CHANNEL not in chans:
        raise Stage4PolicyError(f"Config chính sách thiếu kênh '{UNRESOLVED_CHANNEL}' (chính sách nghiêm nhất)")

    # Đối chiếu vai trò với config nhãn Tầng 3b (tên + index), không theo vị trí cứng.
    labels_path = ROOT / cfg["labels_config"]
    cols = _labels_columns(labels_path)
    by_role_name = {c["role"]: c for c in cols}
    for rk, rv in roles.items():
        col = by_role_name.get(rv.get("label_role"))
        if col is None:
            raise Stage4PolicyError(f"Vai trò policy {rk} ('{rv.get('label_role')}') không có trong {labels_path}")
        if int(col["index"]) != int(rv.get("label_index", -1)):
            raise Stage4PolicyError(
                f"Vai trò policy {rk}: label_index {rv.get('label_index')} != index {col['index']} trong config nhãn")
    missing_cols = sorted(set(by_role_name) - {rv["label_role"] for rv in roles.values()})
    if missing_cols:
        raise Stage4PolicyError(f"Config nhãn có vai trò chưa được policy phân loại: {missing_cols}")

    opt = set(cfg["always_optional_roles"].get("roles", []))
    for r in opt:
        if r not in roles:
            raise Stage4PolicyError(f"always_optional_roles chứa vai trò lạ: {r}")
    union_req = set()
    for cname, cv in chans.items():
        req = cv.get("required_roles")
        if not isinstance(req, list) or not req:
            raise Stage4PolicyError(f"Kênh {cname}: required_roles rỗng / sai kiểu")
        for r in req:
            if r not in roles:
                raise Stage4PolicyError(f"Kênh {cname}: vai trò lạ {r}")
            if r in opt:
                raise Stage4PolicyError(f"Kênh {cname}: vai trò {r} vừa required vừa always_optional")
        if cname != UNRESOLVED_CHANNEL:
            union_req |= set(req)
            if not cv.get("sop_rules"):
                raise Stage4PolicyError(f"Kênh {cname}: thiếu sop_rules (mỗi luật phải trích câu SOP)")
            for s in cv["sop_rules"]:
                if not s.get("quote") or not s.get("sheet") or not s.get("cell"):
                    raise Stage4PolicyError(f"Kênh {cname}: sop_rule thiếu quote/sheet/cell")
    strict = set(chans[UNRESOLVED_CHANNEL]["required_roles"])
    if not union_req <= strict:
        raise Stage4PolicyError(
            f"Kênh {UNRESOLVED_CHANNEL} phải NGHIÊM NHẤT (⊇ hợp mọi kênh); thiếu {sorted(union_req - strict)}")
    s2c = cfg["system_to_channel"]
    for ch in list(s2c.get("exact", {}).values()) + [x.get("channel") for x in s2c.get("prefix", [])]:
        if ch not in chans:
            raise Stage4PolicyError(f"system_to_channel trỏ tới kênh không tồn tại: {ch}")

    cfg = dict(cfg)
    cfg["_path"] = str(p)
    cfg["_mtime"] = mtime
    cfg["_label_to_key"] = {rv["label_role"]: rk for rk, rv in roles.items()}
    _CACHE[key] = (mtime, cfg)
    return cfg


def resolve_lp_channel(system: Optional[str], policy: Optional[Dict[str, Any]] = None) -> Tuple[str, bool, str]:
    """`system` Tầng 2 → (channel, unresolved, lý do). Không khớp gì ⇒ UNRESOLVED."""
    pol = policy or load_lp_required_policy()
    s2c = pol["system_to_channel"]
    s = "" if system is None else str(system)
    if s in set(s2c.get("unresolved_systems", [])):
        return UNRESOLVED_CHANNEL, True, f"SYSTEM_UNRESOLVED({s!r})"
    if s in s2c.get("exact", {}):
        return s2c["exact"][s], False, f"EXACT({s})"
    for pr in s2c.get("prefix", []):
        if s.startswith(pr["prefix"]):
            return pr["channel"], False, f"PREFIX({pr['prefix']})"
    return UNRESOLVED_CHANNEL, True, f"SYSTEM_NOT_IN_CONFIG({s!r})"


def _required_keys(channel: str, pol: Dict[str, Any]) -> List[str]:
    return list(pol["channels"][channel]["required_roles"])


def policy_summary(system: Optional[str], policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Thông tin chính sách áp cho một `system` — để ghi vào manifest/E2E."""
    pol = policy or load_lp_required_policy()
    ch, unresolved, why = resolve_lp_channel(system, pol)
    req = _required_keys(ch, pol)
    return {
        "policy_channel": ch,
        "policy_channel_unresolved": unresolved,
        "policy_channel_reason": why,
        "policy_system": system,
        "required_roles": [pol["roles"][k]["label_role"] for k in req],
        "sop_cells": [f"{s['sheet']}!{s['cell']}" for s in pol["channels"][ch].get("sop_rules", [])],
        "policy_version": pol.get("version"),
        "policy_path": os.path.relpath(pol["_path"], ROOT).replace("\\", "/"),
    }


def apply_lp_required_policy(targets: Iterable[Dict[str, Any]], system: Optional[str],
                             policy: Optional[Dict[str, Any]] = None,
                             channel: Optional[str] = None) -> List[Dict[str, Any]]:
    """Trả BẢN SAO targets với `required` mới theo kênh + `required_source`, `policy_channel`,
    `policy_channel_unresolved`, `required_original`.

    `channel` (tùy chọn) ép kênh đã phân giải ở cấp hồ sơ; mặc định suy từ `system`.
    Vai trò không có trong config nhãn ⇒ required=True (nghiêm) + `policy_role_unresolved=True`.
    """
    pol = policy or load_lp_required_policy()
    if channel is None:
        ch, unresolved, why = resolve_lp_channel(system, pol)
    else:
        if channel not in pol["channels"]:
            raise Stage4PolicyError(f"Kênh ép không tồn tại trong config: {channel}")
        ch, unresolved, why = channel, channel == UNRESOLVED_CHANNEL, f"FORCED({channel})"
    req_keys = set(_required_keys(ch, pol))
    opt_keys = set(pol["always_optional_roles"]["roles"])
    cells = ",".join(f"{s['sheet']}!{s['cell']}" for s in pol["channels"][ch].get("sop_rules", [])[:3])
    out = []
    for t in targets:
        tc = dict(t)
        rk = pol["_label_to_key"].get(tc.get("role"))
        tc["required_original"] = t.get("required")
        tc["policy_channel"] = ch
        tc["policy_channel_unresolved"] = unresolved
        tc["policy_role_key"] = rk
        if rk is None:
            tc["required"] = True
            tc["policy_role_unresolved"] = True
            tc["required_source"] = f"POLICY_ROLE_UNKNOWN_STRICT:{tc.get('role')!r}"
        elif rk in req_keys:
            tc["required"] = True
            tc["required_source"] = (f"POLICY:{ch}:REQUIRED" + (f"[{cells}]" if cells else "")
                                     + ("[STRICTEST_CHANNEL_UNRESOLVED]" if unresolved else ""))
        elif rk in opt_keys:
            tc["required"] = False
            tc["required_source"] = f"POLICY:ALWAYS_OPTIONAL({rk})"
        else:
            tc["required"] = False
            tc["required_source"] = f"POLICY:{ch}:NOT_REQUIRED" + (f"[{cells}]" if cells else "")
        out.append(tc)
    return out


# ---------------------------------------------------------------------------
# Phán quyết hồ sơ đa trang
# ---------------------------------------------------------------------------
def _page_class(r: Optional[Dict[str, Any]]) -> str:
    """SIGNATURE_BLOCK | PAGE_1_NO_BLOCK | BLOCK_ABSTAIN | MISSING."""
    if r is None:
        return "MISSING"
    if r.get("zone_status") == "PAGE_1_NO_SIGNATURES" and not r.get("targets"):
        return "PAGE_1_NO_BLOCK"
    if r.get("targets"):
        return "SIGNATURE_BLOCK"
    # zone ABSTAIN / lỗi ảnh / ngoài scope: không biết trang có khối ký hay không.
    return "BLOCK_ABSTAIN"


def evaluate_lp_dossier_verdicts(page_results: Iterable[Dict[str, Any]], stage3_manifest: Dict[str, Any],
                                 verdict_fn, policy: Optional[Dict[str, Any]] = None,
                                 doc_type: str = "LOADING_PLAN") -> Dict[str, Any]:
    """Gộp phán quyết theo nhóm trang Tầng 3 (`batches[].documents[]` có `doc_type == doc_type`).

    page_results: bản ghi trang của Cell 3 ver2 (file_name, system, zone_status, targets[] đã verify,
                  modality). verdict_fn: `evaluate_document_verdict_v2` (một nguồn sự thật verdict).

    Luật:
      * trang PAGE_1_NO_SIGNATURES không làm hỏng hồ sơ;
      * có trang BLOCK_ABSTAIN (zone ABSTAIN/lỗi ảnh) hoặc trang không có kết quả ⇒ hồ sơ ABSTAIN;
      * không trang nào có khối ký ⇒ KHONG_TIM_THAY_KHOI_KY / REVIEW_REQUIRED (không bao giờ DAT);
      * còn lại: vai trò required (theo kênh HỒ SƠ) đạt khi được ký ở ÍT NHẤT một trang có khối ký;
        vai trò required không có ô nào để đo ⇒ ABSTAIN (không đoán);
      * kênh hồ sơ: các trang cùng kênh ⇒ kênh đó; lệch kênh hoặc có trang chưa rõ kênh ⇒ UNRESOLVED
        (nghiêm nhất) + cờ.
    """
    pol = policy or load_lp_required_policy()
    by_file = {r["file_name"]: r for r in page_results}
    seen_pages: Dict[str, str] = {}
    dossiers = []
    for b in stage3_manifest.get("batches", []):
        for d in b.get("documents", []):
            if d.get("doc_type") != doc_type:
                continue
            pages = [Path(pf).name for pf in (d.get("page_files") or [])]
            if not pages and d.get("file_name"):
                pages = [d["file_name"]]
            dossiers.append(_one_dossier(d.get("doc_id"), b.get("batch_id"), pages, by_file, pol, verdict_fn,
                                         source="STAGE3_DOCUMENT", s3_multi=d.get("is_multi_page")))
            for pg in pages:
                if pg in seen_pages:
                    dossiers[-1]["contract_errors"].append(f"PAGE_IN_MULTIPLE_DOSSIERS:{pg}:{seen_pages[pg]}")
                seen_pages[pg] = d.get("doc_id")
    # Trang LOADING_PLAN (Tầng 2) không thuộc chứng từ LP nào của Tầng 3 ⇒ hồ sơ ABSTAIN tường minh.
    orphans = sorted(fn for fn, r in by_file.items() if r.get("doc_type") == doc_type and fn not in seen_pages)
    for fn in orphans:
        dv = _one_dossier(None, by_file[fn].get("batch_id"), [fn], by_file, pol, verdict_fn,
                          source="PAGE_NOT_IN_STAGE3_DOCUMENT", s3_multi=None)
        dv["doc_status"], dv["action"] = DOSSIER_ABSTAIN_STATUS, "ABSTAIN"
        dv["reason"] = "PAGE_NOT_IN_STAGE3_DOCUMENT: Tầng 3 không gom trang này vào chứng từ LOADING_PLAN nào"
        dossiers.append(dv)
    summary: Dict[str, int] = {}
    for dv in dossiers:
        summary[dv["doc_status"]] = summary.get(dv["doc_status"], 0) + 1
    return {"n_dossiers": len(dossiers), "summary": summary, "orphan_pages": orphans, "dossiers": dossiers}


def _one_dossier(doc_id, batch_id, pages, by_file, pol, verdict_fn, source, s3_multi):
    classes = {pg: _page_class(by_file.get(pg)) for pg in pages}
    systems = sorted({str(by_file[pg].get("system")) for pg in pages if pg in by_file})
    chans = {}
    for pg in pages:
        if pg in by_file:
            chans[pg] = resolve_lp_channel(by_file[pg].get("system"), pol)
    resolved = {c for c, unres, _ in chans.values() if not unres}
    any_unres = any(unres for _, unres, _ in chans.values()) or not chans
    if len(resolved) == 1 and not any_unres:
        ch, ch_unres, ch_why = next(iter(resolved)), False, "PAGES_AGREE"
    elif len(resolved) > 1:
        ch, ch_unres, ch_why = UNRESOLVED_CHANNEL, True, f"CHANNEL_CONFLICT({sorted(resolved)})"
    else:
        ch, ch_unres, ch_why = UNRESOLVED_CHANNEL, True, "PAGE_CHANNEL_UNRESOLVED"
    rec = {
        "dossier_id": doc_id, "batch_id": batch_id, "source": source,
        "stage3_is_multi_page": s3_multi, "pages": pages, "page_classes": classes,
        "page_verdicts": {pg: (by_file[pg].get("doc_status") if pg in by_file else None) for pg in pages},
        "systems": systems, "policy_channel": ch, "policy_channel_unresolved": ch_unres,
        "policy_channel_reason": ch_why,
        "required_roles": [pol["roles"][k]["label_role"] for k in _required_keys(ch, pol)],
        "role_evidence": {}, "contract_errors": [],
        "doc_status": None, "action": None, "reason": None,
    }
    if "MISSING" in classes.values() or "BLOCK_ABSTAIN" in classes.values():
        bad = [f"{pg}[{c}:{(by_file.get(pg) or {}).get('zone_status')}]" for pg, c in classes.items()
               if c in ("MISSING", "BLOCK_ABSTAIN")]
        rec.update(doc_status=DOSSIER_ABSTAIN_STATUS, action="ABSTAIN",
                   reason="PAGE_ABSTAIN: trang chưa đo được khối ký — " + ", ".join(bad))
        return rec
    sig_pages = [pg for pg, c in classes.items() if c == "SIGNATURE_BLOCK"]
    if not sig_pages:
        rec.update(doc_status=DOSSIER_NO_BLOCK_STATUS, action="REVIEW_REQUIRED",
                   reason=f"NO_SIGNATURE_BLOCK_PAGE: {len(pages)} trang, không trang nào có khối ký")
        return rec
    # Gộp theo VAI TRÒ (policy role key) qua mọi trang có khối ký, required theo kênh HỒ SƠ.
    roles: Dict[str, Dict[str, Any]] = {}
    is_color_all = True
    for pg in sig_pages:
        r = by_file[pg]
        is_color_all = is_color_all and (r.get("modality") == "TRUE_COLOR")
        for t in apply_lp_required_policy(r["targets"], r.get("system"), pol, channel=ch):
            k = t.get("policy_role_key") or f"UNKNOWN:{t.get('role')}"
            e = roles.setdefault(k, {"role": t.get("role"), "required": t["required"],
                                     "required_source": t["required_source"], "detected": False,
                                     "review_required": False, "evidence": None, "pages_detected": [],
                                     "pages_measured": []})
            e["required"] = e["required"] or t["required"]
            e["pages_measured"].append(pg)
            if t.get("detected"):
                e["detected"] = True
                e["pages_detected"].append(pg)
            if t.get("review_required"):
                e["review_required"] = True
                e["evidence"] = t.get("evidence")
    rec["role_evidence"] = roles
    unmeasured = [pol["roles"][k]["label_role"] for k in _required_keys(ch, pol) if k not in roles]
    if unmeasured:
        rec.update(doc_status=DOSSIER_ABSTAIN_STATUS, action="ABSTAIN",
                   reason="REQUIRED_ROLE_NOT_MEASURED: " + ", ".join(unmeasured))
        return rec
    st, act, why = verdict_fn(list(roles.values()), is_color=is_color_all)
    rec.update(doc_status=st, action=act, reason=f"[{len(sig_pages)} trang có khối ký/{len(pages)}] " + why)
    return rec
