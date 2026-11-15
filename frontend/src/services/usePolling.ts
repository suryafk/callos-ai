import { useCallback, useEffect, useRef, useState } from "react";

/** Load data now and refresh it on an interval while the tab is visible. */
export function usePolling<T>(loader: () => Promise<T>, deps: unknown[] = [], intervalMs = 5000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const refresh = useCallback(async () => {
    try {
      setData(await loaderRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void refresh();
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, intervalMs);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, intervalMs, ...deps]);

  return { data, error, loading, refresh };
}
