"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { ItemTable } from "@/components/item-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatCurrency } from "@/lib/market";
import { useMarketData } from "@/hooks/use-market-data";
import { useLivePrices } from "@/hooks/use-live-prices";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useSearchItems } from "@/hooks/use-search-items";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { clearClientToken } from "@/lib/auth-token";

export default function HomePage() {
  const router = useRouter();
  const { rows, setRows, loading, error, refresh } = useMarketData();
  useLivePrices(setRows);
  const { user } = useCurrentUser();

  const [searchQuery, setSearchQuery] = useState("");
  const debouncedQuery = useDebouncedValue(searchQuery, 350);
  const {
    rows: searchRows,
    source: searchSource,
    error: searchError,
    isLoading: searchLoading,
    isValidating,
  } = useSearchItems(debouncedQuery.trim());

  const trimmedQuery = debouncedQuery.trim();
  const showingSearch = trimmedQuery.length > 0;
  const optimisticRows = useMemo(() => {
    if (!showingSearch) return [];
    const keyword = trimmedQuery.toLowerCase();
    return rows.filter((row) => {
      const en = row.name.toLowerCase();
      const cn = (row.displayName || "").toLowerCase();
      return en.includes(keyword) || cn.includes(keyword);
    });
  }, [rows, showingSearch, trimmedQuery]);
  const displayRows = showingSearch ? (searchRows.length ? searchRows : optimisticRows) : rows;
  const searchBusy = showingSearch && (searchLoading || isValidating);

  const stats = useMemo(() => {
    const base = displayRows;
    const total = base.length;
    const profitable = base.filter((row) => (row.netProfit ?? 0) > 0).length;
    const emergencies = base.filter((row) => row.status === "emergency").length;
    const avgProfit = base.length
      ? base.reduce((sum, row) => sum + (row.netProfit ?? 0), 0) / base.length
      : 0;
    return { total, profitable, emergencies, avgProfit };
  }, [displayRows]);

  return (
    <div className="min-h-screen px-6 py-10 lg:px-10">
      <header className="mx-auto flex w-full max-w-7xl flex-col gap-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="panel-title">CS 饰品系统</p>
            <h1 className="font-display text-3xl text-glow md:text-4xl">数据展示与风险控制中心</h1>
            <p className="mt-2 max-w-xl text-sm text-slate-300">
              实时聚合价格数据，净利润按 Buff 与悠悠价差计算，并在浮亏超过 10% 时触发紧急撤离提示。
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Button variant="outline" onClick={refresh}>
              刷新数据
            </Button>
            {user ? (
              <div className="flex items-center gap-2">
                <Badge variant="success">{user.username}</Badge>
                <Button
                  variant="ghost"
                  onClick={() => {
                    clearClientToken();
                    window.location.reload();
                  }}
                >
                  退出
                </Button>
              </div>
            ) : (
              <Button variant="ghost" onClick={() => (window.location.href = "/login")}>
                登录 / 注册
              </Button>
            )}
            <Badge variant={stats.emergencies > 0 ? "danger" : "success"}>
              {stats.emergencies > 0 ? `紧急撤离 ${stats.emergencies}` : "风险稳定"}
            </Badge>
          </div>
        </div>
        <div className="flex flex-wrap gap-3 text-sm text-slate-300">
          <Button variant="outline" onClick={() => (window.location.href = "/items")}>
            饰品管理
          </Button>
          <Button variant="outline" onClick={() => (window.location.href = "/arbitrage")}>
            套利分析
          </Button>
          <Button variant="outline" onClick={() => (window.location.href = "/scraper")}>
            爬虫管理
          </Button>
        </div>

        <div className="grid gap-4 md:grid-cols-4 animate-stagger">
          <Card>
            <CardHeader>
              <p className="panel-title">监控饰品</p>
              <CardTitle className="metric text-glow">{stats.total}</CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader>
              <p className="panel-title">盈利中</p>
              <CardTitle className="metric text-emerald-300">{stats.profitable}</CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader>
              <p className="panel-title">平均净利润</p>
              <CardTitle className="metric text-amber-200">{formatCurrency(stats.avgProfit)}</CardTitle>
            </CardHeader>
          </Card>
          <Card>
            <CardHeader>
              <p className="panel-title">紧急状态</p>
              <CardTitle className="metric text-ember">
                {stats.emergencies > 0 ? stats.emergencies : "0"}
              </CardTitle>
            </CardHeader>
          </Card>
        </div>
      </header>

      <main className="mx-auto mt-10 w-full max-w-7xl">
        <Card className="shadow-glow">
          <CardContent className="pt-6">
            {loading ? (
              <p className="text-sm text-slate-400">正在加载价格数据...</p>
            ) : error ? (
              <p className="text-sm text-red-300">{error}</p>
            ) : (
              <ItemTable
                data={displayRows}
                onSelect={(row) => {
                  const params = new URLSearchParams({
                    marketHashName: row.name,
                    displayName: row.displayName || row.name,
                  });
                  router.push(`/trends?${params.toString()}`);
                }}
                searchValue={searchQuery}
                onSearchChange={setSearchQuery}
                searchLoading={searchBusy}
                searchSource={searchSource}
                searchError={searchError}
              />
            )}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
