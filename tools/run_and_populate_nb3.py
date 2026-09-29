import json
import sys
import os
import io
import base64
import time
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
os.environ["PYTHONIOENCODING"] = "utf-8"

from IPython.core.interactiveshell import InteractiveShell
from IPython.utils.capture import capture_output

def execute_and_populate_notebook(nb_path):
    with open(nb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    shell = InteractiveShell.instance()
    shell.run_cell("import sys, os, io; sys.path.insert(0, os.getcwd())")
    print(f"Bắt đầu thực thi notebook: {nb_path} ({len(nb['cells'])} cells)")

    plt.show = lambda: None

    code_counter = 1
    t_start = time.time()
    
    for idx, cell in enumerate(nb["cells"]):
        if cell["cell_type"] == "code":
            code = "".join(cell["source"])
            print(f"--- Đang chạy Cell {idx:02d} ---")
            
            plt.close('all')
            
            with capture_output() as cap:
                result = shell.run_cell(code)
                
            if not result.success:
                print(f"LỖI TẠI CELL {idx:02d}:")
                print(result.error_before_exec or result.error_in_exec)
                sys.exit(1)
                
            outputs = []
            
            # 1. Capture stdout
            if cap.stdout:
                outputs.append({
                    "output_type": "stream",
                    "name": "stdout",
                    "text": [line + "\n" for line in cap.stdout.splitlines()]
                })
                
            # 2. Capture figures from matplotlib if any created
            figs = [plt.figure(n) for n in plt.get_fignums()]
            for fig in figs:
                buf = io.BytesIO()
                fig.savefig(buf, format='png', bbox_inches='tight', dpi=120)
                buf.seek(0)
                img_b64 = base64.b64encode(buf.read()).decode('ascii')
                outputs.append({
                    "output_type": "display_data",
                    "data": {
                        "image/png": img_b64,
                        "text/plain": ["<Figure size ...>"]
                    },
                    "metadata": {}
                })
            plt.close('all')
            
            # 3. Capture rich display outputs (like pandas dataframe display)
            for disp in cap.outputs:
                disp_dict = {
                    "output_type": "display_data" if getattr(disp, 'metadata', None) is not None else "execute_result",
                    "data": disp.data,
                    "metadata": getattr(disp, 'metadata', {}) or {}
                }
                outputs.append(disp_dict)
                
            # 4. If expression returned a value
            if result.result is not None:
                res_data = {}
                if hasattr(result.result, '_repr_html_'):
                    res_data["text/html"] = [result.result._repr_html_()]
                res_data["text/plain"] = [repr(result.result)]
                outputs.append({
                    "output_type": "execute_result",
                    "data": res_data,
                    "metadata": {},
                    "execution_count": code_counter
                })
                
            cell["outputs"] = outputs
            cell["execution_count"] = code_counter
            code_counter += 1
            print(f"Cell {idx:02d} hoàn tất với {len(outputs)} output items.")

    elapsed = round(time.time() - t_start, 2)
    with open(nb_path, "w", encoding="utf-8") as f:
        json.dump(nb, f, indent=1, ensure_ascii=False)
        
    print(f"\n[THÀNH CÔNG] Toàn bộ notebook {nb_path} đã thực thi và lưu kết quả ({elapsed}s)!")

if __name__ == "__main__":
    import argparse
    # argparse tối thiểu: `--help` in hướng dẫn rồi THOÁT, không thực thi notebook (sự cố 27/09:
    # `--help` từng chạy cả notebook và ghi lại manifest). Hành vi mặc định (không tham số) giữ nguyên.
    ap = argparse.ArgumentParser(description="Chạy + điền output notebook Tầng 3b (ghi đè notebook nguồn).")
    ap.add_argument("notebook", nargs="?", default="ocr-tang3-ver2.ipynb",
                    help="Notebook cần chạy (mặc định: ocr-tang3-ver2.ipynb).")
    a = ap.parse_args()
    execute_and_populate_notebook(a.notebook)
