# -*- coding: utf-8 -*-
"""每日 ETF 資金流向 Email 日報：圖表＋分析＋警示。

用法：
  python scripts/report.py --dry-run   # 只產生 report-preview.html（不寄信）
  python scripts/report.py             # 寄信（需環境變數 SMTP_USER / SMTP_PASS / MAIL_TO）

分析規則與網頁「風險警示」分頁一致（連續流出、z-score 異常、動能背離、
流出佔 AUM 比例、地緣叢集、價量背離）。圖表刻意不用中文（避免 CI 缺字型），
中文都放在 HTML 文字裡。
"""
import json
import os
import smtplib
import sys
from datetime import date, datetime, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = "https://aquafa.github.io/etf-flow-monitor/"

INFLOW, OUTFLOW = "#2a78d6", "#e34948"
GRID, INK, MUTED = "#e1e0d9", "#0b0b0b", "#898781"
SEV_STYLE = {
    "critical": ("✖ 嚴重", "#d03b3b"),
    "serious": ("⚠ 警告", "#b3541e"),
    "warn": ("▲ 注意", "#8a6100"),
    "ok": ("✓ 正常", "#006300"),
}
SEV_ORDER = {"critical": 3, "serious": 2, "warn": 1, "ok": 0}

CLUSTERS = [
    ("東亞／台海情勢", ["EWT", "EWY", "EWJ", "MCHI", "EWH"]),
    ("供應鏈移轉（China+1）", ["INDA", "VNM", "EIDO", "THD", "EPHE", "EWM"]),
    ("歐洲／俄烏與能源", ["EWG", "EPOL", "EWQ", "EWU", "NORW"]),
    ("中東情勢", ["EIS", "KSA", "TUR"]),
    ("美元資產避險", ["SPY"]),
]


# ---------- helpers ----------
def fmt_m(v):
    sign = "+" if v > 0 else ("−" if v < 0 else "")
    a = abs(v)
    return f"{sign}{a/1000:.2f} B" if a >= 1000 else f"{sign}{a:.1f} M"


def color_of(v):
    return "#006300" if v > 0 else ("#d03b3b" if v < 0 else MUTED)


def sum_last(rows, n, key="total"):
    return sum(r[key] for r in rows[-n:])


def outflow_streak(rows, key="total"):
    k = 0
    for r in reversed(rows):
        if r[key] < 0:
            k += 1
        else:
            break
    return k


def last_z(rows, key="total", n=90):
    vals = [r[key] for r in rows[-(n + 1):-1]]
    if len(vals) < 20:
        return 0.0
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    sd = var ** 0.5 or 1.0
    return (rows[-1][key] - mean) / sd


def trend_label(s7, s30):
    if abs(s7) + abs(s30) < 1:
        return "持平"
    p7, p30 = s7 / 7, s30 / 30
    if s7 > 0 and s30 > 0:
        return "加速流入" if p7 > 1.5 * p30 else ("流入放緩" if p7 < 0.5 * p30 else "穩定流入")
    if s7 < 0 and s30 < 0:
        return "加速流出" if p7 < 1.5 * p30 else "持續流出"
    return "流出趨緩、轉為流入" if s7 > 0 else "由流入轉為流出"


