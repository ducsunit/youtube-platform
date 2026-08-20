import { useEffect, useMemo, useState } from 'react';
import { Video, Sparkles, Film, CheckSquare, Square } from '../components/Icons';
import {
  ApiError,
  artifactUrl,
  cancelVeoJob,
  getVeoCandidates,
  getVeoJob,
  getVeoJobLog,
  getVeoStatus,
  listRuns,
  startVeoGenerate,
} from '../api';
import { LogViewer } from '../components/LogViewer';
import { usePolling } from '../hooks/usePolling';
import { useT } from '../i18n';
import type { VeoJob } from '../types';

const STATUS_INTERVAL_MS = 8000;
const JOB_INTERVAL_MS = 3000;
const MAX_PER_JOB = 20;

function errMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as { message?: string } | string;
    if (typeof d === 'string') return d;
    if (d && typeof d === 'object' && d.message) return d.message;
  }
  return e instanceof Error ? e.message : String(e);
}

function fmtBytes(n: number | null): string {
  if (n === null) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Trang "Gen video" — gọi Google Veo API (image-to-video) cho ảnh đã gen của
 * một run. Nguồn ảnh + prompt lấy từ chính run (visuals/prompts/prompts-video.txt
 * + video-build/images/), clip ghi ra video-build/clips/IMG-xx.mp4 để engine
 * dựng video ưu tiên dùng. Không gen âm thanh.
 */
export function VideoGenPage() {
  const { t } = useT();

  const veoPoll = usePolling(() => getVeoStatus(), {
    enabled: true,
    intervalMs: STATUS_INTERVAL_MS,
  });
  const veo = veoPoll.data;

  const runsPoll = usePolling(() => listRuns(), {
    enabled: true,
    intervalMs: STATUS_INTERVAL_MS,
  });
  const runs = runsPoll.data?.runs ?? [];

  const [runId, setRunId] = useState<string>('');
  useEffect(() => {
    if (runId === '' && runs.length > 0) {
      const packRuns = runs.filter((r) => r.has_manifest);
      setRunId((packRuns[0] ?? runs[0]).run_id);
    }
  }, [runs, runId]);

  const candPoll = usePolling(() => getVeoCandidates(runId), {
    enabled: runId !== '',
    intervalMs: STATUS_INTERVAL_MS,
  });
  const cand = candPoll.data;
  const candidates = cand?.candidates ?? [];

  const [model, setModel] = useState<string>('');
  useEffect(() => {
    if (model === '' && veo?.default_model) setModel(veo.default_model);
  }, [veo, model]);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  useEffect(() => {
    setSelected(new Set());
  }, [runId]);

  const [skipExisting, setSkipExisting] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);

  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<VeoJob | null>(null);
  const jobDone = job !== null && job.status !== 'running';
  const jobRunning = jobId !== null && !jobDone;
  const jobPoll = usePolling(() => getVeoJob(jobId ?? ''), {
    enabled: jobId !== null && !jobDone,
    intervalMs: JOB_INTERVAL_MS,
  });
  useEffect(() => {
    if (jobPoll.data) setJob(jobPoll.data);
  }, [jobPoll.data]);

  // Job xong → refresh ứng viên để thấy clip mới xuất hiện.
  useEffect(() => {
    if (jobDone) void candPoll.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobDone]);

  const available = candidates.filter((c) => c.image_exists);
  const selectedList = useMemo(
    () => candidates.filter((c) => selected.has(c.index)).map((c) => c.index),
    [candidates, selected],
  );

  const toggle = (index: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });

  const selectAll = () => setSelected(new Set(available.map((c) => c.index)));
  const selectNone = () => setSelected(new Set());
  const selectMissing = () =>
    setSelected(new Set(available.filter((c) => !c.clip_exists).map((c) => c.index)));

  async function doGenerate() {
    setActionError(null);
    if (selectedList.length === 0) return;
    try {
      const started = await startVeoGenerate(runId, {
        images: selectedList,
        model: model || undefined,
        skip_existing: skipExisting,
      });
      setJobId(started.job_id);
      setJob(null);
    } catch (e) {
      setActionError(errMessage(e));
    }
  }

  async function doCancel() {
    if (!jobId) return;
    try {
      await cancelVeoJob(jobId);
    } catch (e) {
      setActionError(errMessage(e));
    }
  }

  const canGenerate =
    (veo?.available ?? false) &&
    runId !== '' &&
    selectedList.length > 0 &&
    selectedList.length <= MAX_PER_JOB &&
    !jobRunning &&
    !(veo?.busy ?? false);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{t('veo.title')}</h2>
          <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>
            Tạo chuyển động video AI với Google Veo (Image-to-Video) cho các hình ảnh trong pipeline
          </div>
        </div>
      </div>
      <p className="veo-desc" style={{ marginTop: -12, marginBottom: 20 }}>{t('veo.desc')}</p>

      {veo && !veo.has_api_key && <div className="orphan-banner">{t('veo.noKey')}</div>}
      {veo && veo.has_api_key && !veo.sdk_ready && (
        <div className="orphan-banner">{t('veo.noSdk')}</div>
      )}

      {/* -------------------------------------------------- chọn run + model */}
      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Video size={16} style={{ color: 'var(--accent)' }} />
            <span>{t('veo.pickRun')}</span>
          </span>
        </div>
        <div className="panel-body">
          <div className="toolbar" style={{ flexWrap: 'wrap', gap: 16 }}>
            <div className="form-row" style={{ marginBottom: 0, flex: 1, minWidth: 240 }}>
              <label htmlFor="veo-run">{t('veo.pickRun')}</label>
              <select
                id="veo-run"
                value={runId}
                onChange={(e) => setRunId(e.target.value)}
                disabled={jobRunning}
              >
                <option value="">{t('veo.pickRunPlaceholder')}</option>
                {runs.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-row" style={{ marginBottom: 0, flex: 1, minWidth: 200 }}>
              <label htmlFor="veo-model">{t('veo.model')}</label>
              <select
                id="veo-model"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                disabled={jobRunning}
                className="mono"
              >
                {(veo?.models ?? []).map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {cand && (
            <p className="veo-desc" style={{ marginTop: 14, marginBottom: 4, fontWeight: 500, color: 'var(--text-heading)' }}>
              {t('veo.summary')
                .replace('{total}', String(cand.total))
                .replace('{ready}', String(cand.images_ready))
                .replace('{done}', String(cand.clips_done))}
            </p>
          )}
          <p className="veo-desc" style={{ margin: 0, fontSize: 12 }}>
            {t('veo.tip')}
          </p>
        </div>
      </div>

      {/* ------------------------------------------------ danh sách ứng viên */}
      {runId !== '' && cand && !cand.prompts_file_exists && (
        <div className="empty-state">{t('veo.noPromptsFile')}</div>
      )}
      {runId !== '' && cand && cand.prompts_file_exists && candidates.length === 0 && (
        <div className="empty-state">{t('veo.noCandidates')}</div>
      )}

      {candidates.length > 0 && (
        <div className="panel" style={{ marginBottom: 20 }}>
          <div className="panel-title">
            <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Sparkles size={16} style={{ color: 'var(--blue)' }} />
              <span>{t('veo.selected').replace('{n}', String(selectedList.length))}</span>
            </span>
          </div>
          <div className="panel-body">
            <div className="toolbar" style={{ marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
              <button type="button" className="btn" onClick={selectAll} disabled={jobRunning}>
                <CheckSquare size={13} />
                {t('veo.selectAll')}
              </button>
              <button type="button" className="btn" onClick={selectMissing} disabled={jobRunning}>
                <Film size={13} />
                {t('veo.selectMissing')}
              </button>
              <button type="button" className="btn" onClick={selectNone} disabled={jobRunning}>
                <Square size={13} />
                {t('veo.selectNone')}
              </button>
              <span className="spacer" />
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={skipExisting}
                  onChange={(e) => setSkipExisting(e.target.checked)}
                  disabled={jobRunning}
                />
                {t('veo.skipExisting')}
              </label>
            </div>

            <ul className="veo-list">
              {candidates.map((c) => (
                <li key={c.index} className={c.image_exists ? '' : 'veo-item-off'}>
                  <div className="veo-item-head">
                    <label className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={selected.has(c.index)}
                        onChange={() => toggle(c.index)}
                        disabled={!c.image_exists || jobRunning}
                      />
                      <span className="mono" style={{ fontWeight: 600, color: 'var(--text-heading)' }}>{c.name}</span>
                    </label>
                    {!c.image_exists && (
                      <span className="badge badge-unknown">{t('veo.noImageWarn')}</span>
                    )}
                    {c.clip_exists && (
                      <span className="badge badge-passed">
                        {t('veo.clipDone')} · {fmtBytes(c.clip_size_bytes)}
                      </span>
                    )}
                    {c.clip_exists && c.clip_path && (
                      <a href={artifactUrl(runId, c.clip_path)} target="_blank" rel="noreferrer" className="btn btn-ghost" style={{ padding: '2px 8px', fontSize: 12 }}>
                        <Film size={12} /> mp4
                      </a>
                    )}
                  </div>
                  {c.motion && (
                    <div className="veo-motion">
                      {t('veo.motion')}: {c.motion}
                    </div>
                  )}
                  <div className="veo-prompt">{c.prompt}</div>
                </li>
              ))}
            </ul>

            <div className="toolbar" style={{ marginTop: 18, gap: 12 }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void doGenerate()}
                disabled={!canGenerate}
              >
                <Sparkles size={15} />
                {jobRunning ? t('veo.generating') : t('veo.generate')}
              </button>
              {selectedList.length > MAX_PER_JOB && (
                <span className="error-text">{t('veo.maxWarn')}</span>
              )}
              {veo?.busy && !jobRunning && (
                <span className="badge badge-running">{t('veo.busy')}</span>
              )}
            </div>
          </div>
        </div>
      )}

      {actionError && (
        <p className="error-text" style={{ marginBottom: 20 }}>
          {actionError}
        </p>
      )}

      {/* --------------------------------------------------------- job + log */}
      {jobId && (
        <div className="panel">
          <div className="panel-title">
            <span>{t('veo.log')}</span>
          </div>
          <div className="panel-body">
            <div className="toolbar" style={{ marginBottom: 12 }}>
              <span
                className={
                  job?.status === 'complete'
                    ? 'badge badge-passed'
                    : job?.status === 'failed'
                      ? 'badge badge-failed'
                      : 'badge badge-running'
                }
              >
                {job?.status === 'complete'
                  ? t('veo.jobComplete')
                  : job?.status === 'failed'
                    ? t('veo.jobFailed')
                    : t('veo.jobRunning')}
              </span>
              <span className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>{jobId.slice(0, 12)}</span>
              <span className="spacer" />
              {jobRunning && (
                <button type="button" className="btn btn-danger" onClick={() => void doCancel()}>
                  <Square size={13} />
                  {t('veo.cancel')}
                </button>
              )}
            </div>
            <LogViewer
              logFetcher={(offset, limit) => getVeoJobLog(jobId, offset, limit)}
              running={jobRunning}
              intervalMs={JOB_INTERVAL_MS}
            />
          </div>
        </div>
      )}
    </div>
  );
}
