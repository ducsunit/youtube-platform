import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  RefreshCw,
  Square,
  Layers,
  Info,
  AlertTriangle,
  AlertOctagon,
  Download,
  Terminal,
  FolderOpen
} from '../components/Icons';
import {
  ApiError,
  artifactUrl,
  cancelRun,
  getConfig,
  getLog,
  getRun,
  getRunStatus,
  logDownloadUrl,
} from '../api';
import { ArtifactBrowser } from '../components/ArtifactBrowser';
import { ArtifactViewer } from '../components/ArtifactViewer';
import { LogViewer } from '../components/LogViewer';
import { ResumeButton } from '../components/ResumeButton';
import { StageList } from '../components/StageList';
import { StatusBadge } from '../components/StatusBadge';
import { usePolling } from '../hooks/usePolling';
import { useT } from '../i18n';
import type { RunDetail } from '../types';
import { formatDate, strField } from '../utils';


function formatElapsed(totalSeconds: number | null | undefined): string {
  if (totalSeconds == null || !Number.isFinite(totalSeconds)) return '—';
  const whole = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const seconds = whole % 60;
  return hours > 0
    ? `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
    : `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
}

function snapshotProfile(snapshot: Record<string, unknown>) {
  const profile = snapshot.minimax_tts_profile;
  if (!profile || typeof profile !== 'object') return null;
  const p = profile as Record<string, unknown>;
  return {
    speed: typeof p.speed === 'number' ? p.speed : null,
    pitch: typeof p.pitch === 'number' ? p.pitch : null,
    volume: typeof p.volume === 'number' ? p.volume : null,
    cpmMin: typeof p.reference_cpm_min === 'number' ? p.reference_cpm_min : null,
    cpmMax: typeof p.reference_cpm_max === 'number' ? p.reference_cpm_max : null,
  };
}

