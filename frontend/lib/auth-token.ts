const TOKEN_KEY = "cs_token";
const COOKIE_KEY = "cs_token";
const TOKEN_CHANGED_EVENT = "cs-auth-token-changed";

function getCookieToken(): string | null {
  if (typeof document === "undefined") return null;
  const found = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${COOKIE_KEY}=`));
  if (!found) return null;
  const value = found.split("=").slice(1).join("=");
  return value ? decodeURIComponent(value) : null;
}

export function getClientToken(): string | null {
  if (typeof window === "undefined") return null;
  const local = localStorage.getItem(TOKEN_KEY);
  return local || getCookieToken();
}

export function setClientToken(token: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
  document.cookie = `${COOKIE_KEY}=${encodeURIComponent(token)}; Path=/; Max-Age=2592000; SameSite=Lax`;
  window.dispatchEvent(new Event(TOKEN_CHANGED_EVENT));
}

export function clearClientToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  document.cookie = `${COOKIE_KEY}=; Path=/; Max-Age=0; SameSite=Lax`;
  window.dispatchEvent(new Event(TOKEN_CHANGED_EVENT));
}

export function subscribeTokenChange(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(TOKEN_CHANGED_EVENT, onChange);
  return () => window.removeEventListener(TOKEN_CHANGED_EVENT, onChange);
}

function decodeBase64Url(input: string): string {
  const normalized = input.replace(/-/g, "+").replace(/_/g, "/");
  const padding = normalized.length % 4 === 0 ? "" : "=".repeat(4 - (normalized.length % 4));
  return atob(normalized + padding);
}

export function getTokenExpiryMs(token: string): number | null {
  try {
    const parts = token.split(".");
    if (parts.length < 2) return null;
    const payloadJson = decodeBase64Url(parts[1]);
    const payload = JSON.parse(payloadJson) as { exp?: number | string };
    const exp = payload.exp;
    if (typeof exp === "number") return exp * 1000;
    if (typeof exp === "string") {
      const n = Number(exp);
      return Number.isFinite(n) ? n * 1000 : null;
    }
    return null;
  } catch {
    return null;
  }
}
