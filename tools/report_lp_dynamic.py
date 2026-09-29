# -*- coding: utf-8 -*-
# >>> HISTORICAL-BANNER (Giai doan 5 cleanup)
# HISTORICAL — raw images, KHONG phan anh production.
# Cong cu nay doc anh goc output/form_samples (~850px) va/hoac box/GT cu
# (output/stage4_dynamic_gt/), trong khi production doc anh Tang 1 resize H=2200
# voi zone Tang 3b hien tai. So do cua file nay KHONG duoc dung de ket luan ve
# production (DINH CHINH AGENTS.md 9.10.D). Duong do hien hanh:
#   tools/lp_production_path.py -> tools/bench_lp_prod.py (GT output/stage4_dynamic_gt_v4/).
# <<< HISTORICAL-BANNER
"""
Sinh bao cao TRUC QUAN (HTML 1 file, anh nhung base64) cho benchmark zone dong LOADING_PLAN.
Doc: output/stage4_out/stage4_lp_dynamic_benchmark.json + crops da sinh.
Ghi: output/stage4_out/stage4_lp_dynamic_report.html
"""
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REP = ROOT / "output/stage4_out/stage4_lp_dynamic_benchmark.json"
GT = ROOT / "output/stage4_dynamic_gt/gt_labeled.json"
OUT = ROOT / "output/stage4_out/stage4_lp_dynamic_report.html"
UNIT = ROOT / "output/stage4_out/unit_test_results.json"


def b64(p, cap=900_000):
    try:
        d = Path(p).read_bytes()
        if len(d) > cap:
            return None
        return "data:image/png;base64," + base64.b64encode(d).decode()
    except Exception:
        return None


def esc(s):
    t = str(s) if s is not None else ""
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def mtable(title, d):
    rows = ""
    for k, v in d.items():
        for eng in ("v1", "v2"):
            m = v[eng]
            label = "v1" if eng == "v1" else "ver2"
            rows += (
                "<tr><td>%s</td><td class='eng %s'>%s</td><td>%d</td><td>%d</td><td>%d</td>"
                "<td class='%s'>%d</td><td class='%s'>%d</td><td><b>%s</b></td><td>%s</td><td>%s</td></tr>"
                % (esc(k), eng, label, m["n"], m["tp"], m["tn"],
                   "bad" if m["fp"] else "ok", m["fp"],
                   "bad" if m["fn"] else "ok", m["fn"],
                   m["precision"], m["recall"], m["f1"])
            )
    return ("<h3>%s</h3><div class='scroll'><table><thead><tr><th>Nhom</th><th>Engine</th><th>n</th><th>TP</th><th>TN</th>"
            "<th>FP</th><th>FN</th><th>P%%</th><th>R%%</th><th>F1%%</th></tr></thead><tbody>%s</tbody></table></div>"
            % (esc(title), rows))