/** Trang chi tiết run: stages, meta, artifacts, log — poll status khi đang chạy. */
export function RunDetailPage() {
  const { runId = '' } = useParams();
  const { t, lang } = useT();
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [detailError, setDetailError] = useState<unknown>(null);
  const [finished, setFinished] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [clockMs, setClockMs] = useState(() => Date.now());

  const configPoll = usePolling(() => getConfig(), {
    enabled: true,
    intervalMs: 60000,
  });
  const intervalMs = configPoll.data?.poll_interval_ms ?? 1500;

  // Detail: retry 404 (run_state.json chưa được ghi ngay sau khi tạo run).
  const detailPoll = usePolling(() => getRun(runId), {
    enabled: detail === null && detailError === null,
    intervalMs: 1500,
  });

  useEffect(() => {
    if (detailPoll.data) {
      setDetail(detailPoll.data);
      setFinished(
        detailPoll.data.state.status === 'complete' ||
          detailPoll.data.state.status === 'failed',
      );
    }
    if (detailPoll.error) {
      const is404 = detailPoll.error instanceof ApiError && detailPoll.error.status === 404;
      if (!is404) setDetailError(detailPoll.error);
    }
  }, [detailPoll.data, detailPoll.error]);

  const statusPoll = usePolling(() => getRunStatus(runId), {
    enabled: detail !== null && !finished,
    intervalMs,
  });

  useEffect(() => {
    if (statusPoll.data) setFinished(statusPoll.data.finished);
  }, [statusPoll.data]);

  const running = !finished;

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setClockMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  const status = statusPoll.data;
  const orphaned = running && (Boolean(status?.orphaned) || Boolean(detail?.orphaned));

  const refreshAll = () => {
    void detailPoll.refresh();
    void statusPoll.refresh();
  };

  const doCancel = async () => {
    if (!window.confirm(t('detail.cancelConfirm'))) return;
    setActionError(null);
    try {
      await cancelRun(runId);
      refreshAll();
    } catch (e) {
      setActionError(String(e));
    }
  };

  if (detailError) {
    return (
      <div className="page">
        <div className="empty-state">
          {String(detailError)}
          <div style={{ marginTop: 16 }}>
            <Link className="btn btn-primary" to="/">
              <ArrowLeft size={14} />
              {t('detail.back')}
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="page">
        <div className="empty-state">Đang tải thông tin chi tiết run...</div>
      </div>
    );
  }

  const profile = snapshotProfile(detail.state.config_snapshot);
  const executionStartedMs = detail.state.execution_started_at ? Date.parse(detail.state.execution_started_at) : NaN;
  const totalStartedMs = detail.state.total_started_at ? Date.parse(detail.state.total_started_at) : NaN;
  const executionBaseSeconds = detail.state.execution_elapsed_seconds ?? null;
  const totalBaseSeconds = detail.state.total_elapsed_seconds ?? null;
  const liveExecutionSeconds =
    running && Number.isFinite(executionStartedMs)
      ? Math.max(0, (clockMs - executionStartedMs) / 1000)
      : executionBaseSeconds;
  const totalElapsedSeconds =
    running && Number.isFinite(totalStartedMs)
      ? Math.max(0, (clockMs - totalStartedMs) / 1000)
      : totalBaseSeconds ?? liveExecutionSeconds;
  const timelineStatus = strField(detail.manifest, 'timeline_status');
  const nextSteps = strField(detail.manifest, 'manual_next_steps');
  const warnings = detail.state.warnings ?? [];
  const errors = detail.state.errors ?? [];

  return (
    <div className="page">
      <div className="page-head">
        <Link className="btn btn-ghost" to="/">
          <ArrowLeft size={15} />
          {t('detail.back')}
        </Link>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <h2 className="mono" style={{ fontSize: 18 }}>{runId}</h2>
            <StatusBadge status={running ? 'running' : detail.state.status} />
          </div>
          {detail.state.topic && (
            <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>
              Chủ đề: <span style={{ color: 'var(--text-heading)', fontWeight: 500 }}>{detail.state.topic}</span>
            </div>
          )}
        </div>
        <div className="spacer" />
        <ResumeButton
          runId={runId}
          disabled={running}
          onResumed={() => {
            setFinished(false);
            refreshAll();
          }}
        />
        <button
          type="button"
          className="btn btn-danger"
          onClick={() => void doCancel()}
          disabled={!running}
        >
          <Square size={14} />
          {t('detail.cancel')}
        </button>
        <button type="button" className="btn" onClick={refreshAll}>
          <RefreshCw size={14} />
          {t('detail.refresh')}
        </button>
      </div>

      {actionError && <div className="error-text" style={{ marginBottom: 16, padding: '10px 14px', background: 'rgba(239,68,68,0.1)', borderRadius: 8 }}>{actionError}</div>}
      {orphaned && <div className="orphan-banner">{t('detail.orphaned')}</div>}

      <div className="grid-detail">
        <div>
          <div className="panel" style={{ marginBottom: 20 }}>
            <div className="panel-title">
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Layers size={16} style={{ color: 'var(--accent)' }} />
                <span>{t('stages.title')}</span>
              </span>
            </div>
            <StageList
              stageOrder={configPoll.data?.stage_order ?? []}
              records={detail.state.stage_records}
              activeStage={status?.active_stage ?? null}
            />
          </div>

          <div className="panel" style={{ marginBottom: 20 }}>
            <div className="panel-title">
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <RefreshCw size={16} style={{ color: 'var(--accent)' }} />
                <span>Thời gian chạy</span>
              </span>
            </div>
            <div className="panel-body">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12 }}>
                <div style={{ padding: '12px 14px', borderRadius: 10, background: 'var(--bg)' }}>
                  <div style={{ color: 'var(--muted)', fontSize: 12 }}>Lần chạy hiện tại</div>
                  <div className="mono" style={{ fontSize: 24, fontWeight: 700, marginTop: 4, color: running ? 'var(--accent)' : 'var(--text-heading)' }}>
                    {formatElapsed(liveExecutionSeconds)}
                  </div>
                </div>
                <div style={{ padding: '12px 14px', borderRadius: 10, background: 'var(--bg)' }}>
                  <div style={{ color: 'var(--muted)', fontSize: 12 }}>Tổng từ lần chạy đầu</div>
                  <div className="mono" style={{ fontSize: 24, fontWeight: 700, marginTop: 4 }}>
                    {formatElapsed(totalElapsedSeconds)}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-title">
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Info size={16} style={{ color: 'var(--blue)' }} />
                <span>{t('detail.meta')}</span>
              </span>
            </div>
            <div className="panel-body">
              <dl className="kv">
                <dt>{t('detail.created')}</dt>
                <dd>{formatDate(detail.state.created_at, lang)}</dd>
                <dt>{t('detail.updated')}</dt>
                <dd>{formatDate(detail.state.updated_at, lang)}</dd>
                <dt>{t('detail.timeline')}</dt>
                <dd>{timelineStatus ?? '—'}</dd>
                {profile && (
                  <>
                    <dt>MiniMax TTS</dt>
                    <dd>
                      speed {profile.speed} · pitch {profile.pitch} · volume {profile.volume}
                    </dd>
                    <dt>Reference CPM</dt>
                    <dd>
                      {profile.cpmMin}–{profile.cpmMax}
                    </dd>
                  </>
                )}
              </dl>
              <div className="toolbar" style={{ marginTop: 14 }}>
                {detail.manifest && (
                  <a
                    className="btn btn-ghost"
                    href={artifactUrl(runId, 'resource_manifest.json', true)}
                    download
                    style={{ padding: '6px 12px', fontSize: 12.5 }}
                  >
                    <Download size={13} />
                    {t('detail.manifest')}
                  </a>
                )}
              </div>
              {nextSteps && (
                <p style={{ fontSize: 12.5, color: 'var(--muted)', marginTop: 12, padding: '8px 12px', background: 'var(--bg)', borderRadius: 8 }}>
                  {t('detail.nextSteps')}: <span className="mono">{nextSteps}</span>
                </p>
              )}
              {warnings.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ color: 'var(--warn)', fontSize: 12.5, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <AlertTriangle size={14} />
                    {t('detail.warnings')}
                  </div>
                  <ul className="meta-list" style={{ color: 'var(--warn)', paddingLeft: 18, margin: '4px 0 0 0', fontSize: 12.5 }}>
                    {warnings.map((w, i) => (
                      <li key={i}>{String(w)}</li>
                    ))}
                  </ul>
                </div>
              )}
              {errors.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ color: 'var(--err)', fontSize: 12.5, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <AlertOctagon size={14} />
                    {t('detail.errors')}
                  </div>
                  <ul className="meta-list" style={{ color: 'var(--err)', paddingLeft: 18, margin: '4px 0 0 0', fontSize: 12.5 }}>
                    {errors.map((e, i) => (
                      <li key={i}>{String(e)}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </div>

        <ArtifactBrowser
          runId={runId}
          running={running}
          intervalMs={3000}
          selected={selected}
          onSelect={setSelected}
        />
      </div>

      <div className="grid-bottom">
        <LogViewer
          key={runId}
          logFetcher={(offset, limit) => getLog(runId, offset, limit)}
          downloadUrl={logDownloadUrl(runId)}
          running={running}
          intervalMs={intervalMs}
        />
        <ArtifactViewer runId={runId} path={selected} />
      </div>
    </div>
  );
}

