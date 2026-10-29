"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import type { Filing, Holding } from "@/lib/contract";
import { computeAlerts, lastSeen, loadSettings, SEEN_EVENT, type Defaults } from "@/lib/alerts";
import { cx } from "./ui";

type Props = {
  holdings: Pick<Holding, "symbol" | "name" | "series">[];
  filings: Pick<Filing, "id" | "filed_at" | "category" | "tier" | "group_lead" | "duplicate_of">[];
  defaults: Defaults;
  builtAt: string; // when this page's data was made
};

const TABS = [
  { href: "/", label: "Today", d: "M4 6h16M4 12h10M4 18h7" },
  { href: "/alerts", label: "Alerts", d: "M6 10a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6M10 20a2 2 0 0 0 4 0" },
  { href: "/portfolio", label: "Portfolio", d: "M4 19V9M10 19V5M16 19v-7M22 19H2" },
  { href: "/research", label: "Research", d: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14ZM21 21l-5-5" },
];

export function TabBar({ holdings, filings, defaults, builtAt }: Props) {
  const path = usePathname();
  const [unread, setUnread] = useState(0);

  // The data is built into each page, so a page left open keeps its old filings and
  // prices. On coming back to the app, and every ten minutes while it is open, ask whether
  // newer data is out, and if so load it.
  useEffect(() => {
    const check = async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const m = (await (await fetch("/data/meta.json", { cache: "no-store" })).json()) as { generated_at?: string };
        if (m.generated_at && m.generated_at > builtAt) window.location.reload();
      } catch {
        /* offline: keep what is on screen */
      }
    };
    const t = setInterval(check, 600_000);
    document.addEventListener("visibilitychange", check);
    return () => {
      clearInterval(t);
      document.removeEventListener("visibilitychange", check);
    };
  }, [builtAt]);

  useEffect(() => {
    const count = () => {
      const now = Date.now();
      setUnread(computeAlerts(holdings, filings, loadSettings(defaults), lastSeen(now)).alerts.length);
    };
    count();
    window.addEventListener(SEEN_EVENT, count);
    window.addEventListener("storage", count);
    return () => {
      window.removeEventListener(SEEN_EVENT, count);
      window.removeEventListener("storage", count);
    };
  }, [holdings, filings, defaults]);

  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur">
      <ul className="mx-auto grid max-w-[520px] grid-cols-4">
        {TABS.map((t) => {
          const active = t.href === "/" ? path === "/" : path.startsWith(t.href);
          return (
            <li key={t.href}>
              <Link
                href={t.href}
                className={cx("relative flex h-14 flex-col items-center justify-center gap-1 text-[11px]", active ? "text-text" : "text-faint")}
                aria-current={active ? "page" : undefined}
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={active ? 2 : 1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d={t.d} />
                </svg>
                {t.label}
                {t.href === "/alerts" && unread > 0 && (
                  <span className="num absolute right-[calc(50%-20px)] top-2 min-w-4 rounded-full bg-down px-1 text-center text-[10px] font-semibold leading-4 text-white">
                    {unread > 99 ? "99+" : unread}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
