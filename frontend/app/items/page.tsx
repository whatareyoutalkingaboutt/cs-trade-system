"use client";

import { useEffect, useMemo, useState } from "react";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";

type Item = {
  id: number;
  market_hash_name: string;
  name_cn?: string | null;
  type?: string | null;
  rarity?: string | null;
  priority: number;
  is_active: boolean;
};

type ItemForm = {
  marketHashName: string;
  nameCn: string;
  type: string;
  rarity: string;
  priority: number;
  isActive: boolean;
};

const EMPTY_FORM: ItemForm = {
  marketHashName: "",
  nameCn: "",
  type: "weapon",
  rarity: "",
  priority: 5,
  isActive: true,
};
const ITEM_PAGE_SIZE = 100;

export default function ItemsPage() {
  const { isAuthed } = useAuth();
  const [items, setItems] = useState<Item[]>([]);
  const [totalItems, setTotalItems] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [query, setQuery] = useState("");
  const [activeFilter, setActiveFilter] = useState<"all" | "active" | "inactive">("all");
  const [sortBy, setSortBy] = useState<"priority_desc" | "name_asc">("priority_desc");
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<ItemForm>(EMPTY_FORM);

  const totalPages = Math.max(1, Math.ceil(totalItems / ITEM_PAGE_SIZE));

  const load = async (targetPage = currentPage) => {
    setLoading(true);
    setMessage(null);
    try {
      const fetchPage = async (page: number) => {
        const params = new URLSearchParams();
        if (query.trim()) params.set("q", query.trim());
        if (activeFilter !== "all") {
          params.set("active", activeFilter === "active" ? "true" : "false");
        }
        params.set("limit", String(ITEM_PAGE_SIZE));
        params.set("offset", String((page - 1) * ITEM_PAGE_SIZE));
        return apiFetch(`/api/items?${params.toString()}`);
      };

      let page = Math.max(1, targetPage);
      let result = await fetchPage(page);
      let total = Number(result.total || 0);
      const pages = Math.max(1, Math.ceil(total / ITEM_PAGE_SIZE));
      if (page > pages) {
        page = pages;
        result = await fetchPage(page);
        total = Number(result.total || 0);
      }

      setItems((result.data || []) as Item[]);
      setTotalItems(total);
      setCurrentPage(page);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  };

  const sortedItems = useMemo(() => {
    const cloned = [...items];
    if (sortBy === "name_asc") {
      cloned.sort((a, b) => a.market_hash_name.localeCompare(b.market_hash_name));
      return cloned;
    }
    cloned.sort((a, b) => {
      if (b.priority !== a.priority) return b.priority - a.priority;
      return a.id - b.id;
    });
    return cloned;
  }, [items, sortBy]);

  const openCreate = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormOpen(true);
    setMessage(null);
  };

  const openEdit = (item: Item) => {
    setEditingId(item.id);
    setForm({
      marketHashName: item.market_hash_name,
      nameCn: item.name_cn || "",
      type: item.type || "weapon",
      rarity: item.rarity || "",
      priority: item.priority,
      isActive: item.is_active,
    });
    setFormOpen(true);
    setMessage(null);
  };

  const closeForm = () => {
    setFormOpen(false);
    setEditingId(null);
  };

  const validateForm = () => {
    if (!form.marketHashName.trim()) return "marketHashName 不能为空";
    if (!form.type.trim()) return "type 不能为空";
    if (!Number.isFinite(form.priority) || form.priority < 0) return "priority 必须是非负数";
    return null;
  };

  const saveForm = async () => {
    if (!isAuthed) {
      setMessage("请先登录");
      return;
    }
    const formError = validateForm();
    if (formError) {
      setMessage(formError);
      return;
    }

    setSaving(true);
    setMessage(null);
    const payload = {
      marketHashName: form.marketHashName.trim(),
      nameCn: form.nameCn.trim() || null,
      type: form.type.trim(),
      rarity: form.rarity.trim() || null,
      priority: form.priority,
      isActive: form.isActive,
    };

    try {
      if (editingId === null) {
        await apiFetch("/api/items", { method: "POST", body: JSON.stringify(payload) });
      } else {
        await apiFetch(`/api/items/${editingId}`, { method: "PUT", body: JSON.stringify(payload) });
      }
      closeForm();
      await load(editingId === null ? 1 : currentPage);
      setMessage(editingId === null ? "创建成功" : "保存成功");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    load(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeFilter]);

  return (
    <div className="min-h-screen px-6 py-10">
      <Card className="max-w-5xl mx-auto">
        <CardHeader>
          <p className="panel-title">饰品管理</p>
          <CardTitle>饰品列表</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {!isAuthed && <p className="text-xs text-amber-200">登录后可进行编辑操作</p>}
          <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
            <Input placeholder="搜索饰品" value={query} onChange={(e) => setQuery(e.target.value)} />
            <select
              value={activeFilter}
              onChange={(e) => setActiveFilter(e.target.value as "all" | "active" | "inactive")}
              className="h-10 rounded-full border border-slate-600/50 bg-slate-900/40 px-4 text-sm"
            >
              <option value="all">全部状态</option>
              <option value="active">仅启用</option>
              <option value="inactive">仅停用</option>
            </select>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as "priority_desc" | "name_asc")}
              className="h-10 rounded-full border border-slate-600/50 bg-slate-900/40 px-4 text-sm"
            >
              <option value="priority_desc">按优先级</option>
              <option value="name_asc">按名称</option>
            </select>
            <Button onClick={() => load(1)} disabled={loading}>
              {loading ? "加载中" : "查询"}
            </Button>
            {isAuthed && (
              <Button variant="outline" onClick={openCreate}>
                新增饰品
              </Button>
            )}
          </div>
          {message && <p className="text-sm text-slate-300">{message}</p>}
          <p className="text-xs text-slate-400">
            共 {totalItems} 条，当前第 {currentPage}/{totalPages} 页，每页 {ITEM_PAGE_SIZE} 条
          </p>
          <div className="overflow-auto">
            <table className="w-full text-sm">
              <thead className="text-slate-400">
                <tr>
                  <th className="text-left py-2">名称</th>
                  <th className="text-left py-2">中文名</th>
                  <th className="text-left py-2">稀有度</th>
                  <th className="text-left py-2">优先级</th>
                  <th className="text-left py-2">状态</th>
                  <th className="text-left py-2">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {sortedItems.map((item) => (
                  <tr key={item.id}>
                    <td className="py-2 text-white">
                      <Link href={`/items/${item.id}`} className="underline decoration-slate-600">
                        {item.market_hash_name}
                      </Link>
                    </td>
                    <td className="py-2">{item.name_cn || "-"}</td>
                    <td className="py-2">{item.rarity || "-"}</td>
                    <td className="py-2">{item.priority}</td>
                    <td className="py-2">{item.is_active ? "启用" : "停用"}</td>
                    <td className="py-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={!isAuthed}
                        onClick={() => openEdit(item)}
                      >
                        编辑
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={loading || currentPage <= 1}
              onClick={() => load(currentPage - 1)}
            >
              上一页
            </Button>
            <span className="text-xs text-slate-300">第 {currentPage} 页</span>
            <Button
              variant="outline"
              size="sm"
              disabled={loading || currentPage >= totalPages}
              onClick={() => load(currentPage + 1)}
            >
              下一页
            </Button>
          </div>
        </CardContent>
      </Card>

      {formOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 px-4">
          <div className="glass w-full max-w-xl rounded-3xl p-6">
            <h2 className="text-lg font-semibold">{editingId === null ? "新增饰品" : "编辑饰品"}</h2>
            <div className="mt-4 grid gap-3">
              <Input
                placeholder="marketHashName"
                value={form.marketHashName}
                onChange={(e) => setForm((prev) => ({ ...prev, marketHashName: e.target.value }))}
              />
              <Input
                placeholder="中文名"
                value={form.nameCn}
                onChange={(e) => setForm((prev) => ({ ...prev, nameCn: e.target.value }))}
              />
              <Input
                placeholder="类型（type）"
                value={form.type}
                onChange={(e) => setForm((prev) => ({ ...prev, type: e.target.value }))}
              />
              <Input
                placeholder="稀有度"
                value={form.rarity}
                onChange={(e) => setForm((prev) => ({ ...prev, rarity: e.target.value }))}
              />
              <Input
                placeholder="优先级"
                value={String(form.priority)}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, priority: Number.parseInt(e.target.value || "0", 10) || 0 }))
                }
              />
              <label className="flex items-center gap-2 text-sm text-slate-200">
                <input
                  type="checkbox"
                  checked={form.isActive}
                  onChange={(e) => setForm((prev) => ({ ...prev, isActive: e.target.checked }))}
                />
                启用
              </label>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button variant="ghost" onClick={closeForm}>
                取消
              </Button>
              <Button onClick={saveForm} disabled={saving}>
                {saving ? "保存中..." : "保存"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
