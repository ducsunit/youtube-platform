import { useEffect, useState } from 'react';
import { PlayCircle, X, FlaskConical, Rocket, FileJson, FolderOutput, Loader2 } from './Icons';
import { ApiError, startRun } from '../api';
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
  const [inputFile, setInputFile] = useState('');
  const [runId, setRunId] = useState('');
  const [outputDir, setOutputDir] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open && initialInputFile) {
      setMode('production');
      setInputFile(initialInputFile);
    }
  }, [open, initialInputFile]);

  if (!open) return null;

  const busy = Boolean(config?.busy);

  /** File hiệu lực: state nếu user chọn, còn không thì dùng default từ server. */
  const effectiveInputFile =
    inputFile || (mode === 'production' ? config?.default_input_file || '' : '');

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const result = await startRun({
        mode,
        ...(mode === 'production' && effectiveInputFile ? { input_file: effectiveInputFile } : {}),
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

  const files = config?.input_files ?? [];

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
                if (!inputFile && config?.default_input_file) {
                  setInputFile(config.default_input_file);
                }
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
            <label htmlFor="new-input-file" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <FileJson size={13} />
              {t('new.inputFile')}
            </label>
            <select
              id="new-input-file"
              value={effectiveInputFile}
              onChange={(e) => setInputFile(e.target.value)}
              disabled={submitting}
            >
              {files.map((f) => (
                <option key={f.name} value={f.name}>
                  {f.name}
                </option>
              ))}
              {files.length === 0 && <option value="">—</option>}
            </select>
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
            disabled={busy || submitting || (mode === 'production' && !effectiveInputFile)}
          >
            {submitting ? <Loader2 size={15} className="spin" /> : <Rocket size={15} />}
            {submitting ? '...' : t('new.submit')}
          </button>
        </div>
      </div>
    </div>
  );
}

