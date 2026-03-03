import { NextRequest, NextResponse } from "next/server";
import fs from "node:fs";
import path from "node:path";

import { DEFAULT_ITEMS } from "@/data/items";

type PlatformKey = "buff" | "steam" | "youpin";

type NormalizedItem = {
  marketHashName: string;
  prices: Partial<Record<PlatformKey, number>>;
  volumes: Partial<Record<PlatformKey, number>>;
  updatedAt: string;
};

const STEAMDT_URL = "https://open.steamdt.com/open/cs2/v1/price/batch";
const KEY_SPLIT_REGEX = /[,;\s]+/;

let keyIndex = 0;

function parseEnvFile(filePath: string): Record<string, string> {
  try {
    if (!fs.existsSync(filePath)) return {};
    const text = fs.readFileSync(filePath, "utf-8");
    const parsed: Record<string, string> = {};
    for (const rawLine of text.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#")) continue;
      const idx = line.indexOf("=");
      if (idx <= 0) continue;
      const key = line.slice(0, idx).trim();
      let value = line.slice(idx + 1).trim();
      if (
        (value.startsWith("\"") && value.endsWith("\"")) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      parsed[key] = value;
    }
    return parsed;
  } catch {
    return {};
  }
}

function loadApiKeysFromFileEnv(): string[] {
  const candidates = [
    path.resolve(process.cwd(), ".env"),
    path.resolve(process.cwd(), "..", ".env"),
  ];

  const keys: string[] = [];
  for (const filePath of candidates) {
    const env = parseEnvFile(filePath);
    const multi = env.STEAMDT_API_KEYS;
    const single = env.STEAMDT_API_KEY;
    if (multi) keys.push(...multi.split(KEY_SPLIT_REGEX));
    if (single) keys.push(single);
    for (let i = 1; i <= 9; i += 1) {
      const v = env[`STEAMDT_API_KEY_${i}`];
      if (v) keys.push(v);
    }
    if (keys.length) break;
  }

  return keys.map((key) => key.trim()).filter((key) => key.length > 0);
}

function loadApiKeys(): string[] {
  const multi = process.env.STEAMDT_API_KEYS;
  const single = process.env.STEAMDT_API_KEY;
  let keys = [
    ...(multi ? multi.split(KEY_SPLIT_REGEX) : []),
    ...(single ? [single] : []),
  ]
    .map((key) => key.trim())
    .filter((key) => key.length > 0);

  if (!keys.length) {
    keys = loadApiKeysFromFileEnv();
  }

  return Array.from(new Set(keys));
}

function nextKey(keys: string[]) {
  const key = keys[keyIndex % keys.length];
  keyIndex = (keyIndex + 1) % keys.length;
  return key;
}

async function requestWithKey(names: string[], apiKey: string) {
  const response = await fetch(STEAMDT_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ marketHashNames: names }),
    cache: "no-store",
  });

  const payload = await response.json().catch(() => null);
  return { response, payload };
}

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const cleaned = String(value).replace(/[,¥$]/g, "").trim();
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizePlatform(value: unknown): PlatformKey | null {
  if (!value) return null;
  const key = String(value).toLowerCase();
  if (key.includes("buff")) return "buff";
  if (key.includes("steam")) return "steam";
  if (key.includes("youpin")) return "youpin";
  return null;
}

