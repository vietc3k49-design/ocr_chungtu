import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { errorMessage, groupsApi, type GroupSummary } from '../api';
import { useAuth } from '../auth/AuthContext';
import { Alert } from '../components/Alert';
import { Badge, DemoReferenceBadge } from '../components/Badge';
import { Spinner } from '../components/Spinner';
import { formatDateTime, groupStatus, isFinal } from '../lib/labels';

export default function GroupList() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const [all, setAll] = useState(false);
  const [groups, setGroups] = useState<GroupSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setGroups(await groupsApi.list(isAdmin && all));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [all, isAdmin]);

  useEffect(() => {
    setGroups(null);
    void load();
  }, [load]);

  // Còn bộ đang xử lý ⇒ tự làm mới mỗi 5s.
  const hasRunning = (groups ?? []).some((g) => !isFinal(g.status));
  useEffect(() => {
    if (!hasRunning) return;
    const t = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(t);
  }, [hasRunning, load]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Bộ chứng từ đã tải lên</h1>
          <p className="muted">Mỗi bộ là một lần tải lên. Gom lô và kiểm chữ ký được thực hiện trong phạm vi từng bộ.</p>
        </div>
        <div className="page-actions">
          {isAdmin && (
            <label className="check">
              <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
              <span>Xem của mọi người dùng</span>
            </label>
          )}
          <Link to="/tai-len" className="btn btn-primary">
            + Tải lên bộ mới
          </Link>
        </div>
      </div>

      {error && <Alert kind="danger">{error}</Alert>}
      {!groups && !error && <Spinner block />}
      {groups && groups.length === 0 && (
        <div className="empty">
          <p>Chưa có bộ chứng từ nào.</p>
          <Link to="/tai-len" className="btn btn-primary">
            Tải lên bộ đầu tiên
          </Link>
        </div>
      )}
      {groups && groups.length > 0 && (
        <div className="card table-card">
          <table className="table table-hover">
            <thead>
              <tr>
                <th>Tiêu đề</th>
                <th>Trạng thái</th>
                <th className="num">Số trang</th>
                <th className="num">Trang có kiểm ký</th>
                <th>Hồ sơ chứng từ (sau duyệt)</th>
                {isAdmin && all && <th>Người tải</th>}
                <th>Tạo lúc</th>
                <th>Xong lúc</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => {
                const st = groupStatus(g.status, g.status_label_vi);
                const summary = Object.entries(g.lp_dossier_summary ?? {});
                const summaryMachine = Object.entries(g.lp_dossier_summary_machine ?? {});
                return (
                  <tr key={g.id} className="clickable" onClick={() => navigate(`/bo/${g.id}`)}>
                    <td>
                      <Link to={`/bo/${g.id}`} onClick={(e) => e.stopPropagation()} className="strong">
                        {g.title || `Bộ #${g.id}`}
                      </Link>
                      {g.use_reference && (
                        <div className="mt-4">
                          <DemoReferenceBadge text={g.reference_badge_vi} />
                        </div>
                      )}
                    </td>
                    <td>
                      <Badge tone={st.tone}>{st.label}</Badge>
                    </td>
                    <td className="num">{g.n_pages}</td>
                    <td className="num">{g.n_lp_pages}</td>
                    <td>
                      {summary.length === 0 ? (
                        <span className="muted">—</span>
                      ) : (
                        <div className="chips">
                          {summary.map(([code, n]) => (
                            <span key={code} className="chip" title="Mã phán quyết hồ sơ sau duyệt">
                              <code>{code}</code> × {n}
                            </span>
                          ))}
                        </div>
                      )}
                      {summaryMachine.length > 0 && JSON.stringify(summaryMachine) !== JSON.stringify(summary) && (
                        <div className="tiny muted mt-4">
                          Máy: {summaryMachine.map(([code, n]) => `${code} × ${n}`).join(', ')}
                        </div>
                      )}
                    </td>
                    {isAdmin && all && <td>{g.owner_email}</td>}
                    <td className="nowrap">{formatDateTime(g.created_at)}</td>
                    <td className="nowrap">{formatDateTime(g.finished_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
