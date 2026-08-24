import type {
  ArtifactTree,
  LogPage,
  NewRunBody,
  RunDetail,
  RunDiagnostics,
  RunStatus,
  RunEvent,
  RunSummary,
  ServerConfig,
  ChannelInfo,
  TtsVoicesResponse,
  RunTtsStatus,
  RunTtsChunksResponse,
  RunTtsSettings,
  BackgroundJob,
  PublishSchedule,
} from '../types';
import { API_BASE, request } from './apiClient';

export const getConfig = () => request<ServerConfig>('/config');

// ---- VOICEVOX TTS -----------------------------------------------------------
export const getTtsVoices = () =>
  request<TtsVoicesResponse>('/tts/voices');
export const previewTtsVoice = (body: {
  speaker: number;
  text?: string;
  speed_scale?: number;
  intonation_scale?: number;
}): Promise<Blob> =>
  fetch(`${API_BASE}/tts/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(async (resp) => {
    if (!resp.ok) {
      let detail: unknown = resp.statusText;
      try { detail = (await resp.json()).detail; } catch { /* ignore */ }
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return resp.blob();
  });
export const startRunTts = (runId: string, force = false) =>
  request<{ started: boolean; pid: number }>(
    `/runs/${encodeURIComponent(runId)}/tts`,
    { method: 'POST', body: JSON.stringify({ force }) },
  );
export const getRunTts = (runId: string) =>
  request<RunTtsStatus>(`/runs/${encodeURIComponent(runId)}/tts`);
export const cancelRunTts = (runId: string) =>
  request<{ cancelled: boolean; run_id: string }>(
    `/runs/${encodeURIComponent(runId)}/tts/cancel`,
    { method: 'POST', body: '{}' },
  );
export const getRunTtsChunks = (runId: string) =>
  request<RunTtsChunksResponse>(`/runs/${encodeURIComponent(runId)}/tts/chunks`);
export const getRunTtsSettings = (runId: string) =>
  request<RunTtsSettings>(`/runs/${encodeURIComponent(runId)}/tts/settings`);
export const updateRunTtsSettings = (
  runId: string,
  body: { tts: RunTtsSettings['tts']; channel_id?: string; save_to_channel?: boolean },
) =>
  request<{ saved: boolean; saved_channel: boolean; tts: RunTtsSettings['tts'] }>(
    `/runs/${encodeURIComponent(runId)}/tts/settings`,
    { method: 'PUT', body: JSON.stringify(body) },
  );

// ---- Jobs nền (tổng hợp mọi runner) ----------------------------------------
export const getActiveJobs = () =>
  request<{ jobs: BackgroundJob[]; busy: boolean }>('/jobs/active');
export const cancelBackgroundJob = (kind: string, jobId: string) =>
  request<{ cancelled: boolean; kind: string; job_id: string }>(
    `/jobs/${encodeURIComponent(kind)}/${encodeURIComponent(jobId)}/cancel`,
    { method: 'POST', body: '{}' },
  );

// ---- Lịch đăng video --------------------------------------------------------
export const getPublishSchedule = () =>
  request<PublishSchedule>('/publish/schedule');
export const setPublishSchedule = (runId: string, date: string | null) =>
  request<{ saved: boolean; run_id: string; date: string | null }>(
    '/publish/schedule',
    { method: 'POST', body: JSON.stringify({ run_id: runId, date }) },
  );

// ---- Channel profiles (multi-channel) --------------------------------------
export const listChannels = () =>
  request<{ channels: ChannelInfo[] }>('/channels');
export const getChannel = (channelId: string) =>
  request<Record<string, unknown>>(`/channels/${encodeURIComponent(channelId)}`);
export const saveChannel = (channelId: string, profile: Record<string, unknown>) =>
  request<{ saved: boolean; path: string }>(`/channels/${encodeURIComponent(channelId)}`, {
    method: 'PUT',
    body: JSON.stringify(profile),
  });
export const listRuns = () => request<{ runs: RunSummary[] }>('/runs');
export const getRun = (runId: string) =>
  request<RunDetail>(`/runs/${encodeURIComponent(runId)}`);
export const getRunStatus = (runId: string) =>
  request<RunStatus>(`/runs/${encodeURIComponent(runId)}/status`);
export const getRunDiagnostics = (runId: string) =>
  request<RunDiagnostics>(`/runs/${encodeURIComponent(runId)}/diagnostics`);

export const runEventsUrl = (runId: string) =>
  `${API_BASE}/runs/${encodeURIComponent(runId)}/events`;

export function connectRunEvents(
  runId: string,
  onEvent: (event: RunEvent) => void,
  onOpen?: () => void,
  onError?: () => void,
): EventSource {
  const source = new EventSource(runEventsUrl(runId));
  source.onopen = () => onOpen?.();
  source.onerror = () => onError?.();
  source.addEventListener('run_update', (message) => {
    try {
      onEvent(JSON.parse((message as MessageEvent).data) as RunEvent);
    } catch (error) {
      console.error('Invalid run_update SSE payload', error);
    }
  });
  return source;
}
export const startRun = (body: NewRunBody) =>
  request<{ run_id: string; status: string; log_path: string }>('/runs', {
    method: 'POST',
    body: JSON.stringify(body),
  });
export const resumeRun = (runId: string) =>
  request<{ run_id: string; resumed: boolean; status: string }>(
    `/runs/${encodeURIComponent(runId)}/resume`,
    { method: 'POST', body: '{}' },
  );
export const updateTopicStatus = (runId: string, status: 'drafted' | 'published' | 'archived') =>
  request<{ run_id: string; topic_status: string }>(
    `/runs/${encodeURIComponent(runId)}/topic-status`,
    { method: 'POST', body: JSON.stringify({ status }) },
  );
export const cancelRun = (runId: string) =>
  request<{ cancelled: boolean; run_id: string }>(
    `/runs/${encodeURIComponent(runId)}/cancel`,
    { method: 'POST', body: '{}' },
  );
export const deleteRun = (runId: string) =>
  request<{ deleted: boolean; run_id: string }>(
    `/runs/${encodeURIComponent(runId)}`,
    { method: 'DELETE' },
  );
export const getLog = (runId: string, offset = 0, limit = 200) =>
  request<LogPage>(
    `/runs/${encodeURIComponent(runId)}/log?offset=${offset}&limit=${limit}`,
  );
export const getArtifactTree = (runId: string) =>
  request<{ run_id: string; tree: ArtifactTree }>(
    `/runs/${encodeURIComponent(runId)}/artifacts`,
  );

export function artifactUrl(
  runId: string,
  path: string,
  download = false,
): string {
  const encPath = path
    .split('/')
    .map((s) => encodeURIComponent(s))
    .join('/');
  let url = `${API_BASE}/runs/${encodeURIComponent(runId)}/artifacts/${encPath}`;
  if (download) url += '?download=1';
  return url;
}

export async function getArtifactText(
  runId: string,
  path: string,
): Promise<string> {
  const url = artifactUrl(runId, path);
  const resp = await fetch(url);
  if (!resp.ok) {
    let detail: unknown = resp.statusText;
    try {
      detail = await resp.json();
    } catch {
      /* không phải JSON */
    }
    const { ApiError } = await import('./apiClient');
    throw new ApiError(resp.status, detail);
  }
  return resp.text();
}

export const logDownloadUrl = (runId: string) =>
  `${API_BASE}/runs/${encodeURIComponent(runId)}/log?download=1`;
