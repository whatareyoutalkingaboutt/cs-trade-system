"use client";

import dynamic from "next/dynamic";
import type { ApexOptions } from "apexcharts";

import type { CandlePoint } from "@/lib/kline";

const Chart = dynamic(() => import("react-apexcharts"), { ssr: false });

export function KlineChart({ series }: { series: CandlePoint[] }) {
  const options: ApexOptions = {
    chart: {
      type: "candlestick",
      background: "transparent",
      toolbar: {
        show: true,
        tools: {
          zoom: true,
          zoomin: true,
          zoomout: true,
          pan: true,
          reset: true,
        },
      },
      zoom: {
        enabled: true,
        type: "x",
        autoScaleYaxis: true,
      },
    },
    xaxis: {
      type: "datetime",
      labels: {
        style: {
          colors: "#94a3b8",
        },
      },
    },
    yaxis: {
      labels: {
        style: {
          colors: "#94a3b8",
        },
      },
      tooltip: {
        enabled: true,
      },
    },
    grid: {
      borderColor: "rgba(148, 163, 184, 0.15)",
    },
    plotOptions: {
      candlestick: {
        colors: {
          upward: "#38bdf8",
          downward: "#f97316",
        },
        wick: {
          useFillColor: true,
        },
      },
    },
    tooltip: {
      theme: "dark",
    },
  };

  return (
    <div className="h-72 w-full">
      <Chart options={options} series={[{ data: series }]} type="candlestick" height="100%" />
    </div>
  );
}
