import { Suspense } from "react";

import { TrendsClient } from "./trends-client";

export default function TrendsPage() {
  return (
    <Suspense fallback={<div className="min-h-screen px-6 py-10 text-slate-300">趋势数据加载中...</div>}>
      <TrendsClient />
    </Suspense>
  );
}
