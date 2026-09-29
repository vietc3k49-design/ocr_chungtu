import type { JobInfo } from '../api/types';
import { normalizeStatus } from '../lib/labels';

const STEPS = [
  { key: 'T1', label: 'T1 · Chuẩn hóa ảnh', from: 0, to: 40 },
  { key: 'T2', label: 'T2 · Phân loại', from: 40, to: 80 },
  { key: 'T3', label: 'T3 · Gom lô', from: 80, to: 85 },
  { key: 'T4', label: 'T4 · Kiểm chữ ký', from: 85, to: 98 },
] as const;

/** Suy ra bước hiện tại từ job.stage (nếu đọc được) hoặc từ % (thang SPEC §4). */
function currentStep(job: JobInfo | null, groupStatus: string): number {
  const gs = normalizeStatus(groupStatus);
  if (gs === 'DONE') return STEPS.length;
  const stage = normalizeStatus(job?.stage);
  if (stage.includes('SAVE') || stage.includes('LUU')) return STEPS.length;
  const m = stage.match(/([1-4])/);
  if (m?.[1]) return Number(m[1]) - 1;
  const p = job?.percent ?? 0;
  if (p >= 98) return STEPS.length;
  const idx = STEPS.findIndex((s) => p >= s.from && p < s.to);
  return idx < 0 ? 0 : idx;
}

export function JobStepper({ job, groupStatus }: { job: JobInfo | null; groupStatus: string }) {
  const gs = normalizeStatus(groupStatus);
  const failed = gs === 'FAILED' || normalizeStatus(job?.status) === 'FAILED';
  const queued = gs === 'QUEUED' || gs === 'PENDING' || normalizeStatus(job?.status) === 'QUEUED';
  const cur = currentStep(job, groupStatus);
  const percent = gs === 'DONE' ? 100 : Math.max(0, Math.min(100, job?.percent ?? 0));

  return (
    <div className="stepper-wrap">
      <ol className="stepper">
        {STEPS.map((s, i) => {
          let state: 'done' | 'active' | 'pending' | 'failed' = 'pending';
          if (i < cur) state = 'done';
          else if (i === cur) state = failed ? 'failed' : queued ? 'pending' : 'active';
          return (
            <li key={s.key} className={`step step-${state}`}>
              <span className="step-dot" aria-hidden="true">
                {state === 'done' ? '✓' : state === 'failed' ? '!' : i + 1}
              </span>
              <span className="step-label">{s.label}</span>
            </li>
          );
        })}
      </ol>
      <div className="progress progress-lg" aria-label={`Tiến độ ${Math.round(percent)}%`}>
        <div className={`progress-bar ${failed ? 'progress-bar-danger' : ''}`} style={{ width: `${percent}%` }} />
      </div>
      <div className="stepper-meta">
        <span className="strong">{Math.round(percent)}%</span>
        <span className="muted">
          {queued && !job?.message ? 'Đang chờ đến lượt xử lý…' : job?.message || ''}
          {job?.stage_total ? ` (${job.stage_done ?? 0}/${job.stage_total})` : ''}
        </span>
      </div>
    </div>
  );
}
