import { request } from './apiClient';
import type { ModelConfig, ModelPreflight } from '../types';

export function getModelConfig(): Promise<ModelConfig> {
  return request<ModelConfig>('/model-config');
}

export function updateModelConfig(body: {
  profiles: Record<string, Record<string, unknown>>;
  role_profiles: Record<string, string>;
}): Promise<ModelConfig> {
  return request<ModelConfig>('/model-config', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export function preflightModelConfig(): Promise<ModelPreflight> {
  return request<ModelPreflight>('/model-config/preflight', {
    method: 'POST',
    body: '{}',
  });
}
