"use client";

import dynamic from "next/dynamic";
import type { ApexOptions } from "apexcharts";

const Chart = dynamic(() => import("react-apexcharts"), { ssr: false });

type TrendSeriesChartProps = {
  title: string;
  series: Array<{
    name: string;
    data: Array<{ x: number; y: number }>;
  }>;
  type?: "line" | "bar";
  yLabel?: string;
  colors?: string[];
};

export function TrendSeriesChart({
  title,
  series,
  type = "line",
  yLabel,
  colors,
}: TrendSeriesChartProps) {
  const options: ApexOptions = {
    chart: {
      type,
      background: "transparent",
      toolbar: {
        show: true,
      },
      zoom: {
        enabled: true,
        type: "x",
      },
    },
    xaxis: {
      type: "datetime",
      labels: {
        formatter: (value: string) => {
          const ts = Number(value);
          if (!Number.isFinite(ts)) return value;
          const dt = new Date(ts);
          return `${dt.getMonth() + 1}月${dt.getDate()}日`;
        },
        style: {
          colors: "#94a3b8",
        },
      },
    },
    yaxis: {
      title: yLabel ? { text: yLabel, style: { color: "#94a3b8" } } : undefined,
      labels: {
        style: {
          colors: "#94a3b8",
        },
      },
    },
    stroke: {
      curve: "smooth",
      width: type === "bar" ? 0 : 2.2,
    },
    colors: colors && colors.length ? colors : ["#38bdf8", "#f59e0b"],
    grid: {
      borderColor: "rgba(148, 163, 184, 0.15)",
    },
    tooltip: {
      theme: "dark",
    },
    legend: {
      labels: {
        colors: "#cbd5e1",
      },
    },
  };

  return (
    <div className="space-y-3 rounded-2xl border border-slate-700/60 bg-slate-900/30 p-4">
      <p className="panel-title">{title}</p>
      <div className="h-72 w-full">
        <Chart options={options} series={series} type={type} height="100%" />
      </div>
    </div>
  );
}
