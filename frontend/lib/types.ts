export type PlatformPrices = {
  buff?: number;
  steam?: number;
  youpin?: number;
};

export type PlatformVolumes = {
  buff?: number;
  steam?: number;
  youpin?: number;
};

export type MarketItem = {
  marketHashName: string;
  displayName?: string;
  prices: PlatformPrices;
  volumes: PlatformVolumes;
  updatedAt: string;
  category?: string;
  rarity?: string;
};

export type TableRow = {
  id: string;
  name: string;
  displayName?: string;
  buffPrice?: number;
  steamPrice?: number;
  youpinPrice?: number;
  volume?: number;
  updatedAt: string;
  category?: string;
  rarity?: string;
  isUpdated?: boolean;
  entryPrice?: number;
  netProfit?: number;
  netProfitRate?: number;
  lossRate?: number;
  status: "normal" | "warning" | "emergency";
};

export type SearchPlatformPayload = {
  raw_price?: number | null;
  net_price?: number | null;
  volume?: number | null;
};

export type SearchItem = {
  item_name: string;
  display_name?: string;
  updated_at?: string;
  base_info?: {
    category?: string | null;
    rarity?: string | null;
    name_cn?: string | null;
  };
  platforms?: {
    steam?: SearchPlatformPayload | null;
    steam_official?: SearchPlatformPayload | null;
    buff?: SearchPlatformPayload | null;
    youyou?: SearchPlatformPayload | null;
    youpin?: SearchPlatformPayload | null;
  };
};
