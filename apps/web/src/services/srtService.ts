import type { LogPage, SrtInputs, SrtJob, SrtStatus } from '../types';
import { request } from './apiClient';

export const getSrtStatus = () => request<SrtStatus>('/srt/status');
export const getSrtInputs = (runId: string) => request<SrtInputs>(`/srt/runs/${encodeURIComponent(runId)}/inputs`);
export const startSrtGenerate = (runId: string, body: { model?: string; device?: string; mode?: string; max_chars?: number }) =>
  request<{ job_id: string; run_id: string }>(`/srt/runs/${encodeURIComponent(runId)}/generate`, { method: 'POST', body: JSON.stringify(body) });
export const getSrtJob = (jobId: string) => request<SrtJob>(`/srt/jobs/${encodeURIComponent(jobId)}`);
export const cancelSrtJob = (jobId: string) => request<{ cancelled: boolean; job_id: string }>(`/srt/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST', body: '{}' });
export const getSrtJobLog = (jobId: string, offset = 0, limit = 200) => request<LogPage>(`/srt/jobs/${encodeURIComponent(jobId)}/log?offset=${offset}&limit=${limit}`);
