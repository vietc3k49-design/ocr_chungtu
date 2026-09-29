# -*- coding: utf-8 -*-
"""Client cho gateway vision chuẩn OpenAI (mặc định platform.beeknoee.com).

Nguyên tắc giữ kỷ luật số liệu của dự án:
  * CACHE theo sha256(bytes ảnh) + model + version prompt -> chạy lại DIFF = 0,
    và mọi con số truy được về file trong `output/vlm_cache/`.
  * Hỏng thì TRẢ LỖI, không raise, không dự phòng âm thầm sang model khác.
  * Không tự ghi vào artifact của Tầng 1-4; caller quyết định dùng kết quả ra sao.

Cấu hình đọc từ `.env` ở gốc dự án (hoặc biến môi trường, ưu tiên môi trường):
  VLM_API      endpoint      (mặc định https://platform.beeknoee.com/v1/chat/completions)
  VLM_MODEL    tên model     (mặc định gemini-2.5-flash-lite)
  VLM_API_KEY  key           (bắt buộc)
"""
import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "output" / "vlm_cache"

DEFAULT_API = "https://platform-api.beeknoee.com/v1/chat/completions"
DEFAULT_MODEL = "gemini-2.5-flash-lite"


def load_env(path=None):
    """Đọc .env dạng KEY=VALUE. Biến môi trường thật được ưu tiên hơn."""
    env = {}
    p = Path(path) if path else ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("VLM_API", "VLM_MODEL", "VLM_API_KEY", "VLM_KEY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def _cfg(env=None):
    env = env if env is not None else load_env()
    key = env.get("VLM_API_KEY") or env.get("VLM_KEY") or ""
    return (env.get("VLM_API") or DEFAULT_API,
            env.get("VLM_MODEL") or DEFAULT_MODEL,
            key)


def cache_key(img_bytes, model, prompt, prompt_version, temperature=0.0):
    h = hashlib.sha256()
    h.update(img_bytes)
    h.update(b"\x00" + model.encode())
    h.update(b"\x00" + prompt_version.encode())
    h.update(b"\x00" + f"t={temperature}".encode())
    h.update(b"\x00" + hashlib.sha256(prompt.encode()).hexdigest().encode())
    return h.hexdigest()


def goi(img_bytes, prompt, *, model=None, prompt_version="v1", mime="image/png",
        max_tokens=4000, timeout=180, so_lan=2, dung_cache=True, env=None,
        temperature=0.0):
    """Gọi gateway với 1 ảnh + 1 prompt. Trả dict, KHÔNG raise.

    Khoá cache tính trên bytes ảnh ĐẦU VÀO của hàm này — caller nào muốn tránh
    lệch Windows/Linux thì truyền bytes ảnh GỐC người dùng nộp, đừng truyền ảnh
    đã qua Tầng 1 (T1 trên Linux lệch pixel 35/72 so Windows).
    """
    api, mdl, key = _cfg(env)
    mdl = model or mdl
    ck = cache_key(img_bytes, mdl, prompt, prompt_version, temperature)
    cpath = CACHE_DIR / mdl / f"{ck}.json"

    if dung_cache and cpath.exists():
        d = json.loads(cpath.read_text(encoding="utf-8"))
        d["cached"] = True
        return d

    if not key:
        return {"ok": False, "error": "THIEU_KEY: chưa có VLM_API_KEY trong .env",
                "content": None, "cached": False, "cache_key": ck}

    payload = {
        "model": mdl,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": f"data:{mime};base64," + base64.b64encode(img_bytes).decode()}},
        ]}],
    }
    body = json.dumps(payload).encode()

    loi = None
    for lan in range(so_lan):
        t0 = time.time()
        req = urllib.request.Request(api, data=body, headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = json.loads(r.read().decode("utf-8", "replace"))
            content = (raw.get("choices") or [{}])[0].get("message", {}).get("content")
            out = {"ok": content is not None, "content": content,
                   "model": mdl, "api": api, "prompt_version": prompt_version,
                   "temperature": temperature,
                   "latency_s": round(time.time() - t0, 2),
                   "usage": raw.get("usage"), "cache_key": ck, "cached": False,
                   "error": None if content is not None else "KHONG_CO_CONTENT"}
            cpath.parent.mkdir(parents=True, exist_ok=True)
            cpath.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
            return out
        except urllib.error.HTTPError as e:
            loi = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}"
        except Exception as e:                                   # noqa: BLE001
            loi = f"{type(e).__name__}: {e}"
        if lan + 1 < so_lan:
            time.sleep(5 * (lan + 1))

    return {"ok": False, "error": loi, "content": None, "model": mdl, "api": api,
            "cache_key": ck, "cached": False}


def thu_nho(img_bytes, max_edge, quality=80):
    """Thu nhỏ về JPEG cạnh dài <= max_edge. NVIDIA NIM chặn ảnh nhúng > ~180KB base64.

    Đo ngày 28/09 trên ảnh A4 H=2200: cạnh 1400 -> 181 KB base64 (sát trần),
    cạnh 1000 -> 115 KB. Mặc định 1400 để giữ chi tiết nét ký nhiều nhất có thể.
    Trả (bytes, mime) — thu nhỏ đổi bytes nên KHÓA CACHE cũng đổi theo, đúng ý.
    """
    from io import BytesIO
    from PIL import Image
    im = Image.open(BytesIO(img_bytes)).convert("RGB")
    s = max_edge / max(im.size)
    if s < 1:
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue(), "image/jpeg"


def goi_file(path, prompt, *, max_edge=None, env=None, **kw):
    p = Path(path)
    data = p.read_bytes()
    mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    e = env if env is not None else load_env()
    me = max_edge if max_edge is not None else int(e.get("VLM_MAX_EDGE") or 0)
    if me:
        data, mime = thu_nho(data, me)
    return goi(data, prompt, mime=mime, env=e, **kw)


if __name__ == "__main__":
    import sys
    api, mdl, key = _cfg()
    print(f"API   : {api}\nMODEL : {mdl}\nKEY   : {'có (' + str(len(key)) + ' ký tự)' if key else 'CHƯA CÓ'}")
    if len(sys.argv) > 1:
        r = goi_file(sys.argv[1], "Ảnh này là gì? Trả lời đúng một câu tiếng Việt.",
                     prompt_version="ping-v1")
        print(f"cached={r.get('cached')} ok={r.get('ok')} latency={r.get('latency_s')}s")
        print("error  :", r.get("error"))
        print("content:", (r.get("content") or "")[:300])
        print("usage  :", r.get("usage"))
