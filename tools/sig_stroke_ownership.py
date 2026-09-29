# -*- coding: utf-8 -*-
"""Đo chữ ký theo QUYỀN SỞ HỮU NÉT — sửa gốc lỗi "chữ ký tràn qua ranh giới ô".

Vì sao không cắt ROI từng ô rồi đo (cách của stage4_verifier_v2):
  phép cắt chặt đứt nét chữ ký ở biên. Đo trên LENH_DIEU_XE (28/09) thấy 5/11 ô sai:
    * ô 9, 11: chữ ký nằm sát mép trái ô -> rơi trọn vào dải biên 20% -> bị luật
      chống-tràn ném đi -> báo TRỐNG dù có ký (mực trong ô 0.0 mm², ở biên 40.7 / 5.8)
    * ô 8:     chữ ký của ô 7 tràn sang  -> báo ĐÃ KÝ dù ô trống (13.1 mm² "trong ô")
    * ô 2, 3:  khung hẹp hơn chữ ký       -> gần hết nét nằm ngoài -> 0.0 mm²

Cách làm ở đây (theo ý tưởng đã kiểm chứng trong repo kido-orc):
  1. Tách mực xanh trên CẢ TRANG, không cắt ô trước.
  2. Giãn nở `cluster_link_mm` để nối các nét rời của cùng một chữ ký -> 1 cụm.
  3. Mỗi cụm thuộc về ô nào chứa >= `nguong_so_huu` (mặc định 50%) diện tích cụm đó.
     Cụm không ô nào đạt -> vô chủ, không cộng cho ai (mực tràn nằm giữa hai ô).
  4. Mỗi ô cộng diện tích các cụm NÓ SỞ HỮU rồi mới so ngưỡng mm².

Bỏ hẳn luật dải-biên-20%: quyền sở hữu đã xử lý đúng việc mực tràn, và chính luật
đó là nguồn của 2 trong 5 lỗi trên.
"""
import cv2
import numpy as np

CFG = {
    "a4_long_edge_mm": 297.0,
    "blue_hsv_lo": (90, 40, 40),      # giữ nguyên định nghĩa mực xanh của v1/ver2
    "blue_hsv_hi": (145, 255, 255),
    "min_blue_cc_mm2": 0.25,          # đốm nhỏ hơn: nhiễu sắc độ của scanner
    "cluster_link_mm": 1.5,           # khoảng hở giữa các nét của CÙNG một chữ ký
    "min_sig_ink_mm2": 2.0,           # chữ ký tối thiểu (nét 10 mm x 0.2 mm)
    "nguong_so_huu": 0.5,             # cụm thuộc ô nào chứa >= 50% diện tích cụm
    # Cụm bị ô NHÌ chiếm >= ngưỡng này => nhiều khả năng là HAI chữ ký của hai ô
    # dính vào nhau, không phải một chữ ký tràn sang. Khi đó tách theo pixel.
    # Đo trên LENH_DIEU_XE (28/09): chữ ký ô7 tràn sang ô8 chỉ chiếm ~11% cụm;
    # còn hai chữ ký ô2+ô3 dính nhau chia nhau 46% / 54%. Ngưỡng 0.25 tách sạch
    # hai trường hợp mà không phải hạ cluster_link (hạ sẽ xé vụn chữ ký rời nét).
    "nguong_tach_cum": 0.25,
}


def mask_muc_xanh(img_bgr, cfg=CFG):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, np.array(cfg["blue_hsv_lo"]), np.array(cfg["blue_hsv_hi"]))
    return (m > 0).astype(np.uint8)


def _bo_dom_nho(mask01, min_px):
    if min_px <= 1:
        return mask01
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask01, 8)
    giu = np.zeros(n, bool)
    giu[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_px
    return (giu[lab]).astype(np.uint8)


def gom_cum(mask01, link_px):
    """Nối các nét cách nhau <= link_px thành cụm. Trả nhãn cụm trên pixel GỐC."""
    k = max(1, int(round(link_px)))
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))
    no = cv2.dilate(mask01, ker)
    n, lab = cv2.connectedComponents(no, 8)
    return n, lab * mask01          # chỉ giữ nhãn ở pixel mực thật, không lấy phần giãn nở


def do_theo_quyen_so_huu(img_bgr, targets, cfg=CFG):
    """targets: list dict có 'box_norm' [x0,y0,x1,y1] 0..1. Trả list kết quả cùng thứ tự."""
    H, W = img_bgr.shape[:2]
    ppm = max(H, W) / cfg["a4_long_edge_mm"]
    mm2 = ppm * ppm

    blue = mask_muc_xanh(img_bgr, cfg)
    blue = _bo_dom_nho(blue, max(1, int(round(cfg["min_blue_cc_mm2"] * mm2))))
    n_cum, lab = gom_cum(blue, cfg["cluster_link_mm"] * ppm)

    boxes_px = []
    for t in targets:
        x0, y0, x1, y1 = t["box_norm"]
        boxes_px.append((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)))

    dt_so_huu = [0.0] * len(targets)
    n_cum_so_huu = [0] * len(targets)
    cum_vo_chu = []

    for c in range(1, n_cum):
        ys, xs = np.nonzero(lab == c)
        if xs.size == 0:
            continue
        tong = float(xs.size)
        phan = []
        for i, (bx0, by0, bx1, by1) in enumerate(boxes_px):
            trong = np.count_nonzero((xs >= bx0) & (xs < bx1) & (ys >= by0) & (ys < by1))
            phan.append((trong / tong, trong, i))
        phan.sort(reverse=True)
        tot_tl, tot_px, tot_i = phan[0]
        nhi_tl = phan[1][0] if len(phan) > 1 else 0.0

        if nhi_tl >= cfg["nguong_tach_cum"]:
            # Hai (hoặc nhiều) chữ ký của các ô khác nhau dính thành một cụm.
            # Tách theo pixel: mỗi ô nhận đúng phần mực nằm trong nó.
            for tl, px, i in phan:
                if px > 0:
                    dt_so_huu[i] += float(px)
                    n_cum_so_huu[i] += 1
        elif tot_tl >= cfg["nguong_so_huu"]:
            dt_so_huu[tot_i] += tong
            n_cum_so_huu[tot_i] += 1
        else:
            cum_vo_chu.append({"dien_tich_mm2": round(tong / mm2, 2),
                               "ti_le_cao_nhat": round(tot_tl, 2),
                               "o_gan_nhat": tot_i,
                               "tam": (int(xs.mean()), int(ys.mean()))})

    kq = []
    for i, t in enumerate(targets):
        s = dt_so_huu[i] / mm2
        det = s >= cfg["min_sig_ink_mm2"]
        kq.append({
            "role": t.get("role"),
            "required": t.get("required", True),
            "detected": det,
            "muc_so_huu_mm2": round(s, 2),
            "so_cum": n_cum_so_huu[i],
            "confidence": round(min(1.0, 0.60 + 0.40 * s / (4 * cfg["min_sig_ink_mm2"])), 2) if det else 0.0,
            "evidence": "BLUE_SIGNATURE_OWNED" if det else "NO_OWNED_INK",
            "box_norm": t["box_norm"],
        })
    return kq, {"n_cum": n_cum - 1, "cum_vo_chu": cum_vo_chu, "px_per_mm": round(ppm, 3)}
