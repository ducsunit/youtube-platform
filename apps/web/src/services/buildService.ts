import type {
  BuildImportResult,
  BuildJob,
  BuildJobStarted,
  BuildStartBody,
  BuildStatus,
  LogPage,
  SubStyle,
} from '../types';
import { API_BASE, request } from './apiClient';

export const getBuildStatus = (runId: string) =>
  request<BuildStatus>(`/build/runs/${encodeURIComponent(runId)}/status`);

export const mergeTtsChunks = (runId: string) =>
  request<{ run_id: string; output: string; chunks: number; size_bytes: number }>(
    `/build/runs/${encodeURIComponent(runId)}/merge-tts-chunks`,
    { method: 'POST', body: '{}' },
  );

export const getSubStyle = (runId: string) =>
  request<{ run_id: string; style: SubStyle }>(
    `/build/runs/${encodeURIComponent(runId)}/sub-style`,
  );

export const putSubStyle = (runId: string, substyle: SubStyle) =>
  request<{ run_id: string; saved: boolean; style: SubStyle }>(
    `/build/runs/${encodeURIComponent(runId)}/sub-style`,
    { method: 'PUT', body: JSON.stringify(substyle) },
  );

export const importPackImages = (
  runId: string,
  body: { source_dir: string; insert?: string; apply?: boolean },
) =>
  request<BuildImportResult>(
    `/build/${encodeURIComponent(runId)}/import-images`,
    { method: 'POST', body: JSON.stringify(body) },
  );

export const startBuild = (runId: string, body: BuildStartBody) =>
  request<BuildJobStarted>(`/build/runs/${encodeURIComponent(runId)}/build`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const getBuildJob = (jobId: string) =>
  request<BuildJob>(`/build/jobs/${encodeURIComponent(jobId)}`);

export const cancelBuildJob = (jobId: string) =>
  request<{ cancelled: boolean; job_id: string }>(
    `/build/jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: 'POST', body: '{}' },
  );

export const getBuildJobLog = (jobId: string, offset = 0, limit = 200) =>
  request<LogPage>(
    `/build/jobs/${encodeURIComponent(jobId)}/log?offset=${offset}&limit=${limit}`,
  );

export const buildJobLogDownloadUrl = (jobId: string) =>
  `${API_BASE}/build/jobs/${encodeURIComponent(jobId)}/log?download=1`;
