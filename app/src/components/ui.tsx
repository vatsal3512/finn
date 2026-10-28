// Small shared pieces. Kept in one file because each is a few lines.

import type { ReactNode } from "react";
import { pct, tone, toneText } from "@/lib/format";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function Chip({ children, tone = "plain" }: { children: ReactNode; tone?: ChipTone }) {
  return (
    <span className={cx("inline-flex items-center whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-medium leading-none", CHIP[tone])}>
      {children}
    </span>
  );
}

export type ChipTone = "plain" | "up" | "down" | "warn" | "accent" | "faint";
const CHIP: Record<ChipTone, string> = {
  plain: "bg-surface-2 text-muted",
  up: "bg-up-soft text-up",
  down: "bg-down-soft text-down",
  warn: "bg-warn-soft text-warn",
  accent: "bg-accent-soft text-accent",
  faint: "text-faint ring-1 ring-line",
};

export function Move({ value, digits = 1, className }: { value: number | null | undefined; digits?: number; className?: string }) {
  return <span className={cx("num", toneText[tone(value)], className)}>{pct(value, digits)}</span>;
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-2 mt-6 flex items-baseline justify-between px-4">
      <h2 className="text-[12px] font-semibold uppercase tracking-[0.08em] text-muted">{children}</h2>
      {aside && <span className="text-[12px] text-faint">{aside}</span>}
    </div>
  );
}

export function Sparkline({ values, width = 72, height = 22 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return null;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const pts = values
    .map((v, i) => `${((i / (values.length - 1)) * width).toFixed(1)},${(height - 2 - ((v - lo) / span) * (height - 4)).toFixed(1)}`)
    .join(" ");
  const t = tone(values[values.length - 1] - values[0]);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={toneText[t]} aria-hidden>
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function ExternalLink({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={cx("text-accent underline-offset-2 hover:underline", className)}>
      {children}
      <span aria-hidden> ↗</span>
    </a>
  );
}

/** The app icon, small, beside the name: the same mark as on the home screen. */
export function Wordmark() {
  return (
    <span className="inline-flex items-center gap-1.5">
      <svg width="18" height="18" viewBox="0 0 64 64" aria-hidden>
        <rect width="64" height="64" rx="14" fill="#0b0d0f" />
        <path d="M22 16h22v7H30v7h12v7H30v11h-8z" fill="#e6e9ec" />
        <circle cx="47" cy="44" r="4.5" fill="#3cc585" />
      </svg>
      <span className="text-[13px] font-bold tracking-[0.14em]">FINN</span>
    </span>
  );
}
