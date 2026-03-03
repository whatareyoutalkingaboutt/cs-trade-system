"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { KlineChart } from "@/components/kline-chart";
import { useKline } from "@/hooks/use-kline";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";

export default function ItemDetailPage() {
  const params = useParams();
  const id = params?.id as string;
  const { isAuthed } = useAuth();
  const [klineInterval, setKlineInterval] = useState<"1h" | "1w">("1h");
  const [item, setItem] = useState<any | null>(null);
  const [recommendations, setRecommendations] = useState<any[]>([]);
  const [arbitrage, setArbitrage] = useState<any[]>([]);
  const [arbLoading, setArbLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const { series: klineSeries, loading: klineLoading, error: klineError } = useKline(
    item?.market_hash_name
      ? {
          name: item.market_hash_name,
          platform: "buff",
          interval: klineInterval,
          lookbackDays: klineInterval === "1w" ? 365 : 7,
        }
      : null
  );

  const load = async () => {
    try {
      setMessage(null);
      const result = await apiFetch(`/api/items/${id}`);
      setItem(result.data);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "加载失败");
    }
  };

  const loadArbitrage = async (itemId: number) => {
    if (!isAuthed) {
      setArbitrage([]);
      return;
    }
    setArbLoading(true);
    try {
      const result = await apiFetch(`/api/arbitrage/calculate/${itemId}`);
      setArbitrage(result.data || []);
    } catch {
      setArbitrage([]);
    } finally {
      setArbLoading(false);
    }
  };

  const loadRecommendations = async (keyword?: string) => {
    if (!keyword) {
      setRecommendations([]);
      return;
    }
    try {
      const result = await apiFetch(`/api/items?q=${encodeURIComponent(keyword)}&limit=8&active=true`);
      const rows = (result.data || []).filter((row: any) => row.id !== Number(id));
      setRecommendations(rows.slice(0, 5));
    } catch {
      setRecommendations([]);
    }
  };

  useEffect(() => {
    if (id) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (!item?.id) return;
    loadArbitrage(item.id);
    loadRecommendations(item.type || item.market_hash_name?.split("|")?.[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.id, item?.type, item?.market_hash_name, isAuthed]);

  const save = async () => {
    if (!item) return;
    setSaving(true);
    try {
      await apiFetch(`/api/items/${id}`, { method: "PUT", body: JSON.stringify(item) });
      setMessage("保存成功");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (!item) {
    return (
      <div className="min-h-screen px-6 py-10">
        <Card className="max-w-3xl mx-auto">
          <CardHeader>
            <p className="panel-title">饰品详情</p>
            <CardTitle>加载中...</CardTitle>
          </CardHeader>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen px-6 py-10">
      <Card className="mx-auto max-w-6xl">
        <CardHeader>
          <p className="panel-title">饰品详情</p>
          <CardTitle>{item.market_hash_name}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-6 lg:grid-cols-2">
          <div className="space-y-4">
            {message && <p className="text-sm text-slate-300">{message}</p>}
            <Input
              placeholder="market_hash_name"
              value={item.market_hash_name}
              onChange={(e) => setItem({ ...item, market_hash_name: e.target.value })}
            />
            <Input
              placeholder="中文名"
              value={item.name_cn || ""}
              onChange={(e) => setItem({ ...item, name_cn: e.target.value })}
            />
            <Input
              placeholder="类型"
              value={item.type || ""}
              onChange={(e) => setItem({ ...item, type: e.target.value })}
            />
            <Input
              placeholder="稀有度"
              value={item.rarity || ""}
              onChange={(e) => setItem({ ...item, rarity: e.target.value })}
            />
            <Input
              placeholder="优先级"
              value={String(item.priority ?? 5)}
              onChange={(e) => setItem({ ...item, priority: Number(e.target.value) || 0 })}
            />
            <Input
              placeholder="是否启用(true/false)"
              value={String(item.is_active)}
              onChange={(e) => setItem({ ...item, is_active: e.target.value === "true" })}
            />
            <Button onClick={save} disabled={!isAuthed || saving}>
              {saving ? "保存中..." : "保存"}
            </Button>
            {!isAuthed && <p className="text-xs text-amber-200">登录后才能保存修改</p>}
          </div>

          <div className="space-y-6">
            <div className="rounded-2xl border border-slate-700/60 bg-slate-900/30 p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="panel-title">价格走势</p>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant={klineInterval === "1h" ? "default" : "outline"}
                    onClick={() => setKlineInterval("1h")}
                  >
                    时线
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant={klineInterval === "1w" ? "default" : "outline"}
                    onClick={() => setKlineInterval("1w")}
                  >
                    周线
                  </Button>
                </div>
              </div>
              {klineLoading ? (
                <p className="mt-2 text-sm text-slate-300">K线加载中...</p>
              ) : klineError ? (
                <p className="mt-2 text-sm text-red-300">{klineError}</p>
              ) : klineSeries.length ? (
                <KlineChart series={klineSeries} />
              ) : (
                <p className="mt-2 text-sm text-slate-300">暂无K线数据</p>
              )}
            </div>

            <div className="rounded-2xl border border-slate-700/60 bg-slate-900/30 p-4">
              <p className="panel-title">套利分析</p>
              {!isAuthed ? (
                <p className="mt-2 text-sm text-amber-200">登录后可查看详细套利分析</p>
              ) : arbLoading ? (
                <p className="mt-2 text-sm text-slate-300">计算中...</p>
              ) : arbitrage.length ? (
                <div className="mt-3 space-y-2 text-sm">
                  {arbitrage.slice(0, 5).map((row) => (
                    <div
                      key={`${row.item_id}-${row.buy_platform}-${row.sell_platform}`}
                      className="rounded-xl border border-slate-700/50 bg-slate-950/40 p-3"
                    >
                      <p>{row.buy_platform} → {row.sell_platform}</p>
                      <p className="text-slate-300">净利润: {row.net_profit} · 利润率: {row.profit_rate}%</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-sm text-slate-300">暂无可用套利数据</p>
              )}
            </div>

            <div className="rounded-2xl border border-slate-700/60 bg-slate-900/30 p-4">
              <p className="panel-title">相关饰品推荐</p>
              {recommendations.length ? (
                <div className="mt-3 space-y-2 text-sm">
                  {recommendations.map((row) => (
                    <a
                      key={row.id}
                      href={`/items/${row.id}`}
                      className="block rounded-xl border border-slate-700/50 bg-slate-950/40 p-3 hover:border-brand-500/60"
                    >
                      <p>{row.market_hash_name}</p>
                      <p className="text-slate-300">稀有度: {row.rarity || "-"} · 优先级: {row.priority}</p>
                    </a>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-sm text-slate-300">暂无相关推荐</p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
