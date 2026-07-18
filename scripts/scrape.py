"""Scrape Farside Investors BTC/ETH spot ETF daily flow tables into JSON.

Usage: python scripts/scrape.py [--local]
  --local : parse already-downloaded HTML in data/*.html instead of fetching.
Outputs data/btc.json and data/eth.json.
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

SOURCES = {
    "btc": "https://farside.co.uk/bitcoin-etf-flow-all-data/",
    "eth": "https://farside.co.uk/ethereum-etf-flow-all-data/",
}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def clean(cell: str) -> str:
    text = re.sub(r"<[^>]+>", "", cell)
    return text.replace("&nbsp;", " ").replace("&#8211;", "-").strip()


def to_number(text: str):
    text = text.replace(",", "").strip()
    if text in ("", "-"):
        return 0.0
    neg = text.startswith("(") and text.endswith(")")
    if neg:
        text = text[1:-1]
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if neg else value


def parse_date(text: str):
    m = re.match(r"(\d{1,2}) (\w{3}) (\d{4})", text)
    if not m:
        return None
    day, mon, year = int(m.group(1)), MONTHS.get(m.group(2)), int(m.group(3))
    if not mon:
        return None
    return f"{year:04d}-{mon:02d}-{day:02d}"


def parse_table(html: str):
    m = re.search(r'<table class="etf">(.*?)</table>', html, re.S)
    if not m:
        raise RuntimeError("etf table not found")
    raw_rows = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S)
    tables = [[clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
              for r in raw_rows]

    tickers = None
    rows = []
    for cells in tables:
        if not cells:
            continue
        if tickers is None:
            candidate = [c for c in cells if re.fullmatch(r"[A-Z]{3,6}", c)]
            if len(candidate) >= 3:
                tickers = cells[1:-1]
            continue
        date = parse_date(cells[0])
        if not date:
            continue
        values = [to_number(c) for c in cells[1:]]
        if any(v is None for v in values):
            continue
        flows = dict(zip(tickers, values[:len(tickers)]))
        total = values[-1] if len(values) > len(tickers) else sum(flows.values())
        rows.append({"date": date, "flows": flows, "total": round(total, 1)})

    rows.sort(key=lambda r: r["date"])
    return tickers, rows


def main():
    local = "--local" in sys.argv
    DATA.mkdir(exist_ok=True)
    for asset, url in SOURCES.items():
        if local:
            html = (DATA / f"{asset}-all.html").read_text(encoding="utf-8", errors="replace")
        else:
            html = fetch(url)
        tickers, rows = parse_table(html)
        cumulative = 0.0
        for row in rows:
            cumulative += row["total"]
            row["cumulative"] = round(cumulative, 1)
        out = {
            "asset": asset.upper(),
            "unit": "US$m",
            "source": url,
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tickers": tickers,
            "rows": rows,
        }
        path = DATA / f"{asset}.json"
        path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        print(f"{asset}: {len(rows)} rows, {rows[0]['date']} .. {rows[-1]['date']} -> {path.name}")


if __name__ == "__main__":
    main()
