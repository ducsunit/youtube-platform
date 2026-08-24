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
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="panel flex items-center justify-between gap-3 p-[18px] transition duration-200 hover:-translate-y-0.5 hover:border-accent hover:shadow-lg">
          <div className="min-w-0">
            <span className="block truncate text-[13px] font-medium text-muted">Total Pipeline Runs</span>
            <div className="mt-2 text-[26px] font-bold leading-none text-heading">{totalCount}</div>
          </div>
          <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent">
            <Layers size={18} />
          </span>
        </div>

        <div className="panel flex items-center justify-between gap-3 p-[18px] transition duration-200 hover:-translate-y-0.5 hover:border-accent hover:shadow-lg">
          <div className="min-w-0">
            <span className="block truncate text-[13px] font-medium text-muted">Active Executions</span>
            <div className="mt-2 text-[26px] font-bold leading-none text-blue">{activeCount}</div>
          </div>
          <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue/15 text-blue">
            <PlayCircle size={18} />
          </span>
        </div>

        <div className="panel flex items-center justify-between gap-3 p-[18px] transition duration-200 hover:-translate-y-0.5 hover:border-accent hover:shadow-lg">
          <div className="min-w-0">
            <span className="block truncate text-[13px] font-medium text-muted">Success Rate</span>
            <div className="mt-2 text-[26px] font-bold leading-none text-ok">{successRate}%</div>
          </div>
          <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-ok/15 text-ok">
            <CheckCircle2 size={18} />
          </span>
        </div>

        <div className="panel flex items-center justify-between gap-3 p-[18px] transition duration-200 hover:-translate-y-0.5 hover:border-accent hover:shadow-lg">
          <div className="min-w-0">
            <span className="block truncate text-[13px] font-medium text-muted">Failed Runs</span>
            <div className="mt-2 text-[26px] font-bold leading-none text-err">{failedCount}</div>
          </div>
          <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-err/15 text-err">
            <AlertCircle size={18} />
          </span>
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
        <div className="msg-banner msg-err" style={{ marginBottom: 16 }}>
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

