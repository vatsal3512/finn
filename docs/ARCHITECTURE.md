# FINN architecture

FINN filters the daily flood of exchange filings, prices and fundamentals down to the few
things an investor needs to see. This document covers the data layer and the AI layer,
which are built. The research engine and the app get their own sections when built.

## The shape of the system

```mermaid
flowchart LR
  subgraph Sources
    Y[Yahoo Finance<br/>end-of-day prices]
    N[NSE<br/>filings, corporate actions]
    B[BSE<br/>fallback filings]
    S[screener.in<br/>tables + document index]
    P[BSE and company sites<br/>transcripts, annual reports]
  end

  subgraph Pipeline["Scheduled pipeline (GitHub Actions, every 30 min)"]
    CA[corp_actions]
    PR[prices]
    FI[filings + rules]
  end

  subgraph OnDemand["On demand, any ticker"]
    FU[fundamentals]
  end

  DB[(finn.db<br/>SQLite)]
  EX[export<br/>validated JSON]
  APP[Phone app<br/>static files]

  N --> CA --> PR
  Y --> PR
  N --> FI
  B -. NSE fails or<br/>NSE copy broken .-> FI
  S --> FU
  P --> FU
  PR --> DB
  FI --> DB
  FU --> DB
  DB --> EX --> APP
```

Push screens read static JSON files, so they open instantly. Only a research request on an
uncached ticker ever needs a live server.

## Decisions and why

| Decision | Why |
|---|---|
| **Static-first.** The pipeline writes JSON that the app loads directly. | Free-tier servers sleep and take about a minute to wake. The investor's daily screens should never wait on that. |
| **Thresholds live in the app.** The data layer ships each day's move and volume ratio. | The investor decides what "unusual" means. Changing 2x volume to 3x needs no server and no re-run. |
| **Rules before AI.** A rule table sorts filings by the exchange's subject line first. | On 601 real filings from October 2026, rules settled 46% with no model call and set the category for 70%. Routine PDFs are never even downloaded. |
| **Every row has provenance.** Each table stores `source_url` and `fetched_at`. | Any number on screen can be traced to its source. That is the basis for citing every claim in research. |
| **Corporate-action days are marked.** Prices carry the ex-date of demergers, splits and bonuses. | Yahoo does not adjust for demergers. Vedanta's demerger on 30 April 2026 looks like a 65% crash, and alerts must not report it as one. |
| **Text quality is judged, not assumed.** Each PDF gets `ok`, `garbled` or `no_text`. | Maruti's and IndusInd's Q2 FY27 results are scans with a corrupted text layer, where "1,005,746" reads "I,005,746". Garbled PDFs are kept for a vision model, and their text is never trusted for numbers. |
| **Downloads are verified, with BSE as the second copy.** | NSE's stored copy of HDFC Bank's Q2 results is truncated on NSE's own server. The downloader rejects incomplete files and fetches the same filing from BSE. |
| **Only three annual-report sections are located.** These are the auditor's report, contingent liabilities and related-party transactions. | These carry the risk signals for the bear case. Parsing hundreds of other pages adds cost, not insight. |
| **screener.in is an index, not the record.** | Its tables are a cross-check and a source for cash-flow history. The documents themselves are fetched from BSE or the company. Its pages are cached for 12 hours and never committed, per its personal-use terms. |
| **One JSON contract.** Pydantic models validate every export and write a JSON Schema. | The frontend generates its types from the schema, so the two sides cannot drift apart silently. |

## Being a good citizen

- Each site has its own minimum gap between requests. A full refresh makes about 400 requests over several minutes.
- Transient failures are retried with exponential backoff and jitter. Anything else fails fast with the status code.
- screener.in gets a User-Agent naming this project. NSE and BSE reject unknown clients, so they get a standard browser User-Agent. Nothing spoofs TLS fingerprints or solves bot challenges. If an exchange refuses, FINN falls back to the other exchange or to cached data.

## Supply-chain hygiene

- Every Python dependency, direct or transitive, is resolved with uv's `exclude-newer` cutoff. Nothing released in the 14 days before locking is used, because that is where regressions and compromised uploads show up first.
- `uv.lock` pins exact versions with hashes.
- GitHub Actions are pinned to full commit SHAs.

| Component | Version | Why this one |
|---|---|---|
| Python | 3.14.7 | A year of patch releases, and supported a year longer than 3.13. Python 3.15 is weeks old. |
| uv | 0.13 | Lockfile, Python management and fast installs in one tool. |
| yfinance | 1.7.0 | Latest. No breaking changes since 1.4. |
| pandas | 3.0.6 | 3.1.0 is newer than the cutoff. |
| pypdfium2 | 5.14.0 | 5 to 60 times faster than pypdf on our filings, with cleaner text, and it can render page images for the vision step. Permissive licence, unlike PyMuPDF's AGPL. |
| requests and tenacity | 2.34.2 and 9.1.4 | Plain, well-understood HTTP with explicit retry policy. |
| beautifulsoup4 and lxml | 4.15.0 and 6.1.3 | Readable parsing. Speed is irrelevant at a few pages per company. |
| pydantic | 2.14.1 | The export contract, shared later with the FastAPI server. |
| google-genai | 2.29.0 | 2.30.1 was uploaded on the cutoff day itself, so the 14-day rule excluded it. |
| groq | 1.7.0 | Latest. Used only as the text fallback. |
| tenacity | 9.1.4 | google-genai 2.29 requires tenacity below 9.2. |
| Pillow | 12.3.0 | Turns rendered PDF pages into PNGs for the vision model. 13.0 is newer than the cutoff. |

