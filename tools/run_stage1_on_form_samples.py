"""
Chạy chuẩn hóa Tầng 1 (Stage 1 Normalizer) trên 72 ảnh biểu mẫu trong output/form_samples/
Sử dụng ĐA TIẾN TRÌNH (concurrent.futures.ProcessPoolExecutor).

VÌ SAO PROCESS CHỨ KHÔNG PHẢI THREAD:
`stage1_normalizer._GRABCUT_RNG_LOCK` phải bọc cặp `cv2.setRNGSeed` + `cv2.grabCut`
vì `setRNGSeed` là trạng thái RNG TOÀN CỤC của tiến trình. Với ThreadPoolExecutor,
lock đó tuần tự hóa `grabCut` — phần nặng nhất pipeline — nên 6 luồng gần như
chạy nối đuôi. Mỗi TIẾN TRÌNH có không gian RNG toàn cục RIÊNG, nên lock vẫn
giữ nguyên (cần thiết, vô hại) mà `grabCut` chạy song song thật.
"""

import sys, io, os, glob, json, time
import multiprocessing
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0, '.')

# Windows dùng 'spawn': tiến trình con NẠP LẠI module này (dưới tên __mp_main__),
# nên mọi thứ ở cấp module phải an toàn khi chạy lại. Trong tiến trình con,
# sys.stdout có thể là None hoặc không có .buffer -> phải bọc phòng thủ,
# nếu không worker chết ngay lúc import và pool vỡ (BrokenProcessPool).
def _force_utf8_stdout():
    try:
        buf = getattr(sys.stdout, "buffer", None)
        if buf is not None and getattr(sys.stdout, "encoding", "").lower() not in ("utf-8", "utf8"):
            sys.stdout = io.TextIOWrapper(buf, encoding="utf-8")
    except Exception:
        pass

_force_utf8_stdout()

import tools.stage1_normalizer as s1

def process_single(args):
    img_path, idx, cfg, batch_id, out_pages_dir, out_images_dir = args
    fn = os.path.basename(img_path)
    try:
        rec, norm_img = s1.process_one(img_path, cfg, batch_id=batch_id, page_index=idx, save=False)
        
        # GIU NGUYEN dang dict cua rec["output"] ma process_one da tra ve
        # ({"image": ..., "width": w, "height": h}) — manifest doc theo
        # (p.get("output") or {}).get("image") nen khong duoc ep ve string/None.
        out_rec = rec.get("output") or {}
        if norm_img is not None:
            out_img_path = str(out_images_dir / fn)
            s1.imwrite_unicode(out_img_path, norm_img, cfg.jpeg_quality)
            out_rec["image"] = out_img_path
        else:
            out_rec["image"] = None
        rec["output"] = out_rec
        # KHONG ghi de rec["action"]: process_one da gan action theo dung rec["status"].
        # Ghi de theo (norm_img is not None) se lam cac trang CHUP_LAI (vd reject DPI —
        # xay ra SAU khi anh da dung xong) van bi gan CHUYEN_TANG_2 va ro sang Tang 2.


        out_json_path = out_pages_dir / f"{Path(fn).stem}.json"
        with open(out_json_path, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
            
        return rec
    except Exception as e:
        print(f"Error processing {fn}: {e}")
        return {
            "source_file": img_path,
            "file_name": fn,
            "status": "CHUP_LAI",
            "action": "YEU_CAU_CHUP_LAI",
            "error": str(e)
        }

def _parse_args(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Chạy Tầng 1 trên output/form_samples/")
    # Mặc định giữ NGUYÊN hành vi cũ (ghi vào output/stage1_out). Dùng --out-dir để
    # chạy kiểm chứng/baseline vào thư mục khác mà không ghi đè artifact đang được
    # Tầng 2 dùng làm đầu vào.
    ap.add_argument("--out-dir", default="output/stage1_out",
                    help="Thư mục gốc đầu ra (mặc định: output/stage1_out)")
    return ap.parse_args(argv)


def main():
    args = _parse_args()
    print("=== CHẠY CHUẨN HÓA TẦNG 1 (ĐA LUỒNG) TRÊN 72 ẢNH BIỂU MẪU KIDO ===")
    
    cfg = s1.Stage1Config(
        input_dir="output/form_samples",
        output_dir=args.out_dir,
        batch_mode="folder",
        min_long_edge=500,
        warn_long_edge=800,
        dpi_reject=40.0,
        dpi_warn=70.0,
        blur_reject=25.0,
        blur_warn=70.0,
        save_debug=True
    )
    
    img_files = sorted(glob.glob("output/form_samples/*.png"))
    print(f"Tìm thấy {len(img_files)} ảnh mẫu trong output/form_samples/")
    
    batch_id = "form_samples"
    out_pages_dir = Path(cfg.output_dir) / "pages" / batch_id
    out_images_dir = Path(cfg.output_dir) / "images" / batch_id
    out_pages_dir.mkdir(parents=True, exist_ok=True)
    out_images_dir.mkdir(parents=True, exist_ok=True)
    
    t0 = time.time()
    results = []
    
    tasks = [
        (p, idx, cfg, batch_id, out_pages_dir, out_images_dir)
        for idx, p in enumerate(img_files)
    ]
    
    max_workers = 6
    print(f"Bắt đầu xử lý song song với {max_workers} tiến trình worker...")
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_single, t): t[0] for t in tasks}
        done_count = 0
        for fut in as_completed(futures):
            done_count += 1
            rec = fut.result()
            results.append(rec)
            status_icon = "✅" if rec.get("status") == "DAT" else ("⚠️" if rec.get("status") == "CANH_BAO" else "❌")
            fn = rec.get("file_name", "")
            needs_180 = rec.get("rotation", {}).get("needs_verification_180", False)
            print(f"[{done_count:02d}/72] {status_icon} {fn:<25} | status={rec.get('status'):<8} | action={rec.get('action'):<15} | 180_verify={needs_180}", flush=True)
            
    elapsed = round(time.time() - t0, 1)
    
    from collections import Counter
    status_counts = Counter(r.get("status") for r in results)
    action_counts = Counter(r.get("action") for r in results)
    verify_180_cnt = sum(1 for r in results if r.get("rotation", {}).get("needs_verification_180"))
    
    print("\n" + "="*50)
    print(f"HOÀN TẤT TẦNG 1: 72 ảnh trong {elapsed}s (tốc độ: {elapsed/72:.2f}s/trang song song)")
    print(f"Trạng thái: {dict(status_counts)}")
    print(f"Hành động : {dict(action_counts)}")
    print(f"Cần xác minh 180 độ ở Tầng 2: {verify_180_cnt}/72 trang")
    print(f"Metadata trang đã lưu tại: {out_pages_dir}")
    print(f"Ảnh chuẩn hóa đã lưu tại : {out_images_dir}")
    print("="*50)

if __name__ == "__main__":
    # Bắt buộc trên Windows (spawn): thiếu guard/freeze_support sẽ đệ quy sinh tiến trình.
    multiprocessing.freeze_support()
    main()
