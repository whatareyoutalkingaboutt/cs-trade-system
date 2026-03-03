import { useCallback, useEffect, useState } from "react";

import { API_BASE } from "@/lib/api";
import { buildRowsFromSearch } from "@/lib/market";
import type { SearchItem, TableRow } from "@/lib/types";

export function useMarketData() {
  const [rows, setRows] = useState<TableRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/items/search?limit=200&use_cache=true`);
      const payload = await response.json();
      if (!response.ok || !payload.success) {
        const message = payload?.detail || payload?.error || "数据获取失败";
        throw new Error(message);
      }
      const data = (payload.data || []) as SearchItem[];
      setRows((prev) => buildRowsFromSearch(data, prev));
    } catch (err) {
      setError(err instanceof Error ? err.message : "数据获取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { rows, setRows, loading, error, refresh };
}
