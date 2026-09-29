import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { errorMessage, groupsApi, type GroupDetail, type GroupStatusOut } from '../api';
import { useAuth } from '../auth/AuthContext';
import { Alert } from '../components/Alert';
import { Badge, DemoReferenceBadge } from '../components/Badge';
import { JobStepper } from '../components/JobStepper';
import { PageThumb } from '../components/PageThumb';
import { Spinner } from '../components/Spinner';
import { formatDateTime, groupStatus, isFinal, normalizeStatus, pageRole, s1Status } from '../lib/labels';
import { dossierEffectiveVerdict, dossierMachineVerdict, isNoSignRequired, pageMachineStatus, pageSignatureStatus, resolveDossierPages } from '../lib/verdict';

const POLL_MS = 1500;

export default function GroupDetailPage() {
  const { id = '' } = useParams();
  const { user, isAdmin } = useAuth();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<GroupDetail | null>(null);
  const [status, setStatus] = useState<GroupStatusOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [rerunning, setRerunning] = useState(false);
  const lastStatus = useRef<string | null>(null);

  const loadDetail = useCallback(async () => {
    try {
      const d = await groupsApi.get(id);
      setDetail(d);
      setError(null);
      return d;
    } catch (e) {
      setError(errorMessage(e));
      return null;
    }
  }, [id]);

  useEffect(() => {
    setDetail(null);
    setStatus(null);
    lastStatus.current = null;
    void loadDetail().then((d) => {
      if (d) {
        lastStatus.current = normalizeStatus(d.status);
        setStatus({ status: d.status, job: d.job });
      }
    });
  }, [loadDetail]);

  // Poll /status mỗi 1.5s cho tới DONE/FAILED; khi kết thúc thì tải lại GroupDetail.
  const currentStatus = status?.status ?? null;
  useEffect(() => {
    if (!currentStatus || isFinal(currentStatus)) return;
    let alive = true;
    let timer = 0;
    const tick = async () => {
      try {
        const s = await groupsApi.status(id);
        if (!alive) return;
        setPollError(null);
        setStatus(s);
        const n = normalizeStatus(s.status);
        if (isFinal(n)) {
          if (lastStatus.current !== n) await loadDetail();
          lastStatus.current = n;
          return;
        }
        lastStatus.current = n;
      } catch (e) {
        if (alive) setPollError(errorMessage(e));
      }
      if (alive) timer = window.setTimeout(() => void tick(), POLL_MS);
    };
    timer = window.setTimeout(() => void tick(), POLL_MS);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [currentStatus, id, loadDetail]);

  const onRerun = async () => {
    if (!window.confirm('Chạy lại toàn bộ bộ này? Kết quả máy hiện tại sẽ được thay; lịch sử duyệt tay vẫn được giữ.')) return;
    setRerunning(true);
    try {
      await groupsApi.rerun(id);
      const d = await loadDetail();
      if (d) setStatus({ status: d.status, job: d.job });
    } catch (e) {
      window.alert(errorMessage(e));
    } finally {
      setRerunning(false);
    }
  };

  if (error && !detail) {
    return (
      <div className="page">
        <Alert kind="danger">{error}</Alert>
        <Link to="/">← Về danh sách bộ</Link>
      </div>
    );
  }
  if (!detail) return <Spinner block />;

  const gStatus = normalizeStatus(status?.status ?? detail.status);
  const st = groupStatus(gStatus, status?.status_label_vi ?? detail.status_label_vi);
  const job = status?.job ?? detail.job;
  const done = gStatus === 'DONE';
  const failed = gStatus === 'FAILED';
  const canRerun = (isAdmin || user?.email === detail.owner_email) && (done || failed);
  const pages = [...(detail.pages ?? [])].sort((a, b) => a.scan_index - b.scan_index);
  const isolated = (detail.batches ?? []).filter((b) => b.is_isolated).length;

  return (
    <div className="page">
      <div className="breadcrumb">
        <Link to="/">Bộ chứng từ</Link> <span>/</span> <span>{detail.title || `Bộ #${detail.id}`}</span>
      </div>
      <div className="page-head">
        <div>
          <h1>{detail.title || `Bộ #${detail.id}`}</h1>
          <div className="head-meta">
            <Badge tone={st.tone}>{st.label}</Badge>
            {detail.use_reference && <DemoReferenceBadge text={detail.reference_badge_vi} />}
            <span className="muted small">
              {detail.n_pages} trang · tải lúc {formatDateTime(detail.created_at)}
              {detail.finished_at ? ` · xong lúc ${formatDateTime(detail.finished_at)}` : ''}
              {isAdmin ? ` · ${detail.owner_email}` : ''}
            </span>
          </div>
          <p className="muted small scope-note">Gom lô trong phạm vi bộ upload này.</p>
        </div>
        <div className="page-actions">
          {canRerun && (
            <button type="button" className="btn btn-secondary" onClick={() => void onRerun()} disabled={rerunning}>
              {rerunning ? 'Đang tạo lượt chạy…' : 'Chạy lại'}
            </button>
          )}
        </div>
      </div>

      {!done && (
        <div className="card">
          <h2 className="card-title">Tiến độ xử lý</h2>
          <JobStepper job={job} groupStatus={gStatus} />
          {pollError && <Alert kind="warning">Mất kết nối khi cập nhật tiến độ: {pollError}. Đang thử lại…</Alert>}
          {failed && (
            <Alert kind="danger">
              <strong>Xử lý thất bại.</strong> {status?.error || detail.error || job?.error?.split('\n').filter(Boolean).slice(-1)[0] || 'Không rõ nguyên nhân.'}
            </Alert>
          )}
        </div>
      )}

      {done && (
        <>
          <section className="card">
            <div className="card-title-row">
              <h2 className="card-title">Hồ sơ chứng từ</h2>
              <span className="muted small">
                {(detail.batches ?? []).length} lô trong bộ{isolated ? ` (${isolated} lô cách ly)` : ''}
              </span>
            </div>
            {(detail.dossiers ?? []).length === 0 ? (
              <p className="muted">Bộ này không có hồ sơ chứng từ nào được kiểm chữ ký.</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Hồ sơ</th>
                    <th>Lô</th>
                    <th>Trang thuộc hồ sơ</th>
                    <th>Kênh chính sách</th>
                    <th>Phán quyết máy</th>
                    <th>Sau duyệt</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.dossiers.map((d) => {
                    const mv = dossierMachineVerdict(d);
                    const ev = dossierEffectiveVerdict(d);
                    const dpages = resolveDossierPages(d, pages);
                    return (
                      <tr key={d.dossier_id}>
                        <td className="mono">{d.dossier_id}</td>
                        <td className="mono small">{d.batch_id ?? '—'}</td>
                        <td>
                          <div className="chips">
                            {dpages.map(({ name, page }) =>
                              page ? (
                                <Link key={name} className="chip chip-link" to={`/trang/${page.id}?bo=${detail.id}`} title={page.original_filename}>
                                  Trang {page.scan_index + 1}
                                </Link>
                              ) : (
                                <span key={name} className="chip" title="Không nối được với trang trong bộ">
                                  {name}
                                </span>
                              ),
                            )}
                          </div>
                        </td>
                        <td>
                          {d.policy_channel ?? '—'}
                          {d.policy_channel_unresolved && (
                            <div>
                              <Badge tone="warning">Chưa xác định kênh</Badge>
                            </div>
                          )}
                        </td>
                        <td>
                          <Badge tone={mv.tone} title={mv.code ?? undefined}>
                            {mv.label}
                          </Badge>
                          {d.reason && <div className="tiny muted mt-4">{d.reason}</div>}
                        </td>
                        <td>
                          {ev ? (
                            <>
                              <Badge tone={ev.tone} title={ev.code ?? undefined}>
                                {ev.label}
                              </Badge>
                              {d.effective_reason && <div className="tiny muted mt-4">{d.effective_reason}</div>}
                            </>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </section>

          <section className="card table-card">
            <div className="card-title-row">
              <h2 className="card-title">Tất cả các trang ({pages.length})</h2>
              <span className="muted small">Bấm vào một trang để xem ảnh, khung ô ký và duyệt tay.</span>
            </div>
            <table className="table table-hover">
              <thead>
                <tr>
                  <th className="num">Trang</th>
                  <th>Ảnh</th>
                  <th>Tệp gốc</th>
                  <th>Loại chứng từ</th>
                  <th>Kênh</th>
                  <th>Vai trò trang</th>
                  <th>Lô</th>
                  <th>Trường khóa</th>
                  <th>Chất lượng ảnh (T1)</th>
                  <th>Kiểm ký (máy)</th>
                  <th>Kiểm ký (sau duyệt)</th>
                </tr>
              </thead>
              <tbody>
                {pages.map((p) => {
                  const s1 = s1Status(p.s1_status, p.s1_status_label_vi, p.s1_status_tone);
                  const sig = pageSignatureStatus(p);
                  const sigM = pageMachineStatus(p);
                  const kf = Object.entries(p.key_fields ?? {}).filter(([, v]) => v !== null && v !== undefined && v !== '');
                  const to = `/trang/${p.id}?bo=${detail.id}`;
                  return (
                    <tr key={p.id} className="clickable" onClick={() => navigate(to)}>
                      <td className="num strong">{p.scan_index + 1}</td>
                      <td>
                        <PageThumb pageId={p.id} alt={`Trang ${p.scan_index + 1}`} />
                      </td>
                      <td className="small break">
                        <Link to={to} onClick={(e) => e.stopPropagation()}>
                          {p.original_filename}
                        </Link>
                      </td>
                      <td>{p.doc_type_vi || p.doc_type || '—'}</td>
                      <td className="mono small">{p.system || '—'}</td>
                      <td>{pageRole(p.page_role)}</td>
                      <td className="mono small">{p.batch_id || '—'}</td>
                      <td className="small">
                        {kf.length === 0 ? (
                          <span className="muted">—</span>
                        ) : (
                          kf.map(([k, v]) => (
                            <div key={k} className="nowrap">
                              <span className="muted">{k}:</span> <span className="mono">{String(v)}</span>
                            </div>
                          ))
                        )}
                      </td>
                      <td>
                        <Badge tone={s1.tone} title={p.s1_status ?? undefined}>
                          {s1.label}
                        </Badge>
                      </td>
                      <td>
                        <Badge tone={sigM.tone} title={sigM.code ?? undefined}>
                          {sigM.label}
                        </Badge>
                      </td>
                      <td>
                        {/* Trang không cần ký thì không có gì để duyệt tay ⇒ hiện thẳng phán quyết. */}
                        {p.supported && !p.reviewed && !isNoSignRequired(p) ? (
                          <span className="muted small">Chưa duyệt tay (= máy)</span>
                        ) : (
                          <Badge tone={sig.tone} title={sig.code ?? undefined}>
                            {sig.label}
                          </Badge>
                        )}
                        {p.reviewed && <span className="reviewed-tag">đã duyệt tay</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}
