import { useEffect, useState } from 'react';
import { Film, RefreshCw } from '../components/Icons';
import {
  buildJobLogDownloadUrl,
  artifactUrl,
  cancelBuildJob,
  getBuildJob,
  getBuildJobLog,
  getBuildStatus,
  mergeTtsChunks,
  getSubStyle,
  importPackImages,
  listRuns,
  putSubStyle,
  startBuild,
  cancelSrtJob,
  getSrtInputs,
  getSrtJob,
  getSrtJobLog,
  getSrtStatus,
  startSrtGenerate,
} from '../api';
import { LogViewer } from '../components/LogViewer';
import { usePolling } from '../hooks/usePolling';
import { useT } from '../i18n';
import { useChannelContext } from '../contexts/ChannelContext';
import type { BuildImportResult, BuildJob, SrtJob, SubStyle } from '../types';
import type { RunScope } from '../services/runsService';
import { formatDate } from '../utils';

const scopeForChannel = (channel: ReturnType<typeof useChannelContext>['currentChannel']): RunScope | null =>
  channel ? { user_id: channel.user_id, channel_id: channel.channel_id } : null;

const STATUS_INTERVAL_MS = 5000;
const JOB_INTERVAL_MS = 1500;

// Options faithful build-video.py.
const ANIMATIONS: ReadonlyArray<readonly [string, string]> = [
  ['none', 'build.option.animation.none'],
  ['zoom', 'build.option.animation.zoom'],
  ['zoom-out', 'build.option.animation.zoomOut'],
  ['pan-h', 'build.option.animation.panH'],
  ['pan-v', 'build.option.animation.panV'],
  ['auto', 'build.option.animation.auto'],
];

const RESOLUTIONS = ['1280x720', '1376x768', '1920x1080'];

// Copy SUB_DEFAULTS của youtube_pipeline/build-video.py — giữ đồng bộ thủ công.
const JP_FONTS = [
  'Hiragino Kaku Gothic Pro',
  'Hiragino Maru Gothic ProN',
  'Hiragino Mincho ProN',
  'Hiragino Sans',
];

const SUB_DEFAULTS: SubStyle = {
  font: 'Hiragino Kaku Gothic Pro',
  fontsize: 44,
  color: '#FFFFFF',
  outline: 3,
  outline_color: '#000000',
  shadow: 1,
  bold: false,
  position: 'bottom',
  margin_v: 36,
};

type PackFileKey = 'prompts_build' | 'marks_tsv';

const PACK_FILE_KEYS: ReadonlyArray<[PackFileKey, string]> = [
  ['prompts_build', 'build.pack.promptsBuild'],
  ['marks_tsv', 'build.pack.marksTsv'],
];

/**
 * Trang "Dựng video" (Flow 3): chọn run đã qua pipeline (dừng ở resource_pack),
 * xem còn thiếu gì (audio ghép / ảnh IMG-xx), import ảnh đã gen, chỉnh style
 * phụ đề, rồi Xem trước (dry-run) hoặc Ráp video — chạy build_service làm
 * subprocess, theo dõi job + log realtime.
 */
