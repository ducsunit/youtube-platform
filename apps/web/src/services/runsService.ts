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
import { API_BASE, authenticatedUrl, authHeaders, request } from './apiClient';

export type RunScope = { user_id: string; channel_id: string };

function scopeQuery(scope?: RunScope): string {
  if (!scope?.user_id || !scope.channel_id) return '';
  return `user_id=${encodeURIComponent(scope.user_id)}&channel_id=${encodeURIComponent(scope.channel_id)}`;
}

function appendScope(path: string, scope?: RunScope): string {
  const query = scopeQuery(scope);
  if (!query) return path;
  return `${path}${path.includes('?') ? '&' : '?'}${query}`;
}

export const getConfig = (scope?: RunScope) =>
  request<ServerConfig>(appendScope('/config', scope));
export const listRuns = (scope?: RunScope) =>
  request<{ runs: RunSummary[] }>(appendScope('/runs', scope));
export const getRun = (runId: string, scope?: RunScope) =>
  request<RunDetail>(appendScope(`/runs/${encodeURIComponent(runId)}`, scope));
export const getRunStatus = (runId: string, scope?: RunScope) =>
  request<RunStatus>(appendScope(`/runs/${encodeURIComponent(runId)}/status`, scope));
export const getRunDiagnostics = (runId: string, scope?: RunScope) =>
  request<RunDiagnostics>(appendScope(`/runs/${encodeURIComponent(runId)}/diagnostics`, scope));

export const runEventsUrl = (runId: string, scope?: RunScope) =>
  authenticatedUrl(appendScope(`${API_BASE}/runs/${encodeURIComponent(runId)}/events`, scope));

export function connectRunEvents(
  runId: string,
  onEvent: (event: RunEvent) => void,
  onOpen?: () => void,
  onError?: () => void,
  scope?: RunScope,
): EventSource {
  const source = new EventSource(runEventsUrl(runId, scope));
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
export const resumeRun = (runId: string, scope?: RunScope) =>
  request<{ run_id: string; resumed: boolean; status: string }>(
    appendScope(`/runs/${encodeURIComponent(runId)}/resume`, scope),
    { method: 'POST', body: '{}' },
  );
export const updateTopicStatus = (runId: string, status: 'drafted' | 'published' | 'archived', scope?: RunScope) =>
  request<{ run_id: string; topic_status: string }>(
    appendScope(`/runs/${encodeURIComponent(runId)}/topic-status`, scope),
    { method: 'POST', body: JSON.stringify({ status }) },
  );
export const cancelRun = (runId: string, scope?: RunScope) =>
  request<{ cancelled: boolean; run_id: string }>(
    appendScope(`/runs/${encodeURIComponent(runId)}/cancel`, scope),
    { method: 'POST', body: '{}' },
  );
export const deleteRun = (runId: string, scope?: RunScope) =>
  request<{ deleted: boolean; run_id: string }>(
    appendScope(`/runs/${encodeURIComponent(runId)}`, scope),
    { method: 'DELETE' },
  );
export const getLog = (runId: string, offset = 0, limit = 200, scope?: RunScope) =>
  request<LogPage>(
    appendScope(`/runs/${encodeURIComponent(runId)}/log?offset=${offset}&limit=${limit}`, scope),
  );
export const getArtifactTree = (runId: string, scope?: RunScope) =>
  request<{ run_id: string; tree: ArtifactTree }>(
    appendScope(`/runs/${encodeURIComponent(runId)}/artifacts`, scope),
  );

export const artifactUrl = (runId: string, path: string, download = false, scope?: RunScope): string => {
  const encPath = path.split('/').map((s) => encodeURIComponent(s)).join('/');
  let url = appendScope(`${API_BASE}/runs/${encodeURIComponent(runId)}/artifact?path=${encPath}`, scope);
  url += `&download=${download ? '1' : '0'}`;
  return url;
};

export async function getArtifactText(runId: string, path: string, scope?: RunScope): Promise<string> {
  const resp = await fetch(artifactUrl(runId, path, false, scope), { headers: authHeaders() });
  if (!resp.ok) {
    let detail: unknown = resp.statusText;
    try { detail = await resp.json(); } catch { /* not JSON */ }
    const { ApiError } = await import('./apiClient');
    throw new ApiError(resp.status, detail);
  }
  return resp.text();
}

export const logDownloadUrl = (runId: string, scope?: RunScope) =>
  appendScope(`${API_BASE}/runs/${encodeURIComponent(runId)}/log?download=1`, scope);
