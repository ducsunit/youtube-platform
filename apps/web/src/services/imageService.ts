import type { ImageConfig, ImageJob, ImagePrompts, ImageStatus, LogPage } from '../types';
import { API_BASE, request } from './apiClient';

export const getImageStatus = () => request<ImageStatus>('/images/status');
export const getImageConfig = () => request<ImageConfig>('/images/config');
export const updateImageConfig = (body: { model: string; base_url: string; api_key_env: string; api_key?: string; default_size: string; default_quality: string }) =>
  request<ImageConfig>('/images/config', { method: 'PUT', body: JSON.stringify(body) });
export const getImagePrompts = (runId: string) =>
  request<ImagePrompts>(`/images/runs/${encodeURIComponent(runId)}/prompts`);
export const startImageGenerate = (runId: string, body: {
  images: string[];
  model?: string;
  size?: string;
  quality?: string;
  skip_existing?: boolean;
}) => request<{ job_id: string | null; run_id: string; images: string[]; status?: string }>(
  `/images/runs/${encodeURIComponent(runId)}/generate`,
  { method: 'POST', body: JSON.stringify(body) },
);
export const getImageJob = (jobId: string) => request<ImageJob>(`/images/jobs/${encodeURIComponent(jobId)}`);
export const cancelImageJob = (jobId: string) => request<{ cancelled: boolean; job_id: string }>(
  `/images/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST', body: '{}' },
);
export const getImageJobLog = (jobId: string, offset = 0, limit = 200) =>
  request<LogPage>(`/images/jobs/${encodeURIComponent(jobId)}/log?offset=${offset}&limit=${limit}`);
export const imageJobLogDownloadUrl = (jobId: string) => `${API_BASE}/images/jobs/${encodeURIComponent(jobId)}/log?download=1`;
