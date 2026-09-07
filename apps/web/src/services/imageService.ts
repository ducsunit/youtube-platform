import type { ChannelScope, ImageConfig, ImageJob, ImagePrompts, ImageStatus, LogPage } from '../types';
import { API_BASE, request } from './apiClient';

function scopedPath(path: string, scope?: ChannelScope): string {
  if (!scope?.user_id || !scope.channel_id) return path;
  const query = `user_id=${encodeURIComponent(scope.user_id)}&channel_id=${encodeURIComponent(scope.channel_id)}`;
  return `${path}${path.includes('?') ? '&' : '?'}${query}`;
}

export const getImageStatus = (scope?: ChannelScope) => request<ImageStatus>(scopedPath('/images/status', scope));
export const getImageConfig = (scope?: ChannelScope) => request<ImageConfig>(scopedPath('/images/config', scope));
export const updateImageConfig = (body: { model: string; base_url: string; api_key_env: string; api_key?: string; default_size: string; default_quality: string }, scope?: ChannelScope) =>
  request<ImageConfig>(scopedPath('/images/config', scope), { method: 'PUT', body: JSON.stringify(body) });
export const getImagePrompts = (runId: string, scope?: ChannelScope) =>
  request<ImagePrompts>(scopedPath(`/images/runs/${encodeURIComponent(runId)}/prompts`, scope));
export const startImageGenerate = (runId: string, body: {
  images: string[];
  model?: string;
  size?: string;
  quality?: string;
  skip_existing?: boolean;
}, scope?: ChannelScope) => request<{ job_id: string | null; run_id: string; images: string[]; status?: string }>(
  scopedPath(`/images/runs/${encodeURIComponent(runId)}/generate`, scope),
  { method: 'POST', body: JSON.stringify(body) },
);
export const getImageJob = (jobId: string, scope?: ChannelScope) => request<ImageJob>(scopedPath(`/images/jobs/${encodeURIComponent(jobId)}`, scope));
export const cancelImageJob = (jobId: string, scope?: ChannelScope) => request<{ cancelled: boolean; job_id: string }>(
  scopedPath(`/images/jobs/${encodeURIComponent(jobId)}/cancel`, scope), { method: 'POST', body: '{}' },
);
export const getImageJobLog = (jobId: string, offset = 0, limit = 200, scope?: ChannelScope) =>
  request<LogPage>(scopedPath(`/images/jobs/${encodeURIComponent(jobId)}/log?offset=${offset}&limit=${limit}`, scope));
export const imageJobLogDownloadUrl = (jobId: string, scope?: ChannelScope) => `${API_BASE}${scopedPath(`/images/jobs/${encodeURIComponent(jobId)}/log?download=1`, scope)}`;
