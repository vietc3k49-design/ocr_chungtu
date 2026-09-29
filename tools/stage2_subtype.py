# -*- coding: utf-8 -*-
"""Tầng 2b — phân loại LOẠI CON của chứng từ (hiện làm cho HOA_DON).

Nguyên tắc (chốt 29/09/2026, sau khi đo cả hai cách trên 21 tờ hóa đơn):

  CHỮ IN là căn cứ CHÍNH — đo được 21/21, điểm khớp mờ 100/100 cả 21 tờ.
  KÝ HIỆU chỉ là ĐỐI CHỨNG — đo được 16/21 dù đã vá 3 tầng đọc.

Vì sao không lấy ký hiệu làm chính, dù nó mã hoá sẵn loại hoá đơn:
  1. Ký hiệu là chữ NHỎ ở góc trang, OCR đọc sai thường xuyên: '1'->'I',
     '2'->'?'/'Đ'/'J'/'Z'. Ký tự BỊ SAI NHIỀU NHẤT lại đúng là ký tự quyết
     định loại hoá đơn -> sai một ký tự là biến hoá đơn bán hàng thành GTGT,
     tức PASS giả.
  2. Ký hiệu ĐỔI THEO NĂM (1C25TAA -> 1C27TAA) và 2 ký tự cuối do người bán
     tự đặt. Neo vào danh sách mã đã biết là hardcode, ảnh mới mã mới là trượt.
     (config/stage2_keywords.json hiện đang hardcode '1C25TAA','1C24TAA' —
      đây là nợ kỹ thuật cần gỡ, ghi nhận 29/09.)
  3. Chữ "HÓA ĐƠN GIÁ TRỊ GIA TĂNG" do Nghị định 123/2020 bắt buộc in, không
     đổi theo năm, không đổi theo nhà cung cấp phần mềm hoá đơn.

Kỹ thuật học từ repo của anh Bắc (github.com/vnb-vnb/kido-orc):
  - So khớp MỜ thay vì chính xác (OCR đọc "GIÁ TĂNG"/"GIA TẮNG").
  - Luật có ĐIỂM ƯU TIÊN, cụm đặc hiệu xét trước cụm chung.
  - Ưu tiên vùng ĐẦU TRANG; khớp ngoài vùng đầu thì hạ mạnh độ tin cậy.
  - Mỏ neo theo TOẠ ĐỘ khi tìm giá trị nằm bên phải một nhãn.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz

CONFIG_PATH = Path("config/stage2_doc_subtypes.json")


def _load(path: Path = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


_CFG = _load()


def bo_dau(s: str) -> str:
    """Bỏ dấu tiếng Việt. 'đ'/'Đ' phải ép TRƯỚC NFD — chúng KHÔNG phân rã."""
    s = str(s or "").replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.upper()).strip()


def _khop(cum: str, text: str, nguong: int) -> int:
    """Điểm khớp mờ 0-100. Trả điểm chứ không trả bool để còn in ra bằng chứng."""
    if cum in text:
        return 100
    return int(fuzz.partial_ratio(cum, text))


# ----------------------------------------------------------------- ký hiệu
_SO = {"I": "1", "L": "1", "|": "1", "!": "1", "(": "1", ")": "1",
       "O": "0", "S": "5", "B": "8", "Z": "2", "G": "6", "?": "2",
       "D": "2", "J": "3", "A": "4", "T": "7"}
_CHU = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z"}
_VT_SO, _VT_CHU = (0, 2, 3), (1, 4)

_THO = re.compile(
    r"(?<![0-9A-Z])([0-9A-ZD|!(){}\[\]?][CKG][0-9A-ZD?|!]{2}[A-Z][0-9A-Z]{2})(?![0-9A-Z])"
)


def _ep_kieu_ky_tu(s: str) -> str:
    """Ép từng vị trí về đúng kiểu ký tự mà Thông tư 78 đòi hỏi.

    Ép theo VỊ TRÍ, không theo hàng xóm. (repo anh Bắc ép theo hàng xóm —
    `chuan_hoa()` chỉ sửa khi ký tự bị kẹp giữa hai chữ số — nên ký tự ĐẦU
    chuỗi không bao giờ được sửa, mà đó đúng là ký tự phân loại.)

    Ép sai không sinh kết quả bậy: chuỗi ép xong còn phải qua `khuon`.
    """
    out = list(s.upper())
    for i, c in enumerate(out):
        if i in _VT_SO and not c.isdigit():
            out[i] = _SO.get(c, c)
        elif i in _VT_CHU and c.isdigit():
            out[i] = _CHU.get(c, c)
    return "".join(out)


def doc_ky_hieu(text: str, khuon: str) -> Optional[Dict[str, str]]:
    """Dò ký hiệu hóa đơn trong văn bản phẳng. None nếu không có chuỗi hợp khuôn."""
    pat = re.compile(khuon)
    for m in _THO.finditer(bo_dau(text)):
        chuan = _ep_kieu_ky_tu(m.group(1))
        if pat.match(chuan):
            return {"tho": m.group(1), "chuan": chuan}
    return None


# ----------------------------------------------------------------- phân loại
def phan_loai_con(doc_type: str, full_text: str) -> Optional[Dict[str, Any]]:
    """Phân loại loại con. Trả None nếu doc_type chưa có luật loại con.

    Kết quả luôn kèm `bang_chung` — chuỗi thật máy đã đọc được, để người soát
    kiểm được vì sao ra kết luận đó (bài học 29/09: tổng đúng mà thành phần sai
    là dạng PASS giả khó thấy nhất).
    """
    cfg = _CFG["subtypes"].get(doc_type)
    if cfg is None:
        return None

    nguong = _CFG["nguong_khop"]
    t = bo_dau(full_text)
    n_dau = max(400, int(len(t) * _CFG["nguong_vung_dau"]))
    dau = t[:n_dau]

    tot = None
    for luat in cfg["luat"]:
        for cum in luat["cum"]:
            diem_khop = _khop(cum, t, nguong)
            if diem_khop < nguong:
                continue
            o_dau = _khop(cum, dau, nguong) >= nguong
            # khớp ngoài vùng đầu trang -> hạ mạnh, không chỉ bớt thưởng
            diem = luat["diem"] + 6 if o_dau else luat["diem"] * 0.55
            ung_vien = (diem, luat, cum, diem_khop, o_dau)
            if tot is None or ung_vien[0] > tot[0]:
                tot = ung_vien
            break

    if tot is None:
        return {
            "subtype": cfg["mac_dinh"], "ten": "Chưa xác định loại",
            "do_tin_cay": 0.0, "bang_chung": None, "o_dau_trang": False,
            "la_ban_chuyen_doi": None, "ky_hieu": None, "mau_thuan": None,
        }

    diem, luat, cum, diem_khop, o_dau = tot
    tin = min(1.0, diem / 106.0) if o_dau else min(0.6, diem / 106.0)

    # bản chuyển đổi ra giấy (mới có chữ ký tay để kiểm)
    cd = cfg.get("co_chuyen_doi", {})
    bc_cd = next((c for c in cd.get("cum", []) if _khop(c, t, nguong) >= nguong), None)

    kq: Dict[str, Any] = {
        "subtype": luat["ma"],
        "ten": luat["ten"],
        "do_tin_cay": round(tin, 3),
        "bang_chung": {"cum_khop": cum, "diem_khop": diem_khop},
        "o_dau_trang": o_dau,
        "la_ban_chuyen_doi": bc_cd is not None,
        "bang_chung_chuyen_doi": bc_cd,
        "ky_hieu": None,
        "mau_thuan": None,
    }

    # ----- đối chứng bằng ký hiệu: CHỈ để bắt mâu thuẫn, không ra kết luận
    dc = cfg.get("doi_chung_ky_hieu", {})
    if dc.get("bat"):
        kh = doc_ky_hieu(full_text, dc["khuon"])
        if kh:
            suy = dc["ky_tu_1_sang_subtype"].get(kh["chuan"][0])
            kq["ky_hieu"] = {
                "tho": kh["tho"], "chuan": kh["chuan"],
                "suy_ra_subtype": suy,
                "co_ma_CQT": kh["chuan"][1] == "C",
                "nam": "20" + kh["chuan"][2:4],
                "tu_may_tinh_tien": kh["chuan"][4] == "M",
            }
            if suy and suy != luat["ma"]:
                kq["mau_thuan"] = (
                    f"Chữ in nói {luat['ma']} nhưng ký hiệu {kh['chuan']} suy ra {suy}"
                )
    return kq
