"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { KlineCandlestickChart } from "@/components/kline-candlestick-chart";
import { TrendSeriesChart } from "@/components/trend-series-chart";
import { API_BASE } from "@/lib/api";
import { formatCurrency } from "@/lib/market";

type TrendPoint = {
  time: string;
  value: number;
};

type PlatformTrend = {
  kline?: Array<{
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    ma5?: number | null;
    ma10?: number | null;
    ma30?: number | null;
  }>;
  price_series?: TrendPoint[];
  volume_series?: TrendPoint[];
  sell_listings_series?: TrendPoint[];
  bid_support_series?: TrendPoint[];
  indicator_series?: {
    spread_ratio_series?: TrendPoint[];
    turnover_ratio_series?: TrendPoint[];
    panic_index_series?: Array<TrendPoint & { signal?: boolean }>;
    inventory_slope_3d_series?: TrendPoint[];
    inventory_slope_5d_series?: TrendPoint[];
    bollinger_series?: Array<{
      time: string;
      middle?: number | null;
      upper?: number | null;
      lower?: number | null;
      modified_lower?: number | null;
    }>;
  };
  indicators?: {
    spread_ratio_pct?: number | null;
    turnover_ratio_pct?: number | null;
    panic_index_pct?: number | null;
    panic_signal?: boolean | null;
    inventory_slope_3d_pct?: number | null;
    inventory_slope_5d_pct?: number | null;
    bollinger_middle?: number | null;
    bollinger_upper?: number | null;
    bollinger_lower?: number | null;
    bollinger_modified_lower?: number | null;
  };
};

type TrendsPayload = {
  market_hash_name: string;
  interval: string;
  lookback_days: number;
  platforms: {
    buff?: PlatformTrend;
    youpin?: PlatformTrend;
  };
  indicators?: {
    platforms?: {
      buff?: PlatformTrend["indicators"];
      youpin?: PlatformTrend["indicators"];
    };
    cross?: {
      cross_drain_index_pct?: number | null;
      liquidity_skew_pct?: number | null;
    };
    series?: {
      cross_drain_series?: TrendPoint[];
      liquidity_skew_series?: TrendPoint[];
    };
  };
};

const INTERVAL_OPTIONS = [
  { label: "1小时", value: "1h" },
  { label: "4小时", value: "4h" },
  { label: "日线", value: "1d" },
  { label: "周线", value: "1w" },
] as const;

const LOOKBACK_BY_INTERVAL: Record<string, string> = {
  "1h": "7",
  "4h": "30",
  "1d": "120",
  "1w": "365",
};

function toSeries(points?: TrendPoint[]) {
  if (!points) return [];
  return points
    .filter((point) => point?.time && point?.value !== undefined && point?.value !== null)
    .map((point) => ({
      x: new Date(point.time).getTime(),
      y: Number(point.value),
    }));
}

function getLatest(points?: TrendPoint[]) {
  if (!points || !points.length) return undefined;
  return points[points.length - 1]?.value;
}

function toPercent(value?: number | null) {
  if (value === undefined || value === null) return "-";
  return `${value.toFixed(2)}%`;
}

function getSpreadMeta(value?: number | null) {
  if (value === undefined || value === null) {
    return { range: "参考区间：0% - 15%", status: "状态：无数据", className: "text-slate-500" };
  }
  if (value > 15) {
    return { range: "参考区间：0% - 15%", status: "状态：偏高（流动性断层）", className: "text-red-300" };
  }
  return { range: "参考区间：0% - 15%", status: "状态：正常", className: "text-emerald-300" };
}

function getTurnoverMeta(value?: number | null) {
  if (value === undefined || value === null) {
    return { range: "参考区间：1% - 50%", status: "状态：无数据", className: "text-slate-500" };
  }
  if (value < 1) {
    return { range: "参考区间：1% - 50%", status: "状态：偏低（死水）", className: "text-amber-300" };
  }
  if (value > 50) {
    return { range: "参考区间：1% - 50%", status: "状态：偏高（高换手）", className: "text-emerald-300" };
  }
  return { range: "参考区间：1% - 50%", status: "状态：正常", className: "text-emerald-300" };
}

