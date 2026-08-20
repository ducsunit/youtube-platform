import { request } from './apiClient';
import type { ModelConfig } from '../types';

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
