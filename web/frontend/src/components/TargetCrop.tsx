import { useEffect, useRef } from 'react';
import { validBox } from '../lib/targets';

const MARGIN = 0.1; // lề 10% quanh ô
const MAX_W = 380;
const MAX_H = 300;

/** Vẽ phóng to vùng ô ký (kèm lề 10%) từ ảnh đã tải, có viền ô. */
export function TargetCrop({
  image,
  boxNorm,
  color,
  dashed,
  version,
}: {
  image: HTMLImageElement | null;
  boxNorm: unknown;
  color: string;
  dashed: boolean;
  version: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const b = validBox(boxNorm);
    if (!canvas || !image || !b || !image.naturalWidth) return;
    const W = image.naturalWidth;
    const H = image.naturalHeight;
    const [y0, x0, y1, x1] = b;
    const bw = (x1 - x0) * W;
    const bh = (y1 - y0) * H;
    const sx = Math.max(0, x0 * W - bw * MARGIN);
    const sy = Math.max(0, y0 * H - bh * MARGIN);
    const ex = Math.min(W, x1 * W + bw * MARGIN);
    const ey = Math.min(H, y1 * H + bh * MARGIN);
    const sw = ex - sx;
    const sh = ey - sy;
    if (sw <= 0 || sh <= 0) return;
    const k = Math.min(MAX_W / sw, MAX_H / sh);
    const cssW = Math.round(sw * k);
    const cssH = Math.round(sh * k);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    canvas.style.width = `${cssW}px`;
    canvas.style.height = `${cssH}px`;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingQuality = 'high';
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, cssW, cssH);
    ctx.drawImage(image, sx, sy, sw, sh, 0, 0, cssW, cssH);
    // Viền ô ký (màu lấy từ biến CSS đã tính).
    const resolved = color.startsWith('var(')
      ? getComputedStyle(document.documentElement).getPropertyValue(color.slice(4, -1)).trim() || '#555'
      : color;
    ctx.strokeStyle = resolved;
    ctx.lineWidth = 2;
    ctx.setLineDash(dashed ? [7, 4] : []);
    ctx.strokeRect((x0 * W - sx) * k, (y0 * H - sy) * k, bw * k, bh * k);
  }, [image, boxNorm, color, dashed, version]);

  if (!validBox(boxNorm)) return <div className="crop-empty">Tọa độ ô không hợp lệ</div>;
  return <canvas ref={ref} className="crop-canvas" aria-label="Ảnh phóng to vùng ô ký" />;
}
