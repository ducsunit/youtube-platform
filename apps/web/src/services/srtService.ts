import type { ChannelScope, LogPage, SrtInputs, SrtJob, SrtStatus } from '../types';
import { request } from './apiClient';

function scopedPath(path: string, scope?: ChannelScope): string {
  if (!scope?.user_id || !scope.channel_id) return path;
  const query = `user_id=${encodeURIComponent(scope.user_id)}&channel_id=${encodeURIComponent(scope.channel_id)}`;
  return `${path}${path.includes('?') ? '&' : '?'}${query}`;
}

export const getSrtStatus = (scope?: ChannelScope) => request<SrtStatus>(scopedPath('/srt/status', scope));
export const getSrtInputs = (runId: string, scope?: ChannelScope) => request<SrtInputs>(scopedPath(`/srt/runs/${encodeURIComponent(runId)}/inputs`, scope));
export const startSrtGenerate = (runId: string, body: { model?: string; device?: string; mode?: string; max_chars?: number }, scope?: ChannelScope) =>
  request<{ job_id: string; run_id: string }>(scopedPath(`/srt/runs/${encodeURIComponent(runId)}/generate`, scope), { method: 'POST', body: JSON.stringify(body) });
export const getSrtJob = (jobId: string, scope?: ChannelScope) => request<SrtJob>(scopedPath(`/srt/jobs/${encodeURIComponent(jobId)}`, scope));
export const cancelSrtJob = (jobId: string, scope?: ChannelScope) => request<{ cancelled: boolean; job_id: string }>(scopedPath(`/srt/jobs/${encodeURIComponent(jobId)}/cancel`, scope), { method: 'POST', body: '{}' });
export const getSrtJobLog = (jobId: string, offset = 0, limit = 200, scope?: ChannelScope) => request<LogPage>(scopedPath(`/srt/jobs/${encodeURIComponent(jobId)}/log?offset=${offset}&limit=${limit}`, scope));
