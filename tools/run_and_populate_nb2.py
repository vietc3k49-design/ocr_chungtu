"""Thực thi notebook Tầng 2 và ghi output vào notebook.

  .venv/Scripts/python.exe tools/run_and_populate_nb2.py                     # chính thức: ghi output/stage2_out
  .venv/Scripts/python.exe tools/run_and_populate_nb2.py --out-dir scratch/_nb/t2/dev --save-to scratch/_nb/t2/dev.ipynb

--out-dir đặt biến môi trường STAGE2_NB_OUT_DIR mà Cell 1 của notebook đọc (mặc định output/stage2_out).
--save-to: nơi lưu notebook đã có output (mặc định ghi đè chính file nguồn).
Cell lỗi -> in traceback, KHÔNG lưu notebook, exit 1.
"""
import argparse
import base64
import io
import json
import os
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent


def execute_and_populate_notebook(nb_path, save_to=None, out_dir=None):
    if out_dir is not None:
        os.environ["STAGE2_NB_OUT_DIR"] = str(out_dir)
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.chdir(ROOT)

    from IPython.core.interactiveshell import InteractiveShell
    from IPython.utils.capture import capture_output

    nb_path = Path(nb_path)
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    shell = InteractiveShell.instance()
    shell.displayhook.write_format_data = lambda *a, **k: None  # tránh in trùng bản text bị cắt
    plt.show = lambda *a, **k: None  # giữ figure để serialize

    print(f"Bắt đầu thực thi notebook: {nb_path} ({len(nb['cells'])} cells) · "
          f"STAGE2_NB_OUT_DIR={os.environ.get('STAGE2_NB_OUT_DIR', '(mặc định output/stage2_out)')}")
    counter = 1
    t_start = time.time()
    for idx, cell in enumerate(nb["cells"]):
        if cell["cell_type"] != "code":
            continue
        src = "".join(cell["source"])
        t0 = time.time()
        plt.close("all")
        with capture_output() as cap:
            result = shell.run_cell(src)
        if not result.success:
            print(cap.stdout[-4000:])
            print(f"LỖI TẠI CELL {idx:02d}: {result.error_before_exec or result.error_in_exec!r}")
            sys.exit(1)

        outputs = []
        if cap.stdout:
            outputs.append({"output_type": "stream", "name": "stdout", "text": cap.stdout.splitlines(keepends=True)})
        if cap.stderr:
            outputs.append({"output_type": "stream", "name": "stderr", "text": cap.stderr.splitlines(keepends=True)})
        for disp in cap.outputs:
            data = dict(getattr(disp, "data", {}) or {})
            if not data:
                continue
            outputs.append({"output_type": "display_data", "data": data, "metadata": getattr(disp, "metadata", {}) or {}})
        for n in plt.get_fignums():
            buf = io.BytesIO()
            plt.figure(n).savefig(buf, format="png", bbox_inches="tight", dpi=90)
            outputs.append({"output_type": "display_data",
                            "data": {"image/png": base64.b64encode(buf.getvalue()).decode("ascii"),
                                     "text/plain": ["<Figure>"]},
                            "metadata": {}})
        plt.close("all")
        if result.result is not None:
            fmt_data, fmt_meta = shell.display_formatter.format(result.result)
            if fmt_data:
                outputs.append({"output_type": "execute_result", "data": fmt_data,
                                "metadata": fmt_meta or {}, "execution_count": counter})
        cell["outputs"] = outputs
        cell["execution_count"] = counter
        counter += 1
        print(f"  Cell {idx:02d} OK ({time.time()-t0:.1f}s, {len(outputs)} output)")

    dest = Path(save_to) if save_to else nb_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"[THÀNH CÔNG] {counter-1} code cell, {time.time()-t_start:.1f}s -> {dest} ({dest.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("notebook", nargs="?", default=str(ROOT / "ocr-tang2-classify.ipynb"))
    ap.add_argument("--out-dir", default=None, help="Thư mục artifact Tầng 2 (mặc định output/stage2_out).")
    ap.add_argument("--save-to", default=None, help="Lưu notebook đã chạy ra file khác (mặc định ghi đè nguồn).")
    a = ap.parse_args()
    execute_and_populate_notebook(a.notebook, save_to=a.save_to, out_dir=a.out_dir)
