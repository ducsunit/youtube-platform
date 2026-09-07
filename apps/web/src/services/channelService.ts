import type {
  ChannelContext,
  ChannelListResponse,
  ChannelResponse,
  RegisterChannelBody,
  UpdateChannelBody,
} from '../types';
import { request } from './apiClient';

const channelQuery = (userId: string, includeInactive = false) =>
  `?user_id=${encodeURIComponent(userId)}&include_inactive=${includeInactive ? 'true' : 'false'}`;

export const listChannels = (userId: string, includeInactive = false) =>
  request<ChannelListResponse>(`/channels${channelQuery(userId, includeInactive)}`);

export const getChannel = (userId: string, channelId: string) =>
  request<ChannelResponse>(
    `/channels/${encodeURIComponent(channelId)}?user_id=${encodeURIComponent(userId)}`,
  );

export const registerChannel = (body: RegisterChannelBody) =>
  request<ChannelResponse>('/channels', {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const updateChannel = (channelId: string, body: UpdateChannelBody) =>
  request<ChannelResponse>(`/channels/${encodeURIComponent(channelId)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });

export const deactivateChannel = (userId: string, channelId: string) =>
  request<ChannelResponse>(
    `/channels/${encodeURIComponent(channelId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

export const channelScope = (channel: ChannelContext) => ({
  user_id: channel.user_id,
  channel_id: channel.channel_id,
});
