# 驗證報告

## 驗證範圍

RACER-GT 將軟體正確性、已知真值下的統計重建能力，以及即時資料取得三者分開驗證。統計核心的驗證不需要即時連線 Google Trends。

## 自動化測試

repository 的測試涵蓋：

- 42-pull 平衡設計產生；
- 重疊視窗建構；
- overlap graph 連通性與聯立尺度校準；
- duplicate-aware covariance consensus；
- 從 GT 式量測誤差中恢復 latent shape 的端到端測試。

執行：

```bash
python -m pytest -q
```

## Replay 壓力測試

執行：

```bash
python examples/05_real_gt_replay_validation.py
```

資料生成程序建立具有週期性、持續性 innovations 與事件尖峰的 latent attention curve。每個 pull 再加入 stream effect、共同取得誤差、請求特定正規化、四捨五入與額外噪音。比較時只為了對照已知真值而做共同尺度重縮放。

主要指標包括 RMSE、MAE、correlation 與 effective pull count。僅有高 correlation 並不足夠，仍須檢查 graph connectivity、edge residuals、duplicate concentration 與 weight concentration。

## 目前限制

repository 提供 replay validation，而未內嵌可能不穩定或具有授權疑慮的即時 GT 資料集。正式應用時，研究者必須保存經授權的 raw CSV exports，並使用相同 pipeline。只有完成 day-30 full batch 後，才能執行正式 acceptance decision。
