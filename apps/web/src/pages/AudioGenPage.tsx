import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Loader2, Mic, PlayCircle, RotateCw, Save, Square } from '../components/Icons';
import {
  ApiError,
  artifactUrl,
  cancelRunTts,
  getRunTts,
  getRunTtsChunks,
  getRunTtsSettings,
  getTtsVoices,
  listChannels,
  listRuns,
  previewTtsVoice,
  startRunTts,
  updateRunTtsSettings,
} from '../api';
import { usePolling } from '../hooks/usePolling';
import type { ChannelInfo, RunTtsChunksResponse, RunTtsSettings, RunTtsStatus } from '../types';

const DEFAULT_SETTINGS: RunTtsSettings['tts'] = {
  speaker: 21,
  speed_scale: 1.0,
  pitch_scale: 0.0,
  intonation_scale: 0.85,
};

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = error.detail as { message?: string } | string;
    if (typeof detail === 'string') return detail;
    if (detail?.message) return detail.message;
  }
  return error instanceof Error ? error.message : String(error);
}

function sameSettings(a: RunTtsSettings['tts'], b: RunTtsSettings['tts']): boolean {
  return a.speaker === b.speaker
    && a.speed_scale === b.speed_scale
    && a.pitch_scale === b.pitch_scale
    && a.intonation_scale === b.intonation_scale;
}

