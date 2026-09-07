import type {
  BuildImportResult,
  BuildJob,
  BuildJobStarted,
  BuildStartBody,
  BuildStatus,
  ChannelScope,
  LogPage,
  SubStyle,
} from '../types';
import { API_BASE, request } from './apiClient';

function scopeQuery(scope?: ChannelScope): string {
  if (!scope?.user_id || !scope.channel_id) return '';
  return `user_id=${encodeURIComponent(scope.user_id)}&channel_id=${encodeURIComponent(scope.channel_id)}`;
}

function scopedPath(path: string, scope?: ChannelScope): string {
  const query = scopeQuery(scope);
  return query ? `${path}${path.includes('?') ? '&' : '?'}${query}` : path;
}

export const getBuildStatus = (runId: string, scope?: ChannelScope) =>
  request<BuildStatus>(scopedPath(`/build/runs/${encodeURIComponent(runId)}/status`, scope));

export const mergeTtsChunks = (runId: string, scope?: ChannelScope) =>
  request<{ run_id: string; output: string; chunks: number; size_bytes: number }>(
    scopedPath(`/build/runs/${encodeURIComponent(runId)}/merge-tts-chunks`, scope),
    { method: 'POST', body: '{}' },
  );

export const getSubStyle = (runId: string, scope?: ChannelScope) =>
  request<{ run_id: string; style: SubStyle }>(
    scopedPath(`/build/runs/${encodeURIComponent(runId)}/sub-style`, scope),
  );

export const putSubStyle = (runId: string, substyle: SubStyle, scope?: ChannelScope) =>
  request<{ run_id: string; saved: boolean; style: SubStyle }>(
    scopedPath(`/build/runs/${encodeURIComponent(runId)}/sub-style`, scope),
    { method: 'PUT', body: JSON.stringify(substyle) },
  );

export const importPackImages = (
  runId: string,
  body: { source_dir: string; insert?: string; apply?: boolean },
  scope?: ChannelScope,
) =>
  request<BuildImportResult>(
    scopedPath(`/build/runs/${encodeURIComponent(runId)}/import-images`, scope),
    { method: 'POST', body: JSON.stringify(body) },
  );

export const startBuild = (runId: string, body: BuildStartBody, scope?: ChannelScope) =>
  request<BuildJobStarted>(scopedPath(`/build/runs/${encodeURIComponent(runId)}/build`, scope), {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const getBuildJob = (jobId: string, scope?: ChannelScope) =>
  request<BuildJob>(scopedPath(`/build/jobs/${encodeURIComponent(jobId)}`, scope));

export const cancelBuildJob = (jobId: string, scope?: ChannelScope) =>
  request<{ cancelled: boolean; job_id: string }>(
    scopedPath(`/build/jobs/${encodeURIComponent(jobId)}/cancel`, scope),
    { method: 'POST', body: '{}' },
  );

export const getBuildJobLog = (jobId: string, offset = 0, limit = 200, scope?: ChannelScope) =>
  request<LogPage>(
    scopedPath(`/build/jobs/${encodeURIComponent(jobId)}/log?offset=${offset}&limit=${limit}`, scope),
  );

export const buildJobLogDownloadUrl = (jobId: string, scope?: ChannelScope) =>
  `${API_BASE}${scopedPath(`/build/jobs/${encodeURIComponent(jobId)}/log?download=1`, scope)}`;
