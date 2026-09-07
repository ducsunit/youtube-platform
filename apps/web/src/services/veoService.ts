import type {
  ChannelScope,
  LogPage,
  VeoCandidates,
  VeoGenerateBody,
  VeoJob,
  VeoJobStarted,
  VeoStatus,
} from '../types';
import { API_BASE, request } from './apiClient';

function scopedPath(path: string, scope?: ChannelScope): string {
  if (!scope?.user_id || !scope.channel_id) return path;
  const query = `user_id=${encodeURIComponent(scope.user_id)}&channel_id=${encodeURIComponent(scope.channel_id)}`;
  return `${path}${path.includes('?') ? '&' : '?'}${query}`;
}

export const getVeoStatus = (scope?: ChannelScope) =>
  request<VeoStatus>(scopedPath('/veo/status', scope));

export const getVeoCandidates = (runId: string, scope?: ChannelScope) =>
  request<VeoCandidates>(scopedPath(`/veo/runs/${encodeURIComponent(runId)}/candidates`, scope));

export const startVeoGenerate = (runId: string, body: VeoGenerateBody, scope?: ChannelScope) =>
  request<VeoJobStarted>(scopedPath(`/veo/runs/${encodeURIComponent(runId)}/generate`, scope), {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const getVeoJob = (jobId: string, scope?: ChannelScope) =>
  request<VeoJob>(scopedPath(`/veo/jobs/${encodeURIComponent(jobId)}`, scope));

export const cancelVeoJob = (jobId: string, scope?: ChannelScope) =>
  request<{ cancelled: boolean; job_id: string }>(
    scopedPath(`/veo/jobs/${encodeURIComponent(jobId)}/cancel`, scope),
    { method: 'POST', body: '{}' },
  );

export const getVeoJobLog = (jobId: string, offset = 0, limit = 200, scope?: ChannelScope) =>
  request<LogPage>(
    scopedPath(`/veo/jobs/${encodeURIComponent(jobId)}/log?offset=${offset}&limit=${limit}`, scope),
  );

export const veoJobLogDownloadUrl = (jobId: string, scope?: ChannelScope) =>
  `${API_BASE}${scopedPath(`/veo/jobs/${encodeURIComponent(jobId)}/log?download=1`, scope)}`;