CSS = """
:root{
  --paper:#f7f7fa; --surface:#ffffff; --surface-2:#f1f1f7;
  --ink:#16181f; --ink-2:#5a5d6b; --ink-3:#8b8e9c;
  --line:#e2e2ec; --line-2:#cfd0dd;
  --accent:#3f4bc4; --good:#0a6b45; --good-bg:#e7f5ee;
  --bad:#b3241b; --bad-bg:#fdedeb; --warn:#8a5000; --warn-bg:#fdf2df;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --paper:#101118; --surface:#191b24; --surface-2:#22242f;
    --ink:#e8e8f0; --ink-2:#a6a9ba; --ink-3:#787c8d;
    --line:#2c2f3c; --line-2:#3b3f4f;
    --accent:#9aa3ff; --good:#4fc98d; --good-bg:#12332a;
    --bad:#ff8a77; --bad-bg:#3a1c1a; --warn:#e8b45c; --warn-bg:#352a15;
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --paper:#101118; --surface:#191b24; --surface-2:#22242f;
  --ink:#e8e8f0; --ink-2:#a6a9ba; --ink-3:#787c8d;
  --line:#2c2f3c; --line-2:#3b3f4f;
  --accent:#9aa3ff; --good:#4fc98d; --good-bg:#12332a;
  --bad:#ff8a77; --bad-bg:#3a1c1a; --warn:#e8b45c; --warn-bg:#352a15;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:"IBM Plex Sans","Segoe UI",system-ui,sans-serif;font-size:15px;line-height:1.55}
.wrap{max-width:1180px;margin:0 auto;padding-inline:20px;padding-block:32px 64px}
h1{font-family:Newsreader,Georgia,serif;font-weight:600;font-size:clamp(26px,4vw,38px);
  line-height:1.15;margin:0 0 10px;text-wrap:balance;letter-spacing:-.01em}
h2{font-family:Newsreader,Georgia,serif;font-weight:600;font-size:22px;margin:44px 0 6px;
  padding-bottom:7px;border-bottom:1px solid var(--line-2);text-wrap:balance}
h3{font-size:12px;font-weight:600;letter-spacing:.09em;text-transform:uppercase;
  color:var(--ink-2);margin:26px 0 8px}
.sub{color:var(--ink-2);font-size:13.5px;margin:0 0 20px;max-width:75ch}
code{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.88em;
  background:var(--surface-2);padding:1px 5px;border-radius:4px}
.scroll{overflow-x:auto;margin-bottom:14px;border-radius:9px;border:1px solid var(--line)}
table{border-collapse:collapse;width:100%;font-size:13px;background:var(--surface);
  font-variant-numeric:tabular-nums}
th,td{border-bottom:1px solid var(--line);padding:8px 11px;text-align:center;white-space:nowrap}
th{background:var(--surface-2);font-weight:600;font-size:11.5px;letter-spacing:.05em;
  text-transform:uppercase;color:var(--ink-2)}
td:first-child,th:first-child{text-align:left;white-space:normal}
tbody tr:last-child td{border-bottom:none}
.hero td,.hero th{font-size:15px;padding:12px 14px}
.eng{font-weight:600}.v1{color:var(--ink-2)}.v2{color:var(--accent)}
.ok{color:var(--good);font-weight:600}
.bad{color:var(--bad);font-weight:700;background:var(--bad-bg)}
.cal{background:var(--warn-bg);border-left:3px solid var(--warn);padding:13px 16px;
  border-radius:0 8px 8px 0;font-size:13.5px;margin:18px 0;max-width:80ch}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:15px}
.card{border:1px solid var(--line);border-radius:11px;padding:12px;background:var(--surface);
  display:flex;flex-direction:column;gap:7px}
.card.warn{border-color:var(--warn);background:var(--warn-bg)}
.ttl{font-family:"IBM Plex Mono",monospace;font-weight:600;font-size:12.5px;
  display:flex;flex-wrap:wrap;gap:6px;align-items:baseline}
.mut{color:var(--ink-3);font-weight:400;font-size:10.5px}
.role{font-size:12px;color:var(--ink-2);display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.req,.opt,.bp{padding:1px 7px;border-radius:20px;font-size:10px;font-weight:600;
  letter-spacing:.03em;white-space:nowrap}
.req{background:var(--surface-2);color:var(--accent)}
.opt{background:var(--surface-2);color:var(--ink-3)}
.bp{background:var(--surface-2);color:var(--ink-3)}
.bp-WRONG_PLACE{background:var(--bad-bg);color:var(--bad)}
.bp-PARTIAL{background:var(--warn-bg);color:var(--warn)}
.bp-GOOD{background:var(--good-bg);color:var(--good)}
img{width:100%;max-width:100%;border:1px solid var(--line);border-radius:7px;
  background:#fff;display:block}
.noimg{padding:26px;text-align:center;color:var(--ink-3);border:1px dashed var(--line-2);
  border-radius:7px;font-size:12px}
.gtl{font-size:12px;color:var(--ink-2)}
.b{display:inline-block;font-size:10.5px;font-weight:600;padding:3px 8px;border-radius:5px;
  margin-right:6px}
.b.g{background:var(--good-bg);color:var(--good)}
.b.r{background:var(--bad-bg);color:var(--bad)}
.ev{font-family:"IBM Plex Mono",monospace;font-size:9.5px;color:var(--ink-3);
  word-break:break-all;line-height:1.45}
.note{font-size:11.5px;color:var(--ink-2);border-top:1px solid var(--line);padding-top:7px}
@media (max-width:480px){.wrap{padding-block:22px 44px}h2{margin-top:32px}}
"""



