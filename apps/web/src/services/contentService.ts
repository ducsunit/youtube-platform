import type {
  ContentQueue,
  CulturalFrameInfo,
  MechanismInfo,
  QueueActionResult,
} from '../types';
import { request } from './apiClient';

export const getContentQueue = () => request<ContentQueue>('/content/queue');
export const getMechanisms = () =>
  request<{ mechanisms: Record<string, MechanismInfo> }>('/content/mechanisms');
export const getCulturalFrames = () =>
  request<{ frames: Record<string, CulturalFrameInfo> }>(
    '/content/cultural-frames',
  );
export const markQueueInProgress = (topicName: string) =>
  request<QueueActionResult>('/content/queue/in-progress', {
    method: 'POST',
    body: JSON.stringify({ hien_tuong: topicName }),
  });
export const publishQueueTopic = (
  topicName: string,
  mechanism: string,
  frame: string,
) =>
  request<QueueActionResult>('/content/queue/publish', {
    method: 'POST',
    body: JSON.stringify({
      hien_tuong: topicName,
      mechanism,
      cultural_frame: frame,
    }),
  });
export const setQueueVideoId = (topicName: string, videoId: string) =>
  request<QueueActionResult>('/content/queue/set-video-id', {
    method: 'POST',
    body: JSON.stringify({ hien_tuong: topicName, video_id: videoId }),
  });
