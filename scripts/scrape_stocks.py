"""Scrape Trackinsight for country stock-market ETF flows into data/stocks.json.

Two datasets:
  countries — flow aggregates (1w/1m/3m/YTD/1y) + AUM for one representative
              US-listed ETF per country, one batched request.
  segments  — daily net-flow history for major region segments.
All values stored in US$m.
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone, date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
BASE = "https://www.trackinsight.com"

# ticker (as stored in Trackinsight) -> Chinese country name
COUNTRIES = {
    "SPY": "美國", "EWJ": "日本", "MCHI": "中國", "EWT": "台灣", "EWY": "韓國",
    "BATS:INDA": "印度", "EWU": "英國", "EWG": "德國", "EWQ": "法國",
    "EWI": "義大利", "EWP": "西班牙", "EWN": "荷蘭", "EWL": "瑞士",
    "EWD": "瑞典", "EPOL": "波蘭", "XNMS:TUR": "土耳其", "GREK": "希臘",
    "NORW": "挪威", "EWC": "加拿大", "EWW": "墨西哥", "EWZ": "巴西",
    "ARGT": "阿根廷", "EWA": "澳洲", "EWS": "新加坡", "EWH": "香港",
    "EWM": "馬來西亞", "THD": "泰國", "EIDO": "印尼", "EPHE": "菲律賓",
    "VNM": "越南", "EIS": "以色列", "KSA": "沙烏地阿拉伯", "EZA": "南非",
}

SEGMENTS = [
    (117, "us", "美國大型股"),
    (147, "japan", "日本"),
    (146, "china", "中國"),
    (148, "europe", "歐洲"),
    (145, "em", "新興市場"),
    (149, "latam", "拉丁美洲"),
    (151, "global", "全球"),
]

SEGMENT_START = "2024-01-01"

# 使用者的 Trackinsight 公開自選清單（在網站上增減 ETF 會自動同步到頁面）
WATCHLIST_ID = "6qRj83ZV"


def get_json(path, retries=4):
    url = BASE + path
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Referer": "https://www.trackinsight.com/en/etf-screener",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            if body.strip():
                return json.loads(body)
            print(f"  empty response (HTTP {resp.status}), retrying...", file=sys.stderr)
        except Exception as e:
            print(f"  {e}, retrying...", file=sys.stderr)
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"failed after {retries} tries: {url}")


class BrowserFetcher:
    """Fetch the same public endpoints through a real (headless) browser.

    Trackinsight 的 search-api 會對非瀏覽器用戶端回 HTTP 202 空回應（bot 驗證），
    urllib/curl 過不了；用 Playwright 以真實頁面的同源 fetch 取資料。
    """

    def __init__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        ctx = self._browser.new_context(locale="en-US")
        self.page = ctx.new_page()
        self.page.goto(BASE + "/en/fund/EWJ", wait_until="domcontentloaded", timeout=90000)
        self.page.wait_for_timeout(4000)

    def get_json(self, path, retries=4):
        for attempt in range(retries):
            try:
                body = self.page.evaluate(
                    "url => fetch(url).then(r => r.text())", path)
                if body and body.strip():
                    return json.loads(body)
                print("  empty response via browser, retrying...", file=sys.stderr)
            except Exception as e:
                print(f"  {e}, retrying...", file=sys.stderr)
            time.sleep(10 * (attempt + 1))
        raise RuntimeError(f"browser fetch failed: {path}")

    def close(self):
        try:
            self._browser.close()
            self._pw.stop()
        except Exception:
            pass


def fetch_countries():
    tickers = ",".join(COUNTRIES)
    fields = ("ticker,label,USD$3axaum,USD$3axflow1w,USD$3axflow1m,"
              "USD$3axflow3m,USD$3axflowYtd,USD$3axflow1y")
    path = f"/search-api/search_v2/_/key$3axticker={tickers}/{fields}/default/0/60"
    docs = get_json(path)["results"]["docs"]
    m = lambda v: round((v or 0) / 1e6, 1)  # USD -> US$m
    out = []
    for d in docs:
        tk = d["ticker"]
        if tk not in COUNTRIES:
            continue
        out.append({
            "ticker": tk.split(":")[-1],
            "country": COUNTRIES[tk],
            "label": d.get("label", ""),
            "aum": m(d.get("USD:aum")),
            "flow1w": m(d.get("USD:flow1w")),
            "flow1m": m(d.get("USD:flow1m")),
            "flow3m": m(d.get("USD:flow3m")),
            "flowYtd": m(d.get("USD:flowYtd")),
            "flow1y": m(d.get("USD:flow1y")),
        })
    out.sort(key=lambda x: -x["aum"])
    missing = set(COUNTRIES) - {d["ticker"] for d in docs}
    if missing:
        print(f"  warning: missing tickers {missing}", file=sys.stderr)
    return out


def fetch_segment(seg_id):
    end = date.today().strftime("%Y-%m-%d")
    path = (f"/search-api/segment/snapshot/key$3axsegmentId={seg_id}/"
            f"{SEGMENT_START}/{end}/stamp,USD$3axflow")
    r = get_json(path)["results"]
    days = r["stamp"]["data"]
    flows = r["flow"]["data"]
    epoch = date(1970, 1, 1)
    rows = []
    for dnum, f in zip(days, flows):
        d = epoch + timedelta(days=dnum)
        rows.append({"date": d.isoformat(), "flow": round(f / 1000.0, 1)})  # k$ -> US$m
    return rows


def fetch_watchlist():
    meta = get_json(f"/user-api/user/lists/public-lists/{WATCHLIST_ID}")
    ids = (meta.get("data") or {}).get("funds") or []
    if not ids:
        return None
    fields = ("ticker,label,USD$3axaum,USD$3axflow1m,USD$3axflowYtd,"
              "USD$3axflow1y,perf1m,perfYtd")
    idlist = ",".join(str(i) for i in ids)
    docs = get_json(f"/search-api/search_v2/_/key$3axid={idlist}/{fields}/default/0/100")["results"]["docs"]
    m = lambda v: round((v or 0) / 1e6, 1)
    funds = [{
        "ticker": d["ticker"].split(":")[-1],
        "label": d.get("label", ""),
        "aum": m(d.get("USD:aum")),
        "flow1m": m(d.get("USD:flow1m")),
        "flowYtd": m(d.get("USD:flowYtd")),
        "flow1y": m(d.get("USD:flow1y")),
        "perf1m": d.get("perf1m"),
        "perfYtd": d.get("perfYtd"),
    } for d in docs]
    funds.sort(key=lambda x: -x["aum"])
    return {"id": WATCHLIST_ID, "name": meta.get("name", ""), "funds": funds}


def main():
    global get_json
    fetcher = None
    if "--browser" in sys.argv:
        fetcher = BrowserFetcher()
        get_json = fetcher.get_json
    DATA.mkdir(exist_ok=True)
    print("countries...")
    countries = fetch_countries()
    time.sleep(3)
    segments = []
    for seg_id, key, name in SEGMENTS:
        print(f"segment {key} ({seg_id})...")
        rows = fetch_segment(seg_id)
        cumulative = 0.0
        for row in rows:
            cumulative += row["flow"]
            row["cumulative"] = round(cumulative, 1)
        segments.append({"id": seg_id, "key": key, "name": name, "rows": rows})
        time.sleep(3)
    watchlist = None
    try:
        time.sleep(3)
        print("watchlist...")
        watchlist = fetch_watchlist()
    except Exception as e:
        print(f"  watchlist failed, skipping: {e}", file=sys.stderr)
    out = {
        "unit": "US$m",
        "source": "https://www.trackinsight.com",
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "countries": countries,
        "segments": segments,
        "watchlist": watchlist,
    }
    path = DATA / "stocks.json"
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"{len(countries)} countries, {len(segments)} segments, "
          f"watchlist={'ok' if watchlist else 'none'} -> {path.name}")
    if fetcher:
        fetcher.close()


if __name__ == "__main__":
    main()
