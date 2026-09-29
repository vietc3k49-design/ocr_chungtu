import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as RPointerEvent, type RefObject } from 'react';
import type { TargetOut } from '../api/types';
import { STATE_COLOR, targetState, validBox } from '../lib/targets';

const MIN_SCALE = 0.05;
const MAX_SCALE = 4;
const STEP = 1.25;

interface Props {
  src: string;
  fallbackSrc?: string;
  targets: TargetOut[];
  /** false ⇒ chỉ hiện ảnh, không vẽ khung (không có ô ký hoặc đang dùng ảnh gốc). */
  drawBoxes: boolean;
  selected: number | null;
  onSelect: (index: number) => void;
  imgRef: RefObject<HTMLImageElement>;
  onImageReady: (info: { width: number; height: number; usedFallback: boolean }) => void;
  onImageError: () => void;
}

export function ImageOverlay({ src, fallbackSrc, targets, drawBoxes, selected, onSelect, imgRef, onImageReady, onImageError }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  const [scale, setScale] = useState(1);
  const [curSrc, setCurSrc] = useState(src);
  const [usedFallback, setUsedFallback] = useState(false);
  const pendingCenter = useRef<{ rx: number; ry: number } | null>(null);
  const drag = useRef<{ x: number; y: number; sl: number; st: number; moved: boolean; id: number } | null>(null);
  const suppressClick = useRef(false);

  useEffect(() => {
    setCurSrc(src);
    setUsedFallback(false);
    setNat(null);
  }, [src]);

  const fitScale = useCallback(
    (mode: 'page' | 'width' = 'page') => {
      const wrap = wrapRef.current;
      if (!wrap || !nat) return 1;
      const pad = 16;
      const sw = (wrap.clientWidth - pad) / nat.w;
      const sh = (wrap.clientHeight - pad) / nat.h;
      const s = mode === 'width' ? sw : Math.min(sw, sh);
      return Math.max(MIN_SCALE, Math.min(MAX_SCALE, s));
    },
    [nat],
  );

  // Ảnh mới ⇒ "vừa khung".
  useLayoutEffect(() => {
    if (nat) setScale(fitScale('page'));
  }, [nat, fitScale]);

  const zoomTo = (next: number) => {
    const wrap = wrapRef.current;
    if (wrap && nat) {
      const cw = nat.w * scale;
      const ch = nat.h * scale;
      pendingCenter.current = {
        rx: cw ? (wrap.scrollLeft + wrap.clientWidth / 2) / cw : 0.5,
        ry: ch ? (wrap.scrollTop + wrap.clientHeight / 2) / ch : 0.5,
      };
    }
    setScale(Math.max(MIN_SCALE, Math.min(MAX_SCALE, next)));
  };

  // Giữ tâm nhìn khi đổi mức phóng.
  useLayoutEffect(() => {
    const wrap = wrapRef.current;
    const c = pendingCenter.current;
    if (!wrap || !nat || !c) return;
    pendingCenter.current = null;
    wrap.scrollLeft = c.rx * nat.w * scale - wrap.clientWidth / 2;
    wrap.scrollTop = c.ry * nat.h * scale - wrap.clientHeight / 2;
  }, [scale, nat]);

  // Chọn ô ⇒ cuộn để ô nằm trong khung nhìn.
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap || !nat || selected === null) return;
    const t = targets.find((x) => x.index === selected);
    const b = t ? validBox(t.box_norm) : null;
    if (!b) return;
    const [y0, x0, y1, x1] = b;
    const left = x0 * nat.w * scale;
    const right = x1 * nat.w * scale;
    const top = y0 * nat.h * scale;
    const bottom = y1 * nat.h * scale;
    const visible =
      left >= wrap.scrollLeft && right <= wrap.scrollLeft + wrap.clientWidth && top >= wrap.scrollTop && bottom <= wrap.scrollTop + wrap.clientHeight;
    if (!visible) {
      wrap.scrollTo({
        left: (left + right) / 2 - wrap.clientWidth / 2,
        top: (top + bottom) / 2 - wrap.clientHeight / 2,
        behavior: 'smooth',
      });
    }
  }, [selected, targets, nat, scale]);

  // Ctrl + lăn chuột ⇒ phóng to/thu nhỏ.
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      setScale((s) => Math.max(MIN_SCALE, Math.min(MAX_SCALE, e.deltaY < 0 ? s * 1.1 : s / 1.1)));
    };
    wrap.addEventListener('wheel', onWheel, { passive: false });
    return () => wrap.removeEventListener('wheel', onWheel);
  }, []);

  const onPointerDown = (e: RPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || !wrapRef.current) return;
    drag.current = { x: e.clientX, y: e.clientY, sl: wrapRef.current.scrollLeft, st: wrapRef.current.scrollTop, moved: false, id: e.pointerId };
  };
  const onPointerMove = (e: RPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    const wrap = wrapRef.current;
    if (!d || !wrap) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) > 4) {
      d.moved = true;
      wrap.setPointerCapture(d.id);
      wrap.classList.add('panning');
    }
    if (d.moved) {
      wrap.scrollLeft = d.sl - dx;
      wrap.scrollTop = d.st - dy;
    }
  };
  const endDrag = () => {
    const d = drag.current;
    const wrap = wrapRef.current;
    if (d?.moved) {
      suppressClick.current = true;
      window.setTimeout(() => (suppressClick.current = false), 0);
    }
    if (wrap) {
      wrap.classList.remove('panning');
      if (d && wrap.hasPointerCapture(d.id)) wrap.releasePointerCapture(d.id);
    }
    drag.current = null;
  };

  const boxes = drawBoxes && nat ? targets : [];
  const fontPx = 12 / scale;
  const strokeLabelPad = 3 / scale;

  return (
    <div className="viewer">
      <div className="viewer-toolbar">
        <button type="button" className="btn btn-sm btn-secondary" onClick={() => zoomTo(scale / STEP)} title="Thu nhỏ" aria-label="Thu nhỏ">
          −
        </button>
        <span className="zoom-level">{Math.round(scale * 100)}%</span>
        <button type="button" className="btn btn-sm btn-secondary" onClick={() => zoomTo(scale * STEP)} title="Phóng to" aria-label="Phóng to">
          +
        </button>
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => setScale(fitScale('page'))}>
          Vừa khung
        </button>
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => setScale(fitScale('width'))}>
          Vừa chiều rộng
        </button>
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => zoomTo(1)}>
          100%
        </button>
        <span className="muted small viewer-hint">Kéo để di chuyển · Ctrl + lăn chuột để phóng</span>
      </div>
      <div
        className="viewer-canvas"
        ref={wrapRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <div className="viewer-content" style={nat ? { width: nat.w * scale, height: nat.h * scale } : undefined}>
          <img
            ref={imgRef}
            src={curSrc}
            alt="Ảnh trang chứng từ"
            draggable={false}
            onLoad={(e) => {
              const im = e.currentTarget;
              setNat({ w: im.naturalWidth, h: im.naturalHeight });
              onImageReady({ width: im.naturalWidth, height: im.naturalHeight, usedFallback });
            }}
            onError={() => {
              if (!usedFallback && fallbackSrc) {
                setUsedFallback(true);
                setCurSrc(fallbackSrc);
              } else {
                onImageError();
              }
            }}
            style={nat ? { width: '100%', height: '100%' } : { maxWidth: '100%' }}
          />
          {nat && boxes.length > 0 && (
            <svg className="viewer-svg" viewBox={`0 0 ${nat.w} ${nat.h}`} preserveAspectRatio="none">
              {boxes.map((t) => {
                const b = validBox(t.box_norm);
                if (!b) return null;
                const [y0, x0, y1, x1] = b;
                const x = x0 * nat.w;
                const y = y0 * nat.h;
                const w = (x1 - x0) * nat.w;
                const h = (y1 - y0) * nat.h;
                const st = targetState(t);
                const color = STATE_COLOR[st];
                const isSel = selected === t.index;
                // Nhãn không tràn khỏi bề rộng ô (tên đầy đủ ở tooltip và panel bên phải).
                const full = `${t.index + 1}. ${t.role}`;
                const charW = fontPx * 0.56;
                const maxChars = Math.max(1, Math.floor((w - strokeLabelPad * 2) / charW));
                const label =
                  full.length <= maxChars ? full : maxChars <= String(t.index + 1).length + 2 ? String(t.index + 1) : `${full.slice(0, maxChars - 1)}…`;
                const labelW = label.length * charW + strokeLabelPad * 2;
                const labelH = fontPx * 1.35;
                const labelY = y - labelH - 2 / scale >= 0 ? y - labelH - 2 / scale : y + 2 / scale;
                return (
                  <g
                    key={t.index}
                    className={`box ${isSel ? 'box-selected' : ''}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (!suppressClick.current) onSelect(t.index);
                    }}
                  >
                    <title>{`${full} — ${t.required ? 'Bắt buộc' : 'Không bắt buộc'}`}</title>
                    <rect
                      x={x}
                      y={y}
                      width={w}
                      height={h}
                      style={{ fill: color, stroke: color }}
                      fillOpacity={isSel ? 0.16 : 0.05}
                      strokeWidth={isSel ? 4 : 2.5}
                      strokeDasharray={t.required ? undefined : '8 5'}
                      vectorEffect="non-scaling-stroke"
                    />
                    <rect x={x} y={labelY} width={labelW} height={labelH} style={{ fill: color }} rx={2 / scale} />
                    <text x={x + strokeLabelPad} y={labelY + labelH * 0.75} fontSize={fontPx} fill="#fff" fontWeight={600}>
                      {label}
                    </text>
                  </g>
                );
              })}
            </svg>
          )}
        </div>
      </div>
    </div>
  );
}
