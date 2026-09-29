import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  errorMessage,
  groupsApi,
  imageUrl,
  pagesApi,
  type PageDetail,
  type PageSummary,
  type ReviewDecision,
  type ReviewOut,
  type TargetOut,
} from '../api';
import { Alert } from '../components/Alert';
import { Badge } from '../components/Badge';
import { ImageOverlay } from '../components/ImageOverlay';
import { Spinner } from '../components/Spinner';
import { TargetCrop } from '../components/TargetCrop';
import { decisionLabel, formatDateTime, formatPercent, pageRole, s1Status } from '../lib/labels';
import { STATE_COLOR, STATE_LABEL, evidenceText, targetState } from '../lib/targets';
import { NOT_SUPPORTED, NO_SIGN_REQUIRED_LABEL, isNoSignRequired, pageEffectiveVerdict, pageMachineVerdict, type Verdict } from '../lib/verdict';

const DECISIONS: Array<{ key: ReviewDecision; label: string; hotkey: string; cls: string }> = [
  { key: 'SIGNED', label: 'Có chữ ký', hotkey: '1', cls: 'btn-decision-signed' },
  { key: 'NOT_SIGNED', label: 'Không có chữ ký', hotkey: '2', cls: 'btn-decision-notsigned' },
  { key: 'UNCLEAR', label: 'Không rõ', hotkey: '3', cls: 'btn-decision-unclear' },
];

function isTyping(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
}

function VerdictBox({ title, v, reason }: { title: string; v: Verdict; reason?: string | null }) {
  return (
    <div className="verdict-box">
      <div className="verdict-title">{title}</div>
      <Badge tone={v.tone} title={v.code ?? undefined}>
        {v.label}
      </Badge>
      {v.code && v.label !== v.code && <div className="mono tiny muted">{v.code}</div>}
      {reason && <div className="small verdict-reason">{reason}</div>}
    </div>
  );
}

function KeyValue({ rows }: { rows: Array<[string, ReactNode]> }) {
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <div key={k} className="kv-row">
          <dt>{k}</dt>
          <dd>{v ?? '—'}</dd>
        </div>
      ))}
    </dl>
  );
}

function renderValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

