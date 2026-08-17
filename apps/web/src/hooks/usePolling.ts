import { useCallback, useEffect, useRef, useState } from 'react';

interface UsePollingOptions {
  enabled: boolean;
  intervalMs: number;
}

/**
 * Poll một fetcher cho tới khi `enabled` đổi sang false.
 * - Chuỗi setTimeout (không dùng setInterval) — mỗi lần tick đợi fetch xong
 *   mới lên lịch lượt sau, tránh chồng request.
 * - Cleanup timeout khi unmount — an toàn với StrictMode double-mount.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  { enabled, intervalMs }: UsePollingOptions,
): { data: T | null; error: unknown; refresh: () => Promise<void> } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(async () => {
    try {
      setData(await fetcherRef.current());
      setError(null);
    } catch (e) {
      setError(e);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timeoutId: number | null = null;

    const tick = async () => {
      if (cancelled) return;
      try {
        const result = await fetcherRef.current();
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e);
      }
      if (!cancelled) {
        timeoutId = window.setTimeout(tick, intervalMs);
      }
    };
    void tick();
    return () => {
      cancelled = true;
      if (timeoutId !== null) window.clearTimeout(timeoutId);
    };
  }, [enabled, intervalMs]);

  return { data, error, refresh };
}
