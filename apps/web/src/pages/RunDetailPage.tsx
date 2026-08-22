import { useEffect, useMemo, useState } from 'react';
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
} from '../components/Icons';
import {
  ApiError,
  artifactUrl,
  cancelRun,
  getConfig,
  getRunDiagnostics,
  getLog,
  getRun,
  getRunStatus,
  logDownloadUrl,
  updateTopicStatus,
} from '../api';
import { connectRunEvents } from '../services/runsService';
import type { RunDiagnostics, RunStatus } from '../types';
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

function formatElapsed(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.floor(Number(seconds ?? 0)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours > 0
    ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
    : `${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

function liveElapsed(startedAt: string | null, persisted: number | null | undefined, finished: boolean): number {
  if (finished || !startedAt) return Number(persisted ?? 0);
  const start = Date.parse(startedAt);
  if (!Number.isFinite(start)) return Number(persisted ?? 0);
  return Math.max(0, (Date.now() - start) / 1000);
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
  const [sseConnected, setSseConnected] = useState(false);
  const [streamStatus, setStreamStatus] = useState<RunStatus | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [selected, setSelected] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

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
    enabled: detail !== null && !finished && !sseConnected,
    intervalMs: Math.max(intervalMs, 5000),
  });
  const diagnosticsPoll = usePolling(() => getRunDiagnostics(runId), {
    enabled: detail !== null,
    intervalMs: finished ? 60000 : 5000,
  });

  useEffect(() => {
    if (!detail || finished) {
      setSseConnected(false);
      return;
    }
    const source = connectRunEvents(
      runId,
      (event) => {
        setSseConnected(true);
        const nextStatus: RunStatus = event;
        setStreamStatus(nextStatus);
        setFinished(nextStatus.finished);
        if (event.state) {
          setDetail((current) => current ? { ...current, state: event.state! } : current);
        }
      },
      () => setSseConnected(true),
      () => setSseConnected(false),
    );
    return () => {
      source.close();
      setSseConnected(false);
    };
  }, [detail?.run_id, finished, runId]);

  useEffect(() => {
    if (finished) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [finished]);

  useEffect(() => {
    if (statusPoll.data?.finished) setFinished(true);
  }, [statusPoll.data]);

  const running = !finished;
  const status = streamStatus ?? statusPoll.data;
  const effectiveStatus = streamStatus ?? statusPoll.data;
  const executionSeconds = useMemo(() => {
    if (effectiveStatus) {
      return liveElapsed(effectiveStatus.execution_started_at, effectiveStatus.execution_elapsed_seconds, effectiveStatus.finished);
    }
    return liveElapsed(
      detail?.state.execution_started_at ?? null,
      detail?.state.execution_elapsed_seconds ?? 0,
      finished,
    );
  }, [effectiveStatus, detail?.state.execution_started_at, detail?.state.execution_elapsed_seconds, finished, now]);
  const totalSeconds = useMemo(() => {
    const persisted = Number(effectiveStatus?.total_elapsed_seconds ?? detail?.state.total_elapsed_seconds ?? 0);
    if (finished) return persisted;
    const started = effectiveStatus?.execution_started_at ?? detail?.state.execution_started_at ?? null;
    const current = liveElapsed(started, effectiveStatus?.execution_elapsed_seconds ?? detail?.state.execution_elapsed_seconds ?? 0, false);
    const previous = Math.max(0, persisted - Number(effectiveStatus?.execution_elapsed_seconds ?? detail?.state.execution_elapsed_seconds ?? 0));
    return previous + current;
  }, [effectiveStatus, detail?.state, finished, now]);
  const orphaned = running && (Boolean(status?.orphaned) || Boolean(detail?.orphaned));

  const refreshAll = () => {
    void detailPoll.refresh();
    void statusPoll.refresh();
    void diagnosticsPoll.refresh();
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

  const markPublished = async () => {
    if (!window.confirm('Đánh dấu topic này đã xuất bản? Các run sau sẽ chặn topic trùng mạnh hơn.')) return;
    setActionError(null);
    try {
      await updateTopicStatus(runId, 'published');
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
  const timelineStatus = strField(detail.manifest, 'timeline_status');
  const nextSteps = strField(detail.manifest, 'manual_next_steps');
  const warnings = detail.state.warnings ?? [];
  const errors = detail.state.errors ?? [];
  const diagnostics: RunDiagnostics | null = diagnosticsPoll.data;
  const routingProfiles = diagnostics?.routing_snapshot?.profiles;
  const calls = diagnostics?.model_calls.calls ?? [];

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
            setStreamStatus(null);
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

      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-body" style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.6 }}>Run time</div>
            <div className="mono" style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-heading)' }}>{formatElapsed(executionSeconds)}</div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.6 }}>Total</div>
            <div className="mono" style={{ fontSize: 18, fontWeight: 600 }}>{formatElapsed(totalSeconds)}</div>
          </div>
          <div className="spacer" />
          <span className={sseConnected ? 'badge badge-passed' : 'badge badge-running'}>
            {sseConnected ? 'LIVE · realtime' : 'SYNC · fallback polling'}
          </span>
        </div>
      </div>

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
                {finished && (
                  <button type="button" className="btn btn-ghost" onClick={() => void markPublished()}>
                    Đánh dấu đã xuất bản
                  </button>
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

          <div className="panel" style={{ marginTop: 20 }}>
            <div className="panel-title">
              <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Info size={16} style={{ color: 'var(--accent)' }} />
                <span>Run diagnostics</span>
              </span>
              <span className={diagnostics?.indexed ? 'badge badge-passed' : 'badge badge-running'}>
                {diagnostics?.indexed ? 'SQLite index' : 'run_state fallback'}
              </span>
            </div>
            <div className="panel-body">
              {!diagnostics ? (
                <div style={{ color: 'var(--muted)', fontSize: 13 }}>Đang tải diagnostics...</div>
              ) : (
                <>
                  <div className="kv" style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px 14px', marginBottom: 12 }}>
                    <span style={{ color: 'var(--muted)' }}>Model calls</span>
                    <span className="mono">{diagnostics.model_calls.total} · {Math.round(diagnostics.model_calls.duration_ms)} ms</span>
                    <span style={{ color: 'var(--muted)' }}>Failed calls</span>
                    <span className="mono" style={{ color: diagnostics.model_calls.failed ? 'var(--err)' : undefined }}>{diagnostics.model_calls.failed}</span>
                  </div>
                  {routingProfiles && typeof routingProfiles === 'object' && (
                    <details>
                      <summary style={{ cursor: 'pointer', fontSize: 13, color: 'var(--text-heading)' }}>Routing snapshot đã khóa</summary>
                      <pre style={{ margin: '8px 0 0', maxHeight: 180, overflow: 'auto', fontSize: 11.5 }}>{JSON.stringify(routingProfiles, null, 2)}</pre>
                    </details>
                  )}
                  {calls.length > 0 && (
                    <div style={{ marginTop: 12, maxHeight: 230, overflow: 'auto' }}>
                      {calls.map((call, index) => (
                        <div key={`${call.label}-${call.started_at}-${index}`} style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 8, padding: '7px 0', borderTop: '1px solid var(--border)', fontSize: 12 }}>
                          <div>
                            <span className="mono">{call.label}</span>
                            <span style={{ color: 'var(--muted)' }}> · {call.provider} / {call.model} · T {call.temperature}</span>
                            {call.error_type && <span style={{ color: 'var(--err)' }}> · {call.error_type}</span>}
                          </div>
                          <span className={call.status === 'failed' ? 'badge badge-failed' : 'badge badge-passed'}>{call.duration_ms === null ? 'running' : `${Math.round(call.duration_ms)} ms`}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
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