def main():
    rep = json.loads(REP.read_text(encoding="utf-8"))
    gt = json.loads(GT.read_text(encoding="utf-8"))
    crop_of = {t["target_id"]: t.get("crop_file") for t in gt["targets"]}

    ov = rep["overall"]
    hero_rows = ""
    for eng, label in (("v1", "v1"), ("v2", "ver2")):
        m = ov[eng]
        hero_rows += (
            "<tr><td class='eng %s'>%s</td><td>%d</td><td>%d</td><td class='%s'>%d</td>"
            "<td class='%s'>%d</td><td><b>%s%%</b></td><td>%s%%</td><td><b>%s%%</b></td><td>%s%%</td></tr>"
            % (eng, label, m["tp"], m["tn"], "bad" if m["fp"] else "ok", m["fp"],
               "bad" if m["fn"] else "ok", m["fn"], m["precision"], m["recall"], m["f1"], m["accuracy"])
        )
    head = ("<table class='hero'><thead><tr><th>Engine</th><th>TP</th><th>TN</th><th>FP</th><th>FN</th>"
            "<th>Precision</th><th>Recall</th><th>F1</th><th>Accuracy</th></tr></thead><tbody>%s</tbody></table>"
            % hero_rows)

    cards = ""
    for r in sorted(rep["per_target"], key=lambda x: (x["file_name"], x["target_id"])):
        cf = crop_of.get(r["target_id"])
        img = b64(ROOT / cf) if cf else None
        exp_present = r["expected"] == "PRESENT"

        def badge(det, lbl):
            ok = det == exp_present
            kind = "TP" if det and exp_present else "FP" if det else "FN" if exp_present else "TN"
            return "<span class='b %s'>%s: %s &middot; %s</span>" % (
                "g" if ok else "r", lbl, "CO" if det else "KHONG", kind)

        both_ok = (r["v1_detected"] == exp_present) and (r["v2_detected"] == exp_present)
        bp = r.get("box_placement") or "NA"
        cards += (
            "<div class='card%s'>"
            "<div class='ttl'>%s <span class='mut'>%s</span></div>"
            "<div class='role'>%s %s <span class='bp bp-%s'>khung: %s</span></div>"
            "%s"
            "<div class='gtl'>GT: <b>%s</b></div>"
            "<div>%s%s</div>"
            "<div class='ev'>v1: %s<br/>ver2: %s</div>"
            "<div class='note'>%s</div></div>"
            % ("" if both_ok else " warn",
               esc(r["target_id"]), esc(r["file_name"]), esc(r["role"]),
               "<span class='req'>bat buoc</span>" if r["required"] else "<span class='opt'>tuy chon</span>",
               esc(bp), esc(bp),
               ("<img src='%s' alt='crop'/>" % img) if img else "<div class='noimg'>(khong co crop)</div>",
               esc(r["expected"]),
               badge(r["v1_detected"], "v1"), badge(r["v2_detected"], "ver2"),
               esc(r["v1_evidence"]), esc(r["v2_evidence"]), esc(r.get("gt_note")))
        )

    unit = ""
    if UNIT.exists():
        u = json.loads(UNIT.read_text(encoding="utf-8"))
        rws = "".join(
            "<tr><td>%s</td><td class='%s'>%s</td><td>%s</td></tr>"
            % (esc(c.get("name")), "ok" if c.get("passed") else "bad",
               "PASS" if c.get("passed") else "FAIL", esc(c.get("detail")))
            for c in u.get("cases", []))
        unit = ("<h2>Unit test engine chu ky (%s/%s PASS)</h2>"
                "<div class='scroll'><table><thead><tr><th>Ca kiem thu</th><th>Ket qua</th><th>Chi tiet</th></tr></thead>"
                "<tbody>%s</tbody></table></div>" % (u.get("passed"), u.get("total"), rws))

    amb = rep.get("ambiguous_targets") or []
    zl = rep["zone_level"]
    zone_tbl = (
        "<h3>Cap zone (phat hien trang khong co khoi ky)</h3><div class='scroll'><table><tbody>"
        "<tr><td>Tong trang cham cap zone</td><td>%d</td></tr>"
        "<tr><td>Dung: trang that su khong co khoi ky</td><td class='ok'>%d</td></tr>"
        "<tr><td>Sai: bo sot khoi ky co that</td><td class='%s'>%d %s</td></tr>"
        "<tr><td>Target AMBIGUOUS (khong cham)</td><td>%d %s</td></tr>"
        "</tbody></table></div>"
        % (zl["total"], zl["correct_no_signature_block"],
           "bad" if zl["missed_signature_block"] else "ok",
           len(zl["missed_signature_block"]), esc(", ".join(zl["missed_signature_block"])),
           len(amb), esc(", ".join(amb)))
    )

    html = (
        "<title>Zone k&#253; Loading Plan</title>"
        "<link rel='stylesheet' href='https://fonts.googleapis.com/css2?"
        "family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&"
        "family=Newsreader:opsz,wght@6..72,500;6..72,600&display=swap'>"
        "<style>%s</style><div class='wrap'>"
        "<h1>T&#7847;ng 4 tr&#234;n zone k&#253; &#273;&#7897;ng c&#7911;a Loading Plan</h1>"
        "<p class='sub'>Ground truth <code>%s</code> &mdash; %s. "
        "%d target ch&#7845;m &#273;i&#7875;m, %d AMBIGUOUS lo&#7841;i kh&#7887;i m&#7851;u s&#7889;, %ss.</p>"
        "<div class='cal'>Benchmark tr&#432;&#7899;c &#273;&#226;y ch&#7841;y ver2 d&#432;&#7899;i b&#7897; h&#7897;p <b>t&#297;nh</b> c&#7911;a v1, "
        "n&#234;n n&#243; &#273;o detector ch&#7913; kh&#244;ng &#273;o pipeline. Trang n&#224;y ch&#7841;y <b>c&#7843; hai</b> engine tr&#234;n c&#249;ng "
        "b&#7897; h&#7897;p <b>&#273;&#7897;ng</b> do T&#7847;ng 3b sinh, ch&#7845;m theo nh&#227;n g&#225;n b&#7857;ng m&#7855;t. "
        "AMBIGUOUS b&#7883; lo&#7841;i kh&#7887;i m&#7851;u s&#7889; thay v&#236; &#226;m th&#7847;m t&#237;nh l&#224; &#273;&#250;ng.</div>"
        "<h2>T&#7893;ng th&#7875;</h2><div class='scroll'>%s</div>"
        "<h2>B&#243;c t&#225;ch</h2>%s%s%s%s"
        "%s"
        "<h2>Th&#432; vi&#7879;n &#244; k&#253;</h2>"
        "<p class='sub'>&#7842;nh crop g&#7889;c, kh&#244;ng x&#7917; l&#253;. Th&#7867; n&#7873;n v&#224;ng l&#224; ca c&#243; &#237;t nh&#7845;t m&#7897;t engine sai.</p>"
        "<div class='grid'>%s</div></div>"
        % (CSS, esc(rep["gt_source"]), esc(rep["gt_method"]), rep["n_scored"],
           rep["n_ambiguous_excluded"], rep["elapsed_sec"], head,
           mtable("Theo required", rep["by_required"]),
           mtable("Theo vai tro ky", rep["by_role"]),
           mtable("Theo chat luong dat khung (annotator cham)", rep["by_box_placement"]),
           zone_tbl, unit, cards)
    )
    OUT.write_text(html, encoding="utf-8")
    print("-> %s  (%.1f KB)" % (OUT, OUT.stat().st_size / 1024))


if __name__ == "__main__":
    import sys
    print("[HISTORICAL] report_lp_dynamic.py: do tren anh RAW ~850px / box-GT cu — KHONG phan anh production. "
          "Dung tools/bench_lp_prod.py (duong production, GT v4).", file=sys.stderr)
    main()
