# ETF 資金流向監測

自動監測 ETF 每日資金流入流出的靜態頁面，涵蓋三個面向：

- **BTC / ETH 現貨 ETF**：來源 [Farside Investors](https://farside.co.uk)，每日各 ETF 明細＋完整歷史
- **各國股市 ETF**（美日中台韓印度等 33 國代表性 ETF）：來源 [Trackinsight](https://www.trackinsight.com)，1週/1月/3月/YTD/1年 淨流量與資產規模
- **區域每日流量**（美國大型股/日本/中國/歐洲/新興市場/拉美/全球）：Trackinsight segment 每日序列
- **風險警示**：前端即時計算的規則式預警——連續流出、單日流量異常值（z-score）、7日/30日動能背離、流出佔 AUM 比例（含絕對金額門檻）、整體風險偏好（risk-on/off 綜合判讀）、地緣政治叢集（台海、China+1、俄烏/歐洲能源、中東、美元避險）同步性判讀。非投資建議。

單位一律 US$m。**自動更新**：GitHub Actions 每日 4 次（UTC 01:30 / 07:30 / 13:30 / 19:30）抓資料寫入 `data/*.json`；頁面每 30 分鐘自動重新讀取。**零依賴**：純 HTML + SVG，可直接部署到 GitHub Pages。

## 結構

| 檔案 | 說明 |
|---|---|
| `index.html` | 監測頁面（BTC/ETH/全球股市 分頁） |
| `scripts/scrape.py` | Farside 完整歷史表格 → `data/btc.json`、`data/eth.json` |
| `scripts/scrape_stocks.py` | Trackinsight 各國/區域流量 → `data/stocks.json` |
| `scripts/receiver.py` | （工具）本機手動補資料用的接收器，部署不需要 |
| `.github/workflows/update-data.yml` | 定時自動更新 |

## 資料更新現況

- **加密 ETF（Farside）**：GitHub Actions 全自動，已驗證可用。
- **股市 ETF（Trackinsight）**：其 search-api 對非瀏覽器用戶端回 202 空回應，對無頭瀏覽器出 Human Verification（CAPTCHA）——**無法全自動**，也不應繞過其驗證。目前做法：在 Claude Code 會話中用瀏覽器分頁（正常瀏覽 session）抓取，經 `scripts/receiver.py` 寫入 `data/stocks.json` 後 push。想更新股市資料時，跟 Claude 說「更新股市資料」即可。`scrape_stocks.py --browser` 為 Playwright 模式，僅在乾淨住宅網路 session 下可能可用。
- workflow 內的股市抓取步驟保留 `continue-on-error`：若 Trackinsight 日後放寬，會自動恢復全自動。

## 本地執行

```
python scripts/scrape.py     # 更新資料
python -m http.server 8765   # 開 http://localhost:8765
```
