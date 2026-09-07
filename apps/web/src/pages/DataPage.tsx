import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Link2, DownloadCloud, BarChart3, PlayCircle, RefreshCw, Square, CheckCircle2 } from '../components/Icons';
import {
  cancelDataJob,
  connectData,
  dataJobLogDownloadUrl,
  getDataJob,
  getDataJobLog,
  getDataStatus,
  pullData,
  reportingData,
} from '../api';
import { LogViewer } from '../components/LogViewer';
import { StatusBadge } from '../components/StatusBadge';
import { usePolling } from '../hooks/usePolling';
import { useT } from '../i18n';
import { useChannelContext } from '../contexts/ChannelContext';
import type { DataJob } from '../types';
import { formatDate } from '../utils';

const DEFAULT_OUT_FILE = 'data/channels/youtube_data.json';

const channelScope = (channel: ReturnType<typeof useChannelContext>['currentChannel']) =>
  channel
    ? {
        user_id: channel.user_id,
        channel_id: channel.channel_id,
        youtube_channel_id: channel.youtube_channel_id,
      }
    : null;

const JOB_INTERVAL_MS = 1500;

/**
 * Trang "Kéo data YouTube": kết nối kênh (OAuth qua puller) rồi kéo data theo
 * video ID / khoảng ngày / tất cả video, tạo job Reporting API. File kết quả
 * ghi ở gốc backend → dùng ngay được trong "Tạo run mới".
 */
