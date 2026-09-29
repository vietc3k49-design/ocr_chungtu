import { useState } from 'react';
import { imageUrl } from '../api';

/** Ảnh thu nhỏ: thử ảnh stage1, lỗi thì dùng ảnh gốc, lỗi nữa thì ô trống. */
export function PageThumb({ pageId, alt, className = 'page-thumb' }: { pageId: number | string; alt: string; className?: string }) {
  const [kind, setKind] = useState<'stage1' | 'original' | 'none'>('stage1');
  if (kind === 'none') {
    return (
      <div className={`${className} page-thumb-empty`} title="Không tải được ảnh">
        ?
      </div>
    );
  }
  return (
    <img
      className={className}
      src={imageUrl(pageId, kind)}
      alt={alt}
      loading="lazy"
      onError={() => setKind((k) => (k === 'stage1' ? 'original' : 'none'))}
    />
  );
}
