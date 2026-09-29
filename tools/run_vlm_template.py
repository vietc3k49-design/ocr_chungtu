# -*- coding: utf-8 -*-
"""Sinh template ô ký + mộc bằng API vision — Giai đoạn 1 của docs/VLM_PIPELINE_PLAN.md.

CHỐNG ĐỐT QUOTA (bắt buộc, vì tài khoản chỉ còn ~1950đ):
  * `--max-calls` cầu dao cứng: đếm số lần gọi THẬT (không tính cache), vượt là dừng.
  * `--dry-run` in đúng danh sách sẽ gọi + tiền ước tính, KHÔNG gọi gì (0đ).
  * Dừng ngay sau `--max-loi` lần lỗi LIÊN TIẾP (mặc định 3) — tránh lặp lỗi đốt tiền.
  * Cache kiểm TRƯỚC khi gọi; ảnh đã có kết quả thì không bao giờ gọi lại.
  * Gọi hỏng KHÔNG ghi cache (nằm ở vlm_gateway) nên không che mất lỗi.

Gửi CẢ TRANG, không cắt: với doc_type chưa có template thì chưa biết ô ký nằm đâu,
cắt bừa có thể cắt mất khối ô ký. Giá không đổi theo kích thước ảnh (đo 28/09).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vlm_gateway as gw                                          # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
IMG_DIR = ROOT / "output/stage1_out/images/form_samples"
MAU = ROOT / "scratch/_vlm_template/mau_chon.json"
OUT = ROOT / "output/vlm_templates/raw"
GIA_MOI_LAN = 5.71                                                # đo từ số dư thật 28/09

PROMPT_VERSION = "template-v2-box2d"
# Dung DUNG dinh dang goc cua Gemini: box_2d = [ymin, xmin, ymax, xmax], so nguyen 0-1000.
# Bat model tra [x0,y0,x1,y1] 0..1 (bang template-v1) lam no LAI hai dinh dang: co anh tra
# x theo ti le con y theo thang 1000, co anh dao truc (x1 < x0). Notebook
# ocr-llm-sig-gemini-test.ipynb cua chinh du an da dung dinh dang goc nay va chay duoc.
PROMPT = """Find EVERY pre-printed signature box on this Vietnamese delivery document (include boxes that are still empty) and EVERY ink stamp/seal applied to the paper. Do NOT include printed body text, titles, table lines, logos, or the digital-signature block of an e-invoice ("Signature Valid", "Duoc ky boi").
Return ONLY a JSON object, no prose: {"loai_chung_tu":"<document type in Vietnamese>","o_ky":[{"ten":"<printed role title above the box>","box_2d":[ymin,xmin,ymax,xmax],"da_ky":true|false}],"moc":[{"box_2d":[ymin,xmin,ymax,xmax],"chu_doc_duoc":"<text on the stamp>"}]}
box_2d holds INTEGERS normalised to 0-1000 in the order ymin, xmin, ymax, xmax; a signature box must cover the blank signing area below its role title, while a stamp box hugs the ink of the seal itself."""


def chuan_hoa_box(b):
    """box_2d [ymin,xmin,ymax,xmax] 0-1000 -> [x0,y0,x1,y1] 0..1, chuan hoa TUNG TRUC.

    Chuan hoa tung truc vi model tung tra lai hai he (x theo ti le, y theo thang 1000);
    chia deu ca 4 so thi x bi ep ve ~0.0001. Tra None neu khong cuu duoc -> nguoi soat quyet.
    """
    if not b or len(b) != 4:
        return None
    try:
        ymin, xmin, ymax, xmax = (float(v) for v in b)
    except (TypeError, ValueError):
        return None
    ys = [v / 1000.0 if max(abs(ymin), abs(ymax)) > 1.5 else v for v in (ymin, ymax)]
    xs = [v / 1000.0 if max(abs(xmin), abs(xmax)) > 1.5 else v for v in (xmin, xmax)]
    y0, y1 = sorted(ys)                       # dao nguoc thi xep lai, khong vut bo
    x0, x1 = sorted(xs)
    out = [x0, y0, x1, y1]
    if any(v < -0.02 or v > 1.02 for v in out) or (x1 - x0) < 0.01 or (y1 - y0) < 0.005:
        return None
    return [min(max(v, 0.0), 1.0) for v in out]


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=25, help="cầu dao cứng số lần gọi THẬT")
    ap.add_argument("--max-loi", type=int, default=3, help="dừng sau N lỗi liên tiếp")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--chi", default=None, help="chỉ chạy doc_type này")
    a = ap.parse_args()

    api, mdl, key = gw._cfg()
    mau = json.loads(MAU.read_text(encoding="utf-8"))
    if a.chi:
        mau = [m for m in mau if m["doc_type"] == a.chi]

    # --- phân loại trước: cái nào đã có cache (0đ), cái nào phải gọi thật
    can_goi, da_co = [], []
    for m in mau:
        p = IMG_DIR / m["file_name"]
        if not p.exists():
            print(f"  ⚠ thiếu ảnh: {m['file_name']}")
            continue
        data, mime = gw.thu_nho(p.read_bytes(), int(gw.load_env().get("VLM_MAX_EDGE") or 1400))
        ck = gw.cache_key(data, mdl, PROMPT, PROMPT_VERSION, 0.0)
        if (gw.CACHE_DIR / mdl / f"{ck}.json").exists():
            da_co.append(m)
        else:
            can_goi.append(m)

    print(f"API   {api}\nMODEL {mdl}\n")
    print(f"Tổng mẫu {len(mau)} · đã có cache {len(da_co)} (0đ) · phải gọi thật {len(can_goi)}")
    print(f"Ước chi: {len(can_goi)} × {GIA_MOI_LAN}đ = {len(can_goi)*GIA_MOI_LAN:.0f}đ")
    print(f"Cầu dao: tối đa {a.max_calls} lần gọi, dừng sau {a.max_loi} lỗi liên tiếp\n")

    if len(can_goi) > a.max_calls:
        print(f"⚠ Cần {len(can_goi)} lần gọi nhưng cầu dao là {a.max_calls} "
              f"⇒ sẽ chạy {a.max_calls} ảnh rồi DỪNG. Phần xong nằm trong cache, "
              f"chạy lại với --max-calls lớn hơn để tiếp tục (không gọi lại phần đã xong).\n")
    if a.dry_run:
        for m in can_goi:
            print(f"  sẽ gọi: {m['doc_type']:20s} {m['system']:22s} {m['file_name']}")
        print("\n(dry-run — chưa gọi gì, 0đ)")
        return 0

    n_goi = n_loi_lien_tiep = n_ok = 0
    for i, m in enumerate(mau, 1):
        p = IMG_DIR / m["file_name"]
        if not p.exists():
            continue
        if n_goi >= a.max_calls:
            print(f"\n⛔ Chạm cầu dao {a.max_calls} lần gọi — dừng, còn {len(mau)-i+1} ảnh chưa chạy.")
            break
        r = gw.goi_file(p, PROMPT, prompt_version=PROMPT_VERSION, so_lan=1)
        if not r.get("cached"):
            n_goi += 1
        data = parse_json(r.get("content"))
        n_hong = 0
        if data:
            for nhom in ("o_ky", "moc"):
                for o in (data.get(nhom) or []):
                    o["bbox"] = chuan_hoa_box(o.get("box_2d") or o.get("bbox"))
                    n_hong += o["bbox"] is None
                    if isinstance(o.get("ten"), str):
                        o["ten"] = " ".join(o["ten"].split())      # gop xuong dong trong nhan
        ok = bool(r.get("ok") and data is not None)
        n_loi_lien_tiep = 0 if ok else n_loi_lien_tiep + 1
        n_ok += ok

        d = OUT / m["doc_type"]
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{Path(m['file_name']).stem}.json").write_text(json.dumps(
            {**m, "data": data, "error": r.get("error"), "cached": r.get("cached"),
             "latency_s": r.get("latency_s"), "usage": r.get("usage"),
             "prompt_version": PROMPT_VERSION}, ensure_ascii=False, indent=1), encoding="utf-8")

        tag = "cache" if r.get("cached") else f"{n_goi}/{a.max_calls}"
        if ok:
            st = (f"{len(data.get('o_ky') or [])} ô ký, {len(data.get('moc') or [])} mộc"
                  + (f"  ⚠ {n_hong} bbox hỏng" if n_hong else ""))
        else:
            st = "✗ " + (r.get("error") or "KHONG_PARSE_JSON")[:80]
        print(f"[{i:2d}/{len(mau)} | {100*i//len(mau):3d}% | {tag:>7s}] "
              f"{m['doc_type']:20s} {Path(m['file_name']).stem:24s} {st}")

        if n_loi_lien_tiep >= a.max_loi:
            print(f"\n⛔ DỪNG: {a.max_loi} lỗi liên tiếp. Đã gọi {n_goi} lần "
                  f"(~{n_goi*GIA_MOI_LAN:.0f}đ). Sửa lỗi rồi chạy lại — phần xong giữ trong cache.")
            break

    print(f"\nXong: {n_ok}/{len(mau)} ảnh có kết quả · gọi thật {n_goi} lần "
          f"(~{n_goi*GIA_MOI_LAN:.0f}đ) · kết quả ở {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
