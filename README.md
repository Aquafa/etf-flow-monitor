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

注意：兩個資料源都有反爬蟲（需瀏覽器 UA；Trackinsight 對高頻請求回 202 限流），`scrape_stocks.py` 內建重試與間隔。

## 本地執行

```
python scripts/scrape.py     # 更新資料
python -m http.server 8765   # 開 http://localhost:8765
```
