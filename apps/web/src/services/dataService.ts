import type {
  DataJob,
  DataJobStarted,
  DataPullBody,
  DataReportingBody,
  DataStatus,
  LogPage,
} from '../types';
import { API_BASE, request } from './apiClient';

export const getDataStatus = () => request<DataStatus>('/data/status');
export const connectData = () =>
  request<DataJobStarted>('/data/connect', { method: 'POST', body: '{}' });
export const pullData = (body: DataPullBody) =>
  request<DataJobStarted>('/data/pull', {
    method: 'POST',
    body: JSON.stringify(body),
  });
export const reportingData = (body: DataReportingBody) =>
  request<DataJobStarted>('/data/reporting', {
    method: 'POST',
    body: JSON.stringify(body),
  });
export const getDataJob = (jobId: string) =>
  request<DataJob>(`/data/jobs/${encodeURIComponent(jobId)}`);
export const cancelDataJob = (jobId: string) =>
  request<{ cancelled: boolean; job_id: string }>(
    `/data/jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: 'POST', body: '{}' },
  );
export const getDataJobLog = (jobId: string, offset = 0, limit = 200) =>
  request<LogPage>(
    `/data/jobs/${encodeURIComponent(jobId)}/log?offset=${offset}&limit=${limit}`,
  );
export const dataJobLogDownloadUrl = (jobId: string) =>
  `${API_BASE}/data/jobs/${encodeURIComponent(jobId)}/log?download=1`;
