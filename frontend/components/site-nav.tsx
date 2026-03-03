"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/dashboard", label: "仪表盘" },
  { href: "/items", label: "饰品管理" },
  { href: "/arbitrage", label: "套利分析" },
  { href: "/scraper", label: "任务监控" },
];

export function SiteNav() {
  const pathname = usePathname();
  if (pathname === "/login") return null;

  return (
    <nav className="sticky top-0 z-40 border-b border-slate-700/50 bg-slate-950/65 backdrop-blur">
      <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-6 py-3 lg:px-10">
        <Link href="/dashboard" className="text-sm font-semibold tracking-[0.2em] text-slate-100">
          CS ITEM OPS
        </Link>
        <div className="flex items-center gap-2">
          {LINKS.map((link) => {
            const active =
              pathname === link.href || (link.href !== "/dashboard" && pathname.startsWith(link.href));
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`rounded-full px-4 py-2 text-sm transition ${
                  active ? "bg-brand-500 text-white" : "text-slate-300 hover:bg-slate-800/50 hover:text-white"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
