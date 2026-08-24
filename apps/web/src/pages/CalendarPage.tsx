import { useMemo, useState } from 'react';
import { CalendarDays, CheckCircle2, ChevronRight, Loader2, RotateCw, Trash2 } from '../components/Icons';
import { ApiError, getPublishSchedule, setPublishSchedule, updateTopicStatus } from '../api';
import { usePolling } from '../hooks/usePolling';
import { useT } from '../i18n';
import type { PublishRunInfo } from '../types';

const WEEKDAY_LABELS = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']; // getDay 1..6,0
const MONTH_NAMES = ['Tháng 1', 'Tháng 2', 'Tháng 3', 'Tháng 4', 'Tháng 5', 'Tháng 6',
  'Tháng 7', 'Tháng 8', 'Tháng 9', 'Tháng 10', 'Tháng 11', 'Tháng 12'];

function errText(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as { message?: string } | string;
    if (typeof d === 'string') return d;
    if (d?.message) return d.message;
  }
  return e instanceof Error ? e.message : String(e);
}

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Trang lịch đăng: gán run hoàn tất vào slot theo cadence + đánh dấu đã đăng. */
export function CalendarPage() {
  const { t } = useT();
  const schedPoll = usePolling(() => getPublishSchedule(), { enabled: true, intervalMs: 10000 });
  const data = schedPoll.data;
  const [cursor, setCursor] = useState(() => new Date());
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cadence = data?.cadence;
  const assignments = data?.assignments ?? {};
  const runs = data?.runs ?? [];

  const byRunId = useMemo(() => {
    const map: Record<string, PublishRunInfo> = {};
    for (const run of runs) map[run.run_id] = run;
    return map;
  }, [runs]);

  const byDate = useMemo(() => {
    const map: Record<string, { run_id: string; published: boolean }[]> = {};
    for (const [runId, value] of Object.entries(assignments)) {
      if (!value?.date) continue;
      (map[value.date] ||= []).push({
        run_id: runId,
        published: (value.topic_status ?? byRunId[runId]?.topic_status) === 'published',
      });
    }
    return map;
  }, [assignments, byRunId]);

  // Pool: run hoàn tất, chưa đăng, chưa có trong lịch
  const pool = runs.filter((r) =>
    r.topic_status !== 'published' && r.topic_status !== 'archived' && !assignments[r.run_id]?.date);

  const publishedCount = runs.filter((r) => r.topic_status === 'published').length;

  async function assign(runId: string, date: string) {
    setBusy(runId);
    setError(null);
    try {
      await setPublishSchedule(runId, date);
      await schedPoll.refresh();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(null);
    }
  }

  function assignNextSlot(runId: string) {
    // Tìm slot trống kế tiếp theo cadence — nếu đã quá giờ đăng hôm nay thì
    // bắt đầu từ ngày mai (không gợi ý ngày đã lỡ giờ).
    const taken = new Set(Object.values(assignments).map((v) => v?.date).filter(Boolean) as string[]);
    const weekdays = new Set((cadence?.weekdays ?? []) as number[]);
    const [hh, mm] = (cadence?.time ?? '18:00').split(':').map(Number);
    const now = new Date();
    const start = new Date();
    if (now.getHours() > hh || (now.getHours() === hh && now.getMinutes() >= mm)) {
      start.setDate(start.getDate() + 1);
    }
    for (let i = 0; i < 60; i++) {
      const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
      const iso = isoDate(d);
      if (weekdays.has(d.getDay()) && !taken.has(iso)) {
        void assign(runId, iso);
        return;
      }
    }
    setError('Không tìm thấy slot trống trong 60 ngày tới.');
  }

  async function markPublished(runId: string) {
    if (!window.confirm(`Đánh dấu ${runId} là ĐÃ ĐĂNG?`)) return;
    setBusy(runId);
    setError(null);
    try {
      await updateTopicStatus(runId, 'published');
      await schedPoll.refresh();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(null);
    }
  }

  async function unassign(runId: string) {
    setBusy(runId);
    setError(null);
    try {
      await setPublishSchedule(runId, null);
      await schedPoll.refresh();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(null);
    }
  }

  // Lưới tháng: bắt đầu từ T2 của tuần chứa ngày 1
  const year = cursor.getFullYear();
  const month = cursor.getMonth();
  const first = new Date(year, month, 1);
  const cells = Array.from({ length: 42 }, (_, i) => new Date(year, month, 1 - ((first.getDay() + 6) % 7) + i));
  const todayIso = isoDate(new Date());
  const cadenceDays = new Set((cadence?.weekdays ?? []).map((d) => (d + 6) % 7)); // convert getDay → index T2=0

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{t('calendar.title')}</h2>
          <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>
            {t('calendar.subtitle')} · {(cadence?.weekdays ?? []).map((d) => WEEKDAY_LABELS[(d + 6) % 7]).join(' · ')} — {cadence?.time ?? '18:00'}
          </div>
        </div>
        <div className="spacer" />
        <span className="badge badge-passed">{publishedCount} {t('calendar.published')}</span>
        <span className="badge badge-running">{pool.length} {t('calendar.pool')}</span>
      </div>

      {error && <p className="error-text">{error}</p>}

      <div className="grid-detail" style={{ gridTemplateColumns: '2fr 1fr' }}>
        {/* ---------------------------------------------- lưới tháng */}
        <div className="panel">
          <div className="panel-title">
            <button type="button" className="btn btn-ghost" style={{ padding: '2px 8px' }}
                    title={t('calendar.unassign')}
                    onClick={() => setCursor(new Date(year, month - 1, 1))}><RotateCw size={13} style={{ transform: 'scaleX(-1)' }} /></button>
            <span>{MONTH_NAMES[month]} {year}</span>
            <button type="button" className="btn btn-ghost" style={{ padding: '2px 8px' }}
                    onClick={() => setCursor(new Date(year, month + 1, 1))}><ChevronRight size={14} /></button>
            <div className="spacer" />
            <CalendarDays size={15} style={{ color: 'var(--accent)' }} />
          </div>
          <div className="panel-body" style={{ padding: 0 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 1, background: 'var(--border)' }}>
              {WEEKDAY_LABELS.map((label, idx) => (
                <div key={label} style={{
                  padding: '8px 6px', textAlign: 'center', fontSize: 11.5, fontWeight: 700,
                  color: cadenceDays.has(idx) ? 'var(--accent)' : 'var(--muted)',
                  background: 'var(--surface)',
                }}>{label}{cadenceDays.has(idx) ? ' ●' : ''}</div>
              ))}
              {cells.map((day) => {
                const iso = isoDate(day);
                const inMonth = day.getMonth() === month;
                const entries = byDate[iso] ?? [];
                const isCadence = cadenceDays.has((day.getDay() + 6) % 7);
                return (
                  <div key={iso} style={{
                    minHeight: 74,
                    padding: 6,
                    background: iso === todayIso ? 'rgba(59,130,246,0.08)' : 'var(--surface)',
                    opacity: inMonth ? 1 : 0.35,
                    border: iso === todayIso ? '1px solid var(--accent)' : 'none',
                    display: 'flex', flexDirection: 'column', gap: 4,
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span className="mono" style={{ fontSize: 11.5, fontWeight: iso === todayIso ? 700 : 400 }}>{day.getDate()}</span>
                      {isCadence && !entries.length && <span title="Slot theo lịch" style={{ width: 5, height: 5, borderRadius: 999, background: 'var(--accent)', opacity: 0.5 }} />}
                    </div>
                    {entries.map((entry) => (
                      <div key={entry.run_id} style={{
                        fontSize: 10.5, padding: '3px 5px', borderRadius: 6,
                        background: entry.published ? 'rgba(16,185,129,0.15)' : 'rgba(59,130,246,0.12)',
                        color: entry.published ? 'var(--ok)' : 'var(--text-secondary)',
                        display: 'flex', alignItems: 'center', gap: 4,
                      }} title={byRunId[entry.run_id]?.topic}>
                        <span style={{
                          width: 6, height: 6, borderRadius: 999, flexShrink: 0,
                          background: entry.published ? 'var(--ok)' : 'var(--blue)',
                        }} />
                        <span className="mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{entry.run_id}</span>
                        {entry.published && <CheckCircle2 size={10} />}
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* ---------------------------------------------- pool chờ lên lịch */}
        <div className="panel">
          <div className="panel-title"><span>{t('calendar.poolTitle')} ({pool.length})</span></div>
          <div className="panel-body" style={{ padding: 0 }}>
            {pool.length === 0 && (
              <div className="empty-state" style={{ padding: '24px 16px', fontSize: 12.5 }}>{t('calendar.poolEmpty')}</div>
            )}
            <div style={{ display: 'grid', gap: 1 }}>
              {pool.map((run) => (
                <div key={run.run_id} style={{ padding: '11px 14px', borderBottom: '1px solid var(--border)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className="mono" style={{ fontWeight: 700, fontSize: 12.5 }}>{run.run_id}</span>
                    {run.has_video && <span className="badge badge-passed" style={{ fontSize: 10 }}>video ✓</span>}
                    <div className="spacer" />
                    <button type="button" className="btn btn-primary" style={{ padding: '3px 10px', fontSize: 11.5 }}
                            onClick={() => assignNextSlot(run.run_id)} disabled={busy === run.run_id}>
                      {busy === run.run_id ? <Loader2 size={12} className="animate-spin" /> : <CalendarDays size={12} />}
                      {t('calendar.scheduleNext')}
                    </button>
                  </div>
                  <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={run.topic}>
                    {run.topic || '—'}
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'center' }}>
                    <input type="date" style={{ fontSize: 11.5, padding: '3px 6px' }}
                           onChange={(e) => { if (e.target.value) void assign(run.run_id, e.target.value); }}
                           disabled={busy === run.run_id} />
                    <span style={{ fontSize: 10.5, color: 'var(--muted)' }}>{t('calendar.pickDate')}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
          {Object.entries(assignments).filter(([, v]) => v?.date).length > 0 && (
            <>
              <div className="panel-title" style={{ borderTop: '1px solid var(--border)' }}>
                <span>{t('calendar.assigned')}</span>
              </div>
              <div className="panel-body" style={{ padding: 0 }}>
                <div style={{ display: 'grid', gap: 1 }}>
                  {Object.entries(assignments)
                    .filter(([, v]) => v?.date)
                    .sort((a, b) => (a[1].date ?? '').localeCompare(b[1].date ?? ''))
                    .map(([runId, value]) => {
                      const published = (value.topic_status ?? byRunId[runId]?.topic_status) === 'published';
                      return (
                        <div key={runId} style={{ padding: '9px 14px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5 }}>
                          <span className="mono" style={{ color: 'var(--muted)', fontSize: 11.5 }}>{value.date}</span>
                          <span className="mono" style={{ fontWeight: 600 }}>{runId}</span>
                          {published
                            ? <span className="badge badge-passed">{t('calendar.publishedBadge')}</span>
                            : <span className="badge badge-running">{t('calendar.scheduledBadge')}</span>}
                          <div className="spacer" />
                          {!published && (
                            <button type="button" className="btn btn-primary" style={{ padding: '2px 8px', fontSize: 11 }}
                                    onClick={() => void markPublished(runId)} disabled={busy === runId}>
                              <CheckCircle2 size={12} /> {t('calendar.markPublished')}
                            </button>
                          )}
                          <button type="button" className="btn btn-ghost" style={{ padding: '2px 6px' }}
                                  title={t('calendar.unassign')} onClick={() => void unassign(runId)} disabled={busy === runId}>
                            <Trash2 size={12} />
                          </button>
                        </div>
                      );
                    })}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
