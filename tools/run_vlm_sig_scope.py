# -*- coding: utf-8 -*-
"""Thử VLM qua gateway để ĐỊNH VỊ ô ký — thử nghiệm độc lập, KHÔNG ghi vào artifact Tầng 1-4.

Hai chế độ:
  --bo lp      : 19 ảnh LOADING_PLAN đã có GT v4 -> chấm điểm khách quan
                 (đối chiếu được với bản gọi thẳng Google: TP43/TN24/FP1/FN1)
  --bo abstain : 53 ảnh doc_type ngoài LOADING_PLAN (đang ABSTAIN) -> soát tay

Mọi output nằm trong output/vlm_sig_scope/<model>/ ; cache ở output/vlm_cache/.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vlm_gateway as gw                                          # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
IMG_DIR = ROOT / "output/stage1_out/images/form_samples"
GT_PATH = ROOT / "output/stage4_dynamic_gt_v4/gt_labeled.json"
MANIFEST = ROOT / "output/stage4_out/stage4_verification_manifest_v2.json"

PROMPT_VERSION = "sig-locate-v2-ngan"
PROMPT = """Tim MOI o ky in san tren chung tu nay (ke ca o dang de trong) va MOI con dau/moc; bo qua chu in, tieu de, duong ke bang, logo va khoi chu ky so cua hoa don dien tu.
Tra ve DUY NHAT JSON: {"loai_chung_tu":"<ten loai>","o_ky":[{"ten":"<chuc danh in phia tren o>","bbox":[x0,y0,x1,y1],"da_ky":true/false}],"moc":[{"bbox":[x0,y0,x1,y1],"chu_doc_duoc":"<chu tren moc>"}]}
bbox la 4 so thuc 0..1 theo ti le rong/cao anh (x0 trai, y0 tren, x1 phai, y1 duoi) va phai bao ca vung trong ben duoi chuc danh noi dat but ky."""


def parse_json(text):
    if not text:
        return None
    t = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.M)
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:                                             # noqa: BLE001
        return None


def danh_sach(bo):
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    docs = man["documents"]
    if bo == "lp":
        names = [d for d in docs if d.get("doc_type") == "LOADING_PLAN"]
    else:
        names = [d for d in docs if d.get("doc_type") != "LOADING_PLAN"]
    out = []
    for d in names:
        stem = d.get("doc_id") or d.get("file_name") or ""
        p = IMG_DIR / (Path(stem).stem + ".png")
        if p.exists():
            out.append((p, d.get("doc_type")))
    return out


def cham_gt(ket_qua):
    """Chấm như notebook Gemini: tâm bbox 'o_ky' rơi vào ô GT nào (ô cột không chồng lấn)."""
    if not GT_PATH.exists():
        return None
    gt = json.loads(GT_PATH.read_text(encoding="utf-8"))
    rows = []
    for t in gt["targets"]:
        if t["own_signature"] == "AMBIGUOUS":
            continue
        f = t["file_name"]
        r = ket_qua.get(Path(f).stem)
        if not r or r.get("data") is None:
            continue                                    # không có kết quả ≠ không có chữ ký
        y1, x1, y2, x2 = t["box_norm"]
        n = 0
        for o in (r["data"].get("o_ky") or []):
            b = o.get("bbox") or []
            if len(b) != 4:
                continue
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            if x1 <= cx <= x2 and y1 <= cy <= y2 and o.get("da_ky"):
                n += 1
        yes = t["own_signature"] == "YES"
        rows.append("TP" if (yes and n) else "FN" if yes else "FP" if n else "TN")
    return Counter(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bo", choices=["lp", "abstain"], default="lp")
    ap.add_argument("--model", default=None)
    ap.add_argument("--gioi-han", type=int, default=0, help="chỉ chạy N ảnh đầu (thử rẻ)")
    a = ap.parse_args()

    api, mdl, key = gw._cfg()
    mdl = a.model or mdl
    if not key:
        print("CHƯA CÓ VLM_API_KEY trong .env — dừng."); return 2
    imgs = danh_sach(a.bo)
    if a.gioi_han:
        imgs = imgs[:a.gioi_han]
    out_dir = ROOT / "output/vlm_sig_scope" / mdl / a.bo
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"API {api}\nMODEL {mdl}\nBỘ {a.bo}: {len(imgs)} ảnh\n")

    ket_qua, n_loi, n_cache = {}, 0, 0
    for i, (p, dt) in enumerate(imgs, 1):
        r = gw.goi_file(p, PROMPT, model=mdl, prompt_version=PROMPT_VERSION)
        data = parse_json(r.get("content"))
        n_cache += bool(r.get("cached"))
        if not r.get("ok") or data is None:
            n_loi += 1
            st = (r.get("error") or "KHONG_PARSE_DUOC_JSON")[:110]
        else:
            st = f"{len(data.get('o_ky') or [])} ô ký ({sum(1 for o in data['o_ky'] if o.get('da_ky'))} đã ký), {len(data.get('moc') or [])} mộc"
        ket_qua[p.stem] = {"doc_type": dt, "data": data, "error": r.get("error"),
                           "cached": r.get("cached"), "latency_s": r.get("latency_s"),
                           "usage": r.get("usage")}
        (out_dir / f"{p.stem}.json").write_text(
            json.dumps(ket_qua[p.stem], ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{i:2d}/{len(imgs)} | {100*i//len(imgs):3d}%] {p.stem:28s} {dt:18s} {st}")

    print(f"\nLỗi/không parse: {n_loi}/{len(imgs)} · từ cache: {n_cache}")
    if a.bo == "lp":
        c = cham_gt(ket_qua)
        if c:
            tp, tn, fp, fn = c["TP"], c["TN"], c["FP"], c["FN"]
            P = tp / (tp + fp) if tp + fp else 0
            R = tp / (tp + fn) if tp + fn else 0
            print(f"\nChấm với GT v4: TP {tp} · TN {tn} · FP {fp} · FN {fn} "
                  f"| P {P*100:.2f}% · R {R*100:.2f}%")
            print("So sánh: engine cổ điển ver2 = 44/25/0/0 (P=R=100%) · "
                  "Gemini gọi thẳng Google = 43/24/1/1 (P=R=97.73%)")
            (out_dir / "_eval.json").write_text(json.dumps(
                {"model": mdl, "api": api, "TP": tp, "TN": tn, "FP": fp, "FN": fn},
                ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