function getPanicMeta(value?: number | null) {
  if (value === undefined || value === null) {
    return { range: "参考区间：<120% 平稳，>180% 警戒", status: "状态：无数据", className: "text-slate-500" };
  }
  if (value >= 180) {
    return { range: "参考区间：<120% 平稳，>180% 警戒", status: "状态：高位（恐慌放量）", className: "text-red-300" };
  }
  if (value >= 120) {
    return { range: "参考区间：<120% 平稳，>180% 警戒", status: "状态：抬升（关注）", className: "text-amber-300" };
  }
  return { range: "参考区间：<120% 平稳，>180% 警戒", status: "状态：平稳", className: "text-emerald-300" };
}

function getCrossDrainMeta(value?: number | null) {
  if (value === undefined || value === null) {
    return { range: "参考区间：>3.5% 扣费后可套利", status: "状态：无数据", className: "text-slate-500" };
  }
  if (value > 3.5) {
    return { range: "参考区间：>3.5% 扣费后可套利", status: "状态：可套利", className: "text-emerald-300" };
  }
  if (value > 0) {
    return { range: "参考区间：>3.5% 扣费后可套利", status: "状态：有价差（偏弱）", className: "text-amber-300" };
  }
  return { range: "参考区间：>3.5% 扣费后可套利", status: "状态：反向或无效", className: "text-red-300" };
}

function getLiquiditySkewMeta(value?: number | null) {
  if (value === undefined || value === null) {
    return { range: "参考区间：10% - 50%", status: "状态：无数据", className: "text-slate-500" };
  }
  if (value > 50) {
    return { range: "参考区间：10% - 50%", status: "状态：偏高（悠悠抛压增）", className: "text-amber-300" };
  }
  if (value < 10) {
    return { range: "参考区间：10% - 50%", status: "状态：偏低（Buff占优）", className: "text-amber-300" };
  }
  return { range: "参考区间：10% - 50%", status: "状态：常态", className: "text-emerald-300" };
}

function getInventorySlopeMeta(values: Array<number | null | undefined>) {
  const valid = values.filter((v): v is number => v !== undefined && v !== null);
  if (!valid.length) {
    return { range: "参考区间：<=-20% 去库存，>=10% 库存扩张", status: "状态：无数据", className: "text-slate-500" };
  }
  const minValue = Math.min(...valid);
  const maxValue = Math.max(...valid);
  if (minValue <= -20) {
    return { range: "参考区间：<=-20% 去库存，>=10% 库存扩张", status: "状态：显著去库存（吸筹）", className: "text-emerald-300" };
  }
  if (maxValue >= 10) {
    return { range: "参考区间：<=-20% 去库存，>=10% 库存扩张", status: "状态：库存扩张（抛压增）", className: "text-amber-300" };
  }
  return { range: "参考区间：<=-20% 去库存，>=10% 库存扩张", status: "状态：中性", className: "text-emerald-300" };
}

function toSeriesFromBollinger(
  points: NonNullable<NonNullable<PlatformTrend["indicator_series"]>["bollinger_series"]> | undefined,
  key: "middle" | "upper" | "modified_lower"
) {
  if (!points) return [];
  return points
    .filter((point) => point?.time && point[key] !== undefined && point[key] !== null)
    .map((point) => ({
      x: new Date(point.time).getTime(),
      y: Number(point[key]),
    }));
}

