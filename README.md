# FINN: Financial Investment Agent

A mobile-first agent for an Indian-equities investor. It does two things:

- **Push.** It watches a portfolio's exchange filings and end-of-day prices, and surfaces only what matters: at most three cards a day, with the rest collapsed.
- **Pull.** It researches any NSE company from primary sources only, meaning annual reports and earnings-call transcripts. Its flagship output compares what management promised with what it delivered.

Built for the ENAM Holdings AI Engineer Build Challenge, October 2026.

## Status

| Part | State |
|---|---|
| Data layer: prices, filings, fundamentals | Built and tested |
| AI layer: results cards, triage, bios | Built. Results cards live from XBRL. Triage and bios need API keys |
| Research engine | Planned |
| Phone app | Planned |

## Where to look

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how it works and why each choice was made.
- [SCOPE.md](SCOPE.md): what the prototype does and what it leaves out on purpose.
- [PROGRESS_LOG.md](PROGRESS_LOG.md): the build diary, with every decision and the reason behind it.

## Quick start

Requires [uv](https://docs.astral.sh/uv/). It installs the right Python by itself.

```bash
cd backend
uv sync
uv run python -m finn.refresh       # fetch and export the portfolio's data
uv run python -m finn.fetch INFY    # fundamentals and documents for any ticker
uv run python -m finn.enrich        # results cards, AI triage and bios; keys go in backend/.env
uv run pytest
```

Data comes from public sources: NSE and BSE filings, Yahoo Finance prices, and the documents indexed on screener.in. Nothing here is investment advice.
