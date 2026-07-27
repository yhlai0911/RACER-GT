# Real-data case studies · 真實資料案例研究

## Status · 現況

**These five case studies are protocol-locked and data-free.**

**這五個案例研究已鎖定 protocol，但不含任何資料。**

This directory contains the locked configuration for each study and nothing
else. No Google Trends observations are distributed here, and none are
simulated and presented as if they were real. That is a deliberate limit, not
an oversight, and the reason follows directly from what this package is for.

本目錄僅包含各研究的鎖定設定，不含其他內容。這裡不散布任何 Google Trends 觀察值，也沒有
把模擬資料當成真實資料呈現。這是刻意的界線而非疏漏，理由直接來自本套件的設計目的。

## Why there is no data here · 為什麼這裡沒有資料

RACER-GT is ingestion-first by design: it embeds no Google Trends client,
because endpoints, rate limits, authentication, and terms of service change, and
a statistical method that depends on an unofficial scraper inherits that
fragility. Collection is therefore the researcher's responsibility, performed
through a route that is lawful, compliant, and auditable in their own
institutional context.

Fabricating the data would defeat the entire point. A framework whose central
claim is that measurement must be preregistered, auditable, and honestly
reported cannot ship invented observations labelled as real. If you see a
`raw_chunks.csv` in this directory, someone put it there — check its provenance.

RACER-GT 刻意採 ingestion-first：不內含任何 Google Trends client，因為端點、rate limit、
認證與服務條款都會改變，統計方法若綁定非官方抓取程式就會繼承那份脆弱性。資料蒐集因此是
研究者的責任，須以在其機構脈絡下合法、合規且可稽核的途徑進行。

捏造資料會使一切失去意義。一個核心主張是「量測必須預先註冊、可稽核、據實回報」的框架，
不可能散布被標示為真實的虛構觀察值。

## What each study costs to collect · 各研究的蒐集成本

Every study uses the same design: 81 chunks × 21 pulls (7 collection days × 3
streams × 1 replicate).

| Study | Keyword | Geo | Category | Chunks | Pulls | GT requests |
|---|---|---|---|---:|---:|---:|
| `bitcoin` | `bitcoin` | US | 7 (Finance) | 81 | 21 | 1,701 |
| `gold` | `gold price` | US | 7 (Finance) | 81 | 21 | 1,701 |
| `inflation` | `inflation` | US | 0 (All) | 81 | 21 | 1,701 |
| `sp500` | `S&P 500` | US | 7 (Finance) | 81 | 21 | 1,701 |
| `vietnam-gold` | `giá vàng` | VN | 0 (All) | 81 | 21 | 1,701 |

Collection is spread over 30 days by design, because the collection-day facet is
the point: pulls taken minutes apart cannot identify day-to-day retrieval
variation.

蒐集刻意分布於 30 天，因為 collection-day facet 正是重點所在：相隔數分鐘的 pull 無法識別
逐日的取得變異。

## Running a study once you have data · 取得資料後的執行方式

```bash
# 1. Generate the schedule and chunk manifest. Follow it exactly.
racergt design examples/case_studies/gold.yaml \
  --out studies/gold/protocol --anchor-date 2026-08-01

# 2. Collect. Convert responses to the long format documented in the user guide.
#    Preserve every raw response unmodified.

# 3. Audit before estimating. Exits 2 on failure.
racergt audit examples/case_studies/gold.yaml studies/gold/raw_chunks.csv \
  --out studies/gold/audit.json

# 4. Run. Exits 3 if the locked decision tree returns FAIL.
racergt run examples/case_studies/gold.yaml studies/gold/raw_chunks.csv \
  --benchmark studies/gold/weekly_benchmark.csv \
  --out studies/gold/results
```

## What each study is chosen to stress · 各案例的設計用意

These are not five copies of the same test. Each targets a different failure
mode, so that a framework that only works on easy series is exposed.

這不是同一個測試的五份副本。每個案例針對不同的失效模式，好讓「只在容易的數列上有效」的
框架無所遁形。

- **`bitcoin`** — high, persistent volume. Zero share should be negligible, so
  Fleiss' κ is undefined and the detection rule is reported as indeterminate and
  automatically non-mandatory. This study verifies that the acceptance logic
  does not penalise a series for a coefficient that cannot exist.
  高且持續的搜尋量。零值占比應可忽略，故 κ 無定義、detection 規則報為 indeterminate 並
  自動轉為非強制。此案例驗證驗收邏輯不會因「無法存在的係數」而懲罰一條數列。

- **`gold`** — moderate volume with episodic spikes. The real test is innovation
  reliability: levels usually reproduce, daily changes often do not.
  中等搜尋量、事件型尖峰。真正的考驗是 innovation reliability：水準通常可重現，日變動則往往不行。

- **`inflation`** — deliberately category 0 rather than Finance. Inflation
  searches are not confined to the Finance category, and restricting to it would
  silently change the construct being measured.
  刻意使用 category 0 而非 Finance。通膨相關搜尋不限於財經類別，限制類別會靜默改變所量測的構念。

- **`sp500`** — the term contains an ampersand and a space. Verify that the
  collector URL-encodes the query byte-identically on every pull. A difference
  changes the query specification while the protocol hash still matches, because
  the hash covers the configuration, not the collector's encoding.
  詞彙含 `&` 與空白。須確認收集器每次 pull 都以位元組相同的方式進行 URL 編碼。編碼不同會改變
  查詢設定，但 protocol hash 仍會相符——因為 hash 涵蓋的是設定，不是收集器的編碼行為。

- **`vietnam-gold`** — non-ASCII query in a smaller search market. A high zero
  share is likely and daily frequency may not be supportable at all. If so, the
  correct outcome is FAIL, and the correct response is to move to weekly
  frequency rather than to relax the threshold.
  較小搜尋市場中的非 ASCII 查詢。零值占比可能偏高，日頻甚至可能根本不可行。若如此，正確的
  結果就是 FAIL，正確的回應是改用週頻，而不是放寬門檻。

## The rule that makes these studies worth running · 讓這些研究有意義的規則

Lock the protocol, collect, audit, run, and report whatever the decision tree
returns — including FAIL. A case study that is only published when it passes is
not evidence about the method; it is evidence about the publication filter.

鎖定 protocol、蒐集、稽核、執行，然後如實回報 decision tree 的結果——包括 FAIL。
一個只在通過時才發表的案例研究，不是關於方法的證據，而是關於發表篩選的證據。