# ---------- analysis (與 index.html 的規則一致) ----------
def analyze_series(name, rows, alerts, quiet=False):
    s7, s30 = sum_last(rows, 7), sum_last(rows, 30)
    streak = outflow_streak(rows)
    z = last_z(rows)
    last = rows[-1]["total"]
    if streak >= 5:
        alerts.append(("serious", f"{name}：連續 {streak} 個交易日淨流出",
                       "資金持續撤離超過一週，通常領先於價格走弱或風險事件確認。"))
    elif streak >= 3:
        alerts.append(("warn", f"{name}：連續 {streak} 個交易日淨流出",
                       "短期資金轉向觀望，若延續至 5 日以上將升級為警告。"))
    if z <= -2.5:
        alerts.append(("serious", f"{name}：異常大額單日流出（{fmt_m(last)}）",
                       f"偏離近 90 日常態 {abs(z):.1f} 個標準差，通常為機構調整或事件驅動避險。"))
    elif z >= 2.5 and not quiet:
        alerts.append(("warn", f"{name}：異常大額單日流入（{fmt_m(last)}）",
                       f"偏離近 90 日常態 {z:.1f} 個標準差，留意是否為短線資金。"))
    if s7 < 0 < s30:
        alerts.append(("warn", f"{name}：趨勢背離（30 日累計流入、近 7 日轉為流出）",
                       f"7 日累計 {fmt_m(s7)}、30 日累計 {fmt_m(s30)}，資金動能領先反轉。"))
    if s30 < 0 and s7 / 7 < (s30 / 30) * 1.5:
        alerts.append(("serious", f"{name}：流出加速中",
                       f"近 7 日日均流出 {fmt_m(s7/7)}，快於 30 日均速，撤離動能增強。"))
    return {"name": name, "day": last, "s7": s7, "s30": s30, "trend": trend_label(s7, s30)}


def compute(btc, eth, stocks):
    alerts, trends = [], []
    trends.append(analyze_series("BTC 現貨 ETF", btc["rows"], alerts))
    trends.append(analyze_series("ETH 現貨 ETF", eth["rows"], alerts))
    seg = {}
    if stocks:
        for s in stocks["segments"]:
            seg[s["key"]] = s
            rows = [{"total": r["flow"]} for r in s["rows"]]
            trends.append(analyze_series(s["name"] + "（區域）", rows, alerts, quiet=True))
        for c in stocks["countries"]:
            pct = (c["flow1m"] / c["aum"] * 100) if c["aum"] > 0 else 0
            if pct <= -6 and abs(c["flow1m"]) >= 100:
                alerts.append(("critical", f"{c['country']}（{c['ticker']}）：單月流出達資產規模 {abs(pct):.1f}%",
                               f"月流出 {fmt_m(c['flow1m'])}，屬系統性撤離訊號。"))
            elif pct <= -3 and abs(c["flow1m"]) >= 50:
                alerts.append(("serious", f"{c['country']}（{c['ticker']}）：單月流出佔資產規模 {abs(pct):.1f}%",
                               f"月流出 {fmt_m(c['flow1m'])}，外資配置明顯下修。"))
        wl = stocks.get("watchlist") or {}
        for f in wl.get("funds", []):
            if f.get("perfYtd") is None:
                continue
            if f["perfYtd"] > 0.15 and f["flowYtd"] < 0:
                alerts.append(("warn", f"自選清單 {f['ticker']}：價漲錢跑",
                               f"YTD +{f['perfYtd']*100:.1f}% 但資金累計流出 {fmt_m(f['flowYtd'])}，上漲缺乏資金支撐。"))
            elif f["perfYtd"] < -0.05 and f["flowYtd"] < 0:
                alerts.append(("serious", f"自選清單 {f['ticker']}：價量同弱",
                               f"YTD {f['perfYtd']*100:.1f}%、累計流出 {fmt_m(f['flowYtd'])}，外資持續減碼。"))
    crypto7 = sum_last(btc["rows"], 7) + sum_last(eth["rows"], 7)
    em7 = sum_last(seg["em"]["rows"], 7, "flow") if "em" in seg else 0
    us7 = sum_last(seg["us"]["rows"], 7, "flow") if "us" in seg else 0
    g7 = sum_last(seg["global"]["rows"], 7, "flow") if "global" in seg else 0
    off = (crypto7 < 0) + (em7 < 0) + (g7 < 0)
    if off >= 2 and us7 > 0:
        appetite = ("serious", "避險（Risk-off）",
                    f"高風險資產遭撤出（加密 {fmt_m(crypto7)}、新興 {fmt_m(em7)}），資金迴流美國核心資產（{fmt_m(us7)}）。")
    elif off >= 2:
        appetite = ("critical", "全面收縮", "加密、新興市場與全球股票同步流出，屬廣泛性去槓桿訊號。")
    elif crypto7 > 0 and em7 > 0:
        appetite = ("ok", "風險偏好（Risk-on）", "加密與新興市場同步獲得流入，資金往高風險資產擴散。")
    else:
        appetite = ("warn", "中性",
                    f"方向分歧（加密 {fmt_m(crypto7)}、新興 {fmt_m(em7)}、美國 {fmt_m(us7)}）。")
    if appetite[0] in ("serious", "critical"):
        alerts.append((appetite[0], "整體風險偏好：" + appetite[1], appetite[2]))

    clusters = []
    if stocks:
        by = {c["ticker"]: c for c in stocks["countries"]}
        for name, tickers in CLUSTERS:
            ms = [by[t] for t in tickers if t in by]
            w = sum(c["flow1w"] for c in ms)
            m = sum(c["flow1m"] for c in ms)
            if w < 0 and m < 0 and w / 7 < (m / 30) * 1.5:
                sev, read = "serious", f"資金加速撤出（週 {fmt_m(w)}／月 {fmt_m(m)}），地緣風險溢價上升。"
                alerts.append((sev, f"地緣叢集「{name}」資金加速撤出", read))
            elif w < 0 and m < 0:
                sev, read = "warn", f"持續淨流出（週 {fmt_m(w)}／月 {fmt_m(m)}），維持觀察。"
            elif w < 0:
                sev, read = "warn", f"近一週轉為流出（{fmt_m(w)}），月累計仍為流入（{fmt_m(m)}）。"
            else:
                sev, read = "ok", f"資金面平穩（週 {fmt_m(w)}／月 {fmt_m(m)}）。"
            clusters.append((sev, name, "・".join(c["ticker"] for c in ms), read))
    alerts.sort(key=lambda a: -SEV_ORDER[a[0]])
    return alerts, trends, clusters, appetite, crypto7


