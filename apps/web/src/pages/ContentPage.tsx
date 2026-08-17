import { useState } from 'react';
import { FileText, ListOrdered, BookOpen, Cpu, Sparkles, RefreshCw, Play, Send, Edit3 } from '../components/Icons';
import {
  getContentQueue,
  getCulturalFrames,
  getMechanisms,
  markQueueInProgress,
  publishQueueTopic,
  setQueueVideoId,
} from '../api';
import { usePolling } from '../hooks/usePolling';
import { useT } from '../i18n';
import type { QueueTopic } from '../types';

type ModalState =
  | { kind: 'publish'; topic: QueueTopic; mechanism: string; frame: string }
  | { kind: 'videoId'; topic: QueueTopic; videoId: string };

function statusBadge(status: string, t: (key: string) => string) {
  const map: Record<string, string> = {
    queued: 'pending',
    in_progress: 'running',
    published: 'complete',
  };
  const cls = map[status] ?? 'unknown';
  return (
    <span className={`badge badge-${cls}`}>{t(`content.status.${status}`)}</span>
  );
}

/** Trang Nội dung: hàng đợi video + nhật ký dùng + thư viện cơ chế/frame. */
export function ContentPage() {
  const { t } = useT();

  const queuePoll = usePolling(() => getContentQueue(), {
    enabled: true,
    intervalMs: 10000,
  });
  const mechPoll = usePolling(() => getMechanisms(), {
    enabled: true,
    intervalMs: 30000,
  });
  const framesPoll = usePolling(() => getCulturalFrames(), {
    enabled: true,
    intervalMs: 30000,
  });

  const [modal, setModal] = useState<ModalState | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const runAction = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      setModal(null);
      await queuePoll.refresh();
    } catch (e) {
      setActionError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const openPublish = (topic: QueueTopic) =>
    setModal({
      kind: 'publish',
      topic,
      mechanism: topic.mechanism,
      frame: topic.cultural_frame,
    });
  const openVideoId = (topic: QueueTopic) =>
    setModal({ kind: 'videoId', topic, videoId: '' });

  const topics = queuePoll.data?.topics ?? null;
  const diary = queuePoll.data?.diary ?? null;
  const recent = queuePoll.data?.recent_mechanisms ?? [];
  const mechs = mechPoll.data?.mechanisms ?? null;
  const frames = framesPoll.data?.frames ?? null;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>{t('content.title')}</h2>
          <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>
            {t('content.desc')}
          </div>
        </div>
        <div className="spacer" />
        <button type="button" className="btn" onClick={() => void queuePoll.refresh()}>
          <RefreshCw size={14} />
          {t('runs.refresh')}
        </button>
      </div>

      {Boolean(queuePoll.error) && (
        <div className="error-text" style={{ marginBottom: 16, padding: '12px 16px', background: 'rgba(239, 68, 68, 0.1)', borderRadius: 10, border: '1px solid rgba(239, 68, 68, 0.2)' }}>
          {String(queuePoll.error)}
        </div>
      )}

      {/* Hàng đợi video */}
      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <ListOrdered size={16} style={{ color: 'var(--accent)' }} />
            <span>{t('content.queue.title')}</span>
          </span>
          {recent.length > 0 && (
            <span className="chip" style={{ marginLeft: 12 }}>
              {t('content.queue.recent')} {recent.join(', ')}
            </span>
          )}
        </div>
        <div className="panel-body">
          {topics === null ? (
            <div className="empty-state">Đang tải hàng đợi…</div>
          ) : topics.length === 0 ? (
            <div className="empty-state">{t('content.queue.empty')}</div>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>{t('content.queue.col.phenomenon')}</th>
                    <th>{t('content.queue.col.mechanism')}</th>
                    <th>{t('content.queue.col.frame')}</th>
                    <th>{t('content.queue.col.status')}</th>
                    <th style={{ textAlign: 'right' }}>{t('content.queue.col.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {topics.map((topic) => (
                    <tr key={topic.queue_no}>
                      <td>{topic.queue_no}</td>
                      <td>
                        <div style={{ fontWeight: 500, color: 'var(--text-heading)' }}>{topic.hien_tuong}</div>
                        {topic.title_jp && (
                          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                            {topic.title_jp}
                          </div>
                        )}
                      </td>
                      <td>
                        <div>{topic.mechanism}</div>
                        {topic.backup_mechanism && topic.backup_mechanism !== '—' && (
                          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                            dự phòng: {topic.backup_mechanism}
                          </div>
                        )}
                      </td>
                      <td>{topic.cultural_frame}</td>
                      <td>{statusBadge(topic.status, t)}</td>
                      <td>
                        <div className="toolbar" style={{ justifyContent: 'flex-end', gap: 8 }}>
                          {topic.status === 'queued' && (
                            <button
                              type="button"
                              className="btn btn-ghost"
                              disabled={busy}
                              onClick={() =>
                                void runAction(() => markQueueInProgress(topic.hien_tuong))
                              }
                            >
                              <Play size={13} />
                              {t('content.queue.start')}
                            </button>
                          )}
                          {(topic.status === 'queued' || topic.status === 'in_progress') && (
                            <button
                              type="button"
                              className="btn btn-primary"
                              disabled={busy}
                              onClick={() => openPublish(topic)}
                            >
                              <Send size={13} />
                              {t('content.queue.publish')}
                            </button>
                          )}
                          {topic.status === 'published' && (
                            <button
                              type="button"
                              className="btn btn-ghost"
                              disabled={busy}
                              onClick={() => openVideoId(topic)}
                            >
                              <Edit3 size={13} />
                              {t('content.queue.fillId')}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Nhật ký dùng */}
      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <BookOpen size={16} style={{ color: 'var(--blue)' }} />
            <span>{t('content.diary.title')}</span>
          </span>
        </div>
        <div className="panel-body">
          {diary === null ? (
            <div className="empty-state">Đang tải nhật ký…</div>
          ) : diary.length === 0 ? (
            <div className="empty-state">{t('content.diary.empty')}</div>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t('content.diary.col.date')}</th>
                    <th>{t('content.diary.col.video')}</th>
                    <th>{t('content.diary.col.mechanism')}</th>
                    <th>{t('content.diary.col.frame')}</th>
                    <th>{t('content.diary.col.videoId')}</th>
                  </tr>
                </thead>
                <tbody>
                  {[...diary].reverse().map((row, i) => (
                    <tr key={i}>
                      <td>{row.ngay}</td>
                      <td>{row.video}</td>
                      <td>{row.mechanism}</td>
                      <td>{row.frame}</td>
                      <td>
                        {row.video_id && row.video_id !== '—' ? (
                          <a
                            href={`https://youtu.be/${row.video_id}`}
                            target="_blank"
                            rel="noreferrer"
                            className="mono"
                            style={{ color: 'var(--blue)' }}
                          >
                            {row.video_id}
                          </a>
                        ) : (
                          <span style={{ color: 'var(--muted)' }}>{row.video_id}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Thư viện cơ chế */}
      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Cpu size={16} style={{ color: 'var(--warn)' }} />
            <span>{t('content.mech.title')}</span>
          </span>
        </div>
        <div className="panel-body">
          {mechs === null ? (
            <div className="empty-state">Đang tải cơ chế…</div>
          ) : Object.keys(mechs).length === 0 ? (
            <div className="empty-state">{t('content.mech.empty')}</div>
          ) : (
            <div className="toolbar" style={{ flexWrap: 'wrap', gap: 12, alignItems: 'stretch' }}>
              {Object.entries(mechs).map(([name, m]) => (
                <div
                  key={name}
                  className="panel"
                  style={{ flex: '1 1 300px', margin: 0 }}
                >
                  <div className="panel-title">
                    {name}
                    {m.paused && (
                      <span className="badge badge-failed" style={{ marginLeft: 8 }}>
                        ⛔ {t('content.mech.paused')}
                      </span>
                    )}
                  </div>
                  <div className="panel-body" style={{ fontSize: 13, lineHeight: 1.6 }}>
                    {m.author_year && (
                      <div>
                        {m.author_year}
                        {m.source ? ` — ${m.source}` : ''}
                      </div>
                    )}
                    {m.hook && (
                      <div style={{ color: 'var(--muted)' }}>
                        {t('content.mech.hook')}: {m.hook}
                      </div>
                    )}
                    {m.core_idea && (
                      <div style={{ color: 'var(--muted)' }}>
                        {t('content.mech.core')}: {m.core_idea}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Frame văn hóa */}
      <div className="panel">
        <div className="panel-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Sparkles size={16} style={{ color: 'var(--ok)' }} />
            <span>{t('content.frames.title')}</span>
          </span>
        </div>
        <div className="panel-body">
          {frames === null ? (
            <div className="empty-state">Đang tải frames…</div>
          ) : Object.keys(frames).length === 0 ? (
            <div className="empty-state">{t('content.frames.empty')}</div>
          ) : (
            <>
              <div
                className="toolbar"
                style={{ flexWrap: 'wrap', gap: 12, alignItems: 'stretch', marginBottom: 16 }}
              >
                {Object.entries(frames).map(([name, f]) => (
                  <div
                    key={name}
                    className="panel"
                    style={{ flex: '1 1 300px', margin: 0 }}
                  >
                    <div className="panel-title">{name}</div>
                    <div className="panel-body" style={{ fontSize: 13, lineHeight: 1.6 }}>
                      {f.concept && (
                        <div>
                          {t('content.frames.concept')}: {f.concept}
                        </div>
                      )}
                      {f.usage_step && (
                        <div style={{ color: 'var(--muted)' }}>
                          {t('content.frames.step')}: {f.usage_step}
                        </div>
                      )}
                      {f.pair_mechanisms && (
                        <div style={{ color: 'var(--muted)' }}>
                          {t('content.frames.pair')}: {f.pair_mechanisms}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              <div style={{ fontSize: 12.5, color: 'var(--muted)' }}>
                {t('content.frames.rule')}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Modal publish / điền video ID */}
      {modal && (
        <div className="modal-overlay" onClick={() => !busy && setModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>
              {modal.kind === 'publish'
                ? t('content.publish.title')
                : t('content.videoId.title')}
              {' — '}
              {modal.topic.hien_tuong}
            </h3>

            {modal.kind === 'publish' && (
              <>
                <div className="form-row">
                  <label htmlFor="content-mechanism">{t('content.publish.mechanism')}</label>
                  <input
                    id="content-mechanism"
                    type="text"
                    value={modal.mechanism}
                    onChange={(e) =>
                      setModal({ ...modal, mechanism: e.target.value })
                    }
                    disabled={busy}
                  />
                </div>
                <div className="form-row">
                  <label htmlFor="content-frame">{t('content.publish.frame')}</label>
                  <input
                    id="content-frame"
                    type="text"
                    value={modal.frame}
                    onChange={(e) => setModal({ ...modal, frame: e.target.value })}
                    disabled={busy}
                  />
                </div>
              </>
            )}

            {modal.kind === 'videoId' && (
              <div className="form-row">
                <label htmlFor="content-video-id">{t('content.videoId.label')}</label>
                <input
                  id="content-video-id"
                  type="text"
                  value={modal.videoId}
                  onChange={(e) => setModal({ ...modal, videoId: e.target.value })}
                  placeholder="dQw4w9WgXcQ"
                  disabled={busy}
                />
                <div style={{ fontSize: 12.5, color: 'var(--muted)' }}>
                  {t('content.videoId.hint')}
                </div>
              </div>
            )}

            {actionError && (
              <div className="error-text" style={{ marginTop: 8 }}>
                {t('content.err')}: {actionError}
              </div>
            )}

            <div className="modal-actions">
              <button
                type="button"
                className="btn btn-ghost"
                disabled={busy}
                onClick={() => setModal(null)}
              >
                {t('content.publish.cancel')}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={busy}
                onClick={() =>
                  void runAction(() =>
                    modal.kind === 'publish'
                      ? publishQueueTopic(
                          modal.topic.hien_tuong,
                          modal.mechanism.trim(),
                          modal.frame.trim(),
                        )
                      : setQueueVideoId(modal.topic.hien_tuong, modal.videoId.trim()),
                  )
                }
              >
                {busy
                  ? t('content.working')
                  : modal.kind === 'publish'
                    ? t('content.publish.submit')
                    : t('content.videoId.submit')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

