"""The list of NSE-listed equities, so the app can search by company name, not only symbol.

An evaluator may type "Infosys" or "Zomato" rather than INFY or ETERNAL, or a symbol from
another market, such as JPM. With NSE's own list, the search box suggests the right
symbol and says plainly when a company is not listed on NSE.

    uv run python -m finn.collectors.symbols
"""

from __future__ import annotations

import csv
import io
import json
import re

from finn import net
from finn.config import EXPORT_DIR

SOURCE = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
SERIES = {"EQ", "BE", "BZ"}  # rolling, trade-for-trade and suspended-trading equities
# Well-known former names, which people still type.
ALIASES = {"ETERNAL": "Zomato"}


def tidy(name: str) -> str:
    """'ETERNAL LIMITED' -> 'Eternal'; 'Infosys Limited' -> 'Infosys'."""
    name = re.sub(r"\s+(limited|ltd\.?)$", "", " ".join(name.split()), flags=re.I)
    if name.isupper():
        name = " ".join(w if len(w) <= 3 else w.capitalize() for w in name.split())
    return name


def fetch() -> list[list[str]]:
    rows = csv.DictReader(io.StringIO(net.nse().get_bytes(SOURCE).decode("utf-8", "replace")))
    out = []
    for r in rows:
        r = {k.strip(): (v or "").strip() for k, v in r.items()}
        if r.get("SERIES") in SERIES and r.get("SYMBOL"):
            entry = [r["SYMBOL"], tidy(r["NAME OF COMPANY"])]
            if r["SYMBOL"] in ALIASES:
                entry.append(ALIASES[r["SYMBOL"]])
            out.append(entry)
    return sorted(out)


def main() -> int:
    symbols = fetch()
    path = EXPORT_DIR / "symbols.json"
    path.write_text(
        json.dumps({"source": SOURCE, "symbols": symbols}, separators=(",", ":")), encoding="utf-8"
    )
    print(f"{len(symbols)} symbols written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