## Data model

| Table | One row per | Key columns |
|---|---|---|
| `companies` | company | symbol, BSE code, bank or not, screener URL |
| `prices` | company per trading day | close, volume, `ret_pct`, `vol_ratio`, `corp_action` |
| `corp_actions` | corporate action | ex-date, kind, subject |
| `filings` | exchange announcement | category, tier, rule that fired, `needs_ai`, text quality, paths to text and kept PDF |
| `documents` | transcript, annual report, presentation or results PDF | period, text path, page count, located annual-report sections |
| `financials` | line item per period | statement, basis, value, raw text |
| `runs` | pipeline run | start, finish, success, per-stage stats |

## The AI layer

Every model call goes through one client, `finn.ai.llm.LLM`. It routes by difficulty,
caches every answer, works down an ordered queue of keys, and logs each real call with
its tokens and latency.

```mermaid
flowchart LR
  T[Task] --> C{Cached?}
  C -- yes --> A[Answer, free]
  C -- no --> R{Tier}
  R -- lite --> L[gemini-3.5-flash-lite<br/>minimal thinking]
  R -- flash --> F[gemini-3.8-flash<br/>low thinking]
  R -- reason --> H[gemini-3.8-flash<br/>high thinking]
  L & F & H --> K[Gemini keys in order<br/>rest on 429]
  K -- all resting, text only --> G[Groq gpt-oss-120b]
  K --> V[Validate against<br/>pydantic schema]
  G --> V --> S[(ai_cache + ai_usage)] --> A
```

| Task | Tier | Why this tier |
|---|---|---|
| Triage: category, tier, title, summary, why it matters | lite, 6 filings per call | High volume and simple judgement. Batching uses one request where six would be needed. |
| Bios from a filing's profile section | lite | Copying facts out of a short, structured section. |
| Results numbers from a PDF's text or page images | flash | Tables need accuracy, and images need a vision model. Only needed until the XBRL arrives. |
| Promised vs. delivered, bull vs. bear (next step) | reason | The few calls that compare and judge. |

### The results ladder

```mermaid
flowchart TD
  X{XBRL filed?} -- yes --> XB[Exact figures from XBRL<br/>no model, no cost]
  X -- not yet --> Q{PDF text clean?}
  Q -- yes --> TX[flash reads the statement text]
  Q -- garbled scan --> IM[render 1 to 3 statement pages<br/>flash reads the images]
  TX & IM --> M[code computes EBITDA, QoQ, YoY, margins]
  XB --> M
  M --> CK{Matches screener.in<br/>within 2%?}
  CK -- yes --> OK[verified badge]
  CK -- no --> FL[mismatch shown on the card]
  Q -- no AI available --> SC[screener.in figures,<br/>labelled unchecked]
```

| Decision | Why |
|---|---|
| **XBRL before any model.** | Companies file machine-readable results with the exchange. They are exact and free. On 27 October all seven portfolio companies that had reported got their card from XBRL, with no model call. |
| **No local OCR.** | The broken text in Maruti's and IndusInd's PDFs is already somebody's OCR. Tesseract-class OCR fails on scanned tables the same way, and would add a system binary to every host. Vision is only for the hours before XBRL arrives. |
| **Code does the arithmetic.** | Models copy numbers from the page; EBITDA, percentage changes and margins are computed in Python, so they cannot be hallucinated. |
| **EBITDA uses screener.in's definition.** | Revenue minus operating costs, where operating costs exclude interest and depreciation. It is unaffected by exceptional items or associates. |
| **The check knows how associates are presented.** | Companies put the share of associates' profit in different places. Maruti shows its ₹69 crore below PBT, and Mazagon Dock's ₹48.5 crore sits inside it. screener.in normalises it. The check accepts either presentation and says which one matched. |
| **Mismatches are shown, not hidden.** | HDFC Bank's consolidated PBT and PAT from XBRL are ₹837 crore below screener.in's, with no associates or minority share to explain it. The card says so. |
| **Banks get their own card.** | Banks have no revenue or EBITDA. The card shows net interest income, operating profit before provisions, provisions, PBT and PAT. |

### Keys and cost

- Keys sit in `backend/.env` locally and in GitHub's encrypted secrets for the scheduled run. Logs and the database only ever see aliases such as `gemini-3`.
- A key that hits a per-minute limit rests for 65 seconds. One that hits its daily quota rests until Google's reset at midnight Pacific time. Cooldowns live in SQLite, so separate runs respect each other.
- Requests are paced at about 9 a minute per key, under the free tier's limit of roughly 10.
- The backlog of 30 days needed about 25 triage calls for 147 filings. A normal day produces about 6 filings, which means 1 or 2 calls.

## Running it

```bash
cd backend
uv sync
uv run python -m finn.refresh            # Push data for the portfolio, then export
uv run python -m finn.fetch INFY         # fundamentals and documents for any ticker
uv run python -m finn.fetch --research-set
uv run python -m finn.enrich --dry-run   # what the AI step would do, and its cost
uv run python -m finn.enrich             # results cards, triage, bios, then export
uv run pytest
```
