# FINN: Financial Investment Agent

FINN is a phone app for someone who owns Indian stocks. It does two jobs:

- **Push:** it reads every filing your companies send to the stock exchange, and shows you only the few that matter today. Everything else is folded away.
- **Pull:** you name any company listed on NSE, and FINN checks whether its management did what it promised on its earnings calls. It uses only the company's own documents.

**Try it on your phone:** https://finn-roan.vercel.app

## Try it in 5 minutes

1. **Open Today.** You see at most three cards. A results card shows revenue, EBITDA, profit before tax and profit after tax, this quarter against last quarter and a year ago.
2. **Tap "What did management say about this?"** on a card. FINN answers from the company's last two earnings calls, and shows the exact sentences it used.
3. **Change the time window** at the top: 24 hours, 3 days, 7 days, 30 days, or your own dates.
4. **Open Alerts** and change the limits: how big a price move, how much extra trading volume, and which kinds of filing should alert you.
5. **Open Research and type a company:** a name like "Infosys" or a symbol like TITAN. Try KAYNES first: it missed three promises in a row. Then try a company nobody prepared, such as CIPLA. FINN reads its documents live, in under a minute or two.

## What makes FINN different

- **It filters.** Out of about 250 filings a month for 18 companies, around 40 are worth reading. The rest are folded into one line, such as "18 routine filings".
- **It checks promises with arithmetic.** An AI model reads each earnings call and lists what management promised. Then code, not the model, compares each promise with the reported numbers. Kaynes promised at least ₹4,000 crore of revenue for FY26 and reported ₹3,626 crore, so FINN marks it "missed".
- **Every quote is real.** Before FINN shows a sentence from a call or an annual report, code finds that exact sentence in the document and records the page. A quote that cannot be found is thrown away.
- **Reports keep up by themselves.** When a company files a new call transcript or new results, its report is rebuilt on the next refresh and says what changed ("Now reads the Q1 FY27 call"). Until then it says it is behind. Calls that screener.in never listed are taken from NSE's own announcements.
- **Numbers come from the source.** Results come from the exchange's own data files, and are cross-checked with screener.in. If they don't match, the card says so.
- **Its output is tested, not trusted.** A model can answer differently each time, so we check what it writes: labels against a hand-labelled set, every quote and number against the source, and the same prompt run three times. Every quote in every report (472 of 472) was found word for word in its source, and no number was found to be made up. When Flash answers, 16 of 18 filing labels match the hand labels. The checks also found bugs, now fixed. See [backend/finn/evals/REPORT.md](backend/finn/evals/REPORT.md).

## How it is built

![FINN: how it works](docs/architecture.png)

```
GitHub Actions, every 30 minutes, around the clock
  -> fetch prices, filings and results from NSE, BSE and Yahoo Finance
  -> sort and summarise filings with Gemini
  -> save the results as JSON files in the repo
Vercel
  -> the phone app (Next.js) reads those files, so screens open instantly
  -> a small Python server (FastAPI) does live research and answers questions
```

- **Backend:** Python, in `backend/`. The data collectors, the AI layer and the research engine.
- **App:** Next.js, in `app/`. Its types are generated from the backend's data schema, so the two sides always agree.
- **AI:** Google Gemini, on the free tier. A cheap, fast model sorts routine filings. A stronger model reads earnings calls and makes the bull and bear case. Every answer is cached, so nothing is paid for twice.

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). What is in and out of scope: [SCOPE.md](SCOPE.md).

## Run it yourself

You need [uv](https://docs.astral.sh/uv/) and Node.js.

```bash
cd backend
uv sync
cp .env.example .env                    # then add your Gemini keys
uv run python -m finn.refresh           # fetch and sort this month's filings and prices
uv run python -m finn.research KAYNES   # research one company
uv run uvicorn finn.api:app --port 8000 # the live server
uv run pytest

cd ../app
npm ci
npm run dev                             # http://localhost:3000
```

Data comes from public sources: NSE and BSE filings, Yahoo Finance prices, and documents listed on screener.in. Nothing here is investment advice.
