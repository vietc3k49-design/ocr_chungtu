"""Lớp (a) — app/services/storage.py: kiểm nội dung bằng Pillow, không tin đuôi file; chống path traversal."""
import io
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import get_settings
from app.services import storage

from conftest import FORM_SAMPLES


def _img_bytes(fmt: str, size=(40, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, format=fmt)
    return buf.getvalue()


def test_accept_real_png_and_jpg():
    for fmt, ext, mime in (("PNG", "png", "image/png"), ("JPEG", "jpg", "image/jpeg")):
        info = storage.validate_image_bytes(_img_bytes(fmt), "a")
        assert (info.ext, info.mime, info.width, info.height) == (ext, mime, 40, 30)
    real = (FORM_SAMPLES / "Load_3.2__0.png").read_bytes()
    assert storage.validate_image_bytes(real, "Load_3.2__0.png").ext == "png"


def test_reject_text_disguised_as_png():
    with pytest.raises(storage.UploadError) as e:
        storage.validate_image_bytes(b"hello, day la van ban\n" * 50, "gia_mao.png")
    assert e.value.code == "INVALID_IMAGE"


def test_reject_gif_and_bmp():
    for fmt in ("GIF", "BMP"):
        with pytest.raises(storage.UploadError) as e:
            storage.validate_image_bytes(_img_bytes(fmt), f"x.png")
        assert e.value.code == "UNSUPPORTED_FORMAT"


def test_reject_truncated_png_and_empty():
    data = _img_bytes("PNG", (300, 300))
    with pytest.raises(storage.UploadError):
        storage.validate_image_bytes(data[: len(data) // 2], "cut.png")
    with pytest.raises(storage.UploadError) as e:
        storage.validate_image_bytes(b"", "empty.png")
    assert e.value.code == "EMPTY_FILE"


def test_limits(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "max_files_per_upload", 2)
    monkeypatch.setattr(s, "max_file_mb", 1)
    with pytest.raises(storage.UploadError) as e:
        storage.check_file_count(3)
    assert e.value.code == "TOO_MANY_FILES"
    with pytest.raises(storage.UploadError) as e:
        storage.check_file_count(0)
    assert e.value.code == "NO_FILES"
    with pytest.raises(storage.UploadError) as e:
        storage.check_file_size(1024 * 1024 + 1, "big.png")
    assert e.value.code == "FILE_TOO_LARGE" and e.value.status_code == 413


def test_save_group_files_naming_order_and_all_or_nothing(data_dir):
    import hashlib
    import uuid
    gid = uuid.uuid4()
    files = [("anh B.jpg", _img_bytes("JPEG")), ("anh A.png", _img_bytes("PNG", (10, 20)))]
    out = storage.save_group_files(gid, files)
    assert [s.scan_index for s in out] == [0, 1]
    for s, (orig, data) in zip(out, files):
        sha = hashlib.sha256(data).hexdigest()
        assert s.sha256 == sha and s.original_filename == orig
        assert s.stored_filename == f"{s.scan_index:03d}_{sha[:8]}.{'jpg' if s.mime == 'image/jpeg' else 'png'}"
        p = Path(s.stored_path)
        assert p.parent == data_dir / "uploads" / str(gid) and p.read_bytes() == data
    assert (out[1].width, out[1].height) == (10, 20)
    # một file hỏng ⇒ không ghi gì
    gid2 = uuid.uuid4()
    with pytest.raises(storage.UploadError):
        storage.save_group_files(gid2, [("ok.png", _img_bytes("PNG")), ("x.png", b"not image")])
    assert not (data_dir / "uploads" / str(gid2)).exists()


def test_path_traversal(data_dir):
    inside = data_dir / "uploads" / "g" / "000_a.png"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_bytes(b"x")
    assert storage.safe_data_path(inside) == inside.resolve()
    assert storage.safe_existing_file(str(inside)) == inside.resolve()
    assert storage.safe_existing_file(data_dir / "uploads" / "khong_co.png") is None
    for bad in (data_dir / ".." / "outside.png", str(data_dir) + "/../../etc/passwd", "../x.png",
                "uploads/../../x.png", Path(__file__).resolve(), data_dir.parent / (data_dir.name + "_evil") / "a.png",
                "", None):
        with pytest.raises(storage.UnsafePathError):
            storage.safe_data_path(bad)
