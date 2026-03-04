"use client";

import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { apiFetch } from "@/lib/api";

type AlertLogRow = {
  id: number;
  event_time: string;
  item_name: string;
  severity: string;
  severity_label: string;
  trigger_type: string;
  trigger_label: string;
  alert_type: string;
  alert_type_label: string;
  message: string;
  action: string;
};

type AlertResponse = {
  success: boolean;
  total: number;
  limit: number;
  offset: number;
  data: AlertLogRow[];
};

const TRIGGER_OPTIONS = [
  { value: "", label: "全部来源" },
  { value: "arbitrage_alerts", label: "套利告警" },
  { value: "arbitrage_alert", label: "套利告警(旧)" },
  { value: "tiered_alerts", label: "分级预警" },
  { value: "market_maker_alerts", label: "庄家预警" },
];

const SEVERITY_OPTIONS = [
  { value: "", label: "全部等级" },
  { value: "critical", label: "严重" },
  { value: "high", label: "高" },
  { value: "medium", label: "中" },
  { value: "low", label: "低" },
  { value: "info", label: "提示" },
];

function severityVariant(severity: string): "danger" | "warning" | "success" | "info" | "default" {
  if (severity === "critical" || severity === "high") return "danger";
  if (severity === "medium") return "warning";
  if (severity === "low") return "info";
  if (severity === "info") return "default";
  return "default";
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

export default function AlertsPage() {
  const { isAuthed } = useAuth();
  const [rows, setRows] = useState<AlertLogRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  const [triggerType, setTriggerType] = useState("");
  const [severity, setSeverity] = useState("");
  const [keyword, setKeyword] = useState("");

  const queryString = useMemo(() => {
    const params = new URLSearchParams({ limit: "50", offset: "0" });
    if (triggerType) params.set("trigger_type", triggerType);
    if (severity) params.set("severity", severity);
    if (keyword.trim()) params.set("keyword", keyword.trim());
    return params.toString();
  }, [triggerType, severity, keyword]);

  const load = async () => {
    setLoading(true);
    setMessage(null);
    try {
      if (!isAuthed) {
        setRows([]);
        setTotal(0);
        setMessage("请先登录后查看报警记录");
        return;
      }
      const result = (await apiFetch(`/api/alerts/logs?${queryString}`)) as AlertResponse;
      setRows(Array.isArray(result.data) ? result.data : []);
      setTotal(Number(result.total || 0));
    } catch (err) {
      setRows([]);
      setTotal(0);
      setMessage(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed, queryString]);

  return (
    <div className="min-h-screen px-6 py-10">
      <Card className="mx-auto max-w-7xl">
        <CardHeader>
          <p className="panel-title">报警记录</p>
          <CardTitle>邮件雷达告警历史</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={load} disabled={loading}>
              {loading ? "加载中" : "刷新"}
            </Button>
            <select
              className="h-10 rounded-full border border-slate-600/50 bg-slate-900/40 px-4 text-sm"
              value={triggerType}
              onChange={(e) => setTriggerType(e.target.value)}
            >
              {TRIGGER_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <select
              className="h-10 rounded-full border border-slate-600/50 bg-slate-900/40 px-4 text-sm"
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
            >
              {SEVERITY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <Input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="按商品名或详情搜索"
              className="w-72"
            />
            <Badge variant="info">总计 {total} 条</Badge>
          </div>

          {message && <p className="text-sm text-slate-300">{message}</p>}

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>时间</TableHead>
                <TableHead>来源</TableHead>
                <TableHead>等级</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>商品</TableHead>
                <TableHead>详情</TableHead>
                <TableHead>操作建议</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="text-slate-300">{formatDateTime(row.event_time)}</TableCell>
                  <TableCell>{row.trigger_label || row.trigger_type || "-"}</TableCell>
                  <TableCell>
                    <Badge variant={severityVariant(row.severity)}>{row.severity_label || row.severity}</Badge>
                  </TableCell>
                  <TableCell>{row.alert_type_label || row.alert_type || "-"}</TableCell>
                  <TableCell>{row.item_name || "-"}</TableCell>
                  <TableCell className="max-w-xl whitespace-pre-wrap break-words text-slate-300">
                    {row.message || "-"}
                  </TableCell>
                  <TableCell className="max-w-sm whitespace-pre-wrap break-words text-emerald-200">
                    {row.action || "继续观察，暂不操作"}
                  </TableCell>
                </TableRow>
              ))}
              {!rows.length && !loading && (
                <TableRow>
                  <TableCell colSpan={7} className="py-10 text-center text-slate-400">
                    暂无告警记录
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
