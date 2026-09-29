"""
Chạy + điền output cho notebook Tầng 1 (`ocr-tang1-ver2.ipynb`, sinh bởi tools/generate_nb1.py).

Dựa trên mẫu tools/run_and_populate_nb4_ver2.py / run_and_populate_nb_e2e.py (không sửa các file đó),
thêm: tham số OUT_DIR / REFERENCE_DIR (truyền cho notebook qua biến môi trường), bắt `execute_result`
(giữ bảng HTML của DataFrame), exit code != 0 khi có cell lỗi, và guard `__main__` bắt buộc vì
notebook gọi runner Tầng 1 dùng ProcessPoolExecutor (Windows spawn nạp lại file này dưới __mp_main__).

Chạy chính thức (ghi output/stage1_out — artifact Tầng 2 đọc):
  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tools/run_and_populate_nb1.py \
        --reference-dir <bản sao output/stage1_out của lần chạy trước>
Chạy kiểm chứng (không đụng artifact chính thức):
  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tools/run_and_populate_nb1.py \
        --out-dir scratch/_nb/t1/stage1_out --reference-dir output/stage1_out
"""
import argparse
import base64
import io
import json
import multiprocessing
import os
import sys
import time


def execute_and_populate_notebook(nb_path, out_dir, reference_dir, save_to=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from IPython.core.interactiveshell import InteractiveShell
    from IPython.utils.capture import capture_output

    os.environ["KIDO_T1_OUT_DIR"] = out_dir
    os.environ["KIDO_T1_REFERENCE_DIR"] = reference_dir or ""
    os.environ["KIDO_PROJECT_DIR"] = os.getcwd()

    with open(nb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    shell = InteractiveShell.instance()
    shell.displayhook.write_format_data = lambda *a, **k: None  # không in trùng bản text bị cắt
    shell.displayhook.write_output_prompt = lambda *a, **k: None  # không in "Out[0]:" vào stdout
    shell.run_cell("import sys, os; sys.path.insert(0, os.getcwd())")
    print(f"Bắt đầu thực thi {nb_path} ({len(nb['cells'])} cells) | OUT_DIR={out_dir} | "
          f"REFERENCE_DIR={reference_dir or '(rỗng)'}", flush=True)
    plt.show = lambda *a, **k: None

    code_counter = 1
    t_start = time.time()
    for idx, cell in enumerate(nb["cells"]):
        if cell["cell_type"] != "code":
            continue
        code = "".join(cell["source"])
        tc = time.time()
        plt.close("all")
        with capture_output() as cap:
            result = shell.run_cell(code)
        dt = time.time() - tc
        print(f"--- Cell {idx:02d}: {dt:.1f}s {'OK' if result.success else 'LỖI'}", flush=True)

        outputs = []
        if cap.stdout:
            outputs.append({"output_type": "stream", "name": "stdout",
                            "text": [l + "\n" for l in cap.stdout.splitlines()]})
        if cap.stderr:
            outputs.append({"output_type": "stream", "name": "stderr",
                            "text": [l + "\n" for l in cap.stderr.splitlines()]})
        for n in plt.get_fignums():
            buf = io.BytesIO()
            plt.figure(n).savefig(buf, format="png", bbox_inches="tight", dpi=90)
            outputs.append({"output_type": "display_data", "metadata": {},
                            "data": {"image/png": base64.b64encode(buf.getvalue()).decode(),
                                     "text/plain": ["<Figure>"]}})
        plt.close("all")
        for out in cap.outputs:
            if hasattr(out, "data"):
                outputs.append({"output_type": "display_data", "data": out.data,
                                "metadata": getattr(out, "metadata", {}) or {}})
        res_obj = getattr(result, "result", None)
        if res_obj is not None:
            fmt_data, fmt_meta = shell.display_formatter.format(res_obj)
            if fmt_data:
                outputs.append({"output_type": "execute_result", "data": fmt_data,
                                "metadata": fmt_meta or {}, "execution_count": code_counter})
        if not result.success:
            err = result.error_in_exec or result.error_before_exec
            outputs.append({"output_type": "error", "ename": type(err).__name__, "evalue": str(err),
                            "traceback": [f"{type(err).__name__}: {err}"]})
        cell["outputs"] = outputs
        cell["execution_count"] = code_counter
        code_counter += 1
        if cap.stdout:
            sys.stdout.write(cap.stdout[-1500:] + ("\n" if not cap.stdout.endswith("\n") else ""))
        if not result.success:
            print(f"LỖI TẠI CELL {idx:02d}: {type(err).__name__}: {err}", flush=True)
            _save(nb, save_to or nb_path)
            return False

    print(f"Hoàn thành {len(nb['cells'])} cells ({code_counter - 1} code) trong {time.time() - t_start:.1f}s")
    _save(nb, save_to or nb_path)
    return True


def _save(nb, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(nb, f, indent=1, ensure_ascii=False)
    print(f"Đã lưu notebook: {path} ({os.path.getsize(path) / 1024:.1f} KB)")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nb", default="ocr-tang1-ver2.ipynb")
    ap.add_argument("--out-dir", default="output/stage1_out")
    ap.add_argument("--reference-dir", default="")
    ap.add_argument("--save-to", default=None, help="Ghi notebook đã điền ra file khác (mặc định: ghi đè --nb)")
    a = ap.parse_args()
    ok = execute_and_populate_notebook(a.nb, a.out_dir, a.reference_dir, a.save_to)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
