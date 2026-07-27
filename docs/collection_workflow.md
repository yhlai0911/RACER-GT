# 資料蒐集與 ingestion workflow

RACER-GT 0.1.0 刻意不內建未經官方保證的 Google Trends scraping。原因是網站端點、認證、rate limit 與服務條款可能改變；將 retrieval client 與統計估計器解耦，可確保研究方法不依賴單一非官方套件。

## 建議流程

1. `racergt design` 產生固定 schedule 與 chunk manifest。
2. 由研究團隊選擇合法、合規且可稽核的取得途徑：官方 API、網站手動匯出，或經研究機構核准的自動化 client。
3. 每個 response 原封不動保存；另外轉換成 RACER-GT long format。
4. 每完成一個 chunk，計算 raw response hash 與 numeric vector hash。
5. 若發生 network interruption、登入改變、cookie 清除或 client 更新，在 metadata 中記錄，不自行判定該 pull 無效。
6. 完成完整 batch 後才鎖檔並執行 formal decision tree。

## Adapter contract

自建 collector 只需輸出 `docs/data_dictionary.md` 所定義的 raw chunk table。統計 pipeline 不需要知道資料是由哪個 client 取得，因此可以在 API alpha、CSV export 或未來官方介面之間替換，而不改變估計邏輯。
