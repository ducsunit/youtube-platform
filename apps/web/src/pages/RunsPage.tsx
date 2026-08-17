import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Plus, RefreshCw, Search, Layers, PlayCircle, CheckCircle2, AlertCircle } from '../components/Icons';
import { getConfig, listRuns } from '../api';
import { NewRunDialog } from '../components/NewRunDialog';
import { RunsTable } from '../components/RunsTable';
import { usePolling } from '../hooks/usePolling';
import { useT } from '../i18n';
import type { RunSummary } from '../types';

/** Trang chủ: danh sách run + tạo run mới. Tự làm mới nhanh khi có run đang chạy. */
export function RunsPage() {
  const { t } = useT();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const inputParam = searchParams.get('input');
  const [dialogOpen, setDialogOpen] = useState(inputParam !== null && inputParam !== '');
  const initialInput = inputParam ?? undefined;
  const [executing, setExecuting] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');

  const configPoll = usePolling(() => getConfig(), {
    enabled: true,
    intervalMs: 30000,
  });
  const runsPoll = usePolling(() => listRuns(), {
    enabled: true,
    intervalMs: executing ? 2500 : 10000,
  });

  useEffect(() => {
    const anyExec = (runsPoll.data?.runs ?? []).some((r: RunSummary) => r.executing);
    setExecuting(anyExec);
  }, [runsPoll.data]);

  const runs = runsPoll.data?.runs ?? null;
  const filteredRuns = runs
    ? runs.filter(
        (r) =>
          r.topic?.toLowerCase().includes(searchTerm.toLowerCase()) ||
          r.run_id?.toLowerCase().includes(searchTerm.toLowerCase())
      )
    : [];

  const totalCount = runs ? runs.length : 0;
  const activeCount = runs ? runs.filter((r) => r.executing || r.status === 'running').length : 0;
  const completedCount = runs ? runs.filter((r) => r.status === 'complete' || r.status === 'passed').length : 0;
  const failedCount = runs ? runs.filter((r) => r.status === 'failed').length : 0;
  const successRate = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  return (
    <div className="page">
      {/* Top Stat Overview Grid */}
      <div className="stats-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16, marginBottom: 24 }}>
        <div className="stat-card" style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ color: 'var(--muted)', fontSize: 13, fontWeight: 500 }}>Total Pipeline Runs</span>
            <Layers size={18} style={{ color: 'var(--accent)' }} />
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, marginTop: 8, color: 'var(--text-heading)' }}>{totalCount}</div>
        </div>

        <div className="stat-card" style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ color: 'var(--muted)', fontSize: 13, fontWeight: 500 }}>Active Executions</span>
            <PlayCircle size={18} style={{ color: 'var(--blue)' }} />
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, marginTop: 8, color: 'var(--blue)' }}>{activeCount}</div>
        </div>

        <div className="stat-card" style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ color: 'var(--muted)', fontSize: 13, fontWeight: 500 }}>Success Rate</span>
            <CheckCircle2 size={18} style={{ color: 'var(--ok)' }} />
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, marginTop: 8, color: 'var(--ok)' }}>{successRate}%</div>
        </div>

        <div className="stat-card" style={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ color: 'var(--muted)', fontSize: 13, fontWeight: 500 }}>Failed Runs</span>
            <AlertCircle size={18} style={{ color: 'var(--err)' }} />
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, marginTop: 8, color: 'var(--err)' }}>{failedCount}</div>
        </div>
      </div>

      <div className="page-head">
        <div>
          <h2>{t('runs.title')}</h2>
          <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>
            Quản lý pipeline tự động hóa nội dung và theo dõi tiến trình chạy
          </div>
        </div>
        <div className="spacer" />

        <div className="search-box" style={{ position: 'relative', width: 240 }}>
          <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--muted)' }} />
          <input
            type="text"
            placeholder="Tìm theo chủ đề hoặc Run ID..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{ paddingLeft: 34, fontSize: 13 }}
          />
        </div>

        <button type="button" className="btn" onClick={() => void runsPoll.refresh()}>
          <RefreshCw size={14} />
          {t('runs.refresh')}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => setDialogOpen(true)}
          disabled={Boolean(configPoll.data?.busy)}
        >
          <Plus size={15} />
          {t('runs.new')}
        </button>
      </div>

      {Boolean(runsPoll.error) && (
        <div className="error-text" style={{ marginBottom: 16, padding: '12px 16px', background: 'rgba(239, 68, 68, 0.1)', borderRadius: 10, border: '1px solid rgba(239, 68, 68, 0.2)' }}>
          {String(runsPoll.error)}
        </div>
      )}

      {runs === null ? (
        <div className="empty-state">Đang tải dữ liệu runs...</div>
      ) : filteredRuns.length === 0 ? (
        <div className="empty-state">
          {searchTerm ? 'Không tìm thấy run nào phù hợp với từ khóa' : t('runs.empty')}
        </div>
      ) : (
        <div className="panel">
          <RunsTable runs={filteredRuns} onDelete={() => void runsPoll.refresh()} />
        </div>
      )}

      <NewRunDialog
        open={dialogOpen}
        config={configPoll.data}
        initialInputFile={initialInput}
        onClose={() => setDialogOpen(false)}
        onStarted={(runId) => navigate(`/runs/${runId}`)}
      />
    </div>
  );
}

