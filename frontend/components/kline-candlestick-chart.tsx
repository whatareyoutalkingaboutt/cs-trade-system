"use client";

import dynamic from "next/dynamic";
import type { ApexOptions } from "apexcharts";

const Chart = dynamic(() => import("react-apexcharts"), { ssr: false });

type KlinePoint = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  ma5?: number | null;
  ma10?: number | null;
  ma30?: number | null;
};

type KlineCandlestickChartProps = {
  title: string;
  kline: KlinePoint[];
  interval?: "1h" | "4h" | "1d" | "1w";
};

export function KlineCandlestickChart({ title, kline, interval = "1d" }: KlineCandlestickChartProps) {
  const candleData = (kline || [])
    .filter((row) => row?.time)
    .map((row) => ({
      x: new Date(row.time).getTime(),
      y: [Number(row.open), Number(row.high), Number(row.low), Number(row.close)],
    }));

  const ma5 = (kline || [])
    .filter((row) => row?.time && row.ma5 !== undefined && row.ma5 !== null)
    .map((row) => ({ x: new Date(row.time).getTime(), y: Number(row.ma5) }));
  const ma10 = (kline || [])
    .filter((row) => row?.time && row.ma10 !== undefined && row.ma10 !== null)
    .map((row) => ({ x: new Date(row.time).getTime(), y: Number(row.ma10) }));
  const ma30 = (kline || [])
    .filter((row) => row?.time && row.ma30 !== undefined && row.ma30 !== null)
    .map((row) => ({ x: new Date(row.time).getTime(), y: Number(row.ma30) }));

  const series = [
    { name: "K线", type: "candlestick" as const, data: candleData },
    { name: "MA5", type: "line" as const, data: ma5 },
    { name: "MA10", type: "line" as const, data: ma10 },
    { name: "MA30", type: "line" as const, data: ma30 },
  ];

  const options: ApexOptions = {
    chart: {
      type: "line",
      background: "transparent",
      toolbar: { show: true },
      zoom: { enabled: true, type: "x" },
    },
    xaxis: {
      type: "datetime",
      labels: {
        formatter: (value: string) => {
          const ts = Number(value);
          if (!Number.isFinite(ts)) return value;
          const dt = new Date(ts);
          const mm = String(dt.getMonth() + 1).padStart(2, "0");
          const dd = String(dt.getDate()).padStart(2, "0");
          const hh = String(dt.getHours()).padStart(2, "0");
          if (interval === "1h" || interval === "4h") {
            return `${mm}-${dd} ${hh}:00`;
          }
          if (interval === "1w") {
            return `${dt.getFullYear()}-${mm}-${dd}`;
          }
          return `${dt.getMonth() + 1}月${dt.getDate()}日`;
        },
        style: { colors: "#94a3b8" },
      },
    },
    yaxis: {
      labels: { style: { colors: "#94a3b8" } },
      title: { text: "价格 (CNY)", style: { color: "#94a3b8" } },
    },
    stroke: {
      curve: ["straight", "smooth", "smooth", "smooth"],
      width: [1, 2, 2, 2],
    },
    markers: {
      size: 0,
      hover: {
        size: 0,
      },
    },
    colors: ["#22c55e", "#f59e0b", "#8b5cf6", "#2563eb"],
    plotOptions: {
      candlestick: {
        colors: {
          upward: "#10b981",
          downward: "#ff2d55",
        },
        wick: {
          useFillColor: true,
        },
      },
    },
    grid: {
      borderColor: "rgba(148, 163, 184, 0.2)",
      strokeDashArray: 3,
    },
    legend: {
      labels: { colors: "#cbd5e1" },
    },
    tooltip: {
      theme: "dark",
    },
  };

  return (
    <div className="space-y-3 rounded-2xl border border-slate-700/60 bg-slate-900/30 p-4">
      <p className="panel-title">{title}</p>
      <div className="h-80 w-full">
        <Chart
          key={`${title}-${interval}-${kline[0]?.time ?? "empty"}-${kline[kline.length - 1]?.time ?? "empty"}`}
          options={options}
          series={series}
          type="line"
          height="100%"
        />
      </div>
    </div>
  );
}
