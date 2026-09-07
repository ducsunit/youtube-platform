import { useEffect, useMemo, useState } from 'react';
import { CheckSquare, Image, Loader2, Save, Square } from '../components/Icons';
import { ApiError, cancelImageJob, getImageConfig, getImageJob, getImageJobLog, getImagePrompts, getImageStatus, listRuns, startImageGenerate, updateImageConfig } from '../api';
import { LogViewer } from '../components/LogViewer';
import { usePolling } from '../hooks/usePolling';
import { useChannelContext } from '../contexts/ChannelContext';
import type { ChannelScope, ImageConfig, ImageJob } from '../types';

const POLL_MS = 3000;

const IMAGE_ASPECT_RATIOS: ReadonlyArray<readonly [string, string]> = [
  ['16:9', 'landscape'],
  ['9:16', 'portrait'],
  ['1:1', 'square'],
];

const IMAGE_RESOLUTIONS: ReadonlyArray<readonly [string, string]> = [
  ['1K', '1K'],
  ['2K', '2K'],
  ['4K', '4K'],
];

const IMAGE_SIZE_BY_RESOLUTION: Record<string, Record<string, string>> = {
  '1K': { landscape: '1024x576', portrait: '576x1024', square: '1024x1024' },
  '2K': { landscape: '2048x1152', portrait: '1152x2048', square: '2048x2048' },
  '4K': { landscape: '3840x2160', portrait: '2160x3840', square: '3840x3840' },
};

function resolutionForSize(size: string): string {
  const dimensions = size.split('x').map(Number);
  const largest = Math.max(...dimensions);
  if (largest >= 3840) return '4K';
  if (largest >= 2048) return '2K';
  return '1K';
}

function aspectForSize(size: string): string {
  if (size === '576x1024' || size === '1152x2048' || size === '2160x3840') return 'portrait';
  if (size === '1024x1024' || size === '2048x2048' || size === '3840x3840') return 'square';
  if (size === '1024x576' || size === '2048x1152' || size === '3840x2160') return 'landscape';
  return 'square';
}

const scopeForChannel = (channel: ReturnType<typeof useChannelContext>['currentChannel']): ChannelScope | null =>
  channel ? { user_id: channel.user_id, channel_id: channel.channel_id } : null;

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = error.detail as { message?: string } | string;
    if (typeof detail === 'string') return detail;
    if (detail?.message) return detail.message;
  }
  return error instanceof Error ? error.message : String(error);
}

