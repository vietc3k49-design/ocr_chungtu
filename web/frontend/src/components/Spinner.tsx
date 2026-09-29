export function Spinner({ label = 'Đang tải…', block = false }: { label?: string; block?: boolean }) {
  return (
    <div className={block ? 'spinner-block' : 'spinner-inline'} role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
