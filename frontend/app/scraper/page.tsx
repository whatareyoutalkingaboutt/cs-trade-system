"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";

type LiveExecution = {
  task_id?: number;
  platform?: string;
  status?: string;
  time?: string;
  items_success?: number;
  items_failed?: number;
};

function resolveWsBase() {
  if (typeof window === "undefined") return "ws://localhost:8001";
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}`;
}

export default function ScraperPage() {
  const { isAuthed } = useAuth();
  const [platforms, setPlatforms] = useState<any[]>([]);
  const [tasks, setTasks] = useState<any[]>([]);
  const [status, setStatus] = useState<any | null>(null);
  const [liveLogs, setLiveLogs] = useState<LiveExecution[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  const load = async () => {
    try {
      if (!isAuthed) {
        setMessage("请先登录");
        return;
      }
      const [platformRes, taskRes, statusRes] = await Promise.all([
        apiFetch("/api/scraper/platforms"),
        apiFetch("/api/scraper/tasks"),
        apiFetch("/api/scraper/monitor/status"),
      ]);
      setPlatforms(platformRes.data || []);
      setTasks(taskRes.data || []);
      setStatus(statusRes.summary || null);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "加载失败");
    }
  };

  const trigger = async (taskId: number) => {
    try {
      if (!isAuthed) {
        setMessage("请先登录");
        return;
      }
      await apiFetch(`/api/scraper/tasks/${taskId}/run`, { method: "POST", body: "{}" });
      await load();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "触发失败");
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthed]);

  useEffect(() => {
    if (!isAuthed) return;
    const wsBase = process.env.NEXT_PUBLIC_WS_URL || resolveWsBase();
    const socket = new WebSocket(`${wsBase}/ws/scraper/monitor`);

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload?.summary) {
          setStatus(payload.summary);
        }
        const recent = payload?.recent_executions;
        if (Array.isArray(recent)) {
          setLiveLogs(recent.slice(0, 20));
          return;
        }

        const data = payload?.data;
        if (Array.isArray(data) && data.length) {
          setLiveLogs((prev) => [...data, ...prev].slice(0, 20));
        } else if (data && typeof data === "object") {
          setLiveLogs((prev) => [data, ...prev].slice(0, 20));
        }
      } catch {
        return;
      }
    };

    socket.onerror = () => {
      setMessage("实时通道连接失败，已回退到轮询（不影响 API 接口）");
    };

    return () => {
      socket.close();
    };
  }, [isAuthed]);

  return (
    <div className="min-h-screen px-6 py-10">
      <Card className="max-w-6xl mx-auto">
        <CardHeader>
          <p className="panel-title">任务监控</p>
          <CardTitle>API 任务与调度状态</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {!isAuthed && <p className="text-xs text-amber-200">登录后可查看任务状态</p>}
          <p className="text-xs text-slate-400">说明：当前系统以 API 为主，本页用于查看调度任务与运行状态。</p>
          {message && <p className="text-sm text-slate-300">{message}</p>}
          {status && (
            <div className="rounded-2xl border border-slate-700/60 bg-slate-900/40 p-4 text-sm text-slate-200">
              总任务 {status.total_tasks} · 运行中 {status.running_tasks} · 启用 {status.active_tasks}
            </div>
          )}

          <div>
            <p className="text-sm uppercase tracking-[0.2em] text-slate-400">平台费率配置</p>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {platforms.map((platform) => (
                <div key={platform.id} className="rounded-2xl border border-slate-700/60 p-4 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-white">{platform.platform}</span>
                    <span>{platform.is_enabled ? "启用" : "停用"}</span>
                  </div>
                  <p className="mt-2 text-slate-400">费率: {platform.sell_fee_rate}</p>
                </div>
              ))}
            </div>
          </div>

          <div>
            <p className="text-sm uppercase tracking-[0.2em] text-slate-400">调度任务</p>
            <div className="mt-3 space-y-3">
              {tasks.map((task) => (
                <div key={task.id} className="rounded-2xl border border-slate-700/60 p-4 text-sm">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-white">{task.name}</p>
                      <p className="text-xs text-slate-400">{task.platform} · {task.task_type}</p>
                    </div>
                    <Button variant="outline" onClick={() => trigger(task.id)}>
                      触发
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <p className="text-sm uppercase tracking-[0.2em] text-slate-400">实时日志</p>
            <div className="mt-3 space-y-2">
              {liveLogs.length ? (
                liveLogs.map((row, index) => (
                  <div key={`${row.task_id}-${row.time}-${index}`} className="rounded-xl border border-slate-700/50 p-3 text-xs">
                    <p>任务 {row.task_id ?? "-"} · {row.platform ?? "-"} · {row.status ?? "-"}</p>
                    <p className="text-slate-400">
                      {row.time ?? "-"} · success {row.items_success ?? 0} / failed {row.items_failed ?? 0}
                    </p>
                  </div>
                ))
              ) : (
                <p className="text-sm text-slate-300">暂无实时日志</p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
