"use client";

import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";

const PLATFORM_LABELS: Record<string, string> = {
  buff: "BUFF",
  youpin: "悠悠有品",
  steam: "Steam",
  c5game: "C5",
};

function platformLabel(platform?: string) {
  if (!platform) return "-";
  return PLATFORM_LABELS[platform.toLowerCase()] || platform;
}

function itemLabel(row: any) {
  return row?.item_name || row?.item_name_en || "-";
}

export default function ArbitragePage() {
  const { isAuthed } = useAuth();
  const [data, setData] = useState<any[]>([]);
  const [history, setHistory] = useState<Array<{ at: string; total: number; best?: number }>>([]);
  const [sortBy, setSortBy] = useState<"net_profit" | "profit_rate">("net_profit");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = async (refresh = false) => {
    setLoading(true);
    setMessage(null);
    try {
      if (!isAuthed) {
        setMessage("请先登录");
        return;
      }
      const result = await apiFetch(`/api/arbitrage/opportunities?limit=50&refresh=${refresh}`);
      const rows = result.data || [];
      setData(rows);
      setHistory((prev) => [
        { at: new Date().toISOString(), total: rows.length, best: rows[0]?.net_profit },
        ...prev,
      ].slice(0, 10));
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  const sortedRows = useMemo(() => {
    const rows = [...data];
    rows.sort((a, b) => Number(b?.[sortBy] || 0) - Number(a?.[sortBy] || 0));
    return rows;
  }, [data, sortBy]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed]);

  return (
    <div className="min-h-screen px-6 py-10">
      <Card className="max-w-6xl mx-auto">
        <CardHeader>
          <p className="panel-title">套利分析</p>
          <CardTitle>实时套利机会</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {!isAuthed && <p className="text-xs text-amber-200">登录后可查看套利数据</p>}
          <div className="flex items-center gap-3">
            <Button onClick={() => load(false)} disabled={loading}>
              {loading ? "加载中" : "刷新"}
            </Button>
            <Button variant="outline" onClick={() => load(true)} disabled={loading}>
              强制刷新缓存
            </Button>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as "net_profit" | "profit_rate")}
              className="h-10 rounded-full border border-slate-600/50 bg-slate-900/40 px-4 text-sm"
            >
              <option value="net_profit">按净利润排序</option>
              <option value="profit_rate">按利润率排序</option>
            </select>
          </div>
          {message && <p className="text-sm text-slate-300">{message}</p>}

          {sortedRows.length > 0 && (
            <div className="grid gap-3 md:grid-cols-3">
              {sortedRows.slice(0, 3).map((row) => (
                <div key={`card-${row.item_id}-${row.buy_platform}-${row.sell_platform}`} className="rounded-2xl border border-slate-700/50 bg-slate-900/30 p-4">
                  <p className="text-sm text-slate-200">{itemLabel(row)}</p>
                  <p className="mt-1 text-xs text-slate-400">
                    {platformLabel(row.buy_platform)} → {platformLabel(row.sell_platform)}
                  </p>
                  <p className="mt-3 text-sm">净利润: <span className="text-emerald-300">{row.net_profit}</span></p>
                  <p className="text-xs text-slate-300">利润率: {row.profit_rate}%</p>
                </div>
              ))}
            </div>
          )}

          <div className="overflow-auto">
            <table className="w-full text-sm">
              <thead className="text-slate-400">
                <tr>
                  <th className="text-left py-2">饰品</th>
                  <th className="text-left py-2">买入平台</th>
                  <th className="text-left py-2">卖出平台</th>
                  <th className="text-left py-2">净利润</th>
                  <th className="text-left py-2">利润率</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {sortedRows.map((row) => (
                  <tr key={`${row.item_id}-${row.buy_platform}-${row.sell_platform}`}>
                    <td className="py-2 text-white">{itemLabel(row)}</td>
                    <td className="py-2">{platformLabel(row.buy_platform)}</td>
                    <td className="py-2">{platformLabel(row.sell_platform)}</td>
                    <td className="py-2">
                      <Badge variant={row.net_profit > 0 ? "success" : "danger"}>
                        {row.net_profit}
                      </Badge>
                    </td>
                    <td className="py-2">{row.profit_rate}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div>
            <p className="text-sm uppercase tracking-[0.2em] text-slate-400">刷新历史</p>
            <div className="mt-2 space-y-2 text-xs">
              {history.length ? (
                history.map((row, index) => (
                  <div key={`${row.at}-${index}`} className="rounded-xl border border-slate-700/50 p-3">
                    <p>{row.at}</p>
                    <p className="text-slate-400">总机会: {row.total} · 最优净利润: {row.best ?? "-"}</p>
                  </div>
                ))
              ) : (
                <p className="text-slate-300">暂无历史记录</p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