/** Trang gen audio VOICEVOX: cấu hình giọng cho run + chunk list + nút gen + player. */
export function AudioGenPage() {
  const runsPoll = usePolling(() => listRuns(), { enabled: true, intervalMs: 8000 });
  const runs = runsPoll.data?.runs ?? [];
  const voicesPoll = usePolling(() => getTtsVoices(), { enabled: true, intervalMs: 15000 });

  const [runId, setRunId] = useState('');
  const [settings, setSettings] = useState<RunTtsSettings['tts']>(DEFAULT_SETTINGS);
  const [channelId, setChannelId] = useState('');
  const channelsPoll = usePolling(() => listChannels(), { enabled: true, intervalMs: 60000 });
  const channels: ChannelInfo[] = useMemo(() => channelsPoll.data?.channels ?? [], [channelsPoll.data]);
  const [savedSettings, setSavedSettings] = useState<RunTtsSettings['tts'] | null>(null);
  const [saveToChannel, setSaveToChannel] = useState(false);
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsSavedAt, setSettingsSavedAt] = useState(0);
  const [previewing, setPreviewing] = useState(false);
  const previewRef = useRef<HTMLAudioElement | null>(null);
  const [tts, setTts] = useState<RunTtsStatus | null>(null);
  const [chunks, setChunks] = useState<RunTtsChunksResponse | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId && runs.length) setRunId((runs.find((run) => run.has_manifest) ?? runs[0]).run_id);
  }, [runId, runs]);

  useEffect(() => {
    if (!runId) { setTts(null); setChunks(null); return; }
    let alive = true;
    void getRunTtsSettings(runId).then((s) => {
      if (!alive) return;
      setSettings(s.tts);
      setSavedSettings(s.tts);
      setChannelId(s.channel_id);
    }).catch(() => { /* ignore */ });
    const refresh = () => {
      void getRunTts(runId).then((s) => { if (alive) setTts(s); }).catch(() => { /* ignore */ });
      void getRunTtsChunks(runId).then((c) => { if (alive) setChunks(c); }).catch(() => { if (alive) setChunks(null); });
    };
    refresh();
    return () => { alive = false; };
  }, [runId]);

  const running = tts?.status === 'running';
  // Poll status + chunks; nhanh hơn khi job đang chạy.
  useEffect(() => {
    if (!runId) return;
    const timer = window.setInterval(() => {
      void getRunTts(runId).then(setTts).catch(() => { /* ignore */ });
      void getRunTtsChunks(runId).then(setChunks).catch(() => { /* ignore */ });
    }, running ? 2500 : 8000);
    return () => window.clearInterval(timer);
  }, [runId, running]);

  const engineOnline = voicesPoll.data?.available === true && tts?.engine_available !== false;
  const total = chunks?.total ?? 0;
  const generated = chunks?.generated ?? 0;
  const missing = Math.max(0, total - generated);
  const done = Boolean(chunks?.merge_exists);
  const settingsDirty = savedSettings !== null && !sameSettings(settings, savedSettings);

  async function generate(force: boolean) {
    if (!runId) return;
    setError(null);
    // Job đọc setting từ snapshot lúc spawn — tự lưu thay đổi trước khi gen.
    if (settingsDirty || saveToChannel) {
      const ok = await persistSettings();
      if (!ok) return;
    }
    setStarting(true);
    try {
      await startRunTts(runId, force);
      setTts(await getRunTts(runId));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setStarting(false);
    }
  }

  async function persistSettings(): Promise<boolean> {
    if (!runId) return false;
    setSavingSettings(true);
    setError(null);
    try {
      const result = await updateRunTtsSettings(runId, {
        tts: settings,
        channel_id: channelId,
        save_to_channel: saveToChannel,
      });
      setSavedSettings(result.tts);
      setSaveToChannel(false);
      setSettingsSavedAt(Date.now());
      return true;
    } catch (e) {
      setError(errorText(e));
      return false;
    } finally {
      setSavingSettings(false);
    }
  }

  async function cancelTts() {
    if (!runId) return;
    setError(null);
    try {
      await cancelRunTts(runId);
      setTts(await getRunTts(runId));
      void getRunTtsChunks(runId).then(setChunks).catch(() => { /* ignore */ });
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function previewVoice() {
    setPreviewing(true);
    setError(null);
    try {
      const blob = await previewTtsVoice({
        speaker: settings.speaker,
        speed_scale: settings.speed_scale,
        intonation_scale: settings.intonation_scale,
      });
      if (!previewRef.current) previewRef.current = new Audio();
      previewRef.current.src = URL.createObjectURL(blob);
      await previewRef.current.play();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setPreviewing(false);
    }
  }

  const speakerOptions = useMemo(() => voicesPoll.data?.voices ?? [], [voicesPoll.data]);
  const currentSpeakerLabel = useMemo(() => {
    for (const v of speakerOptions) {
      const style = v.styles.find((st) => st.id === settings.speaker);
      if (style) return `${v.character} · ${style.name}`;
    }
    return `ID ${settings.speaker}`;
  }, [speakerOptions, settings.speaker]);

  const progress = tts?.progress;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Gen audio</h2>
          <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>
            Đọc toàn bộ script thành giọng nói bằng VOICEVOX local — narration-merged.mp3 dùng cho Dựng video
          </div>
        </div>
      </div>

      {!engineOnline && (
        <div className="orphan-banner">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <AlertTriangle size={14} />
            Engine VOICEVOX offline — bật app VOICEVOX (port 50021) rồi thử lại.
          </span>
        </div>
      )}

      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Mic size={16} /><span>Chọn run</span></span>
          <span
            style={{
              fontSize: 11,
              padding: '2px 8px',
              borderRadius: 999,
              background: engineOnline ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)',
              color: engineOnline ? 'var(--ok)' : 'var(--warn)',
            }}
          >
            {engineOnline ? 'engine online' : 'engine offline'}
          </span>
        </div>
        <div className="panel-body">
          <div className="toolbar" style={{ flexWrap: 'wrap', gap: 14 }}>
            <div className="form-row" style={{ marginBottom: 0, flex: 1, minWidth: 240 }}>
              <label htmlFor="audio-run">Run</label>
              <select id="audio-run" value={runId} onChange={(e) => setRunId(e.target.value)} disabled={running || starting}>
                <option value="">Chọn run</option>
                {runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.run_id}</option>)}
              </select>
            </div>
            <div className="spacer" />
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void generate(false)}
              disabled={!engineOnline || !runId || !chunks?.manifest_exists || starting || running}
              title={!chunks?.manifest_exists ? 'Run chưa có script/audio-chunks/manifest.json' : 'Gen các chunk còn thiếu'}
            >
              {running || starting ? <Loader2 size={14} className="animate-spin" /> : <PlayCircle size={14} />}
              {running ? 'Đang gen…' : missing > 0 ? `Gen ${missing} chunk thiếu` : 'Gen audio'}
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => void generate(true)}
              disabled={!engineOnline || !runId || !chunks?.manifest_exists || starting || running}
              title="Gen lại toàn bộ, bỏ qua file mp3 đã có"
            >
              <RotateCw size={14} />
              Gen lại tất cả
            </button>
            {running && (
              <button type="button" className="btn btn-danger" onClick={() => void cancelTts()} title="Dừng job TTS đang chạy">
                <Square size={14} />
                Hủy
              </button>
            )}
          </div>
        </div>
      </div>

      {runId && (
        <div className="panel" style={{ marginBottom: 20 }}>
          <div className="panel-title">
            <span>Cấu hình giọng đọc</span>
            <div className="spacer" />
            {!engineOnline && <span style={{ fontSize: 11, color: 'var(--muted)' }}>{currentSpeakerLabel} (offline)</span>}
            {settingsDirty && <span className="badge badge-running">Chưa lưu</span>}
            {!settingsDirty && settingsSavedAt > 0 && <span className="badge badge-complete">Đã lưu</span>}
          </div>
          <div className="panel-body">
            <div className="toolbar" style={{ flexWrap: 'wrap', gap: 14, alignItems: 'flex-end' }}>
              <div className="form-row" style={{ marginBottom: 0, minWidth: 260, flex: 1 }}>
                <label htmlFor="audio-speaker">Giọng (speaker)</label>
                <select
                  id="audio-speaker"
                  value={settings.speaker}
                  onChange={(e) => setSettings({ ...settings, speaker: parseInt(e.target.value, 10) })}
                  disabled={!engineOnline || savingSettings}
                >
                  {!engineOnline && <option value={settings.speaker}>{currentSpeakerLabel} (engine offline)</option>}
                  {speakerOptions.map((v) => (
                    v.styles.map((st) => (
                      <option key={st.id} value={st.id}>{v.character} · {st.name} ({st.id})</option>
                    ))
                  ))}
                </select>
              </div>
              <div className="form-row" style={{ marginBottom: 0, width: 110 }}>
                <label htmlFor="audio-speed">Tốc độ</label>
                <input id="audio-speed" type="number" step="0.05" min="0.5" max="2" value={settings.speed_scale}
                       onChange={(e) => setSettings({ ...settings, speed_scale: parseFloat(e.target.value) || 1 })}
                       disabled={savingSettings} />
              </div>
              <div className="form-row" style={{ marginBottom: 0, width: 110 }}>
                <label htmlFor="audio-pitch">Pitch</label>
                <input id="audio-pitch" type="number" step="0.01" min="-0.15" max="0.15" value={settings.pitch_scale}
                       onChange={(e) => setSettings({ ...settings, pitch_scale: parseFloat(e.target.value) || 0 })}
                       disabled={savingSettings} />
              </div>
              <div className="form-row" style={{ marginBottom: 0, width: 130 }}>
                <label htmlFor="audio-intonation">Intonation</label>
                <input id="audio-intonation" type="number" step="0.05" min="0" max="2" value={settings.intonation_scale}
                       onChange={(e) => setSettings({ ...settings, intonation_scale: parseFloat(e.target.value) || 0 })}
                       disabled={savingSettings} />
              </div>
              <button type="button" className="btn" onClick={() => void previewVoice()}
                      disabled={!engineOnline || previewing || savingSettings}>
                {previewing ? <Loader2 size={14} className="animate-spin" /> : <PlayCircle size={14} />}
                Nghe thử
              </button>
            </div>
            <div className="toolbar" style={{ flexWrap: 'wrap', gap: 14, marginTop: 14, alignItems: 'center' }}>
              <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13 }}>
                <input type="checkbox" checked={saveToChannel} onChange={(e) => setSaveToChannel(e.target.checked)} disabled={savingSettings} />
                Lưu luôn làm mặc định kênh
              </label>
              {saveToChannel && (
                <select value={channelId} onChange={(e) => setChannelId(e.target.value)}
                        style={{ maxWidth: 220 }} disabled={savingSettings} aria-label="Kênh áp dụng mặc định">
                  <option value="">Chọn kênh</option>
                  {channels.map((ch) => <option key={ch.channel_id} value={ch.channel_id}>{ch.display_name || ch.channel_id}</option>)}
                </select>
              )}
              <div className="spacer" />
              <button type="button" className="btn btn-primary" onClick={() => void persistSettings()}
                      disabled={!runId || savingSettings || running || (!settingsDirty && !saveToChannel) || (saveToChannel && !channelId)}>
                {savingSettings ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                Lưu cấu hình
              </button>
            </div>
            <small style={{ display: 'block', color: 'var(--muted)', marginTop: 8 }}>
              Cấu hình ghi vào snapshot của run này — job TTS dùng ngay cho lần gen tiếp theo.
            </small>
          </div>
        </div>
      )}

      {!runId && <div className="empty-state">Chọn một run để xem danh sách chunk.</div>}
      {runId && chunks && !chunks.manifest_exists && (
        <div className="empty-state">Run này chưa có `script/audio-chunks/manifest.json` — hãy chạy stage tách script trước.</div>
      )}

      {chunks?.manifest_exists && (
        <div className="panel" style={{ marginBottom: 20 }}>
          <div className="panel-title">
            <span>{generated}/{total} chunk đã có audio</span>
            <div className="spacer" />
            {running && (
              <span className="badge badge-running">
                {progress
                  ? `Chunk ${progress.chunk}/${progress.total_chunks} · mảnh ${progress.piece}/${progress.total_pieces}`
                  : `${tts?.chunks_count ?? generated} mp3 đã ghi`}
              </span>
            )}
            {!running && total > 0 && (
              <span className={missing === 0 ? 'badge badge-passed' : 'badge'}>
                {missing === 0 ? 'Đủ chunk' : `${missing} thiếu`}
              </span>
            )}
          </div>
          <div className="panel-body" style={{ padding: 0 }}>
            <div style={{ display: 'grid', gap: 1 }}>
              {chunks.chunks.map((chunk) => (
                <div key={chunk.id} style={{
                  display: 'grid',
                  gridTemplateColumns: '90px 70px 1fr 70px',
                  gap: 12,
                  alignItems: 'start',
                  padding: '12px 16px',
                  borderBottom: '1px solid var(--border)',
                }}>
                  <span className="mono" style={{ fontWeight: 700 }}>{chunk.id}</span>
                  <span className="mono" style={{ fontSize: 12, color: 'var(--muted)' }}>{(chunk.chars ?? 0).toLocaleString()} ký tự</span>
                  <span style={{ fontSize: 12, lineHeight: 1.45, color: 'var(--text-secondary)' }}>{chunk.preview}</span>
                  <span className={chunk.exists ? 'badge badge-passed' : 'badge'}>{chunk.exists ? 'Đã có' : 'Thiếu'}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {done && (
        <div className="panel">
          <div className="panel-title"><span>Narration hoàn chỉnh</span><span className="spacer" />
            <a className="btn btn-ghost" href={artifactUrl(runId, 'audio/narration-merged.mp3', true)} download style={{ padding: '4px 10px', fontSize: 12 }}>
              Tải narration-merged.mp3
            </a>
          </div>
          <div className="panel-body">
            <audio controls preload="none" src={artifactUrl(runId, 'audio/narration-merged.mp3')} style={{ width: '100%' }} key={`${runId}-${done}`} />
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>
              narration-merged.mp3 · {(tts?.summary?.total_chars ?? 0).toLocaleString()} ký tự · speaker {tts?.summary?.speaker ?? settings.speaker}
            </div>
          </div>
        </div>
      )}

      {tts?.status === 'cancelled' && (
        <p style={{ fontSize: 13, color: 'var(--warn)' }}>Job TTS đã bị hủy — chunk mp3 đã gen xong vẫn giữ nguyên, bấm Gen audio để chạy tiếp phần thiếu.</p>
      )}
      {tts?.status === 'failed' && <p className="error-text">{tts.error ?? 'Job TTS thất bại — xem log trên server.'}</p>}
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
