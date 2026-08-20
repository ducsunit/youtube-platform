import { useEffect, useState } from 'react';
import { PlayCircle, X, FlaskConical, Rocket, FolderOutput, Loader2, RefreshCw } from './Icons';
import { ApiError, getDataJob, getDataStatus, pullData, startRun } from '../api';
import { useT } from '../i18n';
import type { ServerConfig } from '../types';

interface Props {
  open: boolean;
  config: ServerConfig | null;
  /** File input mặc định (từ trang Kéo data → "Tạo run mới với file này"). */
  initialInputFile?: string;
  onClose: () => void;
  onStarted: (runId: string) => void;
}

/** Modal tạo run mới: chọn demo/production + file dữ liệu kênh. */
export function NewRunDialog({ open, config, initialInputFile, onClose, onStarted }: Props) {
  const { t } = useT();
  const [mode, setMode] = useState<'demo' | 'production'>('demo');
  const [autoSync, setAutoSync] = useState(true);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [runId, setRunId] = useState('');
  const [outputDir, setOutputDir] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open && initialInputFile) {
      setMode('production');
      setAutoSync(false);
    }
    if (open) {
      setSyncMessage(null);
      setError(null);
      setSubmitting(false);
    }
  }, [open, initialInputFile]);

  if (!open) return null;

  const busy = Boolean(config?.busy);

  const waitForDataJob = async (jobId: string) => {
    for (;;) {
      const job = await getDataJob(jobId);
      if (job.status !== 'running') return job;
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
    }
  };

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    setSyncMessage(null);
    try {
      let latestInputFile: string | undefined;

      if (mode === 'production' && autoSync) {
        const dataStatus = await getDataStatus();
        if (!dataStatus.available) {
          throw new Error('Không tìm thấy YouTube data puller.');
        }
        if (!dataStatus.connected) {
          throw new Error('YouTube chưa được kết nối. Hãy kết nối kênh ở trang Data trước.');
        }
        if (dataStatus.busy) {
          throw new Error('Đang có một data job khác chạy. Chờ job đó hoàn thành rồi tạo run.');
        }
        setSyncMessage('Đang kéo dữ liệu YouTube mới nhất...');
        const pull = await pullData({
          mode: 'all',
          out_file: 'youtube_data.json',
        });
        const job = await waitForDataJob(pull.job_id);
        if (job.status !== 'complete') {
          throw new Error(`Kéo data thất bại (job ${pull.job_id}). Mở trang Data để xem log.`);
        }
        const refreshed = await getDataStatus();
        latestInputFile = refreshed.last_result?.file ?? 'youtube_data.json';
        setSyncMessage(`Đã cập nhật dữ liệu: ${latestInputFile}`);
      } else if (mode === 'production') {
        latestInputFile = initialInputFile;
      }

      const result = await startRun({
        mode,
        ...(mode === 'production' && latestInputFile ? { input_file: latestInputFile } : {}),
        ...(runId.trim() ? { run_id: runId.trim() } : {}),
        ...(outputDir.trim() ? { output_dir: outputDir.trim() } : {}),
      });
      onStarted(result.run_id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(t('new.busy'));
      } else {
        setError(
          e instanceof ApiError
            ? `${t('new.err')}: ${typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail)}`
            : t('new.err'),
        );
      }
      setSubmitting(false);
    }
  };


  return (
    <div
      className="modal-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget && !submitting) onClose();
      }}
    >
      <div className="modal">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
          <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            <PlayCircle size={20} style={{ color: 'var(--accent)' }} />
            {t('new.title')}
          </h3>
          <button type="button" className="btn btn-ghost" onClick={onClose} disabled={submitting} style={{ padding: '6px' }}>
            <X size={16} />
          </button>
        </div>

        <div className="radio-row">
          <label className={mode === 'demo' ? 'sel' : ''}>
            <input
              type="radio"
              name="mode"
              checked={mode === 'demo'}
              onChange={() => setMode('demo')}
              disabled={submitting}
            />
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <FlaskConical size={14} style={{ color: 'var(--blue)' }} />
                <strong>{t('new.mode.demo')}</strong>
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>Thử nghiệm nhanh dữ liệu mẫu</div>
            </div>
          </label>
          <label className={mode === 'production' ? 'sel' : ''}>
            <input
              type="radio"
              name="mode"
              checked={mode === 'production'}
              onChange={() => {
                setMode('production');
              }}
              disabled={submitting}
            />
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <Rocket size={14} style={{ color: 'var(--accent)' }} />
                <strong>{t('new.mode.production')}</strong>
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>Chạy pipeline dữ liệu thật</div>
            </div>
          </label>
        </div>

        {mode === 'production' && (
          <div className="form-row">
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <RefreshCw size={13} />
              Dữ liệu kênh
            </label>
            <label className="checkbox-row" style={{ marginTop: 0 }}>
              <input
                type="checkbox"
                checked={autoSync}
                onChange={(e) => setAutoSync(e.target.checked)}
                disabled={submitting}
              />
              Tự động kéo data YouTube mới nhất trước khi chạy
            </label>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 5 }}>
              {autoSync
                ? 'Pipeline sẽ tự kéo dataset mới nhất rồi mới bắt đầu run.'
                : initialInputFile
                  ? `Dùng dataset hiện tại: ${initialInputFile}`
                  : 'Không tự kéo data; backend sẽ dùng dataset mới nhất đã có.'}
            </div>
            {syncMessage && (
              <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>
                {syncMessage}
              </div>
            )}
          </div>
        )}

        <div className="form-row">
          <label htmlFor="new-run-id">{t('new.runId')}</label>
          <input
            id="new-run-id"
            type="text"
            value={runId}
            onChange={(e) => setRunId(e.target.value)}
            placeholder="vd: ngu-phap-2026-01"
            disabled={submitting}
          />
        </div>

        <div className="form-row">
          <label htmlFor="new-output-dir" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <FolderOutput size={13} />
            {t('new.outputDir')}
          </label>
          <input
            id="new-output-dir"
            type="text"
            value={outputDir}
            onChange={(e) => setOutputDir(e.target.value)}
            disabled={submitting}
          />
        </div>

        {busy && <div className="error-text" style={{ marginTop: 8 }}>{t('new.busy')}</div>}
        {error && <div className="error-text" style={{ marginTop: 8 }}>{error}</div>}

        <div className="modal-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose} disabled={submitting}>
            {t('new.cancel')}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void submit()}
            disabled={busy || submitting}
          >
            {submitting ? <Loader2 size={15} className="spin" /> : <Rocket size={15} />}
            {submitting ? '...' : t('new.submit')}
          </button>
        </div>
      </div>
    </div>
  );
}
