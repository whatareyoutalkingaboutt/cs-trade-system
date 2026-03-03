import { useEffect, useState } from "react";

import { mapKlineToSeries, type CandlePoint } from "@/lib/kline";

export type KlineQuery = {
  name: string;
  platform?: string;
  interval?: string;
  lookbackDays?: number;
};

type KlineState = {
  series: CandlePoint[];
  loading: boolean;
  error: string | null;
};

const DEFAULT_API_BASE = "http://localhost:8000";

function resolveApiBase() {
  const configured = process.env.NEXT_PUBLIC_API_URL;
  if (configured) return configured;
  if (typeof window === "undefined") return DEFAULT_API_BASE;
  return `${window.location.protocol}//${window.location.host}`;
}

export function useKline(query?: KlineQuery | null): KlineState {
  const [series, setSeries] = useState<CandlePoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!query?.name) {
      setSeries([]);
      setError(null);
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const base = resolveApiBase();
        const params = new URLSearchParams({
          marketHashName: query.name,
          platform: query.platform ?? "buff",
          interval: query.interval ?? "1h",
        });
        if (query.lookbackDays) {
          params.set("lookback_days", String(query.lookbackDays));
        }
        const response = await fetch(`${base}/api/prices/kline?${params.toString()}`, {
          signal: controller.signal,
        });
        const payload = await response.json();
        if (!response.ok || !payload.success) {
          throw new Error(payload.detail || payload.error || "K线数据获取失败");
        }
        const mapped = mapKlineToSeries(payload.data || []);
        setSeries(mapped);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setError(err instanceof Error ? err.message : "K线数据获取失败");
        setSeries([]);
      } finally {
        setLoading(false);
      }
    };

    load();

    return () => controller.abort();
  }, [query?.name, query?.platform, query?.interval, query?.lookbackDays]);

  return { series, loading, error };
}
