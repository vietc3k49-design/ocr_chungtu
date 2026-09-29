import type { ReactNode } from 'react';
import type { StatusTone } from '../api/types';
import { safeTone } from '../lib/labels';

export function Badge({ tone, children, title }: { tone?: StatusTone | string | null; children: ReactNode; title?: string }) {
  return (
    <span className={`badge badge-${safeTone(tone)}`} title={title}>
      {children}
    </span>
  );
}

export function DemoReferenceBadge({ text }: { text?: string | null }) {
  return (
    <span className="badge badge-demo" title="Mã chuyến được hiệu chỉnh bằng dữ liệu demo suy từ ground truth — không phản ánh năng lực thật">
      {text || 'Dùng tham chiếu DEMO (suy từ GT)'}
    </span>
  );
}
