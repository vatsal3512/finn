// Server-side reads of the pipeline's exported JSON. Pages render from these at build
// time, so every Push screen is static and opens instantly (decision D8).

import { readFile } from "node:fs/promises";
import path from "node:path";
import type {
  AskAnswers, Filing, Filings, Holding, Meta, Portfolio, ResearchIndex, ResearchReport,
} from "./contract";

const DATA = path.join(process.cwd(), "public", "data");
const SPARK_SESSIONS = 90; // enough for a sparkline and a 30-day alert window

async function read<T>(name: string): Promise<T | null> {
  try {
    return JSON.parse(await readFile(path.join(DATA, name), "utf8")) as T;
  } catch {
    return null;
  }
}

export async function getMeta(): Promise<Meta> {
  return (await read<Meta>("meta.json"))!;
}

/**
 * One filing per event, trimmed to what the phone shows. Copies of a letter are already
 * folded into their lead by the pipeline, which more than halves what is sent.
 */
export async function getFeed(): Promise<Filing[]> {
  const all = (await read<Filings>("filings.json"))?.filings ?? [];
  return all
    .filter((f) => f.group_lead !== false && !f.duplicate_of)
    .map((f) => ({
      ...f,
      headline: f.insight ? null : f.headline,
      rule: null,
      cards: f.cards?.map((c) => (c.type === "results" ? { ...c, source_urls: [] } : c)),
    }));
}

/** Holdings with only the recent sessions the phone needs, not 400 days of history. */
export async function getHoldings(sessions = SPARK_SESSIONS): Promise<Holding[]> {
  const p = await read<Portfolio>("portfolio.json");
  return (p?.holdings ?? []).map((h) => ({ ...h, series: h.series.slice(-sessions) }));
}

export async function getAsk(): Promise<AskAnswers["answers"]> {
  return (await read<AskAnswers>("ask.json"))?.answers ?? {};
}

export async function getResearchIndex(): Promise<ResearchIndex["reports"]> {
  return (await read<ResearchIndex>("research/index.json"))?.reports ?? [];
}

export async function getReport(symbol: string): Promise<ResearchReport | null> {
  if (!/^[A-Z0-9&-]{1,20}$/.test(symbol)) return null;
  return read<ResearchReport>(`research/${symbol}.json`);
}
