import type { ReactNode } from 'react';

export function Alert({ kind = 'info', children }: { kind?: 'info' | 'danger' | 'warning'; children: ReactNode }) {
  return (
    <div className={`alert alert-${kind}`} role={kind === 'danger' ? 'alert' : 'status'}>
      {children}
    </div>
  );
}

export const DEMO_REFERENCE_WARNING =
  'Bản demo suy từ ground truth của 72 ảnh mẫu — chỉ số khi bật KHÔNG phản ánh năng lực thật.';