function extractPlatformRows(payload: any): Array<{ name: string; platform: PlatformKey; price?: number; volume?: number }> {
  const rows: Array<{ name: string; platform: PlatformKey; price?: number; volume?: number }> = [];

  const pushRow = (name: string, platform: PlatformKey, obj: any) => {
    const price = toNumber(
      obj?.sellPrice ??
        obj?.price ??
        obj?.lowest_price ??
        obj?.lowestPrice ??
        obj?.buff_price ??
        obj?.steam_price ??
        obj?.youpin_price
    );
    const volume = toNumber(obj?.sellCount ?? obj?.volume ?? obj?.count ?? obj?.num);
    rows.push({ name, platform, price: price ?? undefined, volume: volume ?? undefined });
  };

  const handleItem = (name: string, obj: any) => {
    if (!name || !obj) return;
    if (Array.isArray(obj)) {
      obj.forEach((entry) => handleItem(name, entry));
      return;
    }
    const platform = normalizePlatform(obj.platform ?? obj.source ?? obj.market);
    if (platform) {
      pushRow(name, platform, obj);
      return;
    }
    if (obj.buff || obj.buff_price) {
      pushRow(name, "buff", obj.buff ?? obj);
    }
    if (obj.steam || obj.steam_price) {
      pushRow(name, "steam", obj.steam ?? obj);
    }
    if (obj.youpin || obj.youpin_price) {
      pushRow(name, "youpin", obj.youpin ?? obj);
    }
  };

  if (Array.isArray(payload)) {
    payload.forEach((entry) => {
      if (!entry || typeof entry !== "object") return;
      const name = entry.marketHashName ?? entry.market_hash_name ?? entry.name ?? entry.item_name;
      if (entry.platform) {
        const platform = normalizePlatform(entry.platform);
        if (platform && name) {
          pushRow(String(name), platform, entry);
          return;
        }
      }
      if (name) {
        handleItem(String(name), entry);
      }
    });
    return rows;
  }

  if (payload && typeof payload === "object") {
    Object.entries(payload).forEach(([key, value]) => {
      if (!value) return;
      if (key === "items" || key === "data" || key === "list") {
        rows.push(...extractPlatformRows(value));
        return;
      }
      if (typeof value === "object") {
        handleItem(key, value);
      }
    });
  }

  return rows;
}

function buildNormalized(items: Array<{ name: string; platform: PlatformKey; price?: number; volume?: number }>): NormalizedItem[] {
  const map = new Map<string, NormalizedItem>();
  const now = new Date().toISOString();
  items.forEach((row) => {
    const entry = map.get(row.name) ?? {
      marketHashName: row.name,
      prices: {},
      volumes: {},
      updatedAt: now,
    };
    if (row.price !== undefined) {
      entry.prices[row.platform] = row.price;
    }
    if (row.volume !== undefined) {
      entry.volumes[row.platform] = row.volume;
    }
    map.set(row.name, entry);
  });
  return Array.from(map.values());
}

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const names: string[] = Array.isArray(body?.marketHashNames)
    ? body.marketHashNames
    : Array.isArray(body?.names)
    ? body.names
    : DEFAULT_ITEMS;

  const apiKeys = loadApiKeys();
  if (!apiKeys.length) {
    return NextResponse.json({ success: false, error: "STEAMDT_API_KEY(S) not configured" }, { status: 500 });
  }
  let lastError = "SteamDT request failed";

  for (let attempt = 0; attempt < apiKeys.length; attempt += 1) {
    const apiKey = nextKey(apiKeys);
    const { response, payload } = await requestWithKey(names, apiKey);

    if (!response.ok) {
      lastError = `SteamDT request failed (${response.status})`;
      if ([401, 403, 429].includes(response.status)) {
        continue;
      }
      return NextResponse.json({ success: false, error: lastError }, { status: 502 });
    }

    if (payload?.success === false || (payload?.errorCode && payload?.errorCode !== 0)) {
      lastError = payload?.errorMsg ?? "SteamDT error";
      if (apiKeys.length > 1) {
        continue;
      }
      return NextResponse.json({ success: false, error: lastError }, { status: 502 });
    }

    const data = payload?.data ?? payload;
    const rows = extractPlatformRows(data);
    const normalized = buildNormalized(rows);
    return NextResponse.json({ success: true, data: normalized, source: "steamdt" });
  }

  return NextResponse.json({ success: false, error: `${lastError} (all keys exhausted)` }, { status: 502 });
}

export async function GET() {
  return NextResponse.json({ success: true, data: DEFAULT_ITEMS });
}
