export type CandlePoint = {
  x: number;
  y: [number, number, number, number];
};

export type KlineApiPoint = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
};

export function mapKlineToSeries(points: KlineApiPoint[]): CandlePoint[] {
  return points
    .filter((point) => point?.time)
    .map((point) => ({
      x: new Date(point.time).getTime(),
      y: [point.open, point.high, point.low, point.close],
    }));
}

function hashSeed(value: string) {
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash << 5) - hash + value.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

export function buildSyntheticKline(base: number, seed: string, points = 48): CandlePoint[] {
  const result: CandlePoint[] = [];
  const start = Date.now() - points * 60 * 60 * 1000;
  const seedValue = hashSeed(seed);

  let lastClose = base;
  for (let i = 0; i < points; i += 1) {
    const drift = Math.sin((i + seedValue) * 0.35) * (base * 0.015);
    const noise = Math.cos((i + seedValue) * 0.78) * (base * 0.008);
    const open = lastClose;
    const close = Math.max(0.01, open + drift + noise);
    const high = Math.max(open, close) + base * 0.01;
    const low = Math.min(open, close) - base * 0.01;
    result.push({
      x: start + i * 60 * 60 * 1000,
      y: [open, high, low, close],
    });
    lastClose = close;
  }

  return result;
}
