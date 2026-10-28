import type { Metadata } from "next";
import "./style.css";

export const metadata: Metadata = {title: "光谱 OS · 研究工作台", description: "科研证据与研究工作流"};

export default function RootLayout({children}: {children: React.ReactNode}) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
