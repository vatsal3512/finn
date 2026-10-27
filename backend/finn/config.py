"""What FINN watches, where it keeps things, and the default thresholds.

Everything a reader might want to change lives here, so the collectors stay free of
hard-coded company lists and magic numbers.
"""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Local only, git-ignored: database, document text, page caches. On a server whose code
# directory is read-only (Vercel), FINN_DATA_DIR points it at /tmp.
DATA_DIR = Path(os.environ.get("FINN_DATA_DIR") or ROOT / "data")
DOCS_DIR = DATA_DIR / "docs"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "finn.db"
EXPORT_DIR = ROOT / "app" / "public" / "data"  # committed: what the app loads


@dataclass(frozen=True)
class Company:
    symbol: str  # NSE symbol
    name: str
    sector: str
    size: str  # Large, Mid or Small, by market value at selection time
    role: str  # "portfolio" for Push, "research" for the Pull demo set

    @property
    def yahoo(self) -> str:
        return f"{self.symbol}.NS"


def _p(symbol: str, name: str, sector: str, size: str) -> Company:
    return Company(symbol, name, sector, size, "portfolio")


def _r(symbol: str, name: str, sector: str, size: str) -> Company:
    return Company(symbol, name, sector, size, "research")


# Picked on 2026-10-27 from live filings and price data. The reason for each pick is
# recorded in PROGRESS_LOG.md, decision D1.
PORTFOLIO: tuple[Company, ...] = (
    _p("HDFCBANK", "HDFC Bank", "Banking", "Large"),
    _p("RELIANCE", "Reliance Industries", "Conglomerate", "Large"),
    _p("BHARTIARTL", "Bharti Airtel", "Telecom", "Large"),
    _p("MARUTI", "Maruti Suzuki", "Automobiles", "Large"),
    _p("ASIANPAINT", "Asian Paints", "Paints", "Large"),
    _p("SUNPHARMA", "Sun Pharma", "Pharmaceuticals", "Large"),
    _p("ETERNAL", "Eternal", "Internet", "Large"),
    _p("ADANIENT", "Adani Enterprises", "Infrastructure", "Large"),
    _p("INDIGO", "IndiGo", "Aviation", "Large"),
    _p("POLYCAB", "Polycab India", "Cables and wires", "Mid"),
    _p("DIXON", "Dixon Technologies", "Electronics manufacturing", "Mid"),
    _p("MAZDOCK", "Mazagon Dock", "Defence shipbuilding", "Mid"),
    _p("PAYTM", "Paytm", "Fintech", "Mid"),
    _p("PERSISTENT", "Persistent Systems", "IT services", "Mid"),
    _p("INDUSINDBK", "IndusInd Bank", "Banking", "Mid"),
    _p("OLAELEC", "Ola Electric", "Electric vehicles", "Small"),
    _p("NAZARA", "Nazara Technologies", "Gaming", "Small"),
    _p("EMUDHRA", "eMudhra", "Digital security", "Small"),
)

# Decision D2: research companies sit outside the portfolio, to show the engine works
# on any ticker.
RESEARCH: tuple[Company, ...] = (
    _r("INFY", "Infosys", "IT services", "Large"),
    _r("LT", "Larsen & Toubro", "Engineering and construction", "Large"),
    _r("KAYNES", "Kaynes Technology", "Electronics manufacturing", "Mid"),
    _r("INDHOTEL", "Indian Hotels", "Hotels", "Large"),
    _r("HFCL", "HFCL", "Telecom equipment", "Small"),
)

ALL_COMPANIES = PORTFOLIO + RESEARCH
BY_SYMBOL = {c.symbol: c for c in ALL_COMPANIES}

# Collection windows
PRICE_HISTORY_DAYS = 400  # a year of sessions plus room for the 20-day baseline
FILINGS_LOOKBACK_DAYS = 30
CORP_ACTION_LOOKBACK_DAYS = 450

# Alert defaults. The app lets the investor change these. The data layer only ships the
# per-day numbers they are compared against, so thresholds never need a server.
VOLUME_BASELINE_SESSIONS = 20
DEFAULT_PRICE_MOVE_PCT = 5.0
DEFAULT_VOLUME_MULTIPLE = 2.0
EXPORT_PRICE_SESSIONS = 120  # enough for sparklines and recent alert history

# Fundamentals depth (decision D6)
TRANSCRIPTS_PER_COMPANY = 4
ANNUAL_REPORTS_PER_COMPANY = 1
