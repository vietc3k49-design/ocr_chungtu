# -*- coding: utf-8 -*-
"""Giai đoạn 2 + 3 của docs/VLM_PIPELINE_PLAN.md — KHÔNG gọi API, 0đ.

  Giai đoạn 2: đo độ trôi tọa độ giữa các mẫu cùng doc_type -> tự phân hạng A/B.
  Giai đoạn 3: sinh MỘT trang HTML tự chứa để người soát tay, xuất JSON duyệt.

Ngưỡng phân hạng (docs/VLM_PIPELINE_PLAN.md §Giai đoạn 2):
  Δy0 <= 0.05 và Δx0 <= 0.03  -> hạng A, hardcode được
  Δy0 >  0.05                 -> hạng B, phải dò y theo nhãn chức danh
  chỉ 1 mẫu                   -> CHUA_XAC_DINH, tạm xếp B cho an toàn
Mốc đối chiếu đã đo: LOADING_PLAN có Δy0 = 0.54, Δx0 = 0.01–0.06.
"""
import base64
import html
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "output/vlm_templates/raw"
IMG_DIR = ROOT / "output/stage1_out/images/form_samples"
OUT_DIR = ROOT / "output/vlm_templates_review"
NGUONG_Y, NGUONG_X = 0.05, 0.03


