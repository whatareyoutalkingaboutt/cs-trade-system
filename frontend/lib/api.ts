import { clearClientToken, getClientToken, setClientToken } from "@/lib/auth-token";

const DEFAULT_API_BASE = "http://localhost:8000";

function resolveApiBase(): string {
  const configured = process.env.NEXT_PUBLIC_API_URL;
  if (configured) return configured;
  if (typeof window === "undefined") return DEFAULT_API_BASE;
  return `${window.location.protocol}//${window.location.host}`;
}

export const API_BASE = resolveApiBase();

const AUTH_REFRESH_PATH = "/api/auth/refresh";
let refreshingTokenPromise: Promise<string | null> | null = null;

function buildHeaders(options: RequestInit, token?: string | null): HeadersInit {
  const baseHeaders = new Headers(options.headers || {});
  if (!baseHeaders.has("Content-Type")) {
    baseHeaders.set("Content-Type", "application/json");
  }
  if (token) {
    baseHeaders.set("Authorization", `Bearer ${token}`);
  }
  return baseHeaders;
}

async function tryRefreshToken(): Promise<string | null> {
  if (refreshingTokenPromise) return refreshingTokenPromise;
  const currentToken = getClientToken();
  if (!currentToken) return null;

  refreshingTokenPromise = (async () => {
    const response = await fetch(`${resolveApiBase()}${AUTH_REFRESH_PATH}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${currentToken}`,
      },
    });
    if (!response.ok) {
      clearClientToken();
      return null;
    }
    const payload = await response.json().catch(() => ({}));
    const freshToken = typeof payload?.access_token === "string" ? payload.access_token : null;
    if (!freshToken) {
      clearClientToken();
      return null;
    }
    setClientToken(freshToken);
    return freshToken;
  })().finally(() => {
    refreshingTokenPromise = null;
  });

  return refreshingTokenPromise;
}

async function doFetch(path: string, options: RequestInit, token?: string | null): Promise<Response> {
  return fetch(`${resolveApiBase()}${path}`, {
    ...options,
    headers: buildHeaders(options, token),
  });
}

export async function apiFetch(path: string, options: RequestInit = {}) {
  const token = getClientToken();
  let response = await doFetch(path, options, token);
  let payload = await response.json().catch(() => ({}));

  const canRetryWithRefresh =
    response.status === 401 &&
    Boolean(token) &&
    !path.startsWith(AUTH_REFRESH_PATH) &&
    !path.startsWith("/api/auth/login") &&
    !path.startsWith("/api/auth/register");

  if (canRetryWithRefresh) {
    const refreshedToken = await tryRefreshToken();
    if (refreshedToken) {
      response = await doFetch(path, options, refreshedToken);
      payload = await response.json().catch(() => ({}));
    }
  }

  if (!response.ok || payload.success === false) {
    const error = payload.detail || payload.error || (response.status === 401 ? "登录已过期，请重新登录" : "请求失败");
    throw new Error(error);
  }
  return payload;
}
