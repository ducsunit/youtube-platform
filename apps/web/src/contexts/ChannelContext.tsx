import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { listChannels } from '../services/channelService';
import type { ChannelContext as Channel, ChannelScope } from '../types';

interface ChannelContextValue {
  channels: Channel[];
  currentChannel: Channel | null;
  scope: ChannelScope | null;
  loading: boolean;
  error: unknown;
  selectChannel: (channelId: string) => void;
  reload: () => Promise<void>;
}

const ChannelContext = createContext<ChannelContextValue | null>(null);
const DEFAULT_USER_ID = 'dev-user';

export function ChannelProvider({ children, userId = DEFAULT_USER_ID }: { children: ReactNode; userId?: string }) {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const response = await listChannels(userId);
      const validChannels = response.channels.filter((channel) =>
        /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(channel.channel_id),
      );
      setChannels(validChannels);
      setSelectedId((current) =>
        validChannels.some((channel) => channel.channel_id === current)
          ? current
          : validChannels[0]?.channel_id ?? null,
      );
      setError(null);
    } catch (reason) {
      setError(reason);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const currentChannel = channels.find((channel) => channel.channel_id === selectedId) ?? null;
  const value = useMemo<ChannelContextValue>(() => ({
    channels,
    currentChannel,
    scope: currentChannel ? { user_id: currentChannel.user_id, channel_id: currentChannel.channel_id } : null,
    loading,
    error,
    selectChannel: setSelectedId,
    reload,
  }), [channels, currentChannel, loading, error, reload]);

  return <ChannelContext.Provider value={value}>{children}</ChannelContext.Provider>;
}

export function useChannelContext(): ChannelContextValue {
  const context = useContext(ChannelContext);
  if (!context) throw new Error('useChannelContext must be used inside ChannelProvider');
  return context;
}
