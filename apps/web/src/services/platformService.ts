import { request } from './apiClient';

export interface ReindexResult {
  indexed: number;
  skipped: number;
  failures: Array<{ run_id: string; run_dir: string; error: string }>;
}

export const reindexPlatform = () =>
  request<ReindexResult>('/platform/reindex', { method: 'POST', body: '{}' });
