import type {
  LogPage,
  VeoCandidates,
  VeoGenerateBody,
  VeoJob,
  VeoJobStarted,
  VeoStatus,
} from '../types';
import { API_BASE, request } from './apiClient';

export const getVeoStatus = () => request<VeoStatus>('/veo/status');

export const getVeoCandidates = (runId: string) =>
  request<VeoCandidates>(`/veo/candidates/${encodeURIComponent(runId)}`);

export const startVeoGenerate = (runId: string, body: VeoGenerateBody) =>
  request<VeoJobStarted>(`/veo/generate/${encodeURIComponent(runId)}`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const getVeoJob = (jobId: string) =>
  request<VeoJob>(`/veo/jobs/${encodeURIComponent(jobId)}`);

export const cancelVeoJob = (jobId: string) =>
  request<{ cancelled: boolean; job_id: string }>(
    `/veo/jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: 'POST', body: '{}' },
  );

export const getVeoJobLog = (jobId: string, offset = 0, limit = 200) =>
  request<LogPage>(
    `/veo/jobs/${encodeURIComponent(jobId)}/log?offset=${offset}&limit=${limit}`,
  );

export const veoJobLogDownloadUrl = (jobId: string) =>
  `${API_BASE}/veo/jobs/${encodeURIComponent(jobId)}/log?download=1`;
