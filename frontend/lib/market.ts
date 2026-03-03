import type { MarketItem, SearchItem, TableRow } from "@/lib/types";

const WEAR_ORDER: Record<string, number> = {
  "factory new": 0,
  "崭新出厂": 0,
  "minimal wear": 1,
  "略有磨损": 1,
  "field-tested": 2,
  "久经沙场": 2,
  "well-worn": 3,
  "破损不堪": 3,
  "battle-scarred": 4,
  "战痕累累": 4,
};

export function formatCurrency(value?: number): string {
  if (value === null || value === undefined) return "-";
  return `¥${value.toFixed(2)}`;
}

export function computeNetProfit(buffPrice?: number, youpinPrice?: number) {
  if (!buffPrice || !youpinPrice) return { netProfit: undefined, netProfitRate: undefined };
  const buyPrice = Math.min(buffPrice, youpinPrice);
  const sellPrice = Math.max(buffPrice, youpinPrice);
  const netProfit = sellPrice - buyPrice;
  const netProfitRate = buyPrice > 0 ? netProfit / buyPrice : undefined;
  return { netProfit, netProfitRate };
}

export function computeLossRate(entryPrice?: number, currentPrice?: number) {
  if (!entryPrice || !currentPrice) return undefined;
  return (entryPrice - currentPrice) / entryPrice;
}

function getWearRank(row: Pick<TableRow, "name" | "displayName">): number {
  const candidates = [row.displayName || "", row.name || ""].map((v) => v.trim()).filter(Boolean);
  for (const value of candidates) {
    const match = value.match(/[（(]([^()（）]+)[）)]\s*$/);
    if (!match) continue;
    const wear = match[1].trim();
    const normalized = wear.toLowerCase();
    if (WEAR_ORDER[wear] !== undefined) return WEAR_ORDER[wear];
    if (WEAR_ORDER[normalized] !== undefined) return WEAR_ORDER[normalized];
  }
  return 99;
}

function isStatTrakRow(row: Pick<TableRow, "name" | "displayName">): boolean {
  const text = `${row.displayName || ""} ${row.name || ""}`.toLowerCase();
  return text.includes("stattrak");
}

function getFamilyKey(row: Pick<TableRow, "name" | "displayName">): string {
  const raw = (row.displayName || row.name || "").trim();
  return raw
    .replace(/stattrak™?/gi, "")
    .replace(/\(\s*\)|（\s*）/g, "")
    .replace(/\|\s*\|/g, "|")
    .replace(/[（(][^()（）]+[）)]\s*$/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function getComparePrice(row: Pick<TableRow, "buffPrice" | "youpinPrice" | "steamPrice">): number {
  const buff = row.buffPrice ?? Number.POSITIVE_INFINITY;
  const youpin = row.youpinPrice ?? Number.POSITIVE_INFINITY;
  const best = Math.min(buff, youpin);
  if (Number.isFinite(best)) return best;
  return row.steamPrice ?? Number.POSITIVE_INFINITY;
}

export function buildRows(items: MarketItem[], previous?: TableRow[]): TableRow[] {
  const previousMap = new Map(previous?.map((row) => [row.id, row]));
  const rows = items.map((item) => {
    const prev = previousMap.get(item.marketHashName);
    const buffPrice = item.prices.buff;
    const steamPrice = item.prices.steam;
    const youpinPrice = item.prices.youpin;
    const volume = item.volumes.buff ?? item.volumes.youpin ?? item.volumes.steam;
    const entryPrice = prev?.entryPrice ?? buffPrice ?? steamPrice ?? youpinPrice;
    const currentPrice = buffPrice ?? steamPrice ?? youpinPrice;
    const { netProfit, netProfitRate } = computeNetProfit(buffPrice, youpinPrice);
    const lossRate = computeLossRate(entryPrice, currentPrice);
    const isUpdated = Boolean(
      prev &&
        (prev.buffPrice !== buffPrice ||
          prev.steamPrice !== steamPrice ||
          prev.youpinPrice !== youpinPrice)
    );

    let status: TableRow["status"] = "normal";
    if (lossRate !== undefined) {
      if (lossRate >= 0.1) status = "emergency";
      else if (lossRate >= 0.06) status = "warning";
    }

    return {
      id: item.marketHashName,
      name: item.marketHashName,
      displayName: item.displayName ?? prev?.displayName ?? item.marketHashName,
      buffPrice,
      steamPrice,
      youpinPrice,
      volume,
      updatedAt: item.updatedAt,
      category: item.category,
      rarity: item.rarity,
      isUpdated,
      entryPrice,
      netProfit,
      netProfitRate,
      lossRate,
      status,
    };
  });
  return rows.sort((a, b) => {
    const aStat = isStatTrakRow(a) ? 1 : 0;
    const bStat = isStatTrakRow(b) ? 1 : 0;
    if (aStat !== bStat) return aStat - bStat;

    const aWear = getWearRank(a);
    const bWear = getWearRank(b);
    if (aWear !== bWear) return aWear - bWear;

    const aFamily = getFamilyKey(a);
    const bFamily = getFamilyKey(b);
    if (aFamily !== bFamily) return aFamily.localeCompare(bFamily);

    const aPrice = getComparePrice(a);
    const bPrice = getComparePrice(b);
    if (aPrice !== bPrice) return aPrice - bPrice;
    return a.name.localeCompare(b.name);
  });
}

export function applyLiveUpdate(rows: TableRow[], update: Partial<TableRow> & { id?: string; name?: string }) {
  const targetId = update.id ?? update.name;
  if (!targetId) return rows;
  return rows.map((row) => {
    if (row.id !== targetId) return row;
    const merged = { ...row, ...update };
    const currentPrice = merged.buffPrice ?? merged.steamPrice ?? merged.youpinPrice;
    const { netProfit, netProfitRate } = computeNetProfit(merged.buffPrice, merged.youpinPrice);
    const lossRate = computeLossRate(merged.entryPrice, currentPrice);
    const isUpdated = Boolean(
      update.buffPrice !== undefined ||
        update.steamPrice !== undefined ||
        update.youpinPrice !== undefined
    );

    let status: TableRow["status"] = "normal";
    if (lossRate !== undefined) {
      if (lossRate >= 0.1) status = "emergency";
      else if (lossRate >= 0.06) status = "warning";
    }

    return {
      ...merged,
      isUpdated,
      netProfit,
      netProfitRate,
      lossRate,
      status,
    };
  });
}

export function buildRowsFromSearch(items: SearchItem[], previous?: TableRow[]): TableRow[] {
  const mapped: MarketItem[] = items.map((item) => {
    const platforms = item.platforms || {};
    const steam = platforms.steam || platforms.steam_official || undefined;
    const buff = platforms.buff || undefined;
    const youpin = platforms.youyou || platforms.youpin || undefined;
    return {
      marketHashName: item.item_name,
      displayName: item.display_name || item.base_info?.name_cn || item.item_name,
      prices: {
        steam: steam?.raw_price ?? undefined,
        buff: buff?.raw_price ?? undefined,
        youpin: youpin?.raw_price ?? undefined,
      },
      volumes: {
        steam: steam?.volume ?? undefined,
        buff: buff?.volume ?? undefined,
        youpin: youpin?.volume ?? undefined,
      },
      updatedAt: item.updated_at ?? new Date().toISOString(),
      category: item.base_info?.category ?? undefined,
      rarity: item.base_info?.rarity ?? undefined,
    };
  });
  return buildRows(mapped, previous);
}
