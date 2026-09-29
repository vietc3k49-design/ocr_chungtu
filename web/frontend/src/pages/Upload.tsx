import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import { SortableContext, arrayMove, rectSortingStrategy, sortableKeyboardCoordinates, useSortable } from '@dnd-kit/sortable';
import { adminApi, errorMessage, groupsApi } from '../api';
import { useAuth } from '../auth/AuthContext';
import { Alert, DEMO_REFERENCE_WARNING } from '../components/Alert';
import { formatBytes } from '../lib/labels';

interface Item {
  id: string;
  file: File;
  url: string;
}

interface Rejected {
  name: string;
  reason: string;
}

const ACCEPTED_MIME = ['image/jpeg', 'image/png'];

/** Kiểm nhanh chữ ký tệp (magic bytes) phía client — server vẫn kiểm lại bằng Pillow. */
async function sniff(file: File): Promise<'jpeg' | 'png' | null> {
  try {
    const buf = new Uint8Array(await file.slice(0, 8).arrayBuffer());
    if (buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return 'jpeg';
    if (buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) return 'png';
  } catch {
    /* bỏ qua */
  }
  return null;
}

let seq = 0;

function SortableThumb({ item, index, onRemove }: { item: Item; index: number; onRemove: () => void }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: item.id });
  const style = {
    transform: transform ? `translate3d(${Math.round(transform.x)}px, ${Math.round(transform.y)}px, 0)` : undefined,
    transition,
    zIndex: isDragging ? 5 : undefined,
  };
  return (
    <div ref={setNodeRef} style={style} className={`thumb ${isDragging ? 'thumb-dragging' : ''}`}>
      <div className="thumb-handle" {...attributes} {...listeners} title="Kéo để đổi thứ tự" aria-label={`Trang ${index + 1}, kéo để đổi thứ tự`}>
        <img src={item.url} alt={item.file.name} draggable={false} />
      </div>
      <div className="thumb-meta">
        <span className="thumb-page">Trang {index + 1}</span>
        <button type="button" className="icon-btn" onClick={onRemove} title="Xóa trang này" aria-label={`Xóa trang ${index + 1}`}>
          ✕
        </button>
      </div>
      <div className="thumb-name" title={item.file.name}>
        {item.file.name}
      </div>
      <div className="thumb-size">{formatBytes(item.file.size)}</div>
    </div>
  );
}

