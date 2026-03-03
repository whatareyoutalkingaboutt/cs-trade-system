import type { Metadata } from "next";

import { SiteNav } from "@/components/site-nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "CS 饰品系统 · 数据展示",
  description: "CS 饰品数据展示与风险监控面板",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="font-sans">
        <SiteNav />
        {children}
      </body>
    </html>
  );
}
