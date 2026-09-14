import type {
  PSRunBody,
  PSRunResponse,
  PSRunStatus,
  PSRunList,
  PSRunListItem,
  PSArtifactList,
  PSArtifactContent,
} from '../types';
import { request } from './apiClient';

const PS_BASE = '/api/ps-pipeline';

export const startPSRun = (body: PSRunBody) =>
  request<PSRunResponse>(`${PS_BASE}/runs`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const listPSRuns = () =>
  request<{ runs: PSRunListItem[] }>(`${PS_BASE}/runs`);

export const getPSRunStatus = (runId: string) =>
  request<PSRunStatus>(`${PS_BASE}/runs/${encodeURIComponent(runId)}/status`);

export const listPSArtifacts = (runId: string) =>
  request<{ run_id: string; artifacts: Record<string, { type: string; size_bytes: number; path: string }> }>(
    `${PS_BASE}/runs/${encodeURIComponent(runId)}/artifacts`
  );

export const getPSArtifact = (runId: string, path: string) =>
  fetch(`${API_BASE}/ps-pipeline/runs/${encodeURIComponent(runId)}/artifact?path=${encodeURIComponent(path)}`);

export const cancelPSRun = (runId: string) =>
  request<{ cancelled: boolean; run_id: string }>(
    `/api/ps-pipeline/runs/${encodeURIComponent(runId)}/cancel`,
    { method: 'POST', body: '{}' }
  );

export const deletePSRun = (runId: string) =>
  request<{ deleted: boolean; run_id: string }>(
    `/api/ps-pipeline/runs/${encodeURIComponent(runId)}`,
    { method: 'DELETE' }
  );

export const psPipelineEventsUrl = (runId: string) =>
  `${API_BASE}/ps-pipeline/runs/${encodeURIComponent(runId)}/events`; // If SSE is implemented

export function connectPSPipelineEvents(
  runId: string,
  onEvent: (event: any) => void,
  onOpen?: () => void,
  onError?: () => void,
): EventSource {
  const source = new EventSource(`${API_BASE}/ps-pipeline/runs/${encodeURIComponent(runId)}/events`);
  source.onopen = () => onOpen?.();
  source.onerror = () => onError?.();
  source.addEventListener('run_update', (message) => {
    try {
      onEvent(JSON.parse((message as MessageEvent).data));
    } catch (error) {
      console.error('Invalid SSE payload', error);
    }
  });
  return source;
}

export const startPSRun = (body: {
  topic: string;
  mode?: 'demo' | 'production';
  run_id?: string;
  manual_brief?: string;
}) => startPSRun({
  topic: body.topic,
  mode: body.mode || 'production',
  run_id: body.run_id,
  manual_brief: body.manual_brief,
});