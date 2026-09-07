import type {
  DataJob,
  DataJobStarted,
  DataPullBody,
  DataReportingBody,
  DataStatus,
  LogPage,
} from '../types';
import { API_BASE, request } from './apiClient';

type DataScope = Pick<DataPullBody, 'user_id' | 'channel_id'>;
type ConnectScope = Pick<DataPullBody, 'user_id' | 'channel_id' | 'youtube_channel_id'>;

const scopeQuery = (scope?: DataScope) => {
  if (!scope?.user_id || !scope.channel_id) return '';
  return `&user_id=${encodeURIComponent(scope.user_id)}&channel_id=${encodeURIComponent(scope.channel_id)}`;
};

export const getDataStatus = (scope?: DataScope) => {
  const query = scopeQuery(scope).replace(/^&/, '?');
  return request<DataStatus>(`/data/status${query}`);
};

export const connectData = (scope?: ConnectScope) =>
  request<DataJobStarted>('/data/connect', {
    method: 'POST',
    body: JSON.stringify(scope ?? {}),
  });

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

export const getDataJob = (jobId: string, scope?: DataScope) =>
  request<DataJob>(`/data/jobs/${encodeURIComponent(jobId)}?${scopeQuery(scope).replace(/^&/, '')}`);

export const cancelDataJob = (jobId: string, scope?: DataScope) =>
  request<{ cancelled: boolean; job_id: string }>(
    `/data/jobs/${encodeURIComponent(jobId)}/cancel?${scopeQuery(scope).replace(/^&/, '')}`,
    { method: 'POST', body: '{}' },
  );

export const getDataJobLog = (jobId: string, offset = 0, limit = 200, scope?: DataScope) =>
  request<LogPage>(
    `/data/jobs/${encodeURIComponent(jobId)}/log?offset=${offset}&limit=${limit}${scopeQuery(scope)}`,
  );

export const dataJobLogDownloadUrl = (jobId: string, scope?: DataScope) =>
  `${API_BASE}/data/jobs/${encodeURIComponent(jobId)}/log?download=1${scopeQuery(scope)}`;
