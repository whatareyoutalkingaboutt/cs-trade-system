"use client";

import { useMemo, useState } from "react";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow as UITableRow } from "@/components/ui/table";
import { formatCurrency } from "@/lib/market";
import type { TableRow } from "@/lib/types";

const statusLabel: Record<TableRow["status"], { label: string; variant: "success" | "warning" | "danger" }> = {
  normal: { label: "稳定", variant: "success" },
  warning: { label: "关注", variant: "warning" },
  emergency: { label: "紧急撤离", variant: "danger" },
};

function shouldShowWear(row: TableRow) {
  const name = (row.name || "").toLowerCase();
  const category = (row.category || "").toLowerCase();
  const isKnife =
    name.includes("knife") ||
    name.includes("karambit") ||
    name.includes("bayonet") ||
    name.includes("dagger") ||
    name.includes("talon") ||
    name.includes("stiletto") ||
    name.includes("ursus") ||
    name.includes("navaja") ||
    name.includes("bowie") ||
    name.includes("falchion") ||
    name.includes("huntsman") ||
    category.includes("knife");
  const isGlove =
    name.includes("glove") ||
    name.includes("hand wraps") ||
    name.includes("wraps") ||
    category.includes("glove");
  const nonWearKeywords = ["sticker", "patch", "music kit", "graffiti", "case", "capsule", "key", "pass", "token"];
  const isExcluded = nonWearKeywords.some((key) => name.includes(key));
  const isSkin = name.includes("|") && !isExcluded;
  return isKnife || isGlove || isSkin;
}

type ItemTableProps = {
  data: TableRow[];
  onSelect: (row: TableRow) => void;
  searchValue?: string;
  onSearchChange?: (value: string) => void;
  searchLoading?: boolean;
  searchSource?: string;
  searchError?: string | null;
};

export function ItemTable({
  data,
  onSelect,
  searchValue,
  onSearchChange,
  searchLoading,
  searchSource,
  searchError,
}: ItemTableProps) {
  const [globalFilter, setGlobalFilter] = useState("");
  const useServerSearch = typeof onSearchChange === "function";
  const filterValue = useServerSearch ? "" : globalFilter;

  const columns = useMemo<ColumnDef<TableRow>[]>(
    () => [
      {
        accessorKey: "name",
        header: "饰品",
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="text-sm font-semibold text-white">{row.original.displayName || row.original.name}</span>
            {row.original.displayName && row.original.displayName !== row.original.name && (
              <span className="text-xs text-slate-500">{row.original.name}</span>
            )}
            <span className="text-xs text-slate-400">{row.original.updatedAt.slice(11, 19)}</span>
          </div>
        ),
      },
      {
        accessorKey: "steamPrice",
        header: "Steam",
        cell: ({ row }) => <span>{formatCurrency(row.original.steamPrice)}</span>,
      },
      {
        accessorKey: "buffPrice",
        header: "Buff",
        cell: ({ row }) => <span>{formatCurrency(row.original.buffPrice)}</span>,
      },
      {
        accessorKey: "youpinPrice",
        header: "悠悠",
        cell: ({ row }) => <span>{formatCurrency(row.original.youpinPrice)}</span>,
      },
      {
        accessorKey: "netProfit",
        header: "净利润 (Buff/悠悠)",
        cell: ({ row }) => {
          const value = row.original.netProfit;
          if (value === undefined) return <span>-</span>;
          const positive = value >= 0;
          return (
            <span className={positive ? "text-emerald-300" : "text-red-300"}>
              {positive ? "+" : ""}{value.toFixed(2)}
            </span>
          );
        },
      },
      {
        accessorKey: "netProfitRate",
        header: "利润率",
        cell: ({ row }) => {
          const value = row.original.netProfitRate;
          if (value === undefined) return <span>-</span>;
          return <span>{(value * 100).toFixed(2)}%</span>;
        },
      },
      {
        accessorKey: "volume",
        header: "成交量",
        cell: ({ row }) => <span>{row.original.volume ?? "-"}</span>,
      },
      {
        accessorKey: "status",
        header: "风险状态",
        cell: ({ row }) => {
          const meta = statusLabel[row.original.status];
          return <Badge variant={meta.variant}>{meta.label}</Badge>;
        },
      },
      {
        accessorKey: "wear",
        header: "磨损",
        cell: ({ row }) => (
          shouldShowWear(row.original) ? <span className="text-emerald-300">可查</span> : <span className="text-slate-500">不适用</span>
        ),
      },
    ],
    []
  );

  const table = useReactTable({
    data,
    columns,
    state: { globalFilter: filterValue },
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: useServerSearch ? undefined : getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="panel-title">饰品看板</p>
          <p className="text-sm text-slate-400">实时价格 + Buff/悠悠价差净利润 + 10% 止损告警</p>
          {searchValue !== undefined && (
            <p className="text-xs text-slate-500">
              {searchError
                ? `搜索失败：${searchError}`
                : searchLoading
                ? "正在聚合搜索..."
                : searchSource
                ? `数据源：${searchSource}`
                : "输入关键词实时搜索"}
            </p>
          )}
        </div>
        <Input
          placeholder="搜索饰品名称..."
          value={searchValue !== undefined ? searchValue : globalFilter}
          onChange={(event) => {
            const next = event.target.value;
            if (onSearchChange) {
              onSearchChange(next);
            } else {
              setGlobalFilter(next);
            }
          }}
          className="sm:max-w-xs"
        />
      </div>

      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <UITableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead key={header.id}>
                  {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              ))}
            </UITableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length ? (
            table.getRowModel().rows.map((row) => (
              <UITableRow
                key={row.id}
                className={`cursor-pointer ${row.original.isUpdated ? "bg-emerald-500/10" : ""}`}
                onClick={() => onSelect(row.original)}
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                ))}
              </UITableRow>
            ))
          ) : (
            <UITableRow>
              <TableCell colSpan={columns.length} className="text-center text-slate-400">
                暂无数据
              </TableCell>
            </UITableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
