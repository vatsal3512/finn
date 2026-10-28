# FINN Scope

What FINN does in this prototype, and what it leaves out on purpose.

## Product idea

FINN's job is filtering, not collecting. The investor sees the few things that matter today and nothing else.

**Interaction model: "Today's 3" with "ask about this".**
- The app opens on at most 3 cards: the things that matter most since the investor last looked.
- Everything else sits below in the full digest, collapsed, with a count such as "44 other items, all routine".
- Every card has an "ask about this" button that opens research on that exact event, so Push becomes the doorway into Pull.
- The point of view: the investor has a limited attention budget, and FINN spends it for them.
- Stretch goal if time is left: a portfolio radar screen with 18 tiles sized by how much attention each company needs.

## Push: FINN speaks first

### 1. Windowed digest
- Covers every filing from the 18 portfolio companies in a window the investor picks. The default is the last 24 hours, with options like 3 days, 7 days or custom.
- Each filing is read from its PDF, not just its title, and sorted into the categories from the reference document.
- Filings are ranked into three tiers:
  - **Must see:** results, M&A, management change, fund raise, litigation, pledging, credit rating downgrade.
  - **Worth a glance:** dividend, bonus or split, capex, other credit ratings, insider trading, order wins and other press releases.
  - **Routine, collapsed:** AGM and EGM, postal ballot, investor meetings, earnings-call notices, unclassified paperwork.
- The tier can move with the content. Polycab's insolvency case was over ₹2.79 crore and stayed by the tribunal, so it should not sit at the top like a real insolvency.
- Must-see and worth-a-glance items get a one-line summary of why they matter.

### 2. Results card
- Shows Revenue, EBITDA, PBT and PAT for this quarter, compared with last quarter and with the same quarter last year.
- Numbers come from the results filing itself. A model reads the results-table page as an image, because some PDFs have corrupted text layers.
- EBITDA is not printed in filings. Code computes it as PBT + finance costs + depreciation - other income.
- A "verified" badge shows when the numbers match screener.in's quarterly table. A mismatch is flagged, not hidden.
- Banks get their own version with interest earned, operating profit, provisions and PAT, since they have no revenue or EBITDA.
- If extraction fails, the card falls back to screener.in's numbers with a link to the filing.

### 3. Management-change card
- The bio comes from the filing's official "brief profile" section.
- If a filing is only a follow-up, like "assumed charge", FINN links back to the original appointment filing for the profile.
- If someone leaves with no successor named, the card says so.

### 4. Alerts
- Price move: default ±5% in one day, set by the investor.
- Volume: default 2× the 20-day average, set by the investor.
- Filing types: the investor chooses which categories alert immediately.
- Corporate-action days like demergers and splits are skipped, so they don't fire fake crash alerts.
- Alerts appear in an in-app inbox with an unread badge.

## Pull: the investor asks

- Works on any NSE ticker, not just the demo picks.
- Sources, and nothing else:
  - The last 4 earnings-call transcripts.
  - screener.in's standard financial tables, compiled from company filings.
  - Three annual-report sections only: the auditor's report, contingent liabilities and related-party transactions.
- No news, broker notes or model memory. Every claim cites its document and page.

| Output | Role |
|---|---|
| Promised vs. delivered | The flagship. Guidance from each of the last 4 calls against what was actually reported |
| Cash quality | Do profits turn into cash? Operating cash flow vs profit, free cash flow, working-capital trend |
| Bull vs. bear | A tight case each way, built from the two outputs above plus the three annual-report sections |
| Snapshot header | One line of context: what the company does and its latest headline numbers |

The 5 demo companies are researched ahead of time and cached. A new ticker is researched live.

## Model routing and cost

- **Cheap model:** classifying filings, one-line summaries, pulling guidance statements out of each transcript.
- **Cheap vision-capable model:** reading results-table pages.
- **Strong model:** only the promised-vs-delivered comparison and the bull vs. bear synthesis.
- **Cache:** every result is stored by filing ID or document hash, so nothing is paid for twice.

## Deliberately left out

These go into the covering email under "what I left out".

- Web search for executive bios. The filing's official profile is more accurate and free.
- Real phone notifications. Alerts live in an in-app inbox, because web push on iPhones needs an installed app and adds failure points.
- Intraday prices. The brief asks for end-of-day data only.
- The other five research outputs: business snapshot, full financial snapshot, trajectory, balance sheet and guidance as standalone sections.
- Full annual-report parsing. Only three targeted sections are read.
- Voice briefing and swipe-to-train ranking.
- User accounts and login. The prototype has one demo investor.

## Companies

- Portfolio (18): HDFCBANK, RELIANCE, BHARTIARTL, MARUTI, ASIANPAINT, SUNPHARMA, ETERNAL, ADANIENT, INDIGO, POLYCAB, DIXON, MAZDOCK, PAYTM, PERSISTENT, INDUSINDBK, OLAELEC, NAZARA, EMUDHRA. Picked so the week's filings show every feature: results, a CEO change, a fund raise, an insolvency case, sharp price moves.
- Research picks (5): INFY, LT, KAYNES, INDHOTEL, HFCL, all outside the portfolio, to show research works on any company.
