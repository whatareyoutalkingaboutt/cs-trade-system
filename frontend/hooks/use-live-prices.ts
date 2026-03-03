import type { Dispatch, SetStateAction } from "react";
import { useEffect } from "react";

import { applyLiveUpdate } from "@/lib/market";
import type { TableRow } from "@/lib/types";

type UpdatePayload = Partial<TableRow> & { id?: string; name?: string };

const DEFAULT_WS_URL = "ws://localhost:8001";
const WS_PATH = "/ws/arbitrage";

function resolveWsBase() {
  if (typeof window === "undefined") return DEFAULT_WS_URL;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}`;
}

function extractUpdates(message: any): UpdatePayload[] {
  if (!message) return [];
  const payload = message?.data ?? message;
  if (Array.isArray(payload)) {
    return payload.flatMap(extractUpdates);
  }
  if (typeof payload !== "object") return [];

  const id = payload.item_name ?? payload.marketHashName ?? payload.market_hash_name ?? payload.name;
  const buffPrice = payload.buff_price ?? payload.buffPrice ?? payload.buy_price;
  const steamPrice = payload.steam_price ?? payload.steamPrice ?? payload.sell_price;
  const youpinPrice = payload.youpin_price ?? payload.youpinPrice;
  const volume = payload.volume ?? payload.sellCount ?? payload.count;

  if (!id) return [];
  return [
    {
      id: String(id),
      name: String(id),
      buffPrice: buffPrice ? Number(buffPrice) : undefined,
      steamPrice: steamPrice ? Number(steamPrice) : undefined,
      youpinPrice: youpinPrice ? Number(youpinPrice) : undefined,
      volume: volume ? Number(volume) : undefined,
      updatedAt: new Date().toISOString(),
    },
  ];
}

export function useLivePrices(setRows: Dispatch<SetStateAction<TableRow[]>>) {
  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_WS_URL || resolveWsBase();
    const socket = new WebSocket(`${base}${WS_PATH}`);

    socket.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);
        const updates = extractUpdates(parsed);
        if (!updates.length) return;
        setRows((prev) => {
          let next = prev;
          updates.forEach((update) => {
            next = applyLiveUpdate(next, update);
          });
          return next;
        });
      } catch (err) {
        return;
      }
    };

    socket.onerror = () => {
      // noop: keep silent to avoid noisy UI
    };

    return () => {
      socket.close();
    };
  }, [setRows]);
}
