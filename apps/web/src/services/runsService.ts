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
} from '../types';
import { API_BASE, request } from './apiClient';

export const getConfig = () => request<ServerConfig>('/config');
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
