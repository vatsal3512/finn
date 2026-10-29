import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { TabBar } from "@/components/TabBar";
import { getFeed, getHoldings, getMeta } from "@/lib/data";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains", display: "swap" });

export const metadata: Metadata = {
  title: "FINN",
  description: "What changed in your portfolio today, and whether management did what it said.",
  appleWebApp: { capable: true, title: "FINN", statusBarStyle: "default" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f4f5f3" },
    { media: "(prefers-color-scheme: dark)", color: "#0b0d0f" },
  ],
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const [meta, holdings, feed] = await Promise.all([getMeta(), getHoldings(30), getFeed()]);
  // The tab bar only needs enough to count unread alerts.
  const badgeFilings = feed.map(({ id, filed_at, category, tier, group_lead, duplicate_of }) => ({
    id, filed_at, category, tier, group_lead, duplicate_of,
  }));
  const badgeHoldings = holdings.map(({ symbol, name, series }) => ({ symbol, name, series }));
  return (
    <html lang="en-IN" className={`${inter.variable} ${mono.variable}`}>
      <body>
        <div className="mx-auto min-h-dvh max-w-[520px] pb-[calc(72px+env(safe-area-inset-bottom))]">{children}</div>
        <TabBar holdings={badgeHoldings} filings={badgeFilings} defaults={meta.alert_defaults} builtAt={meta.generated_at} />
      </body>
    </html>
  );
}
