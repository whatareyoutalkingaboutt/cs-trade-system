"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import { setClientToken } from "@/lib/auth-token";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    setLoading(true);
    setMessage(null);
    try {
      if (mode === "register") {
        await apiFetch("/api/auth/register", {
          method: "POST",
          body: JSON.stringify({ username, email, password }),
        });
        setMode("login");
        setMessage("注册成功，请登录");
        return;
      }
      const result = await apiFetch("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setClientToken(result.access_token);
      setMessage("登录成功，正在跳转...");
      const nextPath =
        typeof window !== "undefined"
          ? new URLSearchParams(window.location.search).get("next")
          : null;
      router.push(nextPath || "/dashboard");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "操作失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <p className="panel-title">账户</p>
          <CardTitle>{mode === "login" ? "登录" : "注册"}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Input placeholder="用户名" value={username} onChange={(e) => setUsername(e.target.value)} />
          {mode === "register" && (
            <Input placeholder="邮箱" value={email} onChange={(e) => setEmail(e.target.value)} />
          )}
          <Input
            placeholder="密码"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {message && <p className="text-sm text-slate-300">{message}</p>}
          <div className="flex items-center justify-between">
            <Button onClick={handleSubmit} disabled={loading}>
              {loading ? "处理中..." : mode === "login" ? "登录" : "注册"}
            </Button>
            <Button
              variant="ghost"
              onClick={() => setMode(mode === "login" ? "register" : "login")}
            >
              {mode === "login" ? "去注册" : "去登录"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