export function ImageGenPage() {
  const { currentChannel, loading: channelLoading } = useChannelContext();
  const scope = scopeForChannel(currentChannel);
  const channelScope = scope ?? undefined;
  const scopeKey = scope ? `${scope.user_id}:${scope.channel_id}` : null;
  const statusPoll = usePolling(() => getImageStatus(channelScope), { enabled: scope !== null, intervalMs: 8000 });
  const configPoll = usePolling(() => getImageConfig(channelScope), { enabled: scope !== null, intervalMs: 12000 });
  const runsPoll = usePolling(() => (scope ? listRuns(scope) : Promise.resolve(null)), { enabled: scope !== null, intervalMs: 8000 });
  const [runsScopeKey, setRunsScopeKey] = useState<string | null>(null);
  const runs = runsScopeKey === scopeKey ? runsPoll.data?.runs ?? [] : [];
  const [runId, setRunId] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [model, setModel] = useState('gpt-image-2');
  const [size, setSize] = useState('1024x576');
  const [aspect, setAspect] = useState('landscape');
  const [resolution, setResolution] = useState('1K');
  const [quality, setQuality] = useState('medium');
  const [skipExisting, setSkipExisting] = useState(true);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<ImageJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setJobId(null);
    setJob(null);
    setSelected(new Set());
    setSelectedRunId('');
    setError(null);
  }, [scopeKey]);
  const [imageConfig, setImageConfig] = useState<ImageConfig | null>(null);
  const [configDraft, setConfigDraft] = useState({ model: 'gpt-image-2', base_url: 'https://api.openai.com/v1', api_key_env: 'OPENAI_API_KEY', api_key: '', default_size: '1024x576', default_quality: 'medium' });
  const [configSaved, setConfigSaved] = useState(false);
  const [configSaving, setConfigSaving] = useState(false);

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
    if (!runId && runs.length) setRunId((runs.find((run) => run.has_manifest) ?? runs[0]).run_id);
  }, [runId, runs]);

  const promptsPoll = usePolling(() => getImagePrompts(runId, channelScope), { enabled: Boolean(runId) && scope !== null, intervalMs: 8000 });
  const prompts = promptsPoll.data;
  const running = job?.status === 'running' || (jobId !== null && job === null);
  const jobPoll = usePolling(() => getImageJob(jobId ?? '', channelScope), { enabled: Boolean(jobId) && running && scope !== null, intervalMs: POLL_MS });
  useEffect(() => { if (jobPoll.data) setJob(jobPoll.data); }, [jobPoll.data]);
  useEffect(() => {
    const config = configPoll.data;
    if (!config) return;
    setImageConfig(config);
    setConfigDraft((old) => ({ ...old, model: config.model, base_url: config.base_url, api_key_env: config.api_key_env, default_size: config.default_size, default_quality: config.default_quality }));
    setSize(config.default_size);
    setResolution(resolutionForSize(config.default_size));
    setAspect(aspectForSize(config.default_size));
    setQuality(config.default_quality);
  }, [configPoll.data]);
  useEffect(() => {
    if (prompts && prompts.run_id === runId && selectedRunId !== runId) {
      setSelected(new Set(prompts.prompts.filter((row) => !row.exists).map((row) => row.image_id)));
      setSelectedRunId(runId);
    }
  }, [prompts, runId, selectedRunId]);
  useEffect(() => { if (job && job.status !== 'running') void promptsPoll.refresh(); }, [job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedList = useMemo(() => [...selected], [selected]);
  const toggle = (id: string) => setSelected((old) => {
    const next = new Set(old);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  async function generate() {
    if (!runId || !selectedList.length) return;
    setError(null);
    try {
      const result = await startImageGenerate(runId, { images: selectedList, model, size, quality, skip_existing: skipExisting }, channelScope);
      if (result.job_id) { setJobId(result.job_id); setJob(null); }
      else await promptsPoll.refresh();
    } catch (e) { setError(errorText(e)); }
  }

  async function cancel() {
    if (!jobId) return;
    try { await cancelImageJob(jobId, channelScope); } catch (e) { setError(errorText(e)); }
  }

  async function saveImageConfig() {
    setConfigSaving(true);
    setError(null);
    try {
      const saved = await updateImageConfig(configDraft, channelScope);
      setImageConfig(saved);
      setConfigDraft((old) => ({ ...old, api_key: '' }));
      setConfigSaved(true);
    } catch (e) { setError(errorText(e)); }
    finally { setConfigSaving(false); }
  }

  const imageStatus = statusPoll.data;
  if (channelLoading || !currentChannel) {
    return <div className="page"><div className="empty-state">{channelLoading ? 'Đang tải channel...' : 'Chưa có channel được đăng ký.'}</div></div>;
  }
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Gen hình ảnh</h2>
          <div style={{ fontSize: 13, color: 'var(--muted)', marginTop: 2 }}>Tạo ảnh từ prompt của resource pack bằng OpenAI gpt-image-2</div>
        </div>
      </div>

      {imageStatus && !imageStatus.has_api_key && <div className="orphan-banner">Thiếu OPENAI_API_KEY trên API server hoặc file .env.</div>}
      {imageStatus && imageStatus.has_api_key && !imageStatus.sdk_ready && <div className="orphan-banner">Python package openai chưa sẵn sàng trên môi trường API server.</div>}

      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title"><span style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Image size={16} /><span>Thiết lập batch</span></span></div>
        <div className="panel-body">
          <div className="toolbar" style={{ flexWrap: 'wrap', gap: 14 }}>
            <div className="form-row" style={{ marginBottom: 0, flex: 1, minWidth: 220 }}>
              <label htmlFor="image-run">Run</label>
              <select id="image-run" value={runId} onChange={(event) => setRunId(event.target.value)} disabled={running}>
                <option value="">Chọn run</option>
                {runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.run_id}</option>)}
              </select>
            </div>
            <div className="form-row" style={{ marginBottom: 0, minWidth: 150 }}><label htmlFor="image-model">Model</label><select id="image-model" value={model} onChange={(e) => setModel(e.target.value)} disabled={running}><option>gpt-image-2</option></select></div>
            <div className="form-row" style={{ marginBottom: 0, minWidth: 190 }}>
              <span className="form-label">Tỷ lệ khung hình</span>
              <div className="segmented-control" role="group" aria-label="Tỷ lệ khung hình">
                {IMAGE_ASPECT_RATIOS.map(([ratio, value]) => <button type="button" className={aspect === value ? 'segment active' : 'segment'} key={value} aria-pressed={aspect === value} onClick={() => { setAspect(value); setSize(IMAGE_SIZE_BY_RESOLUTION[resolution][value]); }} disabled={running}>{ratio}</button>)}
              </div>
            </div>
            <div className="form-row" style={{ marginBottom: 0, minWidth: 190 }}>
              <span className="form-label">Độ phân giải</span>
              <div className="segmented-control" role="group" aria-label="Độ phân giải">
                {IMAGE_RESOLUTIONS.map(([label, value]) => <button type="button" className={resolution === value ? 'segment active' : 'segment'} key={value} aria-pressed={resolution === value} onClick={() => { setResolution(value); setSize(IMAGE_SIZE_BY_RESOLUTION[value][aspect]); }} disabled={running}>{label}</button>)}
              </div>
            </div>
            <div className="form-row" style={{ marginBottom: 0, minWidth: 130 }}><label htmlFor="image-quality">Quality</label><select id="image-quality" value={quality} onChange={(e) => setQuality(e.target.value)} disabled={running}><option>low</option><option>medium</option><option>high</option></select></div>
          </div>
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 14, fontSize: 13 }}><input type="checkbox" checked={skipExisting} onChange={(e) => setSkipExisting(e.target.checked)} disabled={running} /> Bỏ qua ảnh đã tồn tại</label>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title"><span>Cấu hình GPT Image</span><span className="spacer" />{configSaved && <span className="badge badge-complete">Đã lưu</span>}</div>
        <div className="panel-body">
          <div className="toolbar" style={{ flexWrap: 'wrap', gap: 14 }}>
            <div className="form-row" style={{ marginBottom: 0, minWidth: 180 }}><label htmlFor="image-config-model">Model</label><select id="image-config-model" value={configDraft.model} onChange={(e) => setConfigDraft({ ...configDraft, model: e.target.value })} disabled={running || configSaving}>{(imageConfig?.models ?? ['gpt-image-2']).map((value) => <option key={value}>{value}</option>)}</select></div>
            <div className="form-row" style={{ marginBottom: 0, minWidth: 260, flex: 1 }}><label htmlFor="image-config-base-url">Base URL</label><input id="image-config-base-url" type="url" value={configDraft.base_url} onChange={(e) => setConfigDraft({ ...configDraft, base_url: e.target.value })} disabled={running || configSaving} /></div>
            <div className="form-row" style={{ marginBottom: 0, minWidth: 190 }}><label htmlFor="image-config-key-env">API key env</label><input id="image-config-key-env" type="text" value={configDraft.api_key_env} onChange={(e) => setConfigDraft({ ...configDraft, api_key_env: e.target.value })} disabled={running || configSaving} /></div>
            <div className="form-row" style={{ marginBottom: 0, minWidth: 220 }}><label htmlFor="image-config-key">API key</label><input id="image-config-key" type="password" value={configDraft.api_key} placeholder={imageConfig?.api_key_configured ? '••••••••  (đã cấu hình)' : ''} onChange={(e) => setConfigDraft({ ...configDraft, api_key: e.target.value })} disabled={running || configSaving} autoComplete="new-password" /></div>
          </div>
          <div className="toolbar" style={{ flexWrap: 'wrap', gap: 14, marginTop: 14, alignItems: 'flex-end' }}>
            <div className="form-row" style={{ marginBottom: 0 }}><label htmlFor="image-config-size">Khung mặc định</label><select id="image-config-size" value={configDraft.default_size} onChange={(e) => { setConfigDraft({ ...configDraft, default_size: e.target.value }); setSize(e.target.value); setResolution(resolutionForSize(e.target.value)); setAspect(aspectForSize(e.target.value)); }} disabled={running || configSaving}>{Object.entries(IMAGE_SIZE_BY_RESOLUTION).flatMap(([level, sizes]) => Object.entries(sizes).map(([shape, pixels]) => <option key={pixels} value={pixels}>{level} · {shape === 'landscape' ? '16:9' : shape === 'portrait' ? '9:16' : '1:1'} · {pixels}</option>))}</select></div>
            <div className="form-row" style={{ marginBottom: 0 }}><label htmlFor="image-config-quality">Quality mặc định</label><select id="image-config-quality" value={configDraft.default_quality} onChange={(e) => { setConfigDraft({ ...configDraft, default_quality: e.target.value }); setQuality(e.target.value); }} disabled={running || configSaving}><option>low</option><option>medium</option><option>high</option></select></div>
            <button type="button" className="btn btn-primary" onClick={() => void saveImageConfig()} disabled={running || configSaving}><Save size={14} /> {configSaving ? 'Đang lưu…' : 'Lưu cấu hình'}</button>
          </div>
          <small style={{ display: 'block', color: 'var(--muted)', marginTop: 10 }}>API key được lưu ở API server và không trả về giao diện.</small>
        </div>
      </div>

      {prompts && !prompts.prompt_pack_exists && <div className="empty-state">Run này chưa có `visuals/prompt-pack.json`.</div>}
      {prompts && prompts.prompt_pack_exists && <div className="panel" style={{ marginBottom: 20 }}>
        <div className="panel-title"><span>{prompts.generated}/{prompts.total} ảnh đã có · {selectedList.length} ảnh được chọn</span><span className="spacer" /><button type="button" className="btn" onClick={() => setSelected(new Set(prompts.prompts.filter((row) => !row.exists).map((row) => row.image_id)))} disabled={running}><CheckSquare size={13} /> Chọn ảnh thiếu</button></div>
        <div className="panel-body" style={{ padding: 0 }}>
          <div style={{ display: 'grid', gap: 1 }}>
            {prompts.prompts.map((row) => <label key={row.image_id} style={{ display: 'grid', gridTemplateColumns: '24px 90px 1fr 70px', gap: 12, alignItems: 'start', padding: '12px 16px', background: selected.has(row.image_id) ? 'var(--surface-hover)' : 'transparent', borderBottom: '1px solid var(--border)' }}>
              <input type="checkbox" checked={selected.has(row.image_id)} onChange={() => toggle(row.image_id)} disabled={running} />
              <span className="mono" style={{ fontWeight: 700 }}>{row.image_id}</span>
              <span style={{ fontSize: 12, lineHeight: 1.45, color: 'var(--text-secondary)' }}>{row.prompt}</span>
              <span className={row.exists ? 'badge badge-passed' : 'badge'}>{row.exists ? 'Đã có' : 'Thiếu'}</span>
            </label>)}
          </div>
        </div>
        <div className="panel-body" style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}><button type="button" className="btn btn-primary" onClick={() => void generate()} disabled={!imageStatus?.available || !selectedList.length || running || imageStatus.busy}><Image size={14} /> {running ? 'Đang gen…' : 'Gen ảnh đã chọn'}</button></div>
      </div>}

      {error && <p className="error-text">{error}</p>}
      {jobId && <div className="panel"><div className="panel-title"><span>{job?.status === 'complete' ? 'Gen ảnh hoàn tất' : job?.status === 'failed' ? 'Gen ảnh thất bại' : 'Đang gen ảnh'}</span><span className="spacer" />{running && <button type="button" className="btn btn-danger" onClick={() => void cancel()}><Square size={13} /> Hủy</button>}</div><div className="panel-body"><LogViewer logFetcher={(offset, limit) => getImageJobLog(jobId, offset, limit, channelScope)} running={running} intervalMs={POLL_MS} /></div></div>}
      {!prompts && runId && <div className="empty-state"><Loader2 size={16} className="spin" /> Đang đọc prompt pack…</div>}
    </div>
  );
}