def doc_ket_qua():
    recs = []
    for f in sorted(RAW.glob("*/*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("data"):
            recs.append(d)
    return recs


def ghep_vai_tro(ten):
    """Gom nhãn về dạng so khớp được: bỏ dấu ngoặc hướng dẫn, thường hoá."""
    t = (ten or "").lower()
    for bo in ("(ký ghi rõ họ tên)", "(ký, ghi rõ họ tên)", "(ký và ghi rõ họ tên)",
               "(ký tên)", "(ký)"):
        t = t.replace(bo, "")
    return " ".join(t.split())


def phan_hang(recs):
    """Trả {doc_type: {hang, n_mau, vai_tro: {ten: {x0,y0,x1,y1, dy, dx, n}}}}"""
    theo_dt = defaultdict(list)
    for r in recs:
        theo_dt[r["doc_type"]].append(r)

    kq = {}
    for dt, rs in sorted(theo_dt.items()):
        # Gom theo (vai trò, thứ tự trong CHÍNH ảnh đó) rồi mới so GIỮA CÁC ẢNH.
        # Không tách theo ảnh thì nhãn trùng nhau trong cùng một tờ (biểu mẫu có nhiều ô
        # cùng tên) bị tính nhầm thành "lệch giữa các mẫu" — 1 mẫu vẫn ra Δ khác 0.
        vt = defaultdict(dict)                      # khoá -> {file_name: bbox}
        for r in rs:
            cung_ten = defaultdict(list)
            for o in (r["data"].get("o_ky") or []):
                if o.get("bbox"):
                    cung_ten[ghep_vai_tro(o.get("ten"))].append(o["bbox"])
            for ten, bs in cung_ten.items():
                bs.sort(key=lambda b: b[0])         # trái sang phải, để đánh số ổn định
                for k, b in enumerate(bs):
                    khoa = ten if len(bs) == 1 else f"{ten} #{k+1}"
                    vt[khoa][r["file_name"]] = b

        vai_tro, dy_max, dx_max = {}, 0.0, 0.0
        for ten, theo_file in vt.items():
            boxes = list(theo_file.values())
            xs0 = [b[0] for b in boxes]; ys0 = [b[1] for b in boxes]
            xs1 = [b[2] for b in boxes]; ys1 = [b[3] for b in boxes]
            n_anh = len(theo_file)                  # SỐ ẢNH, không phải số hộp
            dy = (max(ys0) - min(ys0)) if n_anh > 1 else 0.0
            dx = (max(xs0) - min(xs0)) if n_anh > 1 else 0.0
            if n_anh > 1:
                dy_max = max(dy_max, dy); dx_max = max(dx_max, dx)
            vai_tro[ten] = {"x0": min(xs0), "y0": min(ys0), "x1": max(xs1), "y1": max(ys1),
                            "dy": round(dy, 3), "dx": round(dx, 3), "n": n_anh}
        # mộc: bao chung mọi mẫu
        mb = [o["bbox"] for r in rs for o in (r["data"].get("moc") or []) if o.get("bbox")]
        moc = None
        if mb:
            moc = {"x0": min(b[0] for b in mb), "y0": min(b[1] for b in mb),
                   "x1": max(b[2] for b in mb), "y1": max(b[3] for b in mb), "n": len(mb)}

        nhieu_mau = any(v["n"] > 1 for v in vai_tro.values())
        if not nhieu_mau:
            hang = "CHUA_XAC_DINH"
            ly_do = ("chỉ có 1 mẫu" if len(rs) < 2
                     else "nhiều mẫu nhưng KHÔNG khớp được nhãn vai trò nào giữa các mẫu")
        elif dy_max <= NGUONG_Y and dx_max <= NGUONG_X:
            hang = "A"; ly_do = f"Δy={dy_max:.3f} ≤ {NGUONG_Y} và Δx={dx_max:.3f} ≤ {NGUONG_X}"
        else:
            hang = "B"; ly_do = f"Δy={dy_max:.3f} / Δx={dx_max:.3f} vượt ngưỡng"
        kq[dt] = {"hang": hang, "n_mau": len(rs), "dy_max": round(dy_max, 3),
                  "dx_max": round(dx_max, 3), "vai_tro": vai_tro, "moc": moc, "ly_do": ly_do,
                  "systems": sorted({r["system"] for r in rs})}
    return kq


def anh_b64(name, max_w=1100):
    from io import BytesIO
    from PIL import Image
    p = IMG_DIR / name
    im = Image.open(p).convert("RGB")
    if im.width > max_w:
        s = max_w / im.width
        im = im.resize((max_w, round(im.height * s)), Image.LANCZOS)
    b = BytesIO(); im.save(b, "JPEG", quality=72)
    return base64.b64encode(b.getvalue()).decode()


CSS = """
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 system-ui,Segoe UI,sans-serif;background:#f6f7f9;color:#14181f}
header{position:sticky;top:0;z-index:9;background:#fff;border-bottom:1px solid #dfe3e8;padding:12px 18px;
  display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:17px;margin:0}
.pill{padding:2px 9px;border-radius:99px;font-size:12px;font-weight:600}
.A{background:#d9f2e3;color:#0d6b3d}.B{background:#fde8cf;color:#8a4b00}.CHUA_XAC_DINH{background:#e8e8ee;color:#444}
main{padding:18px;max-width:1240px;margin:0 auto}
.dt{background:#fff;border:1px solid #dfe3e8;border-radius:10px;margin-bottom:22px;overflow:hidden}
.dt>h2{margin:0;padding:12px 16px;font-size:15px;border-bottom:1px solid #eceff3;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.meta{font-size:12px;color:#5b6472;font-weight:400}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid #eceff3;padding:6px 10px;text-align:left}
th{background:#fafbfc;font-weight:600}
.imgs{display:flex;flex-wrap:wrap;gap:18px;padding:14px 16px}
.card{flex:1 1 360px;min-width:300px}
.wrap{position:relative;display:inline-block;width:100%;border:1px solid #dfe3e8;border-radius:6px;overflow:hidden;background:#fff}
.wrap img{display:block;width:100%}
.bx{position:absolute;border:2px solid;border-radius:2px}
.sig{border-color:#1f9d55;background:rgba(31,157,85,.10)}
.stamp{border-color:#8b5cf6;background:rgba(139,92,246,.12)}
.lb{position:absolute;transform:translateY(-100%);background:#1f9d55;color:#fff;font-size:10px;
  padding:1px 4px;border-radius:3px;white-space:nowrap}
.lb.s{background:#8b5cf6}
.rows{margin-top:8px}
.row{display:flex;gap:6px;align-items:center;padding:3px 0;font-size:12.5px;border-bottom:1px dashed #eceff3}
.row .n{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row button{border:1px solid #cfd6de;background:#fff;border-radius:5px;padding:2px 7px;cursor:pointer;font-size:12px}
.row button.on[data-v=dung]{background:#1f9d55;color:#fff;border-color:#1f9d55}
.row button.on[data-v=sai]{background:#dc2626;color:#fff;border-color:#dc2626}
.row button.on[data-v=lech]{background:#d97706;color:#fff;border-color:#d97706}
.miss{margin-top:6px}
.miss textarea{width:100%;min-height:42px;font:12px system-ui;border:1px solid #cfd6de;border-radius:5px;padding:5px}
#xuat{margin-left:auto;background:#14181f;color:#fff;border:0;border-radius:7px;padding:9px 16px;cursor:pointer;font-weight:600}
#dem{font-size:12px;color:#5b6472}
.warn{color:#b91c1c;font-weight:600}
"""

JS = """
const KQ={};
function bam(b){
  const r=b.closest('.row'), id=r.dataset.id, v=b.dataset.v;
  r.querySelectorAll('button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on'); KQ[id]=v; dem();
}
function dem(){
  const t=document.querySelectorAll('.row').length;
  document.getElementById('dem').textContent=`đã chấm ${Object.keys(KQ).length}/${t} khung`;
}
function xuat(){
  const bo={};
  document.querySelectorAll('.miss textarea').forEach(t=>{ if(t.value.trim()) bo[t.dataset.file]=t.value.trim(); });
  const data={danh_gia:KQ, bo_sot:bo, luc:new Date().toISOString()};
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,1)],{type:'application/json'}));
  a.download='vlm_review_ket_qua.json'; a.click();
}
document.addEventListener('DOMContentLoaded',dem);
"""


def sinh_html(recs, hang):
    theo_dt = defaultdict(list)
    for r in recs:
        theo_dt[r["doc_type"]].append(r)

    p = ['<!doctype html><html lang="vi"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>Soát template ô ký & mộc</title><style>', CSS, '</style></head><body>',
         '<header><h1>Soát template ô ký &amp; mộc</h1>',
         f'<span class="meta">{len(recs)} ảnh · {len(theo_dt)} doc_type · '
         'xanh = ô ký, tím = mộc</span>',
         '<span id="dem" class="meta"></span>',
         '<button id="xuat" onclick="xuat()">Xuất JSON đã chấm</button></header><main>']

    for dt in sorted(theo_dt):
        h = hang[dt]
        p.append(f'<section class="dt"><h2>{html.escape(dt)} '
                 f'<span class="pill {h["hang"]}">hạng {h["hang"]}</span>'
                 f'<span class="meta">{h["n_mau"]} mẫu · kênh: {", ".join(h["systems"])} · '
                 f'Δy={h["dy_max"]} Δx={h["dx_max"]} · {html.escape(h["ly_do"])}</span></h2>')

        p.append('<table><tr><th>Vai trò</th><th>x0</th><th>y0</th><th>x1</th><th>y1</th>'
                 '<th>Δy</th><th>Δx</th><th>số mẫu</th></tr>')
        for ten, v in h["vai_tro"].items():
            canh = ' class="warn"' if v["dy"] > NGUONG_Y else ''
            p.append(f'<tr><td>{html.escape(ten)}</td><td>{v["x0"]:.3f}</td><td>{v["y0"]:.3f}</td>'
                     f'<td>{v["x1"]:.3f}</td><td>{v["y1"]:.3f}</td><td{canh}>{v["dy"]}</td>'
                     f'<td>{v["dx"]}</td><td>{v["n"]}</td></tr>')
        if h["moc"]:
            m = h["moc"]
            p.append(f'<tr><td><b>MỘC (bao chung)</b></td><td>{m["x0"]:.3f}</td><td>{m["y0"]:.3f}</td>'
                     f'<td>{m["x1"]:.3f}</td><td>{m["y1"]:.3f}</td><td>—</td><td>—</td><td>{m["n"]}</td></tr>')
        p.append('</table><div class="imgs">')

        for r in theo_dt[dt]:
            fn = r["file_name"]
            p.append(f'<div class="card"><div class="meta" style="margin-bottom:5px">'
                     f'{html.escape(Path(fn).stem)} · <b>{html.escape(r["system"])}</b></div>')
            p.append(f'<div class="wrap"><img src="data:image/jpeg;base64,{anh_b64(fn)}" alt="">')
            khung = []
            for i, o in enumerate(r["data"].get("o_ky") or []):
                if o.get("bbox"):
                    khung.append(("sig", i, o["bbox"], o.get("ten") or "?",
                                  "ĐÃ KÝ" if o.get("da_ky") else "trống"))
            for i, o in enumerate(r["data"].get("moc") or []):
                if o.get("bbox"):
                    khung.append(("stamp", i, o["bbox"], o.get("chu_doc_duoc") or "mộc", ""))
            for kind, i, b, ten, tt in khung:
                x0, y0, x1, y1 = b
                p.append(f'<div class="bx {kind}" style="left:{x0*100:.2f}%;top:{y0*100:.2f}%;'
                         f'width:{(x1-x0)*100:.2f}%;height:{(y1-y0)*100:.2f}%">'
                         f'<span class="lb{" s" if kind=="stamp" else ""}">{i}</span></div>')
            p.append('</div><div class="rows">')
            for kind, i, b, ten, tt in khung:
                rid = f'{fn}#{kind}{i}'
                p.append(f'<div class="row" data-id="{html.escape(rid)}">'
                         f'<span class="n"><b>{i}</b> {"🖊" if kind=="sig" else "🔴"} '
                         f'{html.escape(ten[:44])} <span class="meta">{tt}</span></span>'
                         '<button data-v="dung" onclick="bam(this)">Đúng</button>'
                         '<button data-v="lech" onclick="bam(this)">Lệch</button>'
                         '<button data-v="sai" onclick="bam(this)">Sai</button></div>')
            p.append(f'</div><div class="miss"><textarea data-file="{html.escape(fn)}" '
                     'placeholder="API bỏ sót khung nào? Ghi vào đây (vd: thiếu ô Thủ kho ở giữa dưới)">'
                     '</textarea></div></div>')
        p.append('</div></section>')

    p.append('</main><script>' + JS + '</script></body></html>')
    return "".join(p)


def main():
    recs = doc_ket_qua()
    if not recs:
        print("Chưa có kết quả nào ở", RAW); return 2
    hang = phan_hang(recs)

    print(f"{len(recs)} ảnh · {len(hang)} doc_type\n")
    print(f"{'doc_type':22s} {'hạng':14s} {'mẫu':>4s} {'Δy':>6s} {'Δx':>6s}  ô ký  mộc")
    for dt, h in hang.items():
        print(f"{dt:22s} {h['hang']:14s} {h['n_mau']:4d} {h['dy_max']:6.3f} {h['dx_max']:6.3f}"
              f"  {len(h['vai_tro']):4d}  {h['moc']['n'] if h['moc'] else 0:3d}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "phan_hang.json").write_text(
        json.dumps(hang, ensure_ascii=False, indent=1), encoding="utf-8")
    f = OUT_DIR / "index.html"
    f.write_text(sinh_html(recs, hang), encoding="utf-8")
    print(f"\nTrang soát: {f}  ({f.stat().st_size/1024:.0f} KB)")
    print(f"Phân hạng : {OUT_DIR/'phan_hang.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
