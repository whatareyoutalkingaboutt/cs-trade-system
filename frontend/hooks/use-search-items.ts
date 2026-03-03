import { useEffect, useState } from "react";
import useSWR from "swr";

import { buildRowsFromSearch } from "@/lib/market";
import { API_BASE } from "@/lib/api";
import type { SearchItem, TableRow } from "@/lib/types";

type SearchResponse = {
  source?: string;
  data?: SearchItem[];
};

const fetcher = async (url: string): Promise<SearchResponse> => {
  const response = await fetch(url);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.success === false) {
    const message = payload.detail || payload.error || "搜索失败";
    throw new Error(message);
  }
  return payload;
};

export function useSearchItems(query: string) {
  const key = query ? `${API_BASE}/api/items/search?q=${encodeURIComponent(query)}&limit=20` : null;
  const { data, error, isLoading, isValidating } = useSWR<SearchResponse>(key, fetcher, {
    keepPreviousData: true,
    revalidateOnFocus: false,
  });

  const [rows, setRows] = useState<TableRow[]>([]);

  useEffect(() => {
    if (!query) {
      setRows([]);
      return;
    }
    if (data?.data) {
      setRows((prev) => buildRowsFromSearch(data.data as SearchItem[], prev));
    }
  }, [data, query]);

  return {
    rows,
    source: data?.source,
    error: error ? (error as Error).message : null,
    isLoading,
    isValidating,
  };
}
