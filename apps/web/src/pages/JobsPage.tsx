import { useState } from 'react';
import { Activity, Loader2, Square } from '../components/Icons';
import { ApiError, cancelBackgroundJob, getActiveJobs } from '../api';
import { usePolling } from '../hooks/usePolling';
import { useT } from '../i18n';
import type { BackgroundJob } from '../types';

const POLL_MS = 3000;

const KIND_META: Record<BackgroundJob['kind'], { label: string; color: string }> = {
  pipeline: { label: 'Pipeline', color: 'var(--accent)' },
  tts: { label: 'Gen audio', color: '#10b981' },
  build: { label: 'Dựng video', color: '#6366f1' },
  veo: { label: 'Gen video Veo', color: '#f59e0b' },
  image: { label: 'Gen ảnh', color: '#ec4899' },
  srt: { label: 'Gen SRT', color: '#06b6d4' },
  data: { label: 'Kéo data', color: '#8b5cf6' },
};

function errText(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as { message?: string } | string;
    if (typeof d === 'string') return d;
    if (d?.message) return d.message;
  }
  return e instanceof Error ? e.message : String(e);
}

function elapsedSince(startedAt: string | null | undefined): string {
  if (!startedAt) return '—';
  const start = Date.parse(startedAt);
  if (!Number.isFinite(start)) return '—';
  const total = Math.max(0, Math.floor((Date.now() - start) / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}h ${String(m).padStart(2, '0')}m`
    : `${m}p ${String(s).padStart(2, '0')}s`;
}

/** Trang quản trị job nền: mọi worker đang chạy + kill trực tiếp. */
export function JobsPage() {
  const { t } = useT();
  const jobsPoll = usePolling(() => getActiveJobs(), {
    enabled: true,
    intervalMs: POLL_MS,
  });
  const jobs = jobsPoll.data?.jobs ?? [];
  const [killing, setKilling] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const kill = async (job: BackgroundJob) => {
    if (!window.confirm(`Kill job ${KIND_META[job.kind]?.label ?? job.kind} (${job.id})? Process sẽ nhận SIGTERM ngay lập tức.`)) return;
    setKilling(job.kind + ':' + job.id);
    setError(null);
    try {
      await cancelBackgroundJob(job.kind, job.id);
      await jobsPoll.refresh();
    } catch (e) {
      setError(errText(e));
    } finally {
      setKilling(null);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{t('jobs.title')}</h2>
          <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>
            {t('jobs.subtitle')}
          </div>
        </div>
        <div className="spacer" />
        <span className={jobs.length > 0 ? 'badge badge-running' : 'badge badge-passed'}>
          {jobs.length > 0 ? `${jobs.length} ${t('jobs.count')}` : t('jobs.empty')}
        </span>
      </div>

      {error && <p className="error-text">{error}</p>}

      {jobs.length === 0 ? (
        <div className="empty-state">
          <Activity size={20} style={{ display: 'block', margin: '0 auto 8px', color: 'var(--muted)' }} />
          {t('jobs.none')}
        </div>
      ) : (
        <div className="panel">
          <div className="panel-body" style={{ padding: 0 }}>
            <div style={{ display: 'grid', gap: 1 }}>
              {jobs.map((job) => {
                const meta = KIND_META[job.kind] ?? { label: job.kind, color: 'var(--muted)' };
                const key = job.kind + ':' + job.id;
                const busyKilling = killing === key;
                return (
                  <div key={key} style={{
                    display: 'grid',
                    gridTemplateColumns: '140px minmax(120px,1fr) minmax(100px,1fr) 90px minmax(150px,1.2fr) 80px auto',
                    gap: 12,
                    alignItems: 'center',
                    padding: '13px 16px',
                    borderBottom: '1px solid var(--border)',
                    fontSize: 13,
                  }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontWeight: 600 }}>
                      <span style={{ width: 8, height: 8, borderRadius: 999, background: meta.color, flexShrink: 0 }} />
                      {meta.label}
                    </span>
                    <span className="mono">
                      {job.run_id
                        ? <a href={`/runs/${encodeURIComponent(job.run_id)}`} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>
                            {job.run_id} ↗
                          </a>
                        : <span style={{ color: 'var(--muted)' }}>—</span>}
                    </span>
                    <span className="mono" style={{ fontSize: 12, color: 'var(--text-secondary)' }} title={job.id}>
                      {job.id.length > 18 ? job.id.slice(0, 18) + '…' : job.id}
                    </span>
                    <span className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>
                      {elapsedSince(job.started_at)}
                    </span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                      {job.progress ? (
                        <>
                          <div style={{
                            flex: 1,
                            height: 6,
                            borderRadius: 999,
                            background: 'var(--surface-hover, rgba(128,128,128,0.2))',
                            overflow: 'hidden',
                            minWidth: 60,
                          }}>
                            <div style={{
                              width: `${Math.min(100, job.progress.percent)}%`,
                              height: '100%',
                              borderRadius: 999,
                              background: meta.color,
                              transition: 'width 0.4s ease',
                            }} />
                          </div>
                          <span className="mono" style={{ fontSize: 11.5, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                            {job.progress.percent}% · {job.progress.detail}
                          </span>
                        </>
                      ) : (
                        <span className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>—</span>
                      )}
                    </span>
                    <span>
                      {job.orphaned && (
                        <span title="Server đã restart nhưng process vẫn sống" className="badge badge-unknown">mồ côi</span>
                      )}
                    </span>
                    <button
                      type="button"
                      className="btn btn-danger"
                      onClick={() => void kill(job)}
                      disabled={busyKilling}
                      title="SIGTERM cả process group — dừng ngay"
                    >
                      {busyKilling ? <Loader2 size={13} className="animate-spin" /> : <Square size={13} />}
                      Kill
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      <small style={{ display: 'block', color: 'var(--muted)', marginTop: 12 }}>
        {t('jobs.note')}
      </small>
    </div>
  );
}