export default function PageViewer() {
  const { id = '' } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [page, setPage] = useState<PageDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [siblings, setSiblings] = useState<PageSummary[] | null>(null);
  const [reviews, setReviews] = useState<ReviewOut[] | null>(null);
  const [reviewsError, setReviewsError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [imgInfo, setImgInfo] = useState<{ ready: boolean; usedFallback: boolean; failed: boolean }>({
    ready: false,
    usedFallback: false,
    failed: false,
  });
  const [imgVersion, setImgVersion] = useState(0);
  const imgRef = useRef<HTMLImageElement>(null);

  const groupId = page?.group_id ?? params.get('bo');

  const loadReviews = useCallback(async () => {
    try {
      setReviews(await pagesApi.reviews(id));
      setReviewsError(null);
    } catch (e) {
      setReviewsError(errorMessage(e));
    }
  }, [id]);

  useEffect(() => {
    let alive = true;
    setPage(null);
    setError(null);
    setSelected(null);
    setNote('');
    setReviews(null);
    setReviewError(null);
    setImgInfo({ ready: false, usedFallback: false, failed: false });
    pagesApi.get(id).then(
      (p) => {
        if (!alive) return;
        setPage(p);
        const first = p.s4?.targets?.[0];
        if (first) setSelected(first.index);
      },
      (e: unknown) => alive && setError(errorMessage(e)),
    );
    void loadReviews();
    return () => {
      alive = false;
    };
  }, [id, loadReviews]);

  useEffect(() => {
    if (!groupId) return;
    let alive = true;
    groupsApi.get(groupId).then(
      (g) => alive && setSiblings([...(g.pages ?? [])].sort((a, b) => a.scan_index - b.scan_index)),
      () => alive && setSiblings(null),
    );
    return () => {
      alive = false;
    };
  }, [groupId]);

  const targets: TargetOut[] = useMemo(() => [...(page?.s4?.targets ?? [])].sort((a, b) => a.index - b.index), [page]);
  const selTarget = targets.find((t) => t.index === selected) ?? null;

  const submitReview = useCallback(
    async (decision: ReviewDecision) => {
      if (!page || selTarget === null || busy) return;
      setBusy(true);
      setReviewError(null);
      try {
        const updated = await pagesApi.review(page.id, selTarget.index, decision, note.trim());
        setPage(updated);
        setNote('');
        void loadReviews();
      } catch (e) {
        setReviewError(errorMessage(e));
      } finally {
        setBusy(false);
      }
    },
    [page, selTarget, busy, note, loadReviews],
  );

  // Phím tắt: 1/2/3 duyệt ô đang chọn; ←/→ chọn ô.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      if (!targets.length) return;
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault();
        const pos = targets.findIndex((t) => t.index === selected);
        const delta = e.key === 'ArrowRight' ? 1 : -1;
        const next = pos < 0 ? 0 : (pos + delta + targets.length) % targets.length;
        setSelected(targets[next]?.index ?? null);
        return;
      }
      const d = DECISIONS.find((x) => x.hotkey === e.key);
      if (d && selTarget) {
        e.preventDefault();
        void submitReview(d.key);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [targets, selected, selTarget, submitReview]);

  if (error) {
    return (
      <div className="page">
        <Alert kind="danger">{error}</Alert>
        <Link to="/">← Về danh sách bộ</Link>
      </div>
    );
  }
  if (!page) return <Spinner block />;

  const pos = siblings ? siblings.findIndex((p) => String(p.id) === String(page.id)) : -1;
  const prev = pos > 0 ? siblings?.[pos - 1] : undefined;
  const next = pos >= 0 && siblings && pos < siblings.length - 1 ? siblings[pos + 1] : undefined;
  const q = groupId ? `?bo=${encodeURIComponent(String(groupId))}` : '';

  const machine = pageMachineVerdict(page);
  const effective = pageEffectiveVerdict(page);
  const s1 = page.s1;
  const s2 = page.s2;
  const s4 = page.s4;
  const s1st = s1Status(s1?.status ?? page.s1_status, s1?.status_label_vi ?? page.s1_status_label_vi, page.s1_status_tone);
  const hasTargets = targets.length > 0;
  const drawBoxes = hasTargets && !imgInfo.usedFallback;
  const selState = selTarget ? targetState(selTarget) : null;
  const keyFields = Object.entries(s2?.key_fields ?? {}).filter(([, v]) => v !== null && v !== undefined && v !== '');
  const targetReviews = (reviews ?? []).filter((r) => selTarget && r.target_index === selTarget.index);

  // Thông báo khi trang không có ô ký nào. Ba trường hợp KHÁC NHAU, không gộp:
  //  1) Biểu mẫu không cần ký theo SOP (vd. Biểu đồ nhiệt độ) — bình thường, tone info.
  //  2) Loại chứng từ chưa có mẫu vùng ký — "Chưa hỗ trợ kiểm chữ ký".
  //  3) Có hỗ trợ nhưng không dò được vùng ký — nêu lý do của máy.
  const noSignRequired = isNoSignRequired(page);
  let noTargetMessage: string | null = null;
  if (!hasTargets) {
    if (noSignRequired) {
      noTargetMessage = `${NO_SIGN_REQUIRED_LABEL}: biểu mẫu "${
        page.doc_type_vi || page.doc_type || 'chưa xác định'
      }" không có ô ký nào cần kiểm.${s4?.reason ? ` ${s4.reason}` : ''}`;
    } else if (!page.supported) {
      noTargetMessage = `${NOT_SUPPORTED.label}: hiện hệ thống kiểm chữ ký cho Lệnh điều xe, Biểu đồ nhiệt độ hành trình và Loading Plan (trang này được phân loại là "${
        page.doc_type_vi || page.doc_type || 'chưa xác định'
      }").`;
    } else {
      noTargetMessage = s4?.reason || s4?.zone_description || 'Không xác định được vùng ký trên trang này.';
    }
  }

  return (
    <div className="page page-wide">
      <div className="viewer-head">
        <div>
          <div className="breadcrumb">
            <Link to="/">Bộ chứng từ</Link> <span>/</span>{' '}
            {groupId ? <Link to={`/bo/${groupId}`}>{page.group_title || `Bộ #${String(groupId).slice(0, 8)}`}</Link> : <span>Bộ</span>} <span>/</span>{' '}
            <span>Trang {page.scan_index + 1}</span>
          </div>
          <h1 className="viewer-title">
            Trang {page.scan_index + 1}
            {siblings ? <span className="muted"> / {siblings.length}</span> : null}
            <span className="viewer-subtitle">
              {page.doc_type_vi || page.doc_type || 'Chưa phân loại'} · <span className="mono">{page.original_filename}</span>
            </span>
          </h1>
        </div>
        <div className="page-actions">
          <button type="button" className="btn btn-secondary" disabled={!prev} onClick={() => prev && navigate(`/trang/${prev.id}${q}`)}>
            ← Trang trước
          </button>
          <button type="button" className="btn btn-secondary" disabled={!next} onClick={() => next && navigate(`/trang/${next.id}${q}`)}>
            Trang sau →
          </button>
        </div>
      </div>

      <div className="viewer-layout">
        <div className="viewer-main card">
          {imgInfo.failed ? (
            <Alert kind="danger">Không tải được ảnh của trang này.</Alert>
          ) : (
            <ImageOverlay
              src={imageUrl(page.id, 'stage1')}
              fallbackSrc={imageUrl(page.id, 'original')}
              targets={targets}
              drawBoxes={drawBoxes}
              selected={selected}
              onSelect={setSelected}
              imgRef={imgRef}
              onImageReady={({ usedFallback }) => {
                setImgInfo({ ready: true, usedFallback, failed: false });
                setImgVersion((v) => v + 1);
              }}
              onImageError={() => setImgInfo({ ready: false, usedFallback: false, failed: true })}
            />
          )}
          {imgInfo.usedFallback && hasTargets && (
            <Alert kind="warning">
              Không tải được ảnh đã chuẩn hóa (Tầng 1) — đang hiện ảnh gốc. Không vẽ khung ô ký vì tọa độ quy chiếu theo ảnh đã chuẩn
              hóa.
            </Alert>
          )}
          {noTargetMessage && <Alert kind="info">{noTargetMessage}</Alert>}
          {hasTargets && (
            <div className="legend">
              <span>
                <i className="swatch" style={{ borderColor: STATE_COLOR.signed }} /> Có chữ ký
              </span>
              <span>
                <i className="swatch" style={{ borderColor: STATE_COLOR.missing_required }} /> Bắt buộc, không thấy
              </span>
              <span>
                <i className="swatch" style={{ borderColor: STATE_COLOR.missing_optional }} /> Không bắt buộc, không thấy
              </span>
              <span>
                <i className="swatch" style={{ borderColor: STATE_COLOR.review }} /> Cần kiểm tra tay
              </span>
              <span>
                <i className="swatch" /> Nét liền = bắt buộc
              </span>
              <span>
                <i className="swatch swatch-dashed" /> Nét đứt = không bắt buộc
              </span>
            </div>
          )}
        </div>

        <aside className="viewer-side">
          <section className="card">
            <h2 className="card-title">Phán quyết trang</h2>
            <div className="verdict-pair">
              <VerdictBox title="Phán quyết máy" v={machine} reason={s4?.reason} />
              <VerdictBox title="Sau duyệt" v={effective} reason={page.effective?.reason} />
            </div>
            {page.supported && (
              <div className="small muted mt-8">
                Số ô đã sửa khi duyệt: <strong>{page.effective?.n_overridden ?? 0}</strong>
                {typeof page.effective?.n_reviewed === 'number' && (
                  <>
                    {' '}
                    · Số ô đã duyệt: <strong>{page.effective.n_reviewed}</strong>
                  </>
                )}
                {typeof s4?.required_policy?.policy_channel === 'string' && (
                  <>
                    {' '}
                    · Kênh chính sách: <strong>{s4.required_policy.policy_channel}</strong>
                  </>
                )}
                {s4?.required_policy?.policy_channel_unresolved === true && (
                  <>
                    {' '}
                    <Badge tone="warning">Chưa xác định kênh — áp chính sách nghiêm nhất</Badge>
                  </>
                )}
              </div>
            )}
          </section>

          {hasTargets && (
            <section className="card">
              <div className="card-title-row">
                <h2 className="card-title">Ô ký ({targets.length})</h2>
                <span className="tiny muted">←/→ chọn ô · 1/2/3 duyệt</span>
              </div>
              <ul className="target-list">
                {targets.map((t) => {
                  const st = targetState(t);
                  return (
                    <li key={t.index}>
                      <button
                        type="button"
                        className={`target-item ${selected === t.index ? 'target-item-active' : ''}`}
                        onClick={() => setSelected(t.index)}
                      >
                        <i
                          className={`swatch ${t.required ? '' : 'swatch-dashed'}`}
                          style={{ borderColor: STATE_COLOR[st] }}
                          aria-hidden="true"
                        />
                        <span className="target-item-role">
                          {t.index + 1}. {t.role}
                        </span>
                        <span className="tiny muted">{t.required ? 'Bắt buộc' : 'Không bắt buộc'}</span>
                        {t.latest_review && <span className="reviewed-tag">đã duyệt</span>}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          {selTarget && selState && (
            <section className="card target-panel">
              <h2 className="card-title">
                Ô {selTarget.index + 1}: {selTarget.role}
              </h2>
              <div className="crop-wrap">
                {imgInfo.ready && !imgInfo.usedFallback ? (
                  <TargetCrop
                    image={imgRef.current}
                    boxNorm={selTarget.box_norm}
                    color={STATE_COLOR[selState]}
                    dashed={!selTarget.required}
                    version={imgVersion}
                  />
                ) : (
                  <div className="crop-empty">Đang tải ảnh…</div>
                )}
              </div>
              <div className="state-line" style={{ borderLeftColor: STATE_COLOR[selState] }}>
                {STATE_LABEL[selState]}
              </div>
              <KeyValue
                rows={[
                  ['Yêu cầu', selTarget.required ? <strong>Bắt buộc</strong> : 'Không bắt buộc'],
                  ['Nguồn chính sách', <span className="mono tiny break">{selTarget.required_source || '—'}</span>],
                  ['Kênh chính sách', selTarget.policy_channel || '—'],
                  ['Máy phát hiện', selTarget.detected ? 'Có' : 'Không'],
                  ['Độ tin cậy', formatPercent(selTarget.confidence)],
                  // Chỉ hiện khi backend có trả (trang LOADING_PLAN cũ không có hai trường này).
                  ...(typeof selTarget.muc_so_huu_mm2 === 'number'
                    ? ([['Mực thuộc ô', `${selTarget.muc_so_huu_mm2.toFixed(1)} mm²`]] as Array<[string, ReactNode]>)
                    : []),
                  ...(typeof selTarget.so_cum === 'number'
                    ? ([['Số cụm nét', String(selTarget.so_cum)]] as Array<[string, ReactNode]>)
                    : []),
                  [
                    'Bằng chứng',
                    <span className="break">
                      {evidenceText(selTarget)}
                      {evidenceText(selTarget) !== selTarget.evidence && selTarget.evidence ? (
                        <span className="mono tiny muted"> ({selTarget.evidence})</span>
                      ) : null}
                    </span>,
                  ],
                  ['Lý do (máy)', selTarget.reason || '—'],
                  ['Cần kiểm tra tay', selTarget.review_required ? 'Có' : 'Không'],
                  [
                    'Duyệt gần nhất',
                    selTarget.latest_review ? (
                      <span>
                        <strong>{selTarget.latest_review.decision_vi || decisionLabel(selTarget.latest_review.decision)}</strong> — {selTarget.latest_review.reviewer_email},{' '}
                        {formatDateTime(selTarget.latest_review.created_at)}
                        {selTarget.latest_review.note ? <em className="block">“{selTarget.latest_review.note}”</em> : null}
                      </span>
                    ) : (
                      'Chưa duyệt'
                    ),
                  ],
                ]}
              />

              <div className="review-box">
                <div className="review-title">Duyệt tay ô này</div>
                <textarea
                  rows={2}
                  placeholder="Ghi chú (không bắt buộc)"
                  value={note}
                  maxLength={1000}
                  onChange={(e) => setNote(e.target.value)}
                />
                <div className="decision-row">
                  {DECISIONS.map((d) => (
                    <button
                      key={d.key}
                      type="button"
                      className={`btn btn-decision ${d.cls} ${selTarget.latest_review?.decision === d.key ? 'is-current' : ''}`}
                      disabled={busy}
                      onClick={() => void submitReview(d.key)}
                      title={`Phím tắt: ${d.hotkey}`}
                    >
                      <kbd>{d.hotkey}</kbd> {d.label}
                    </button>
                  ))}
                </div>
                {busy && <Spinner label="Đang lưu duyệt…" />}
                {reviewError && <Alert kind="danger">{reviewError}</Alert>}
                <p className="tiny muted">Kết quả máy giữ nguyên; mỗi lần duyệt được lưu thêm vào lịch sử (không ghi đè).</p>
              </div>

              <div className="history">
                <div className="review-title">Lịch sử duyệt ô này</div>
                {reviewsError && <Alert kind="warning">{reviewsError}</Alert>}
                {!reviews && !reviewsError && <Spinner label="Đang tải lịch sử…" />}
                {reviews && targetReviews.length === 0 && <p className="muted small">Chưa có lượt duyệt nào.</p>}
                {targetReviews.length > 0 && (
                  <ol className="history-list">
                    {[...targetReviews]
                      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
                      .map((r, i) => (
                        <li key={r.id ?? `${r.created_at}-${i}`}>
                          <div>
                            <strong>{r.decision_vi || decisionLabel(r.decision)}</strong>{' '}
                            {r.stale && <Badge tone="warning">Không còn khớp sau chạy lại</Badge>}
                          </div>
                          <div className="tiny muted">
                            {r.reviewer_email} · {formatDateTime(r.created_at)}
                          </div>
                          {r.note && <div className="small">“{r.note}”</div>}
                        </li>
                      ))}
                  </ol>
                )}
              </div>
            </section>
          )}

          <section className="card">
            <h2 className="card-title">Tầng 1 · Chất lượng ảnh</h2>
            <KeyValue
              rows={[
                ['Trạng thái', <Badge tone={s1st.tone} title={s1?.status ?? undefined}>{s1st.label}</Badge>],
                ['Hành động', <span className="mono small">{s1?.action || '—'}</span>],
                ['Nguồn ảnh', s1?.source_type === 'scan' ? 'Máy scan' : s1?.source_type === 'photo' ? 'Ảnh chụp' : s1?.source_type || '—'],
                [
                  'Độ phân giải',
                  s1?.low_resolution ? (
                    <Badge tone="warning">DPI thấp{s1.effective_dpi ? ` (~${Math.round(s1.effective_dpi)} DPI)` : ''}</Badge>
                  ) : s1?.effective_dpi ? (
                    `~${Math.round(s1.effective_dpi)} DPI`
                  ) : (
                    '—'
                  ),
                ],
                [
                  'Cảnh báo',
                  s1?.warns?.length ? (
                    <ul className="list-tight">
                      {s1.warns.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  ) : (
                    'Không có'
                  ),
                ],
                [
                  'Lý do từ chối',
                  s1?.rejects?.length ? (
                    <ul className="list-tight">
                      {s1.rejects.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  ) : (
                    'Không có'
                  ),
                ],
              ]}
            />
          </section>

          <section className="card">
            <h2 className="card-title">Tầng 2 · Phân loại</h2>
            <KeyValue
              rows={[
                [
                  'Loại chứng từ',
                  <span>
                    {page.doc_type_vi || s2?.doc_type || '—'} {s2?.doc_type && <span className="mono tiny muted">({s2.doc_type})</span>}
                  </span>,
                ],
                ['Kênh / hệ thống', <span className="mono small">{s2?.system || page.system || '—'}</span>],
                ['Vai trò trang', pageRole(s2?.page_role ?? page.page_role)],
                ['Độ tin cậy', formatPercent(s2?.confidence)],
                ['Gác cổng T2', <span className="mono small">{s2?.status || '—'}</span>],
                ['Lô (T3)', <span className="mono small">{page.batch_id || '—'}</span>],
              ]}
            />
            <div className="review-title mt-8">Trường khóa</div>
            {keyFields.length === 0 ? (
              <p className="muted small">Không bóc tách được trường khóa nào.</p>
            ) : (
              <table className="table table-compact">
                <tbody>
                  {keyFields.map(([k, v]) => (
                    <tr key={k}>
                      <td className="mono small">{k}</td>
                      <td className="mono small break">{renderValue(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {s4 && (
            <section className="card">
              <h2 className="card-title">Tầng 3b/4 · Vùng ký</h2>
              <KeyValue
                rows={[
                  [
                    'Trạng thái vùng ký',
                    <span>
                      {s4.zone_status_label_vi || s4.zone_status || '—'}{' '}
                      {s4.zone_status_label_vi && <span className="mono tiny muted">({s4.zone_status})</span>}
                    </span>,
                  ],
                  ['Mô tả', s4.zone_description || '—'],
                  ['Loại ảnh', <span className="mono small">{s4.modality || '—'}</span>],
                  ['Hành động (máy)', <span>{s4.action_label_vi || s4.action || '—'}</span>],
                  ['Hành động (sau duyệt)', <span>{page.effective?.action_label_vi || page.effective?.action || '—'}</span>],
                ]}
              />
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
