# RACER-GT 資料字典

## 1. Raw chunk data

一個 `pull_id` 代表在同一套鎖定規格下，為重建完整歷史日頻數列而進行的一整組 chunk requests。每個 `chunk_id` 是固定日期視窗；不同 pull 必須使用完全相同的 chunk set。

### 必要欄位

| 欄位 | 允許值／格式 | 驗證規則 |
|---|---|---|
| `series_id` | UTF-8 string | 同一 pipeline run 應為單一研究指標 |
| `pull_id` | unique string | 一個 pull 只能對應一組 day/stream/replicate |
| `chunk_id` | `C0001` 等 | 必須存在於 locked chunk manifest |
| `historical_date` | `YYYY-MM-DD` | 必須位於 window_start 與 window_end 之間 |
| `value` | numeric | 原始 GT 通常在 0--100；已校準輸入可超出 |
| `collection_day` | integer factor | 代表資料蒐集日層級，不是日曆日期差值本身 |
| `stream_id` | string factor | 複合蒐集環境，不可直接解釋為 IP |
| `replicate_id` | string factor | technical replicate 識別碼 |
| `window_start` | `YYYY-MM-DD` | 必須與 protocol manifest 相符 |
| `window_end` | `YYYY-MM-DD` | 必須與 protocol manifest 相符 |

### 強烈建議欄位

| 欄位 | 用途 |
|---|---|
| `retrieved_at` | UTC timestamp，檢查 timing/order |
| `protocol_hash` | 防止設定漂移 |
| `keyword` | 查詢文字或 topic ID |
| `topic_or_term` | `topic` / `term` |
| `geo` | 地理區域 |
| `category` | GT category code |
| `search_property` | web/news/images/youtube/froogle |
| `language` | 查詢語言設定 |
| `is_partial` | partial period 必須排除 |
| `raw_response_hash` | 原始 response 的 hash |
| `numeric_vector_hash` | chunk numeric vector hash |
| `browser_profile` | stream 環境稽核 |
| `login_status` | stream 環境稽核 |
| `public_ip_hash` | 可匿名保存，不作 independence 證據 |
| `network_event` | 中斷、改線、重新登入等紀錄 |
| `request_order` | 平衡與 order-effect 診斷 |

## 2. Lower-frequency benchmark

`period_start` 與 `period_end` 可表示週、月或其他不重疊／部分重疊期間。若 benchmark 也由多次 GT pulls 建立，應先在其頻率內建構 consensus 與 `se`，再輸入本模組。

## 3. Final series

| 欄位 | 說明 |
|---|---|
| `historical_date` | 日頻日期 |
| `preliminary_value` | benchmark 前共識值（啟用 benchmark 時） |
| `value` | 最終 RACER-GT 指標 |
| `standard_error` | 跨 pull measurement uncertainty 的條件式近似 |
| `ci_lower_95`, `ci_upper_95` | 條件式 95% interval |
| `n_available_pulls` | 當日可用 unique pulls 數 |
| `benchmark_correction` | lower-frequency calibration 修正量 |

Benchmark 後信賴區間保留 cross-pull uncertainty，但 1.0.0 版尚未把 benchmark 本身的不確定性完整傳播到 interval；正式推論應另作 bootstrap 或 joint state-space sensitivity analysis。
