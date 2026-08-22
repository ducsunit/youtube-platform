import { useEffect, useState } from 'react';
import { PlayCircle, X, FlaskConical, Rocket, FolderOutput, Loader2, RefreshCw } from './Icons';
import { ApiError, getDataJob, getDataStatus, pullData, reportingData, startRun } from '../api';
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
  const [channelDataMode, setChannelDataMode] = useState<'refresh' | 'snapshot' | 'none'>('snapshot');
  const [inputFile, setInputFile] = useState('');
  const [manualTopic, setManualTopic] = useState('');
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [runId, setRunId] = useState('');
  const [outputDir, setOutputDir] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setChannelDataMode('snapshot');
      setManualTopic('');
      if (initialInputFile) {
        setMode('production');
        setInputFile(initialInputFile);
      } else if (config?.default_input_file) {
        setInputFile(config.default_input_file);
      }
      setSyncMessage(null);
      setError(null);
      setSubmitting(false);
    }
  }, [open, initialInputFile, config?.default_input_file]);

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
      let latestInputFile = inputFile || config?.default_input_file || undefined;

      if (mode === 'production' && channelDataMode === 'refresh') {
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
          out_file: 'data/channels/youtube_data.json',
        });
        const job = await waitForDataJob(pull.job_id);
        if (job.status !== 'complete') {
          throw new Error(`Kéo data thất bại (job ${pull.job_id}). Mở trang Data để xem log.`);
        }
        setSyncMessage('Đang đồng bộ Reporting analytics (CTR, impressions, retention)...');
        const reporting = await reportingData({ action: 'sync', out_file: 'data/channels/youtube_data.json' });
        const reportingJob = await waitForDataJob(reporting.job_id);
        if (reportingJob.status !== 'complete') {
          throw new Error('Reporting sync thất bại. Kiểm tra kết nối Reporting API ở trang Data trước khi chạy.');
        }
        latestInputFile = 'data/channels/youtube_data.json';
        setSyncMessage(`Đã cập nhật và khóa dữ liệu: ${latestInputFile}`);
      }

      if (mode === 'production' && channelDataMode === 'snapshot' && !latestInputFile) {
        throw new Error('Chưa có dataset hợp lệ. Hãy chọn snapshot hoặc làm mới dữ liệu.');
      }
      const result = await startRun({
        mode,
        ...(mode === 'production' ? { channel_data_mode: channelDataMode } : {}),
        ...(mode === 'production' && channelDataMode !== 'none' && latestInputFile ? { input_file: latestInputFile } : {}),
        ...(mode === 'production' && channelDataMode === 'none' && manualTopic.trim() ? { manual_topic: manualTopic.trim() } : {}),
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
            <div className="radio-row" style={{ marginTop: 6 }}>
              <label className={channelDataMode === 'refresh' ? 'sel' : ''}>
                <input type="radio" name="channel-data-mode" checked={channelDataMode === 'refresh'} onChange={() => setChannelDataMode('refresh')} disabled={submitting} />
                <div><strong>Làm mới dữ liệu</strong><div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>Pull YouTube + Reporting analytics rồi chạy</div></div>
              </label>
              <label className={channelDataMode === 'snapshot' ? 'sel' : ''}>
                <input type="radio" name="channel-data-mode" checked={channelDataMode === 'snapshot'} onChange={() => setChannelDataMode('snapshot')} disabled={submitting} />
                <div><strong>Dùng snapshot</strong><div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>Replay với dữ liệu đã lưu, không tốn quota</div></div>
              </label>
              <label className={channelDataMode === 'none' ? 'sel' : ''}>
                <input type="radio" name="channel-data-mode" checked={channelDataMode === 'none'} onChange={() => setChannelDataMode('none')} disabled={submitting} />
                <div><strong>Chỉ dùng dữ liệu đối thủ</strong><div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>AI đề xuất và chọn topic từ competitor intelligence</div></div>
              </label>
            </div>
            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 5 }}>
              {channelDataMode === 'refresh'
                ? 'Pull dữ liệu mới, đồng bộ CTR/impressions/retention, rồi mới bắt đầu run.'
                : channelDataMode === 'snapshot'
                  ? 'Dùng snapshot đã chọn; phù hợp cho replay và không tốn thêm quota.'
                  : 'Không dùng analytics hay lịch sử kênh. AI nghiên cứu đối thủ, đề xuất candidates rồi chọn một topic để tạo source pack.'}
            </div>
            {channelDataMode === 'snapshot' && (
              <select
                value={inputFile}
                onChange={(event) => setInputFile(event.target.value)}
                disabled={submitting}
                style={{ marginTop: 8, width: '100%' }}
              >
                <option value="">Chọn dataset...</option>
                {(config?.input_files ?? []).map((file) => (
                  <option key={file.file} value={file.file}>
                    {file.file} — {file.video_count} video — {file.freshness === 'fresh' ? 'mới' : file.freshness === 'stale' ? 'cũ' : 'không rõ'}{file.has_reporting_reach ? ' — có CTR' : ' — thiếu CTR'}
                  </option>
                ))}
              </select>
            )}
            {channelDataMode === 'snapshot' && inputFile && (() => {
              const selected = (config?.input_files ?? []).find((file) => file.file === inputFile);
              return selected ? (
                <div style={{ fontSize: 11, color: selected.freshness === 'stale' ? 'var(--warn)' : 'var(--muted)', marginTop: 5 }}>
                  Snapshot: {selected.generated_at ?? 'không rõ thời điểm'}{selected.age_hours !== null ? ` (${selected.age_hours} giờ trước)` : ''}. {selected.has_reporting_reach ? 'Có Reporting reach.' : 'Thiếu Reporting reach/CTR.'}
                </div>
              ) : null;
            })()}
            {channelDataMode === 'none' && (
              <div style={{ marginTop: 8 }}>
                <label htmlFor="manual-topic" style={{ fontSize: 12 }}>Chủ đề gợi ý thêm (tùy chọn)</label>
                <input
                  id="manual-topic"
                  type="text"
                  value={manualTopic}
                  onChange={(event) => setManualTopic(event.target.value)}
                  placeholder="Để trống để AI tự đề xuất từ dữ liệu đối thủ"
                  disabled={submitting}
                  style={{ marginTop: 5, width: '100%' }}
                />
              </div>
            )}
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