export function TrendsClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const marketHashName = searchParams.get("marketHashName") || "";
  const displayName = searchParams.get("displayName") || marketHashName;
  const [interval, setInterval] = useState<string>("1d");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<TrendsPayload | null>(null);

  useEffect(() => {
    if (!marketHashName) return;
    const controller = new AbortController();

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          marketHashName,
          interval,
          lookback_days: LOOKBACK_BY_INTERVAL[interval] || "7",
          use_cache: "false",
        });
        const response = await fetch(`${API_BASE}/api/prices/trends?${params.toString()}`, {
          signal: controller.signal,
          cache: "no-store",
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.success === false) {
          throw new Error(payload.detail || payload.error || "趋势数据获取失败");
        }
        setData(payload.data as TrendsPayload);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setError(err instanceof Error ? err.message : "趋势数据获取失败");
      } finally {
        setLoading(false);
      }
    };

    load();
    return () => controller.abort();
  }, [interval, marketHashName]);

  const chartData = useMemo(() => {
    const buff = data?.platforms?.buff;
    const youpin = data?.platforms?.youpin;

    return {
      buffKline: buff?.kline || [],
      youpinKline: youpin?.kline || [],
      volume: [
        { name: "Buff", data: toSeries(buff?.volume_series) },
        { name: "悠悠", data: toSeries(youpin?.volume_series) },
      ],
      listings: [
        { name: "Buff", data: toSeries(buff?.sell_listings_series) },
        { name: "悠悠", data: toSeries(youpin?.sell_listings_series) },
      ],
      spreadRatio: [
        { name: "Buff 断层率", data: toSeries(buff?.indicator_series?.spread_ratio_series) },
        { name: "悠悠 断层率", data: toSeries(youpin?.indicator_series?.spread_ratio_series) },
      ],
      turnoverRatio: [
        { name: "Buff 动销比", data: toSeries(buff?.indicator_series?.turnover_ratio_series) },
        { name: "悠悠 动销比", data: toSeries(youpin?.indicator_series?.turnover_ratio_series) },
      ],
      panicIndex: [
        { name: "Buff 恐慌指数", data: toSeries(buff?.indicator_series?.panic_index_series) },
        { name: "悠悠 恐慌指数", data: toSeries(youpin?.indicator_series?.panic_index_series) },
      ],
      crossDrain: [
        { name: "跨端吸血指数", data: toSeries(data?.indicators?.series?.cross_drain_series) },
      ],
      liquiditySkew: [
        { name: "流动性偏移度", data: toSeries(data?.indicators?.series?.liquidity_skew_series) },
      ],
      inventorySlope: [
        { name: "Buff 3D", data: toSeries(buff?.indicator_series?.inventory_slope_3d_series) },
        { name: "Buff 5D", data: toSeries(buff?.indicator_series?.inventory_slope_5d_series) },
        { name: "悠悠 3D", data: toSeries(youpin?.indicator_series?.inventory_slope_3d_series) },
        { name: "悠悠 5D", data: toSeries(youpin?.indicator_series?.inventory_slope_5d_series) },
      ],
      bollingerBuff: [
        { name: "悠悠 收盘价", data: toSeries(youpin?.price_series) },
        {
          name: "中轨",
          data: toSeriesFromBollinger(youpin?.indicator_series?.bollinger_series, "middle"),
        },
        {
          name: "上轨",
          data: toSeriesFromBollinger(youpin?.indicator_series?.bollinger_series, "upper"),
        },
        {
          name: "修正下轨",
          data: toSeriesFromBollinger(youpin?.indicator_series?.bollinger_series, "modified_lower"),
        },
      ],
      latest: {
        buffPrice: getLatest(buff?.price_series),
        youpinPrice: getLatest(youpin?.price_series),
        buffVolume: getLatest(buff?.volume_series),
        youpinVolume: getLatest(youpin?.volume_series),
        buffListings: getLatest(buff?.sell_listings_series),
        youpinListings: getLatest(youpin?.sell_listings_series),
        buffSpreadRatio: buff?.indicators?.spread_ratio_pct,
        youpinSpreadRatio: youpin?.indicators?.spread_ratio_pct,
        buffTurnover: buff?.indicators?.turnover_ratio_pct,
        youpinTurnover: youpin?.indicators?.turnover_ratio_pct,
        buffPanicIndex: buff?.indicators?.panic_index_pct,
        youpinPanicIndex: youpin?.indicators?.panic_index_pct,
        buffPanicSignal: buff?.indicators?.panic_signal,
        youpinPanicSignal: youpin?.indicators?.panic_signal,
        buffInventory3d: buff?.indicators?.inventory_slope_3d_pct,
        buffInventory5d: buff?.indicators?.inventory_slope_5d_pct,
        youpinInventory3d: youpin?.indicators?.inventory_slope_3d_pct,
        youpinInventory5d: youpin?.indicators?.inventory_slope_5d_pct,
        crossDrain: data?.indicators?.cross?.cross_drain_index_pct,
        liquiditySkew: data?.indicators?.cross?.liquidity_skew_pct,
      },
    };
  }, [data]);

  const spreadMeta = getSpreadMeta(Math.max(chartData.latest.buffSpreadRatio ?? 0, chartData.latest.youpinSpreadRatio ?? 0));
  const turnoverMeta = getTurnoverMeta(Math.max(chartData.latest.buffTurnover ?? 0, chartData.latest.youpinTurnover ?? 0));
  const panicMeta = getPanicMeta(Math.max(chartData.latest.buffPanicIndex ?? 0, chartData.latest.youpinPanicIndex ?? 0));
  const crossDrainMeta = getCrossDrainMeta(chartData.latest.crossDrain);
  const liquiditySkewMeta = getLiquiditySkewMeta(chartData.latest.liquiditySkew);
  const inventorySlopeMeta = getInventorySlopeMeta([
    chartData.latest.buffInventory3d,
    chartData.latest.buffInventory5d,
    chartData.latest.youpinInventory3d,
    chartData.latest.youpinInventory5d,
  ]);

  if (!marketHashName) {
    return (
      <div className="min-h-screen px-6 py-10 lg:px-10">
        <Card className="mx-auto max-w-3xl">
          <CardHeader>
            <p className="panel-title">趋势详情</p>
            <CardTitle>缺少 marketHashName 参数</CardTitle>
          </CardHeader>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen px-6 py-10 lg:px-10">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="panel-title">饰品趋势详情</p>
            <h1 className="font-display text-2xl text-glow md:text-3xl">{displayName}</h1>
            <p className="mt-1 text-sm text-slate-400">{marketHashName}</p>
          </div>
          <div className="flex items-center gap-2">
            {INTERVAL_OPTIONS.map((opt) => (
              <Button
                key={opt.value}
                variant={interval === opt.value ? "default" : "outline"}
                onClick={() => setInterval(opt.value)}
              >
                {opt.label}
              </Button>
            ))}
            <Button variant="outline" onClick={() => router.push("/")}>返回首页</Button>
          </div>
        </div>
        <p className="text-xs text-slate-400">当前周期：{data?.interval || interval}</p>

        {loading ? (
          <Card>
            <CardContent className="pt-6 text-sm text-slate-300">趋势数据加载中...</CardContent>
          </Card>
        ) : error ? (
          <Card>
            <CardContent className="pt-6 text-sm text-red-300">{error}</CardContent>
          </Card>
        ) : (
          <>
            <div className="grid gap-4 md:grid-cols-3">
              <Card>
                <CardHeader>
                  <p className="panel-title">最新价格</p>
                  <CardTitle className="text-base">
                    Buff {formatCurrency(chartData.latest.buffPrice)} / 悠悠 {formatCurrency(chartData.latest.youpinPrice)}
                  </CardTitle>
                </CardHeader>
              </Card>
              <Card>
                <CardHeader>
                  <p className="panel-title">最新成交量</p>
                  <CardTitle className="text-base">
                    Buff {chartData.latest.buffVolume ?? "-"} / 悠悠 {chartData.latest.youpinVolume ?? "-"}
                  </CardTitle>
                </CardHeader>
              </Card>
              <Card>
                <CardHeader>
                  <p className="panel-title">最新在售数量</p>
                  <CardTitle className="text-base">
                    Buff {chartData.latest.buffListings ?? "-"} / 悠悠 {chartData.latest.youpinListings ?? "-"}
                  </CardTitle>
                </CardHeader>
              </Card>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              <Card>
                <CardHeader>
                  <p className="panel-title">深度断层率</p>
                  <CardTitle className="text-base">
                    Buff {toPercent(chartData.latest.buffSpreadRatio)} / 悠悠 {toPercent(chartData.latest.youpinSpreadRatio)}
                  </CardTitle>
                  <p className="text-xs text-slate-400">{spreadMeta.range}</p>
                  <p className={`text-xs ${spreadMeta.className}`}>{spreadMeta.status}</p>
                </CardHeader>
              </Card>
              <Card>
                <CardHeader>
                  <p className="panel-title">动销比</p>
                  <CardTitle className="text-base">
                    Buff {toPercent(chartData.latest.buffTurnover)} / 悠悠 {toPercent(chartData.latest.youpinTurnover)}
                  </CardTitle>
                  <p className="text-xs text-slate-400">{turnoverMeta.range}</p>
                  <p className={`text-xs ${turnoverMeta.className}`}>{turnoverMeta.status}</p>
                </CardHeader>
              </Card>
              <Card>
                <CardHeader>
                  <p className="panel-title">恐慌指数</p>
                  <CardTitle className="text-base">
                    Buff {toPercent(chartData.latest.buffPanicIndex)} / 悠悠 {toPercent(chartData.latest.youpinPanicIndex)}
                  </CardTitle>
                  <p className="text-xs text-slate-400">
                    信号: Buff {chartData.latest.buffPanicSignal ? "触发" : "未触发"} / 悠悠 {chartData.latest.youpinPanicSignal ? "触发" : "未触发"}
                  </p>
                  <p className="text-xs text-slate-400">{panicMeta.range}</p>
                  <p className={`text-xs ${panicMeta.className}`}>{panicMeta.status}</p>
                </CardHeader>
              </Card>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              <Card>
                <CardHeader>
                  <p className="panel-title">跨端吸血指数</p>
                  <CardTitle className="text-base">{toPercent(chartData.latest.crossDrain)}</CardTitle>
                  <p className="text-xs text-slate-400">{crossDrainMeta.range}</p>
                  <p className={`text-xs ${crossDrainMeta.className}`}>{crossDrainMeta.status}</p>
                </CardHeader>
              </Card>
              <Card>
                <CardHeader>
                  <p className="panel-title">流动性偏移度</p>
                  <CardTitle className="text-base">{toPercent(chartData.latest.liquiditySkew)}</CardTitle>
                  <p className="text-xs text-slate-400">{liquiditySkewMeta.range}</p>
                  <p className={`text-xs ${liquiditySkewMeta.className}`}>{liquiditySkewMeta.status}</p>
                </CardHeader>
              </Card>
              <Card>
                <CardHeader>
                  <p className="panel-title">存量倾角</p>
                  <CardTitle className="text-base">
                    Buff 3D {toPercent(chartData.latest.buffInventory3d)} / 5D {toPercent(chartData.latest.buffInventory5d)}
                  </CardTitle>
                  <CardTitle className="text-base">
                    悠悠 3D {toPercent(chartData.latest.youpinInventory3d)} / 5D {toPercent(chartData.latest.youpinInventory5d)}
                  </CardTitle>
                  <p className="text-xs text-slate-400">{inventorySlopeMeta.range}</p>
                  <p className={`text-xs ${inventorySlopeMeta.className}`}>{inventorySlopeMeta.status}</p>
                </CardHeader>
              </Card>
            </div>

            <div className="grid gap-4">
              <KlineCandlestickChart
                title="悠悠 价格 K线（MA5/MA10/MA30）"
                kline={chartData.youpinKline}
                interval={interval as "1h" | "4h" | "1d" | "1w"}
              />
              <KlineCandlestickChart
                title="Buff 价格 K线（MA5/MA10/MA30）"
                kline={chartData.buffKline}
                interval={interval as "1h" | "4h" | "1d" | "1w"}
              />
            </div>

            <TrendSeriesChart
              title="成交量走势（Buff vs 悠悠）"
              series={chartData.volume}
              type="line"
              yLabel="成交量"
            />

            <TrendSeriesChart
              title="在售数量走势（Buff vs 悠悠）"
              series={chartData.listings}
              type="line"
              yLabel="在售数量"
            />

            <TrendSeriesChart
              title="深度断层率（Spread Ratio）"
              series={chartData.spreadRatio}
              type="line"
              yLabel="%"
            />

            <TrendSeriesChart
              title="动销比（Turnover Ratio）"
              series={chartData.turnoverRatio}
              type="line"
              yLabel="%"
            />

            <TrendSeriesChart
              title="恐慌指数（Panic Index）"
              series={chartData.panicIndex}
              type="line"
              yLabel="%"
            />

            <TrendSeriesChart
              title="跨端吸血指数（Buff Bid vs 悠悠 Ask）"
              series={chartData.crossDrain}
              type="line"
              yLabel="%"
            />

            <TrendSeriesChart
              title="流动性偏移度（悠悠在售 / Buff在售）"
              series={chartData.liquiditySkew}
              type="line"
              yLabel="%"
            />

            <TrendSeriesChart
              title="存量倾角走势（3D / 5D）"
              series={chartData.inventorySlope}
              type="line"
              yLabel="%"
              colors={["#22d3ee", "#f59e0b", "#10b981", "#e879f9"]}
            />

            <TrendSeriesChart
              title="悠悠 修正布林带（含 Bid 支撑修正下轨）"
              series={chartData.bollingerBuff}
              type="line"
              yLabel="价格 (CNY)"
              colors={["#38bdf8", "#f59e0b", "#8b5cf6", "#ef4444"]}
            />
          </>
        )}
      </div>
    </div>
  );
}
