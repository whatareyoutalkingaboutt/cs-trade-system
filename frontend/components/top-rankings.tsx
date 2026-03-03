"use client";

import { useState } from "react";
import useSWR from "swr";

import { API_BASE } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type RankingItem = {
  id: number;
  market_hash_name: string;
  image_url?: string | null;
  price?: number;
  volume?: number;
  change_pct?: number;
};

type RankingResponse = {
  success?: boolean;
  top_gainers?: RankingItem[];
  top_volume?: RankingItem[];
};

const fetcher = async (url: string): Promise<RankingResponse> => {
  const response = await fetch(url);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.success === false) {
    const message = payload.detail || payload.error || "获取榜单失败";
    throw new Error(message);
  }
  return payload as RankingResponse;
};

export function TopRankings() {
  const [tab, setTab] = useState<"gainers" | "volume">("gainers");
  const { data, error, isLoading } = useSWR<RankingResponse>(`${API_BASE}/api/items/rankings`, fetcher, {
    refreshInterval: 60_000,
    revalidateOnFocus: false,
  });

  const gainers = data?.top_gainers || [];
  const volumes = data?.top_volume || [];
  const list = tab === "gainers" ? gainers : volumes;

  return (
    <Card className="h-full">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="panel-title">市场风向标</p>
            <CardTitle className="text-base md:text-lg">24H 热门榜</CardTitle>
          </div>
          <div className="rounded-xl border border-slate-700/60 bg-slate-900/60 p-1">
            <button
              type="button"
              className={cn(
                "rounded-lg px-2 py-1 text-xs transition-colors",
                tab === "gainers" ? "bg-emerald-600/25 text-emerald-300" : "text-slate-400 hover:text-slate-200",
              )}
              onClick={() => setTab("gainers")}
            >
              涨幅榜
            </button>
            <button
              type="button"
              className={cn(
                "rounded-lg px-2 py-1 text-xs transition-colors",
                tab === "volume" ? "bg-sky-600/25 text-sky-300" : "text-slate-400 hover:text-slate-200",
              )}
              onClick={() => setTab("volume")}
            >
              活跃榜
            </button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? <p className="text-sm text-slate-400">榜单计算中...</p> : null}
        {error ? <p className="text-sm text-red-300">榜单加载失败</p> : null}
        {!isLoading && !error && list.length === 0 ? <p className="text-sm text-slate-400">暂无数据</p> : null}
        {!isLoading && !error && list.length > 0 ? (
          <div className="max-h-[520px] space-y-3 overflow-y-auto pr-1">
            {list.map((item, index) => {
              const price = Number(item.price || 0);
              const change = Number(item.change_pct || 0);
              const volume = Number(item.volume || 0);
              return (
                <div key={`${tab}-${item.id}-${index}`} className="flex items-center justify-between gap-3">
                  <div className="min-w-0 flex items-center gap-3">
                    <span className="w-5 text-right text-xs text-slate-500">{index + 1}</span>
                    {item.image_url ? (
                      <img
                        src={item.image_url}
                        alt={item.market_hash_name}
                        className="h-8 w-8 rounded bg-slate-800 object-contain"
                        loading="lazy"
                      />
                    ) : (
                      <div className="h-8 w-8 rounded bg-slate-800" />
                    )}
                    <div className="min-w-0">
                      <p className="truncate text-sm text-slate-100" title={item.market_hash_name}>
                        {item.market_hash_name}
                      </p>
                      <p className="text-xs text-slate-400">¥{price.toFixed(2)}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    {tab === "gainers" ? (
                      <p className={cn("text-sm font-semibold", change >= 0 ? "text-emerald-300" : "text-red-300")}>
                        {change >= 0 ? "+" : ""}
                        {change.toFixed(2)}%
                      </p>
                    ) : (
                      <p className="text-sm font-semibold text-sky-300">{volume.toLocaleString()} 件</p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