export function DataPage() {
  const { t, lang } = useT();
  const navigate = useNavigate();
  const { currentChannel, loading: channelLoading } = useChannelContext();
  const scope = channelScope(currentChannel);
  const scopeKey = scope ? `${scope.user_id}:${scope.channel_id}` : null;

  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<DataJob | null>(null);
  const [jobError, setJobError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [statusScopeKey, setStatusScopeKey] = useState<string | null>(null);
  const statusPoll = usePolling(
    () => (scope ? getDataStatus(scope) : Promise.resolve(null)),
    {
      enabled: scope !== null,
      intervalMs: busy ? 2500 : 10000,
    },
  );
  useEffect(() => {
    setBusy(Boolean(statusPoll.data?.busy));
  }, [statusPoll.data]);
  const status = statusScopeKey === scopeKey ? statusPoll.data : null;

  useEffect(() => {
    let cancelled = false;
    setStatusScopeKey(null);
    setBusy(false);
    setJobId(null);
    setJob(null);
    setJobError(null);
    setActionError(null);
    if (scopeKey) {
      void statusPoll.refresh().then(() => {
        if (!cancelled) setStatusScopeKey(scopeKey);
      });
    }
    return () => { cancelled = true; };
  }, [scopeKey, statusPoll.refresh]);

  const jobDone = job !== null && job.status !== 'running';
  const jobPoll = usePolling(
    () => (scope && jobId ? getDataJob(jobId, scope) : Promise.resolve(null)),
    {
      enabled: scope !== null && jobId !== null && !jobDone,
      intervalMs: JOB_INTERVAL_MS,
    },
  );
  useEffect(() => {
    if (jobPoll.data) setJob(jobPoll.data);
    if (jobPoll.error) setJobError(jobPoll.error);
  }, [jobPoll.data, jobPoll.error]);

  // Form kéo data.
  const [mode, setMode] = useState<'video_ids' | 'range' | 'all'>('video_ids');
  const [videoIds, setVideoIds] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [maxComments, setMaxComments] = useState('');
  const [maxReplies, setMaxReplies] = useState('');
  const [noReplies, setNoReplies] = useState(false);
  const [outFile, setOutFile] = useState(DEFAULT_OUT_FILE);

  const trackJob = (id: string) => {
    setJobId(id);
    setJob(null);
    setJobError(null);
    setActionError(null);
    void statusPoll.refresh();
  };

  const doConnect = async () => {
    setActionError(null);
    try {
      if (!scope) return;
      const r = await connectData(scope);
      trackJob(r.job_id);
    } catch (e) {
      setActionError(String(e));
    }
  };

  const doPull = async () => {
    setActionError(null);
    try {
      if (!scope) return;
      const r = await pullData({
        ...scope,
        mode,
        ...(mode === 'video_ids'
          ? { video_ids: videoIds.split(',').map((s) => s.trim()).filter(Boolean) }
          : {}),
        ...(mode === 'range' ? { start_date: startDate, end_date: endDate } : {}),
        ...(maxComments.trim() ? { max_comments: Number(maxComments) } : {}),
        ...(maxReplies.trim() ? { max_replies: Number(maxReplies) } : {}),
        no_replies: noReplies,
        out_file: outFile.trim() || DEFAULT_OUT_FILE,
      });
      trackJob(r.job_id);
    } catch (e) {
      setActionError(String(e));
    }
  };

  const doReporting = async (action: 'setup' | 'sync') => {
    setActionError(null);
    try {
      if (!scope) return;
      const r = await reportingData({
        ...scope,
        action,
        ...(action === 'sync' ? { out_file: outFile.trim() || DEFAULT_OUT_FILE } : {}),
      });
      trackJob(r.job_id);
    } catch (e) {
      setActionError(String(e));
    }
  };

  const doCancelJob = async () => {
    if (!jobId) return;
    if (!window.confirm(t('data.job.cancelConfirm'))) return;
    setActionError(null);
    try {
      if (!scope) return;
      await cancelDataJob(jobId, scope);
      void statusPoll.refresh();
      void jobPoll.refresh();
    } catch (e) {
      setActionError(String(e));
    }
  };

  if (channelLoading || !currentChannel) {
    return (
      <div className="page">
        <div className="empty-state">
          {channelLoading ? 'Đang tải channel...' : 'Chưa có channel được đăng ký.'}
        </div>
      </div>
    );
  }

  if (!status) {
    return <div className="page"><div className="empty-state">Đang tải dữ liệu trang...</div></div>;
  }

  const connected = status.connected;
  const activeJob = status.active_job;
  const connectActive = activeJob?.kind === 'connect';
  const canSubmit = !busy && connected;
  const result = status.last_result;
  const jobRunning = jobId !== null && (job === null || job.status === 'running');

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{t('data.title')}</h2>
          <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>
            Kết nối YouTube Data API & Reporting API để thu thập dữ liệu video & bình luận
          </div>
        </div>
        <div className="spacer" />
        <button type="button" className="btn" onClick={() => void statusPoll.refresh()}>
          <RefreshCw size={14} />
          {t('runs.refresh')}
        </button>
      </div>

      {actionError && <div className="error-text" style={{ marginBottom: 16, padding: '10px 14px', background: 'rgba(239, 68, 68, 0.1)', borderRadius: 8 }}>{actionError}</div>}
      {Boolean(statusPoll.error) && (
        <div className="error-text" style={{ marginBottom: 16 }}>
          {String(statusPoll.error)}
        </div>
      )}

      {!status.available && (
        <div className="orphan-banner">{t('data.unavailable')}</div>
      )}

      {/* --------------------------------------------------- kết nối */}
      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Link2 size={16} style={{ color: 'var(--blue)' }} />
            <span>{t('data.conn.title')}</span>
          </span>
          <span className="spacer" />
          {connected ? (
            <span className="badge badge-complete">{t('data.conn.connected')}</span>
          ) : status.available ? (
            <span className="badge badge-unknown">{t('data.conn.notConnected')}</span>
          ) : null}
        </div>
        <div className="panel-body">
          <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 0 }}>
            {t('data.conn.desc')}
          </p>
          <div className="toolbar">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void doConnect()}
              disabled={busy || !status.available}
            >
              <Link2 size={14} />
              {t('data.conn.connect')}
            </button>
            {status.expires_at && (
              <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>
                {t('data.conn.expiresAt')}: {formatDate(status.expires_at, lang)}
              </span>
            )}
          </div>
          {!status.scopes_ok && status.available && (
            <p style={{ fontSize: 12.5, color: 'var(--warn)', marginBottom: 0, marginTop: 10 }}>
              {t('data.conn.scopeMissing')}
            </p>
          )}
        </div>
      </div>

      {connectActive && (
        <div className="orphan-banner" style={{ marginBottom: 20 }}>
          {t('data.conn.waitingBrowser')}
        </div>
      )}

      {/* --------------------------------------------------- kéo data */}
      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <DownloadCloud size={16} style={{ color: 'var(--accent)' }} />
            <span>{t('data.pull.title')}</span>
          </span>
        </div>
        <div className="panel-body">
          <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 0 }}>
            {t('data.pull.desc')}
          </p>

          <div className="radio-row">
            <label className={mode === 'video_ids' ? 'sel' : ''}>
              <input
                type="radio"
                name="pull-mode"
                checked={mode === 'video_ids'}
                onChange={() => setMode('video_ids')}
                disabled={busy}
              />
              <div>
                <strong>{t('data.pull.mode.ids')}</strong>
              </div>
            </label>
            <label className={mode === 'range' ? 'sel' : ''}>
              <input
                type="radio"
                name="pull-mode"
                checked={mode === 'range'}
                onChange={() => setMode('range')}
                disabled={busy}
              />
              <div>
                <strong>{t('data.pull.mode.range')}</strong>
              </div>
            </label>
            <label className={mode === 'all' ? 'sel' : ''}>
              <input
                type="radio"
                name="pull-mode"
                checked={mode === 'all'}
                onChange={() => setMode('all')}
                disabled={busy}
              />
              <div>
                <strong>{t('data.pull.mode.all')}</strong>
              </div>
            </label>
          </div>

          {mode === 'video_ids' && (
            <div className="form-row">
              <label htmlFor="data-video-ids">{t('data.pull.mode.ids')}</label>
              <input
                id="data-video-ids"
                type="text"
                value={videoIds}
                onChange={(e) => setVideoIds(e.target.value)}
                placeholder={t('data.pull.mode.ids.placeholder')}
                disabled={busy}
              />
            </div>
          )}
          {mode === 'range' && (
            <div className="toolbar" style={{ gap: 16, marginBottom: 16 }}>
              <div className="form-row" style={{ marginBottom: 0, flex: 1 }}>
                <label htmlFor="data-start-date">{t('data.pull.startDate')}</label>
                <input
                  id="data-start-date"
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  disabled={busy}
                />
              </div>
              <div className="form-row" style={{ marginBottom: 0, flex: 1 }}>
                <label htmlFor="data-end-date">{t('data.pull.endDate')}</label>
                <input
                  id="data-end-date"
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  disabled={busy}
                />
              </div>
            </div>
          )}

          <div style={{ marginTop: 14, fontSize: 13, fontWeight: 600, color: 'var(--text-heading)' }}>
            {t('data.pull.options')}
          </div>
          <div className="toolbar" style={{ marginTop: 8, flexWrap: 'wrap', gap: 16 }}>
            <div className="form-row" style={{ marginBottom: 0 }}>
              <label htmlFor="data-max-comments">{t('data.pull.maxComments')}</label>
              <input
                id="data-max-comments"
                type="number"
                min={0}
                value={maxComments}
                onChange={(e) => setMaxComments(e.target.value)}
                disabled={busy}
                style={{ width: 120 }}
              />
            </div>
            <div className="form-row" style={{ marginBottom: 0 }}>
              <label htmlFor="data-max-replies">{t('data.pull.maxReplies')}</label>
              <input
                id="data-max-replies"
                type="number"
                min={0}
                value={maxReplies}
                onChange={(e) => setMaxReplies(e.target.value)}
                disabled={busy}
                style={{ width: 120 }}
              />
            </div>
            <label className="checkbox-row" style={{ marginTop: 24 }}>
              <input
                type="checkbox"
                checked={noReplies}
                onChange={(e) => setNoReplies(e.target.checked)}
                disabled={busy}
              />
              {t('data.pull.noReplies')}
            </label>
          </div>

          <div className="form-row" style={{ marginTop: 16 }}>
            <label htmlFor="data-out-file">{t('data.pull.outFile')}</label>
            <input
              id="data-out-file"
              type="text"
              value={outFile}
              onChange={(e) => setOutFile(e.target.value)}
              disabled={busy}
              className="mono"
            />
          </div>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4, marginBottom: 16 }}>
            {t('data.pull.outFileHint')}
          </p>

          {!connected && status.available && (
            <div className="error-text" style={{ marginBottom: 12 }}>{t('data.pull.needConnect')}</div>
          )}
          {busy && <div className="error-text" style={{ marginBottom: 12 }}>{t('data.pull.busy')}</div>}

          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void doPull()}
            disabled={!canSubmit}
          >
            <DownloadCloud size={15} />
            {t('data.pull.submit')}
          </button>
        </div>
      </div>

      {/* --------------------------------------------------- reporting */}
      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <BarChart3 size={16} style={{ color: 'var(--warn)' }} />
            <span>{t('data.reporting.title')}</span>
          </span>
        </div>
        <div className="panel-body">
          <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 0 }}>
            {t('data.reporting.desc')}
          </p>
          <div className="toolbar">
            <button
              type="button"
              className="btn"
              onClick={() => void doReporting('setup')}
              disabled={!canSubmit}
            >
              {t('data.reporting.setup')}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void doReporting('sync')}
              disabled={!canSubmit}
            >
              <RefreshCw size={14} />
              {t('data.reporting.sync')}
            </button>
          </div>
        </div>
      </div>

      {/* --------------------------------------------------- job đang theo dõi */}
      {jobId !== null && (
        <div className="panel" style={{ marginBottom: 20 }}>
          <div className="panel-title">
            {job ? (
              <StatusBadge status={job.status} />
            ) : (
              <span className="badge badge-running">{t('data.job.running')}</span>
            )}
            <span className="spacer" />
            {jobRunning && (
              <button type="button" className="btn btn-danger" onClick={() => void doCancelJob()}>
                <Square size={13} />
                {t('data.job.cancel')}
              </button>
            )}
          </div>
          {Boolean(jobError) && (
            <div className="error-text" style={{ margin: 12 }}>{String(jobError)}</div>
          )}
          <LogViewer
            logFetcher={(offset, limit) => getDataJobLog(jobId, offset, limit, scope ?? undefined)}
            downloadUrl={dataJobLogDownloadUrl(jobId, scope ?? undefined)}
            running={jobRunning}
            intervalMs={JOB_INTERVAL_MS}
          />
        </div>
      )}

      {/* --------------------------------------------------- kết quả gần nhất */}
      <div className="panel">
        <div className="panel-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <CheckCircle2 size={16} style={{ color: 'var(--ok)' }} />
            <span>{t('data.result.title')}</span>
          </span>
        </div>
        <div className="panel-body">
          {!result ? (
            <div className="empty-state">{t('data.result.none')}</div>
          ) : (
            <>
              <dl className="kv">
                <dt>{t('data.result.generatedAt')}</dt>
                <dd>{formatDate(result.generated_at, lang)}</dd>
                <dt>{t('data.result.channel')}</dt>
                <dd className="mono">{result.channel_id ?? '—'}</dd>
                <dt>{t('data.result.videos')}</dt>
                <dd style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{result.video_count}</dd>
                <dt>{t('data.result.window')}</dt>
                <dd>
                  {result.analytics_window
                    ? `${result.analytics_window.start} → ${result.analytics_window.end}`
                    : '—'}
                </dd>
                <dt>{t('data.pull.outFile')}</dt>
                <dd className="mono" style={{ color: 'var(--accent)' }}>{result.file}</dd>
              </dl>
              <div className="toolbar" style={{ marginTop: 16 }}>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => navigate(`/?input=${encodeURIComponent(result.file)}`)}
                >
                  <PlayCircle size={15} />
                  {t('data.result.newRun')}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
