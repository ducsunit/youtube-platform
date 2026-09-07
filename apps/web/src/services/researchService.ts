import type { ApproveResearchResponse, ResearchLogResponse, ResearchRun, StartResearchBody, StartResearchResponse, AtlasRequest, AtlasResponse, SuggestRequest, SuggestResponse } from '../types';
import { request } from './apiClient';

type Scope = { user_id: string; channel_id: string };

function query(scope: Scope): string {
  return `user_id=${encodeURIComponent(scope.user_id)}&channel_id=${encodeURIComponent(scope.channel_id)}`;
}

export const startResearch = (body: StartResearchBody) =>
  request<StartResearchResponse>('/research/runs', {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const runAtlas = (body: AtlasRequest) =>
  request<AtlasResponse>('/research/atlas', {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const suggestKeywords = (body: SuggestRequest) =>
  request<SuggestResponse>('/research/suggest', {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const getResearch = (researchRunId: string, scope: Scope) =>
  request<ResearchRun>(`/research/runs/${encodeURIComponent(researchRunId)}?${query(scope)}`);

export const getResearchLog = (researchRunId: string, scope: Scope) =>
  request<ResearchLogResponse>(`/research/runs/${encodeURIComponent(researchRunId)}/log?${query(scope)}`);

export const approveResearch = (researchRunId: string, opportunityId: string, scope: Scope) =>
  request<ApproveResearchResponse>(`/research/runs/${encodeURIComponent(researchRunId)}/approve?${query(scope)}`, {
    method: 'POST',
    body: JSON.stringify({ opportunity_id: opportunityId }),
  });