export default function Upload() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const [items, setItems] = useState<Item[]>([]);
  const [rejected, setRejected] = useState<Rejected[]>([]);
  const [title, setTitle] = useState('');
  const [useReference, setUseReference] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const itemsRef = useRef<Item[]>([]);
  itemsRef.current = items;

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  useEffect(() => {
    if (!isAdmin) return;
    adminApi
      .settings()
      .then((s) => setUseReference(Boolean(s.use_reference_default)))
      .catch(() => setUseReference(false));
  }, [isAdmin]);

  // Giải phóng object URL khi rời trang.
  useEffect(() => () => itemsRef.current.forEach((it) => URL.revokeObjectURL(it.url)), []);

  const addFiles = useCallback(async (list: FileList | File[]) => {
    const files = Array.from(list);
    const ok: Item[] = [];
    const bad: Rejected[] = [];
    for (const f of files) {
      if (!ACCEPTED_MIME.includes(f.type)) {
        bad.push({ name: f.name, reason: f.type ? `định dạng ${f.type} không được nhận` : 'không xác định được định dạng' });
        continue;
      }
      const kind = await sniff(f);
      if (!kind) {
        bad.push({ name: f.name, reason: 'nội dung không phải ảnh JPG/PNG hợp lệ' });
        continue;
      }
      if (f.size === 0) {
        bad.push({ name: f.name, reason: 'tệp rỗng' });
        continue;
      }
      seq += 1;
      ok.push({ id: `f${seq}`, file: f, url: URL.createObjectURL(f) });
    }
    setRejected(bad);
    if (ok.length) setItems((prev) => [...prev, ...ok]);
  }, []);

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files?.length) void addFiles(e.dataTransfer.files);
  };

  const onDragEnd = (e: DragEndEvent) => {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    setItems((prev) => {
      const from = prev.findIndex((i) => i.id === active.id);
      const to = prev.findIndex((i) => i.id === over.id);
      return from < 0 || to < 0 ? prev : arrayMove(prev, from, to);
    });
  };

  const remove = (id: string) => {
    setItems((prev) => {
      const it = prev.find((i) => i.id === id);
      if (it) URL.revokeObjectURL(it.url);
      return prev.filter((i) => i.id !== id);
    });
  };

  const clearAll = () => {
    items.forEach((it) => URL.revokeObjectURL(it.url));
    setItems([]);
  };

  const totalBytes = items.reduce((s, i) => s + i.file.size, 0);
  const uploading = progress !== null;

  const submit = async () => {
    if (!items.length) return;
    setError(null);
    setProgress(0);
    try {
      const g = await groupsApi.create(
        items.map((i) => i.file),
        title,
        isAdmin ? useReference : undefined,
        (loaded, total) => setProgress(total ? loaded / total : 0),
      );
      navigate(`/bo/${g.id}`);
    } catch (e) {
      setError(errorMessage(e));
      setProgress(null);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Tải lên bộ chứng từ</h1>
          <p className="muted">
            Chỉ nhận ảnh <strong>JPG/PNG</strong>. Thứ tự trang trong bộ là thứ tự quét (Trang 1, 2, …) — kéo thả ảnh để sắp
            lại cho đúng thứ tự chứng từ gốc.
          </p>
        </div>
      </div>

      <div className="upload-layout">
        <div className="card">
          <label className="field">
            <span>Tiêu đề bộ (không bắt buộc)</span>
            <input
              value={title}
              maxLength={200}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Ví dụ: Chuyến 130771 — BigC ngày 27/09"
              disabled={uploading}
            />
          </label>

          <div
            className={`dropzone ${dragOver ? 'dropzone-over' : ''}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={() => !uploading && inputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if ((e.key === 'Enter' || e.key === ' ') && !uploading) inputRef.current?.click();
            }}
            aria-label="Kéo thả ảnh vào đây hoặc bấm để chọn tệp"
          >
            <div className="dropzone-icon" aria-hidden="true">
              ⬆
            </div>
            <div className="dropzone-text">
              <strong>Kéo thả ảnh vào đây</strong> hoặc bấm để chọn tệp
            </div>
            <div className="muted small">Nhận nhiều ảnh cùng lúc · JPG, PNG</div>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept="image/jpeg,image/png"
              hidden
              onChange={(e) => {
                if (e.target.files) void addFiles(e.target.files);
                e.target.value = '';
              }}
            />
          </div>

          {rejected.length > 0 && (
            <Alert kind="warning">
              <strong>{rejected.length} tệp bị loại:</strong>
              <ul className="list-tight">
                {rejected.map((r, i) => (
                  <li key={`${r.name}-${i}`}>
                    <code>{r.name}</code> — {r.reason}
                  </li>
                ))}
              </ul>
            </Alert>
          )}

          {items.length > 0 && (
            <>
              <div className="thumbs-head">
                <span>
                  <strong>{items.length}</strong> trang · {formatBytes(totalBytes)}
                </span>
                <button type="button" className="btn btn-ghost btn-sm" onClick={clearAll} disabled={uploading}>
                  Xóa tất cả
                </button>
              </div>
              <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
                <SortableContext items={items.map((i) => i.id)} strategy={rectSortingStrategy}>
                  <div className="thumbs">
                    {items.map((it, idx) => (
                      <SortableThumb key={it.id} item={it} index={idx} onRemove={() => remove(it.id)} />
                    ))}
                  </div>
                </SortableContext>
              </DndContext>
            </>
          )}
        </div>

        <aside className="card upload-side">
          <h2>Gửi xử lý</h2>
          <ul className="list-tight muted small">
            <li>Hệ thống chạy 4 tầng: chuẩn hóa ảnh → phân loại → gom lô → kiểm chữ ký.</li>
            <li>Gom lô chỉ thực hiện trong phạm vi bộ này.</li>
            <li>
              Hiện kiểm chữ ký cho <strong>Lệnh điều xe</strong>, <strong>Biểu đồ nhiệt độ hành trình</strong> và{' '}
              <strong>Loading Plan</strong>. Biểu đồ nhiệt độ hành trình không có ô ký nào theo SOP nên hiển thị "Không yêu cầu ký
              theo SOP"; loại chứng từ khác hiển thị "Chưa hỗ trợ kiểm chữ ký".
            </li>
          </ul>

          {isAdmin && (
            <div className="ref-box">
              <label className="check">
                <input
                  type="checkbox"
                  checked={useReference}
                  onChange={(e) => setUseReference(e.target.checked)}
                  disabled={uploading}
                />
                <span>Dùng dữ liệu tham chiếu mã chuyến DEMO</span>
              </label>
              <p className="warn-red">{DEMO_REFERENCE_WARNING}</p>
            </div>
          )}

          {error && <Alert kind="danger">{error}</Alert>}

          {uploading && (
            <div className="upload-progress" aria-live="polite">
              <div className="progress">
                <div className="progress-bar" style={{ width: `${Math.round((progress ?? 0) * 100)}%` }} />
              </div>
              <div className="small muted">
                {(progress ?? 0) < 1 ? `Đang tải lên… ${Math.round((progress ?? 0) * 100)}%` : 'Đã tải xong, đang tạo bộ…'}
              </div>
            </div>
          )}

          <button type="button" className="btn btn-primary btn-block" disabled={!items.length || uploading} onClick={() => void submit()}>
            {uploading ? 'Đang tải lên…' : `Tải lên ${items.length || ''} trang`.replace('  ', ' ')}
          </button>
        </aside>
      </div>
    </div>
  );
}
