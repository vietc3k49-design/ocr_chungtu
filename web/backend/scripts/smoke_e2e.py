"""Smoke test E2E trên compose đang chạy: đăng ký → mail Mailpit → xác thực → đăng nhập → upload → worker → kết quả → duyệt.

    python web/backend/scripts/smoke_e2e.py [--api http://localhost:8000/api] [--mailpit http://localhost:8025]
In JSON tóm tắt; exit 1 nếu có bước hỏng.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
H = {"X-Requested-With": "kido"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000/api")
    ap.add_argument("--mailpit", default="http://localhost:8025")
    ap.add_argument("--files", nargs="*", default=["Load_3.2__0.png", "Load_3.2__1.png"])
    ap.add_argument("--reference", action="store_true", help="(chỉ admin mới được bật — user thường bị bỏ qua)")
    a = ap.parse_args()
    out = {}
    email = f"smoke_{uuid.uuid4().hex[:8]}@kido-ocr.local"
    pw = "MatKhau123!"
    c = httpx.Client(base_url=a.api, headers=H, timeout=60)
    r = c.post("/auth/register", json={"email": email, "password": pw, "full_name": "Smoke Test"})
    out["register"] = r.status_code
    r = c.post("/auth/login", json={"email": email, "password": pw})
    out["login_before_verify"] = [r.status_code, r.json().get("detail", {}).get("code")]
    tok = None
    for _ in range(20):
        msgs = httpx.get(f"{a.mailpit}/api/v1/search", params={"query": f"to:{email}"}).json().get("messages", [])
        if msgs:
            m = httpx.get(f"{a.mailpit}/api/v1/message/{msgs[0]['ID']}").json()
            mt = re.search(r"token=([A-Za-z0-9_\-]+)", m.get("Text", ""))
            tok = mt.group(1) if mt else None
            out["mail_subject"] = m.get("Subject")
            break
        time.sleep(0.5)
    if not tok:
        out["error"] = "không thấy mail xác thực trong Mailpit"
        print(json.dumps(out, ensure_ascii=False, indent=1)); return 1
    out["verify"] = c.post("/auth/verify-email", json={"token": tok}).status_code
    out["verify_reuse"] = c.post("/auth/verify-email", json={"token": tok}).json().get("detail", {}).get("code")
    r = c.post("/auth/login", json={"email": email, "password": pw})
    out["login"] = r.status_code
    files = [("files", (fn, (ROOT / "output/form_samples" / fn).read_bytes(), "image/png")) for fn in a.files]
    files.append(("files", ("gia_mao.png", b"day khong phai anh", "image/png")))
    r = c.post("/groups", data={"title": "smoke bad"}, files=files)
    out["upload_fake_png"] = [r.status_code, r.json().get("detail", {}).get("code")]
    files = files[:-1]
    t0 = time.time()
    r = c.post("/groups", data={"title": "smoke " + "+".join(a.files), "use_reference": str(a.reference).lower()},
               files=files)
    out["upload"] = r.status_code
    g = r.json()
    gid = g["id"]
    out["use_reference_effective"] = g.get("use_reference")
    last = None
    while time.time() - t0 < 600:
        s = c.get(f"/groups/{gid}/status").json()
        j = s.get("job") or {}
        cur = (j.get("stage"), j.get("percent"))
        if cur != last:
            print(f"  {time.time()-t0:5.1f}s {s['status']} {j.get('stage')} {j.get('percent')}% {j.get('message')}",
                  flush=True)
            last = cur
        if s["status"] in ("DONE", "FAILED"):
            break
        time.sleep(1.5)
    out["job_status"] = s["status"]
    out["job_sec"] = round(time.time() - t0, 1)
    if s["status"] != "DONE":
        out["job_error"] = (s.get("job") or {}).get("error")
        print(json.dumps(out, ensure_ascii=False, indent=1)); return 1
    d = c.get(f"/groups/{gid}").json()
    out["pages"] = [{k: p.get(k) for k in ("scan_index", "doc_type", "system", "s4_doc_status",
                                           "status_label_vi", "status_tone", "supported")} for p in d["pages"]]
    out["dossiers"] = [{k: x.get(k) for k in ("doc_status", "effective_doc_status", "pages", "page_refs")}
                       for x in d.get("dossiers", [])]
    lp = [p for p in d["pages"] if p.get("supported")]
    if lp:
        pid = lp[0]["id"]
        pd = c.get(f"/pages/{pid}").json()
        tg = pd["s4"]["targets"]
        out["page0_targets"] = [(t["role"], t["required"], t["detected"]) for t in tg]
        req = [t for t in tg if t["required"]]
        if req:
            r = c.post(f"/pages/{pid}/targets/{req[0]['index']}/review",
                       json={"decision": "NOT_SIGNED", "note": "smoke: thử đánh thiếu"})
            out["review_status"] = r.status_code
            e = r.json().get("effective", {})
            out["effective_after_not_signed_required"] = e.get("doc_status")
        img = c.get(f"/pages/{pid}/image", params={"kind": "stage1"})
        out["image_stage1"] = [img.status_code, img.headers.get("content-type"), len(img.content)]
    c2 = httpx.Client(base_url=a.api, headers=H)
    out["anon_group_access"] = c2.get(f"/groups/{gid}").status_code
    out["no_csrf_header"] = httpx.post(f"{a.api}/auth/logout", cookies=c.cookies).status_code
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
