# -*- coding: utf-8 -*-
"""Vẽ ảnh soát tay các ô ký của một template -> test/<DOC_TYPE>_o_bat_buoc.png

Dùng khi làm template theo từng biểu mẫu: đọc config/form_signature_templates.json,
khoanh các ô BẮT BUỘC (xanh) và tuỳ chọn khoanh cả ô không bắt buộc (xám),
kèm bảng chú thích tên vai trò bên dưới ảnh.

  python tools/ve_o_bat_buoc.py LENH_DIEU_XE
  python tools/ve_o_bat_buoc.py LENH_DIEU_XE --ca-o-khong-bat-buoc
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / "config/form_signature_templates.json"
IMG_DIR = ROOT / "output/stage1_out/images/form_samples"
OUT_DIR = ROOT / "test"

XANH, XAM = (0, 150, 60), (140, 140, 140)


def font(sz):
    for p in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf",
              r"C:\Windows\Fonts\tahoma.ttf"):
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, sz)
            except Exception:                                     # noqa: BLE001
                pass
    return ImageFont.load_default()


def _bo_dau(s):
    import unicodedata
    s = s.replace("Đ", "D").replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return "_".join(s.split())


def ten_file(T, doc_type):
    """Tên file theo quy ước test/: <số thứ tự 2 chữ số>_<Tên tiếng Việt bỏ dấu>."""
    stt = T.get("so_thu_tu")
    ten = _bo_dau(T.get("ten_hien_thi") or doc_type)
    return f"{stt:02d}_{ten}" if stt else ten


def ve(doc_type, anh, targets, ten_file_ra):
    im = Image.open(anh).convert("RGB")
    W, H = im.size
    n_dong = (len(targets) + 1) // 2
    chu_thich_h = 130 + n_dong * 46 + 60
    canvas = Image.new("RGB", (W, H + chu_thich_h), (255, 255, 255))
    canvas.paste(im, (0, 0))
    dr = ImageDraw.Draw(canvas)
    F_SO, F_TEN, F_TD = font(30), font(26), font(36)

    for i, t in enumerate(targets, 1):
        mau = XANH if t.get("required", True) else XAM
        b = t["box_norm"]
        x0, y0, x1, y1 = b[0] * W, b[1] * H, b[2] * W, b[3] * H
        dr.rectangle([x0, y0, x1, y1], outline=mau, width=6)
        by = y0 - 40 if y0 > 45 else y0 + 4
        dr.ellipse([x0 - 4, by, x0 + 40, by + 40], fill=mau, outline=(255, 255, 255), width=3)
        w = dr.textlength(str(i), font=F_SO)
        dr.text((x0 + 18 - w / 2, by + 4), str(i), fill=(255, 255, 255), font=F_SO)

    dr.line([(0, H), (W, H)], fill=(200, 200, 200), width=3)
    n_bb = sum(1 for t in targets if t.get("required", True))
    dr.text((30, H + 18), f"{doc_type} — {n_bb} ô ký BẮT BUỘC / {len(targets)} ô",
            fill=(20, 20, 20), font=F_TD)
    y = H + 84
    for i, t in enumerate(targets, 1):
        cx = 40 if i <= n_dong else int(W * 0.52)
        cy = y + ((i - 1) % n_dong) * 46
        mau = XANH if t.get("required", True) else XAM
        dr.ellipse([cx, cy, cx + 36, cy + 36], fill=mau)
        w = dr.textlength(str(i), font=F_SO)
        dr.text((cx + 18 - w / 2, cy + 3), str(i), fill=(255, 255, 255), font=F_SO)
        hau = "" if t.get("required", True) else "  (không bắt buộc)"
        dr.text((cx + 50, cy + 5), t["role"] + hau, fill=(20, 20, 20), font=F_TEN)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / ten_file_ra
    canvas.save(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_type")
    ap.add_argument("--anh", default=None, help="đường dẫn ảnh; mặc định lấy mẫu đã soát")
    ap.add_argument("--ca-o-khong-bat-buoc", action="store_true")
    a = ap.parse_args()

    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    T = cfg["templates"].get(a.doc_type)
    if not T:
        print(f"Chưa có template {a.doc_type} trong {CFG.name}. "
              f"Có: {', '.join(cfg['templates'])}")
        return 2
    targets = T["targets"] if a.ca_o_khong_bat_buoc else [
        t for t in T["targets"] if t.get("required", True)]

    anh = Path(a.anh) if a.anh else IMG_DIR / (T.get("anh_mau") or "")
    if not anh.exists():
        cands = sorted(IMG_DIR.glob("*.png"))
        print(f"Không thấy ảnh mẫu. Truyền --anh <đường dẫn>. ({len(cands)} ảnh trong {IMG_DIR.name})")
        return 2

    hau = "tat_ca_o" if a.ca_o_khong_bat_buoc else "o_bat_buoc"
    out = ve(a.doc_type, anh, targets, f"{ten_file(T, a.doc_type)}__{hau}.png")
    print(f"{out}  ({out.stat().st_size/1024:.0f} KB, {len(targets)} ô)")
    for i, t in enumerate(targets, 1):
        print(f"  {i:2d}. {'[BB]' if t.get('required', True) else '[--]'} {t['role']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