export function BuildPage() {
  const { t, lang } = useT();
  const { currentChannel, loading: channelLoading } = useChannelContext();
  const scope = scopeForChannel(currentChannel);
  const channelScope = currentChannel
    ? { user_id: currentChannel.user_id, channel_id: currentChannel.channel_id }
    : undefined;
  const channelScopeKey = channelScope ? `${channelScope.user_id}:${channelScope.channel_id}` : null;
  const scopeKey = scope ? `${scope.user_id}:${scope.channel_id}` : null;

  // Danh sách run để chọn, giới hạn trong channel đang chọn.
  const runsPoll = usePolling(() => (scope ? listRuns(scope) : Promise.resolve(null)), {
    enabled: scope !== null,
    intervalMs: STATUS_INTERVAL_MS,
  });
  const [runsScopeKey, setRunsScopeKey] = useState<string | null>(null);
  const runs = runsScopeKey === scopeKey ? runsPoll.data?.runs ?? [] : [];

  // Run đang xem (mặc định run mới nhất có resource_pack).
  const [runId, setRunId] = useState<string>('');
  useEffect(() => {
    let cancelled = false;
    setRunId('');
    setRunsScopeKey(null);
    if (!scopeKey) return () => { cancelled = true; };
    void runsPoll.refresh().then(() => {
      if (!cancelled) setRunsScopeKey(scopeKey);
    });
    return () => { cancelled = true; };
  }, [scopeKey, runsPoll.refresh]);
  useEffect(() => {
    if (runId === '' && runs.length > 0) {
      const packRuns = runs.filter((r) => r.has_manifest);
      setRunId((packRuns[0] ?? runs[0]).run_id);
    }
  }, [runs, runId]);

  // Trạng thái tài nguyên của run đang xem.
  const statusPoll = usePolling(() => getBuildStatus(runId, channelScope), {
    enabled: runId !== '' && scope !== null,
    intervalMs: STATUS_INTERVAL_MS,
  });

  if (channelLoading || !currentChannel) {
    return <div className="page"><div className="empty-state">{channelLoading ? 'Đang tải channel...' : 'Chưa có channel được đăng ký.'}</div></div>;
  }
  const status = statusPoll.data;

  // Job dựng đang theo dõi — kèm log live.
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<BuildJob | null>(null);
  const [jobError, setJobError] = useState<unknown>(null);
  const jobDone = job !== null && job.status !== 'running';
  const jobPoll = usePolling(() => getBuildJob(jobId ?? '', channelScope), {
    enabled: jobId !== null && !jobDone,
    intervalMs: JOB_INTERVAL_MS,
  });
  useEffect(() => {
    if (jobPoll.data) setJob(jobPoll.data);
    if (jobPoll.error) setJobError(jobPoll.error);
  }, [jobPoll.data, jobPoll.error]);

  // Options dựng (faithful GUI: animation dropdown + fade slider + dry-run).
  const [animation, setAnimation] = useState('zoom');
  const [fade, setFade] = useState('0.5');
  const [resolution, setResolution] = useState('1280x720');
  const [dryRun, setDryRun] = useState(false);
  const [subtitles, setSubtitles] = useState(false);
  const [render, setRender] = useState(true);
  const [logoCleanup, setLogoCleanup] = useState(false);
  const [logoMode, setLogoMode] = useState<'delogo' | 'blur'>('delogo');
  const [actionError, setActionError] = useState<string | null>(null);

  // SRT is generated from the selected run's script and narration audio.
  const srtStatusPoll = usePolling(() => getSrtStatus(channelScope), { enabled: scope !== null, intervalMs: STATUS_INTERVAL_MS * 2 });
  const srtInputsPoll = usePolling(() => getSrtInputs(runId, channelScope), { enabled: runId !== '' && scope !== null, intervalMs: STATUS_INTERVAL_MS });
  const [srtModel, setSrtModel] = useState('large-v3');
  const [srtDevice, setSrtDevice] = useState('cpu');
  const [srtMode, setSrtMode] = useState('accurate');
  const [srtMaxChars, setSrtMaxChars] = useState(24);
  const [srtJobId, setSrtJobId] = useState<string | null>(null);
  const [srtJob, setSrtJob] = useState<SrtJob | null>(null);
  const [srtError, setSrtError] = useState<string | null>(null);
  const srtRunning = srtJobId !== null && (srtJob === null || srtJob.status === 'running');
  const srtJobPoll = usePolling(() => getSrtJob(srtJobId ?? '', channelScope), { enabled: srtRunning && scope !== null, intervalMs: JOB_INTERVAL_MS });
  useEffect(() => {
    if (srtJobPoll.data) setSrtJob(srtJobPoll.data);
    if (srtJobPoll.error) setSrtError(String(srtJobPoll.error));
  }, [srtJobPoll.data, srtJobPoll.error]);

  // Style phụ đề — nạp từ server khi đổi run.
  const [subStyle, setSubStyle] = useState<SubStyle>(SUB_DEFAULTS);
  const [subLoaded, setSubLoaded] = useState(false);
  const [subSaved, setSubSaved] = useState(false);
  const [subError, setSubError] = useState<string | null>(null);
  useEffect(() => {
    if (runId === '') return;
    let cancelled = false;
    setSubLoaded(false);
    setSubSaved(false);
    setSubError(null);
    getSubStyle(runId, channelScope)
      .then((r) => {
        if (cancelled) return;
        setSubStyle({ ...SUB_DEFAULTS, ...r.style });
        setSubLoaded(true);
      })
      .catch((e) => {
        if (!cancelled) setSubError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [runId, channelScopeKey]);

  const doSaveSubStyle = async () => {
    if (!runId) return;
    setSubError(null);
    try {
      const r = await putSubStyle(runId, subStyle, channelScope);
      setSubStyle(r.style);
      setSubSaved(true);
    } catch (e) {
      setSubError(String(e));
    }
  };

  // Import ảnh đã gen — Xem map (apply=false) / Áp dụng đổi tên (apply=true).
  const [importDir, setImportDir] = useState('');
  const [importInsert, setImportInsert] = useState('');
  const [importBusy, setImportBusy] = useState(false);
  const [importResult, setImportResult] = useState<(BuildImportResult & { apply: boolean }) | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const doImport = async (apply: boolean) => {
    if (!runId || !importDir.trim()) {
      setImportError(t('build.import.noDir'));
      return;
    }
    if (apply && !window.confirm(t('build.import.applyConfirm'))) return;
    setImportBusy(true);
    setImportError(null);
    setImportResult(null);
    try {
      const r = await importPackImages(runId, {
        source_dir: importDir.trim(),
        ...(importInsert.trim() ? { insert: importInsert.trim() } : {}),
        apply,
      }, channelScope);
      setImportResult({ ...r, apply });
      if (apply && r.ok) void statusPoll.refresh();
    } catch (e) {
      setImportError(String(e));
    } finally {
      setImportBusy(false);
    }
  };

  const doStart = async (preview: boolean) => {
    setActionError(null);
    try {
      if (subtitles && !preview) await putSubStyle(runId, subStyle, channelScope);
      const parts = resolution.split('x').map((s) => Number(s.trim()));
      const body = {
        render: preview ? true : render,
        animation,
        ...(fade.trim() ? { transition: Number(fade) } : {}),
        ...(parts.length === 2 && parts.every((v) => Number.isFinite(v))
          ? { resolution: parts as [number, number] }
          : {}),
        dry_run: preview ? true : dryRun,
        ...(subtitles && !preview ? { subtitles: true } : {}),
        ...(logoCleanup ? { logo_cleanup: true, logo_mode: logoMode } : {}),
      };
      const r = await startBuild(runId, body, channelScope);
      setJobId(r.job_id);
      setJob(null);
      setJobError(null);
      void statusPoll.refresh();
    } catch (e) {
      setActionError(String(e));
    }
  };

  const doCancelJob = async () => {
    if (!jobId) return;
    if (!window.confirm(t('build.job.cancelConfirm'))) return;
    setActionError(null);
    try {
      await cancelBuildJob(jobId, channelScope);
      void statusPoll.refresh();
      void jobPoll.refresh();
    } catch (e) {
      setActionError(String(e));
    }
  };

  const doMergeTtsChunks = async () => {
    if (!runId) return;
    setActionError(null);
    try {
      await mergeTtsChunks(runId, channelScope);
      void statusPoll.refresh();
      void srtInputsPoll.refresh();
    } catch (e) {
      setActionError(String(e));
    }
  };

  const doStartSrt = async () => {
    if (!runId) return;
    setSrtError(null);
    try {
      const result = await startSrtGenerate(runId, { model: srtModel, device: srtDevice, mode: srtMode, max_chars: srtMaxChars }, channelScope);
      setSrtJobId(result.job_id);
      setSrtJob(null);
      void srtInputsPoll.refresh();
    } catch (e) {
      setSrtError(String(e));
    }
  };

  const doCancelSrt = async () => {
    if (!srtJobId) return;
    try {
      await cancelSrtJob(srtJobId, channelScope);
      void srtJobPoll.refresh();
    } catch (e) {
      setSrtError(String(e));
    }
  };

  const busy = Boolean(status?.busy);
  const ready = Boolean(status?.pack_ready);
  const jobRunning = jobId !== null && (job === null || job.status === 'running');
  const cannotStart = busy || !ready || runId === '';

  return (
    <div className="page">
      <div className="page-head">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Film className="text-primary" size={24} />
          <div>
            <h2>{t('build.title')}</h2>
            <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>
              Ráp video tự động từ ảnh, audio và cấu hình phụ đề
            </div>
          </div>
        </div>
        <div className="spacer" />
        <button
          type="button"
          className="btn"
          onClick={() => {
            void runsPoll.refresh();
            void statusPoll.refresh();
          }}
        >
          <RefreshCw size={14} />
          {t('build.refresh')}
        </button>
      </div>

      <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: -12, marginBottom: 20, maxWidth: 760 }}>
        {t('build.desc')}
      </p>

      {actionError && <div className="error-text" style={{ marginBottom: 16, padding: '10px 14px', background: 'rgba(239, 68, 68, 0.1)', borderRadius: 8 }}>{actionError}</div>}
      {Boolean(statusPoll.error) && (
        <div className="error-text" style={{ marginBottom: 16 }}>
          {String(statusPoll.error)}
        </div>
      )}
      {Boolean(jobError) && (
        <div className="error-text" style={{ marginBottom: 16 }}>{String(jobError)}</div>
      )}
      {srtError && <div className="error-text" style={{ marginBottom: 16 }}>{srtError}</div>}

      {/* ------------------------------------------------ chọn run + trạng thái */}
      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title">
          <span>{t('build.run')}</span>
          <span className="spacer" />
          {status &&
            (ready ? (
              <span className="badge badge-complete">{t('build.readyBadge')}</span>
            ) : (
              <span className="badge badge-unknown">{t('build.notReady')}</span>
            ))}
        </div>
        <div className="panel-body">
          {runs.length === 0 ? (
            <div className="empty-state">{t('build.run.none')}</div>
          ) : (
            <>
              <div className="form-row">
                <label htmlFor="build-run">{t('build.run')}</label>
                <select
                  id="build-run"
                  value={runId}
                  onChange={(e) => {
                    setRunId(e.target.value);
                    setJobId(null);
                    setJob(null);
                  }}
                  disabled={busy}
                >
                  {runs.map((r) => (
                    <option key={r.run_id} value={r.run_id}>
                      {r.run_id} — {r.topic || r.status}
                    </option>
                  ))}
                </select>
              </div>

              {!status ? (
                <div className="empty-state">Đang kiểm tra tài nguyên...</div>
              ) : (
                <>
                  {status.missing_reason && !ready && (
                    <div className="orphan-banner" style={{ marginTop: 12 }}>
                      <strong>{t('build.missingReason')}</strong> {status.missing_reason}
                    </div>
                  )}
                  {ready && (
                    <div className="orphan-banner" style={{ marginTop: 12, background: 'rgba(16, 185, 129, 0.12)', border: '1px solid rgba(16, 185, 129, 0.3)', color: 'var(--ok)' }}>
                      {t('build.ready')}
                    </div>
                  )}

                  <dl className="kv" style={{ marginTop: 14 }}>
                    <dt>{t('build.timeline')}</dt>
                    <dd>
                      {status.timeline_status === 'FINAL_TIMING'
                        ? t('build.timeline.final')
                        : status.timeline_status === 'DRAFT_TIMING'
                          ? t('build.timeline.draft')
                          : '—'}
                    </dd>
                    <dt>{t('build.sections')}</dt>
                    <dd>{status.sections_count ?? '—'}</dd>
                    <dt>{t('build.events')}</dt>
                    <dd>{status.events_count ?? '—'}</dd>
                    <dt>{t('build.images.count')}</dt>
                    <dd>{status.unique_images ?? '—'}</dd>
                  </dl>

                  {/* audio */}
                  <div className="form-row" style={{ marginTop: 14 }}>
                    <label style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{t('build.audio.title')}</label>
                    <span>
                      {status.audio_ready ? (
                        <span className="badge badge-complete">{t('build.audio.ready')}</span>
                      ) : (
                        <span className="badge badge-unknown">{t('build.audio.missing')}</span>
                      )}
                    </span>
                  </div>
                  {status.audio && (
                    <dl className="kv">
                      <dt>{t('build.audio.file')}</dt>
                      <dd className="mono">{status.audio.file}</dd>
                      <dt>{t('build.audio.duration')}</dt>
                      <dd>{status.audio.duration_seconds != null ? `${status.audio.duration_seconds.toFixed(1)}s` : '—'}</dd>
                      {status.audio.measured_cpm != null && (
                        <>
                          <dt>{t('build.audio.cpm')}</dt>
                          <dd>{status.audio.measured_cpm}</dd>
                        </>
                      )}
                    </dl>
                  )}
                  {status.tts_chunks.available && !status.audio_ready && (
                    <div style={{ marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
                      <div className="form-row">
                        <label style={{ fontWeight: 600, color: 'var(--text-heading)' }}>TTS chunks</label>
                        <span className={`badge ${status.tts_chunks.generated === status.tts_chunks.total ? 'badge-complete' : 'badge-unknown'}`}>
                          {status.tts_chunks.generated}/{status.tts_chunks.total}
                        </span>
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                        {status.tts_chunks.chunks.map((chunk) => (
                          <a key={chunk.id} className="btn btn-ghost" style={{ padding: '3px 8px', fontSize: 12 }} href={artifactUrl(runId, chunk.path, true, scope ?? undefined)}>
                            {chunk.id} · {chunk.chars.toLocaleString()} ký tự
                          </a>
                        ))}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 9 }}>
                        <span style={{ fontSize: 12, color: 'var(--muted)' }}>Audio: audio/chunks/001.mp3 ...</span>
                        <button type="button" className="btn btn-secondary" onClick={() => void doMergeTtsChunks()} disabled={status.tts_chunks.generated !== status.tts_chunks.total}>
                          Ghép audio chunks
                        </button>
                      </div>
                    </div>
                  )}

                  {/* ảnh */}
                  <div className="form-row" style={{ marginTop: 14 }}>
                    <label style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{t('build.images.title')}</label>
                    <span>
                      {status.images_ready ? (
                        <span className="badge badge-complete">{t('build.images.ready')}</span>
                      ) : (
                        <span className="badge badge-unknown">{t('build.images.missing')}</span>
                      )}
                    </span>
                  </div>
                  {status.images.missing.length > 0 && (
                    <p style={{ fontSize: 12.5, color: 'var(--muted)', marginTop: 4 }}>
                      {status.images.missing.slice(0, 12).join(', ')}
                      {status.images.missing.length > 12 ? ` … (+${status.images.missing.length - 12})` : ''}
                      {' — '}
                      {status.images.present}/{status.unique_images} {t('build.images.present')}
                    </p>
                  )}

                  {/* pack files */}
                  {status.pack_files && (
                    <div className="form-row" style={{ marginTop: 14, alignItems: 'flex-start' }}>
                      <label style={{ paddingTop: 2, fontWeight: 600, color: 'var(--text-heading)' }}>{t('build.pack.files')}</label>
                      <span>
                        {PACK_FILE_KEYS.map(([key, labelKey]) => (
                          <span key={key} style={{ display: 'inline-block', marginRight: 12, whiteSpace: 'nowrap' }}>
                            <span className={`badge ${status.pack_files[key] ? 'badge-complete' : 'badge-unknown'}`}>
                              {status.pack_files[key] ? '✓' : '✗'}
                            </span>{' '}
                            <span className="mono">{t(labelKey)}</span>
                          </span>
                        ))}
                      </span>
                    </div>
                  )}

                  {/* pack + video */}
                  <dl className="kv" style={{ marginTop: 12 }}>
                    <dt>{t('build.pack.title')}</dt>
                    <dd>
                      {status.pack_ready ? (
                        <span className="badge badge-complete">{t('build.pack.ready')}</span>
                      ) : (
                        <span className="badge badge-unknown">{t('build.pack.waiting')}</span>
                      )}
                    </dd>
                    <dt>{t('build.video.title')}</dt>
                    <dd>
                      {status.video_ready ? (
                        <span className="badge badge-complete">{t('build.video.ready')}</span>
                      ) : (
                        <span className="badge badge-unknown">{t('build.video.missing')}</span>
                      )}
                    </dd>
                    <dt>{t('build.tool')}</dt>
                    <dd className="mono">{status.tool.build_video_script}</dd>
                  </dl>
                </>
              )}
            </>
          )}
        </div>
      </div>

      {/* ------------------------------------------------ gen SRT */}
      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title">
          <span>{t('srt.title')}</span>
          <span className="spacer" />
          {srtInputsPoll.data?.srt_exists && <span className="badge badge-complete">{t('srt.ready')}</span>}
        </div>
        <div className="panel-body">
          <p style={{ fontSize: 13, color: 'var(--muted)', marginTop: 0 }}>{t('srt.desc')}</p>
          {runId === '' ? <div className="empty-state">{t('build.run.none')}</div> : (
            <>
              <div className="toolbar" style={{ flexWrap: 'wrap', gap: 12 }}>
                <span className={`badge ${srtInputsPoll.data?.script_exists ? 'badge-complete' : 'badge-unknown'}`}>
                  {srtInputsPoll.data?.script_exists ? `✓ ${t('srt.script')}` : `✗ ${t('srt.scriptMissing')}`}
                </span>
                <span className={`badge ${srtInputsPoll.data?.audio_exists ? 'badge-complete' : 'badge-unknown'}`}>
                  {srtInputsPoll.data?.audio_exists ? `✓ ${t('srt.audio')}` : `✗ ${t('srt.audioMissing')}`}
                </span>
                {srtInputsPoll.data?.srt_exists && <span className="mono" style={{ fontSize: 12 }}>{srtInputsPoll.data.srt_path}</span>}
              </div>
              <div className="toolbar" style={{ flexWrap: 'wrap', gap: 14, alignItems: 'flex-end', marginTop: 14 }}>
                <div className="form-row" style={{ marginBottom: 0 }}>
                  <label htmlFor="srt-model">{t('srt.model')}</label>
                  <select id="srt-model" value={srtModel} onChange={(e) => setSrtModel(e.target.value)} disabled={srtRunning}>
                    {(srtStatusPoll.data?.models ?? ['large-v3']).map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                </div>
                <div className="form-row" style={{ marginBottom: 0 }}>
                  <label htmlFor="srt-device">{t('srt.device')}</label>
                  <select id="srt-device" value={srtDevice} onChange={(e) => setSrtDevice(e.target.value)} disabled={srtRunning}>
                    {(srtStatusPoll.data?.devices ?? ['cpu']).map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                </div>
                <div className="form-row" style={{ marginBottom: 0 }}>
                  <label htmlFor="srt-mode">{t('srt.mode')}</label>
                  <select id="srt-mode" value={srtMode} onChange={(e) => setSrtMode(e.target.value)} disabled={srtRunning}>
                    <option value="accurate">{t('srt.accurate')}</option>
                    <option value="fast">{t('srt.fast')}</option>
                  </select>
                </div>
                <div className="form-row" style={{ marginBottom: 0 }}>
                  <label htmlFor="srt-max-chars">{t('srt.maxChars')}</label>
                  <input id="srt-max-chars" type="number" min={8} max={50} value={srtMaxChars} onChange={(e) => setSrtMaxChars(Number(e.target.value))} disabled={srtRunning} style={{ width: 80 }} />
                </div>
              </div>
              {!srtStatusPoll.data?.sdk_ready && <p className="error-text" style={{ marginBottom: 8 }}>{t('srt.noSdk')}</p>}
              {srtMode === 'accurate' && srtStatusPoll.data && !srtStatusPoll.data.accurate_ready && <p className="error-text" style={{ marginBottom: 8 }}>{t('srt.noAccurate')}</p>}
              <div className="toolbar" style={{ marginTop: 14 }}>
                <button type="button" className="btn btn-primary" onClick={() => void doStartSrt()} disabled={srtRunning || !srtInputsPoll.data?.script_exists || !srtInputsPoll.data?.audio_exists || !srtStatusPoll.data?.sdk_ready || (srtMode === 'accurate' && !srtStatusPoll.data?.accurate_ready)}>
                  {srtRunning ? t('srt.running') : t('srt.generate')}
                </button>
                {srtRunning && <button type="button" className="btn btn-danger" onClick={() => void doCancelSrt()}>{t('srt.cancel')}</button>}
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>{t('srt.output')}</span>
              </div>
            </>
          )}
        </div>
      </div>

      {srtJobId !== null && <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title"><span>{t('srt.log')}</span><span className="spacer" /><span className={`badge badge-${srtJob?.status ?? 'running'}`}>{t(`srt.${srtJob?.status ?? 'running'}`)}</span></div>
        <LogViewer logFetcher={(offset, limit) => getSrtJobLog(srtJobId, offset, limit, channelScope)} running={srtRunning} intervalMs={JOB_INTERVAL_MS} />
      </div>}

      {/* ------------------------------------------------ báo cáo gần nhất */}
      {status?.last_report && (
        <div className="panel" style={{ marginBottom: 20 }}>
          <div className="panel-title">
            <span>{t('build.lastReport')}</span>
          </div>
          <div className="panel-body">
            <dl className="kv">
              <dt>{t('build.lastReport.status')}</dt>
              <dd className="mono">{status.last_report.status ?? '—'}</dd>
              <dt>{t('build.lastReport.generatedAt')}</dt>
              <dd>{formatDate(status.last_report.generated_at, lang)}</dd>
              {status.last_report.error && (
                <>
                  <dt>{t('build.lastReport.error')}</dt>
                  <dd className="mono" style={{ color: 'var(--err)' }}>{status.last_report.error}</dd>
                </>
              )}
              {status.last_report.next_step && (
                <>
                  <dt>{t('build.lastReport.nextStep')}</dt>
                  <dd>{status.last_report.next_step}</dd>
                </>
              )}
            </dl>
          </div>
        </div>
      )}

      {/* ------------------------------------------------ import ảnh đã gen */}
      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title">
          <span>{t('build.import.title')}</span>
        </div>
        <div className="panel-body">
          <div className="form-row">
            <label htmlFor="import-dir">{t('build.import.dir')}</label>
            <input
              id="import-dir"
              type="text"
              value={importDir}
              onChange={(e) => setImportDir(e.target.value)}
              placeholder="/path/to/gen-images"
              className="mono"
              disabled={busy || importBusy}
              style={{ flex: 1, minWidth: 200 }}
            />
          </div>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
            {t('build.import.dirHint')}
          </p>
          <div className="form-row" style={{ marginTop: 12 }}>
            <label htmlFor="import-insert">{t('build.import.insert')}</label>
            <input
              id="import-insert"
              type="text"
              value={importInsert}
              onChange={(e) => setImportInsert(e.target.value)}
              placeholder="IMG-12:ten_file"
              className="mono"
              disabled={busy || importBusy}
              style={{ width: 240 }}
            />
          </div>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
            {t('build.import.insertHint')}
          </p>
          <div className="toolbar" style={{ marginTop: 14 }}>
            <button
              type="button"
              className="btn"
              onClick={() => void doImport(false)}
              disabled={busy || importBusy}
            >
              {t('build.import.preview')}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void doImport(true)}
              disabled={busy || importBusy}
            >
              {t('build.import.apply')}
            </button>
            {importBusy && <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>{t('build.import.applying')}</span>}
          </div>

          {importError && <div className="error-text" style={{ marginTop: 12 }}>{importError}</div>}
          {importResult && (
            <div style={{ marginTop: 14 }}>
              {importResult.ok && importResult.apply === false && (
                <p style={{ fontSize: 12.5, color: 'var(--muted)', margin: '0 0 6px' }}>
                  {t('build.import.preview')}
                </p>
              )}
              {importResult.mapping.length > 0 && (
                <table style={{ borderCollapse: 'collapse', fontSize: 12.5, width: '100%' }}>
                  <thead>
                    <tr style={{ textAlign: 'left', color: 'var(--muted)' }}>
                      <th style={{ padding: '4px 14px 4px 0' }}>IMG</th>
                      <th style={{ padding: '4px 0' }}>← file</th>
                    </tr>
                  </thead>
                  <tbody>
                    {importResult.mapping.map((m) => (
                      <tr key={m.img}>
                        <td className="mono" style={{ padding: '4px 14px 4px 0', color: 'var(--accent)' }}>{m.img}</td>
                        <td className="mono" style={{ padding: '4px 0' }}>{m.file}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {importResult.extra > 0 && (
                <p style={{ fontSize: 12.5, color: 'var(--muted)', margin: '6px 0 0' }}>
                  {importResult.extra} {t('build.import.extra')}
                </p>
              )}
              {importResult.ok ? (
                <p style={{ fontSize: 13, color: 'var(--ok)', margin: '8px 0 0', fontWeight: 600 }}>
                  {t('build.import.done')}
                </p>
              ) : (
                <div className="error-text" style={{ marginTop: 8 }}>
                  {importResult.error ?? t('build.import.fail')}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ------------------------------------------------ options + nút chạy */}
      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title">
          <span>{t('build.build.title')}</span>
        </div>
        <div className="panel-body">
          <div className="toolbar" style={{ flexWrap: 'wrap', gap: 20 }}>
            <div className="form-row" style={{ marginBottom: 0 }}>
              <label htmlFor="build-animation">{t('build.option.animation')}</label>
              <select
                id="build-animation"
                value={animation}
                onChange={(e) => setAnimation(e.target.value)}
                disabled={busy}
              >
                {ANIMATIONS.map(([value, labelKey]) => (
                  <option key={value} value={value}>{t(labelKey)}</option>
                ))}
              </select>
            </div>
            <div className="form-row" style={{ marginBottom: 0 }}>
              <label htmlFor="build-fade">{t('build.option.fade')}</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <input
                  id="build-fade"
                  type="range"
                  min={0}
                  max={0.5}
                  step={0.05}
                  value={fade}
                  onChange={(e) => setFade(e.target.value)}
                  disabled={busy}
                  style={{ width: 140 }}
                />
                <span className="mono" style={{ width: 48, textAlign: 'right', fontWeight: 600 }}>
                  {Number(fade).toFixed(2)}s
                </span>
              </div>
            </div>
            <div className="form-row" style={{ marginBottom: 0 }}>
              <label htmlFor="build-resolution">{t('build.build.resolution')}</label>
              <select
                id="build-resolution"
                value={resolution}
                onChange={(e) => setResolution(e.target.value)}
                disabled={busy}
                className="mono"
              >
                {RESOLUTIONS.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>
          </div>

          <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={dryRun}
                onChange={(e) => setDryRun(e.target.checked)}
                disabled={busy}
              />
              {t('build.option.dryRun')}
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={subtitles}
                onChange={(e) => setSubtitles(e.target.checked)}
                disabled={busy}
              />
              {t('build.option.subtitles')}
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={logoCleanup} onChange={(e) => setLogoCleanup(e.target.checked)} disabled={busy} />
              Xóa logo góc phải dưới
            </label>
            {logoCleanup && <div className="form-row" style={{ marginBottom: 0 }}>
              <label htmlFor="build-logo-mode">Phương pháp</label>
              <select id="build-logo-mode" value={logoMode} onChange={(e) => setLogoMode(e.target.value as 'delogo' | 'blur')} disabled={busy}>
                <option value="delogo">Delogo (xóa nội suy)</option>
                <option value="blur">Blur vùng logo</option>
              </select>
            </div>}
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={render}
                onChange={(e) => setRender(e.target.checked)}
                disabled={busy}
              />
              {t('build.build.render')}
            </label>
          </div>
          <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6, marginBottom: 16 }}>
            {t('build.build.render.hint')}
          </p>

          {!ready && status && <div className="error-text" style={{ marginBottom: 12 }}>{t('build.build.needAssets')}</div>}
          {busy && <div className="error-text" style={{ marginBottom: 12 }}>{t('build.build.busy')}</div>}

          <div className="toolbar" style={{ gap: 12 }}>
            <button
              type="button"
              className="btn"
              onClick={() => void doStart(true)}
              disabled={cannotStart}
            >
              {t('build.preview')}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void doStart(false)}
              disabled={cannotStart}
            >
              {t('build.buildNow')}
            </button>
          </div>
        </div>
      </div>

      {/* ------------------------------------------------ style phụ đề (CapCut) */}
      {subtitles && (
        <div className="panel" style={{ marginBottom: 20 }}>
          <div className="panel-title">
            <span>{t('build.style.title')}</span>
            <span className="spacer" />
            {subSaved && <span style={{ fontSize: 12.5, color: 'var(--ok)', fontWeight: 600 }}>{t('build.style.saved')}</span>}
          </div>
          <div className="panel-body">
            {subError && <div className="error-text" style={{ marginBottom: 12 }}>{subError}</div>}
            <div className="toolbar" style={{ flexWrap: 'wrap', gap: 16, alignItems: 'flex-end' }}>
              <div className="form-row" style={{ marginBottom: 0 }}>
                <label htmlFor="sub-font">{t('build.style.font')}</label>
                <select
                  id="sub-font"
                  value={subStyle.font}
                  onChange={(e) => setSubStyle({ ...subStyle, font: e.target.value as SubStyle['font'] })}
                  disabled={busy}
                >
                  {JP_FONTS.map((f) => (
                    <option key={f} value={f} style={{ fontFamily: f }}>{f}</option>
                  ))}
                </select>
              </div>
              <div className="form-row" style={{ marginBottom: 0 }}>
                <label htmlFor="sub-fontsize">{t('build.style.fontsize')}</label>
                <input
                  id="sub-fontsize"
                  type="number"
                  min={28}
                  max={80}
                  value={subStyle.fontsize}
                  onChange={(e) => setSubStyle({ ...subStyle, fontsize: Number(e.target.value) })}
                  disabled={busy}
                  style={{ width: 80 }}
                />
              </div>
              <div className="form-row" style={{ marginBottom: 0 }}>
                <label htmlFor="sub-color">{t('build.style.color')}</label>
                <input
                  id="sub-color"
                  type="text"
                  value={subStyle.color}
                  onChange={(e) => setSubStyle({ ...subStyle, color: e.target.value })}
                  disabled={busy}
                  className="mono"
                  style={{ width: 100 }}
                  placeholder="#FFFFFF"
                />
              </div>
              <label className="checkbox-row" style={{ marginBottom: 4 }}>
                <input
                  type="checkbox"
                  checked={subStyle.bold}
                  onChange={(e) => setSubStyle({ ...subStyle, bold: e.target.checked })}
                  disabled={busy}
                />
                {t('build.style.bold')}
              </label>
            </div>

            <div className="toolbar" style={{ flexWrap: 'wrap', gap: 16, alignItems: 'flex-end', marginTop: 12 }}>
              <div className="form-row" style={{ marginBottom: 0 }}>
                <label htmlFor="sub-outline">{t('build.style.outline')}</label>
                <input
                  id="sub-outline"
                  type="number"
                  min={0}
                  max={6}
                  value={subStyle.outline}
                  onChange={(e) => setSubStyle({ ...subStyle, outline: Number(e.target.value) })}
                  disabled={busy}
                  style={{ width: 80 }}
                />
              </div>
              <div className="form-row" style={{ marginBottom: 0 }}>
                <label htmlFor="sub-outline-color">{t('build.style.outlineColor')}</label>
                <input
                  id="sub-outline-color"
                  type="text"
                  value={subStyle.outline_color}
                  onChange={(e) => setSubStyle({ ...subStyle, outline_color: e.target.value })}
                  disabled={busy}
                  className="mono"
                  style={{ width: 100 }}
                  placeholder="#000000"
                />
              </div>
              <div className="form-row" style={{ marginBottom: 0 }}>
                <label htmlFor="sub-shadow">{t('build.style.shadow')}</label>
                <input
                  id="sub-shadow"
                  type="number"
                  min={0}
                  max={5}
                  value={subStyle.shadow}
                  onChange={(e) => setSubStyle({ ...subStyle, shadow: Number(e.target.value) })}
                  disabled={busy}
                  style={{ width: 80 }}
                />
              </div>
              <div className="form-row" style={{ marginBottom: 0 }}>
                <label htmlFor="sub-position">{t('build.style.position')}</label>
                <select
                  id="sub-position"
                  value={subStyle.position}
                  onChange={(e) => setSubStyle({ ...subStyle, position: e.target.value as SubStyle['position'] })}
                  disabled={busy}
                >
                  <option value="bottom">{t('build.style.position.bottom')}</option>
                  <option value="top">{t('build.style.position.top')}</option>
                  <option value="middle">{t('build.style.position.middle')}</option>
                </select>
              </div>
            </div>

            {/* Preview Subtitle */}
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8, fontWeight: 500 }}>{t('build.style.preview')}</div>
              <div
                style={{
                  background: 'repeating-linear-gradient(45deg, #12151e, #12151e 10px, #1a1e2b 10px, #1a1e2b 20px)',
                  borderRadius: 10,
                  border: '1px solid var(--border)',
                  padding: '24px 16px',
                  textAlign: subStyle.position === 'middle' ? 'center' : 'left',
                  display: 'flex',
                  alignItems: subStyle.position === 'top' ? 'flex-start' : subStyle.position === 'middle' ? 'center' : 'flex-end',
                  justifyContent: 'center'
                }}
              >
                <span
                  style={{
                    fontFamily: `'${subStyle.font}', 'Hiragino Kaku Gothic Pro', sans-serif`,
                    fontSize: Math.min(subStyle.fontsize, 48),
                    color: subStyle.color,
                    fontWeight: subStyle.bold ? 700 : 400,
                    textShadow: subStyle.shadow > 0 ? `0 ${subStyle.shadow}px ${subStyle.shadow}px rgba(0,0,0,0.85)` : undefined,
                    WebkitTextStroke: subStyle.outline > 0 ? `${subStyle.outline}px ${subStyle.outline_color}` : undefined,
                  }}
                >
                  テスト字幕 Preview Text
                </span>
              </div>
            </div>

            <div className="toolbar" style={{ marginTop: 16, gap: 12 }}>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setSubStyle({ ...SUB_DEFAULTS });
                  setSubSaved(false);
                }}
                disabled={busy}
              >
                {t('build.style.reset')}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void doSaveSubStyle()}
                disabled={busy || !subLoaded || !subStyle}
              >
                {t('build.style.save')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ------------------------------------------------ job đang theo dõi */}
      {jobId !== null && (
        <div className="panel" style={{ marginBottom: 20 }}>
          <div className="panel-title">
            {job ? (
              <span className={`badge badge-${job.status}`}>{t(`build.job.${job.status}`)}</span>
            ) : (
              <span className="badge badge-running">{t('build.job.running')}</span>
            )}
            <span className="spacer" />
            {jobRunning && (
              <button type="button" className="btn btn-danger" onClick={() => void doCancelJob()}>
                {t('build.job.cancel')}
              </button>
            )}
          </div>
          <LogViewer
            logFetcher={(offset, limit) => getBuildJobLog(jobId, offset, limit, channelScope)}
            downloadUrl={buildJobLogDownloadUrl(jobId, channelScope)}
            running={jobRunning}
            intervalMs={JOB_INTERVAL_MS}
          />
        </div>
      )}
    </div>
  );
}
