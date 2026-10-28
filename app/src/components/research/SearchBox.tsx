"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

const SYMBOL = /^[A-Z0-9&-]{1,20}$/;

export function SearchBox() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const symbol = q.trim().toUpperCase().replace(/\.NS$/, "");
  const ok = SYMBOL.test(symbol);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (ok) router.push(`/research/${encodeURIComponent(symbol)}`);
      }}
      className="flex gap-2 px-4"
    >
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Any NSE symbol, e.g. TITAN"
        autoCapitalize="characters"
        autoCorrect="off"
        spellCheck={false}
        aria-label="NSE symbol"
        className="ticker min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2.5 text-[15px] uppercase placeholder:normal-case placeholder:font-normal placeholder:tracking-normal placeholder:text-faint"
      />
      <button type="submit" disabled={!ok} className="rounded-lg bg-accent px-4 text-[14px] font-semibold text-white disabled:opacity-40">
        Research
      </button>
    </form>
  );
}