# ---------- charts ----------
def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.yaxis.grid(True, color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)


def daily_png(rows, key, title, path):
    rows = rows[-90:]
    vals = [r[key] for r in rows]
    fig, ax = plt.subplots(figsize=(7.6, 2.4), dpi=110)
    ax.bar(range(len(vals)), vals,
           color=[INFLOW if v >= 0 else OUTFLOW for v in vals], width=0.8)
    ax.axhline(0, color="#c3c2b7", linewidth=0.8)
    ticks = list(range(0, len(rows), max(1, len(rows) // 5)))
    ax.set_xticks(ticks)
    ax.set_xticklabels([rows[i]["date"][5:].replace("-", "/") for i in ticks])
    ax.set_title(title, loc="left", fontsize=10, color=INK)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def countries_png(countries, path):
    rows = sorted(countries, key=lambda c: c["flow1m"])
    vals = [c["flow1m"] for c in rows]
    labels = [c["ticker"] for c in rows]
    fig, ax = plt.subplots(figsize=(7.6, 5.6), dpi=110)
    ax.barh(range(len(vals)), vals,
            color=[INFLOW if v >= 0 else OUTFLOW for v in vals], height=0.72)
    ax.axvline(0, color="#c3c2b7", linewidth=0.8)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=7.5)
    ax.set_title("Country ETF net flows – 1M (US$m)", loc="left", fontsize=10, color=INK)
    ax.xaxis.grid(True, color=GRID, linewidth=0.7)
    ax.yaxis.grid(False)
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


# ---------- html ----------
def chip(sev):
    label, color = SEV_STYLE[sev]
    return (f'<span style="color:{color};font-weight:700;font-size:12px;'
            f'white-space:nowrap">{label}</span>')


def build_html(btc, eth, stocks, alerts, trends, clusters, appetite, crypto7, cids):
    today = date.today().isoformat()
    stale = ""
    if stocks:
        sd = (date.today() - date.fromisoformat(stocks["updated"][:10])).days
        if sd >= 3:
            stale = (f'<p style="color:#8a6100;font-size:12px">注意：股市資料為 {sd} 天前'
                     f'（{stocks["updated"][:10]}）更新，如需最新請至頁面手動更新。</p>')
    tile = lambda label, v: (
        f'<td style="border:1px solid #e1e0d9;border-radius:8px;padding:10px 14px">'
        f'<div style="font-size:12px;color:#898781">{label}</div>'
        f'<div style="font-size:20px;font-weight:700;color:{color_of(v)}">US$ {fmt_m(v)}</div></td>')
    h = [f'''<div style="font-family:system-ui,-apple-system,'Segoe UI','Microsoft JhengHei',sans-serif;max-width:720px;margin:auto;color:#0b0b0b">
<h2 style="margin:6px 0">ETF 資金流向日報 <span style="font-weight:400;color:#898781;font-size:14px">{today}・最新交易日 {btc["rows"][-1]["date"]}</span></h2>
{'<p style="color:#8a6100;font-size:12.5px;margin:2px 0">今日為週末／假日後，市場尚無新交易日資料，內容與上一封相同。</p>' if (date.today() - date.fromisoformat(btc["rows"][-1]["date"])).days >= 2 else ''}
<p style="margin:4px 0 12px;font-size:14px">整體風險偏好：{chip(appetite[0])} <b>{appetite[1]}</b><br>
<span style="color:#52514e;font-size:13px">{appetite[2]}</span></p>
{stale}
<table cellspacing="6" style="border-collapse:separate;width:100%"><tr>
{tile("BTC 最新單日", btc["rows"][-1]["total"])}
{tile("ETH 最新單日", eth["rows"][-1]["total"])}
{tile("加密近 7 日", crypto7)}
</tr></table>''']
    n_bad = sum(1 for a in alerts if SEV_ORDER[a[0]] >= 2)
    h.append(f'<h3 style="margin:16px 0 6px">預警訊號（{len(alerts)} 條，其中 {n_bad} 條警告以上）</h3>')
    if not alerts:
        h.append(f'<p>{chip("ok")} 目前沒有觸發任何警示</p>')
    for sev, title, detail in alerts[:14]:
        h.append(f'<p style="margin:6px 0;font-size:13.5px">{chip(sev)} <b>{title}</b><br>'
                 f'<span style="color:#52514e;font-size:12.5px">{detail}</span></p>')
    if len(alerts) > 14:
        h.append(f'<p style="color:#898781;font-size:12px">…另有 {len(alerts)-14} 條，詳見網頁。</p>')
    for cid, caption in cids:
        h.append(f'<h3 style="margin:16px 0 4px;font-size:15px">{caption}</h3>'
                 f'<img src="cid:{cid}" style="max-width:100%;border:1px solid #e1e0d9;border-radius:8px">')
    h.append('<h3 style="margin:16px 0 6px">資金動能總表（US$m）</h3>'
             '<table style="border-collapse:collapse;width:100%;font-size:12.5px">'
             '<tr style="color:#898781"><th align="left">市場</th><th align="right">單日</th>'
             '<th align="right">近7日</th><th align="right">近30日</th><th align="left">判讀</th></tr>')
    for t in trends:
        h.append(f'<tr style="border-top:1px solid #e1e0d9"><td>{t["name"]}</td>'
                 f'<td align="right" style="color:{color_of(t["day"])}">{t["day"]:,.1f}</td>'
                 f'<td align="right" style="color:{color_of(t["s7"])}">{t["s7"]:,.1f}</td>'
                 f'<td align="right" style="color:{color_of(t["s30"])}">{t["s30"]:,.1f}</td>'
                 f'<td style="color:#52514e">{t["trend"]}</td></tr>')
    h.append("</table>")
    if clusters:
        h.append('<h3 style="margin:16px 0 6px">地緣政治叢集</h3>')
        for sev, name, tickers, read in clusters:
            h.append(f'<p style="margin:6px 0;font-size:13.5px">{chip(sev)} <b>{name}</b> '
                     f'<span style="color:#898781;font-size:12px">{tickers}</span><br>'
                     f'<span style="color:#52514e;font-size:12.5px">{read}</span></p>')
    h.append(f'''<p style="margin:18px 0 6px"><a href="{SITE}" style="color:#2a78d6">→ 開啟完整互動頁面</a></p>
<p style="color:#898781;font-size:11.5px;border-top:1px solid #e1e0d9;padding-top:8px">
單位：百萬美元（US$m）。本報告為規則式資金面訊號，非投資建議。
資料來源：Farside Investors（加密）、Trackinsight（股市）。</p></div>''')
    return "".join(h)


# ---------- main ----------
def main():
    dry = "--dry-run" in sys.argv
    btc = json.loads((DATA / "btc.json").read_text(encoding="utf-8"))
    eth = json.loads((DATA / "eth.json").read_text(encoding="utf-8"))
    stocks = None
    if (DATA / "stocks.json").exists():
        stocks = json.loads((DATA / "stocks.json").read_text(encoding="utf-8"))

    alerts, trends, clusters, appetite, crypto7 = compute(btc, eth, stocks)

    tmp = ROOT / "report-tmp"
    tmp.mkdir(exist_ok=True)
    charts = [("btc", "BTC 現貨 ETF 每日淨流量（近 90 交易日）",
               lambda p: daily_png(btc["rows"], "total", "BTC spot ETF daily net flow (US$m)", p)),
              ("eth", "ETH 現貨 ETF 每日淨流量（近 90 交易日）",
               lambda p: daily_png(eth["rows"], "total", "ETH spot ETF daily net flow (US$m)", p))]
    if stocks:
        us = next(s for s in stocks["segments"] if s["key"] == "us")
        charts.append(("us", "美國大型股區域每日淨流量（近 90 交易日）",
                       lambda p: daily_png([{"total": r["flow"], "date": r["date"]} for r in us["rows"]],
                                           "total", "US large-cap segment daily net flow (US$m)", p)))
        charts.append(("countries", "各國股市 ETF 近 1 月淨流量",
                       lambda p: countries_png(stocks["countries"], p)))

    cid_list, files = [], []
    for key, caption, fn in charts:
        p = tmp / f"{key}.png"
        fn(str(p))
        cid = make_msgid(domain="etf-monitor")[1:-1]
        cid_list.append((cid, caption))
        files.append((cid, p))

    html = build_html(btc, eth, stocks, alerts, trends, clusters, appetite, crypto7, cid_list)

    if dry:
        preview = html
        for cid, p in files:
            preview = preview.replace(f"cid:{cid}", p.name)
        (tmp / "report-preview.html").write_text(
            '<!DOCTYPE html><meta charset="utf-8">' + preview, encoding="utf-8")
        print(f"dry-run -> {tmp/'report-preview.html'} ({len(alerts)} alerts)")
        return

    user = os.environ["SMTP_USER"]
    pwd = os.environ["SMTP_PASS"]
    to = os.environ.get("MAIL_TO", user)
    n_bad = sum(1 for a in alerts if SEV_ORDER[a[0]] >= 2)
    msg = EmailMessage()
    last_day = btc["rows"][-1]["date"][5:].replace("-", "/")
    msg["Subject"] = (f"ETF 日報 {date.today().isoformat()}｜資料至 {last_day}｜{appetite[1]}｜"
                      f"BTC {fmt_m(btc['rows'][-1]['total'])}｜警示 {n_bad} 條")
    msg["From"] = user
    msg["To"] = to
    msg.set_content("請使用支援 HTML 的郵件軟體檢視此報告。互動頁面：" + SITE)
    msg.add_alternative(html, subtype="html")
    for cid, p in files:
        msg.get_payload()[1].add_related(p.read_bytes(), "image", "png", cid=f"<{cid}>")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, pwd)
        s.send_message(msg)
    print(f"sent to {to} ({len(alerts)} alerts)")


if __name__ == "__main__":
    main()
