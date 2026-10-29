"use client";

import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";

type Entry = [symbol: string, name: string, alias?: string];
const SYMBOL = /^[A-Z0-9&-]{1,20}$/;
const SHOWN = 6;

/**
 * Search by NSE symbol or company name ("Infosys", "Zomato"). The list is NSE's own
 * register of listed equities, loaded the first time the box is used.
 */
export function SearchBox() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [list, setList] = useState<Entry[] | null>(null);
  const loading = useRef(false);

  function load() {
    if (list || loading.current) return;
    loading.current = true;
    fetch("/data/symbols.json")
      .then((r) => r.json())
      .then((d: { symbols: Entry[] }) => setList(d.symbols))
      .catch(() => setList([]));
  }

  const query = q.trim();
  const matches = useMemo(() => (list && query ? rank(list, query) : []), [list, query]);
  const exact = list?.find((e) => e[0] === query.toUpperCase().replace(/\.NS$/, ""));

  function go(symbol: string) {
    router.push(`/research/${encodeURIComponent(symbol)}`);
  }

  function submit() {
    if (exact) return go(exact[0]);
    if (matches.length) return go(matches[0][0]);
    // The list may lag a new listing, so a well-formed symbol is still tried; for one that is
    // not on NSE, such as JPM, the server says so plainly.
    const raw = query.toUpperCase().replace(/\.NS$/, "");
    if (SYMBOL.test(raw)) go(raw);
  }

  return (
    <div className="px-4">
      <form onSubmit={(e) => { e.preventDefault(); submit(); }} className="flex gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={load}
          placeholder="Company or NSE symbol, e.g. Titan"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          aria-label="Company name or NSE symbol"
          aria-autocomplete="list"
          className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2.5 text-[15px] placeholder:text-faint"
        />
        <button type="submit" disabled={!query} className="rounded-lg bg-accent px-4 text-[14px] font-semibold text-white disabled:opacity-40">
          Research
        </button>
      </form>
      {query.length >= 2 && list && (
        <ul className="mt-2 overflow-hidden rounded-lg border border-line bg-surface" role="listbox">
          {matches.map(([symbol, name, alias]) => (
            <li key={symbol}>
              <button onClick={() => go(symbol)} className="flex w-full items-baseline gap-3 border-t border-line px-3 py-2 text-left first:border-t-0">
                <span className="ticker w-[92px] shrink-0 truncate text-[13px]">{symbol}</span>
                <span className="min-w-0 flex-1 truncate text-[14px] text-muted">
                  {name}{alias ? <span className="text-faint"> · formerly {alias}</span> : null}
                </span>
              </button>
            </li>
          ))}
          {matches.length === 0 && (
            <li className="px-3 py-2.5 text-[13px] text-muted">
              No NSE-listed company matches “{query}”. FINN researches Indian companies listed on NSE;
              symbols look like INFY, TITAN or M&amp;M.
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

/** Exact symbol, then symbols that start with it, then names with a word that starts with it. */
function rank(list: Entry[], query: string): Entry[] {
  const up = query.toUpperCase();
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const scored: [number, Entry][] = [];
  for (const e of list) {
    const [symbol, name, alias] = e;
    const hay = `${name} ${alias ?? ""}`.toLowerCase();
    let score = 0;
    if (symbol === up) score = 100;
    else if (symbol.startsWith(up)) score = 60 - symbol.length;
    else if (words.every((w) => hay.split(/[\s&.-]+/).some((t) => t.startsWith(w)))) score = 30 - name.length / 100;
    if (score > 0) scored.push([score, e]);
  }
  return scored.sort((a, b) => b[0] - a[0]).slice(0, SHOWN).map(([, e]) => e);
}
