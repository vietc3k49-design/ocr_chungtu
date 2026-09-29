"""Lưu ảnh upload + kiểm an toàn đường dẫn.

* Định dạng kiểm bằng NỘI DUNG (Pillow `Image.open` + `verify` + giải mã đầy đủ), KHÔNG tin phần mở rộng
  hay Content-Type do client gửi. Chỉ nhận JPEG / PNG (SPEC §0).
* Tên lưu: `{data_dir}/uploads/{group_id}/{scan_index:03d}_{sha8}.{jpg|png}` — đây cũng là `file_name`
  gửi pipeline (pipeline KHÔNG thấy tên file gốc của người dùng).
* Mọi đường dẫn trả cho FileResponse đi qua `safe_data_path` (phải nằm trong data_dir).
"""
from __future__ import annotations

import hashlib
import io
import shutil
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

from PIL import Image

from app.core.config import get_settings

# format Pillow → (đuôi lưu, mime). "MPO" = JPEG nhiều khung (nhiều điện thoại/máy ảnh ghi JPEG dạng này);
# vẫn là JPEG baseline ở khung đầu, OpenCV đọc được như JPEG ⇒ lưu .jpg.
ALLOWED_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "MPO": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
}


class UploadError(Exception):
    """Lỗi kiểm tra upload — API chuyển thành {"detail": {"code", "message"}}."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class UnsafePathError(Exception):
    pass


@dataclass
class ImageInfo:
    format: str
    ext: str
    mime: str
    width: int
    height: int


@dataclass
class StoredFile:
    scan_index: int
    original_filename: str
    stored_filename: str
    stored_path: str
    sha256: str
    mime: str
    width: int
    height: int
    size_bytes: int


def data_dir() -> Path:
    return Path(get_settings().data_dir).resolve()


def max_file_bytes() -> int:
    return int(get_settings().max_file_mb) * 1024 * 1024


def validate_image_bytes(data: bytes, display_name: str = "") -> ImageInfo:
    """Kiểm nội dung là ảnh JPEG/PNG giải mã được. Không nhìn phần mở rộng."""
    who = f"'{display_name}'" if display_name else "Tệp"
    if not data:
        raise UploadError("EMPTY_FILE", f"{who} rỗng.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                fmt = im.format
                if fmt not in ALLOWED_FORMATS:
                    raise UploadError("UNSUPPORTED_FORMAT",
                                      f"{who} không phải ảnh JPG/PNG (định dạng thực: {fmt or 'không xác định'}).")
                im.verify()
            # verify() làm hỏng đối tượng ⇒ mở lại và giải mã đầy đủ (bắt ảnh cụt / hỏng dữ liệu).
            with Image.open(io.BytesIO(data)) as im2:
                im2.load()
                width, height = im2.size
    except UploadError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise UploadError("IMAGE_TOO_LARGE", f"{who} có số điểm ảnh quá lớn.")
    except Exception as e:  # PIL.UnidentifiedImageError, OSError (truncated), SyntaxError (PNG hỏng)...
        raise UploadError("INVALID_IMAGE", f"{who} không phải ảnh JPG/PNG hợp lệ ({type(e).__name__}).")
    if width <= 0 or height <= 0:
        raise UploadError("INVALID_IMAGE", f"{who} có kích thước không hợp lệ.")
    ext, mime = ALLOWED_FORMATS[fmt]
    return ImageInfo(format=fmt, ext=ext, mime=mime, width=int(width), height=int(height))


def check_file_count(n: int) -> None:
    mx = int(get_settings().max_files_per_upload)
    if n <= 0:
        raise UploadError("NO_FILES", "Chưa chọn ảnh nào để tải lên.")
    if n > mx:
        raise UploadError("TOO_MANY_FILES", f"Tối đa {mx} ảnh mỗi lần tải lên (đã chọn {n}).")


def check_file_size(size: int, display_name: str = "") -> None:
    if size > max_file_bytes():
        who = f"'{display_name}'" if display_name else "Tệp"
        raise UploadError("FILE_TOO_LARGE", f"{who} vượt quá {get_settings().max_file_mb} MB.", status_code=413)


def group_upload_dir(group_id) -> Path:
    return data_dir() / "uploads" / str(group_id)


def group_work_dir(group_id) -> Path:
    return data_dir() / "work" / str(group_id)


def save_group_files(group_id, files: Iterable[Tuple[str, bytes]]) -> List[StoredFile]:
    """files: [(tên file gốc, bytes)] theo đúng thứ tự ⇒ scan_index 0..n-1.

    Kiểm TẤT CẢ trước khi ghi (all-or-nothing). Lỗi ⇒ UploadError, không ghi gì.
    """
    files = list(files)
    check_file_count(len(files))
    checked = []
    for i, (orig, data) in enumerate(files):
        name = orig or f"trang {i + 1}"
        check_file_size(len(data), name)
        info = validate_image_bytes(data, name)
        checked.append((i, orig or "", data, info))
    out_dir = group_upload_dir(group_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    stored: List[StoredFile] = []
    try:
        for i, orig, data, info in checked:
            sha = hashlib.sha256(data).hexdigest()
            fn = f"{i:03d}_{sha[:8]}.{info.ext}"
            path = out_dir / fn
            path.write_bytes(data)
            stored.append(StoredFile(scan_index=i, original_filename=orig[:500], stored_filename=fn,
                                     stored_path=str(path), sha256=sha, mime=info.mime,
                                     width=info.width, height=info.height, size_bytes=len(data)))
    except Exception:
        remove_group_files(group_id)
        raise
    return stored


def remove_group_files(group_id) -> None:
    d = group_upload_dir(group_id)
    if d.exists():
        shutil.rmtree(safe_data_path(d), ignore_errors=True)


def safe_data_path(path: Union[str, Path, None]) -> Path:
    """Trả đường dẫn tuyệt đối đã resolve nếu nằm TRONG data_dir; không thì UnsafePathError."""
    if path is None or str(path) == "":
        raise UnsafePathError("Đường dẫn rỗng")
    root = data_dir()
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    if p != root and not p.is_relative_to(root):
        raise UnsafePathError(f"Đường dẫn nằm ngoài data_dir: {path}")
    return p


def safe_existing_file(path: Union[str, Path, None]) -> Optional[Path]:
    """Như safe_data_path nhưng trả None nếu file không tồn tại (không lộ lý do cho client)."""
    p = safe_data_path(path)
    return p if p.is_file() else None
