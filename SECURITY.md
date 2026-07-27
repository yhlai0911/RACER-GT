# Security Policy · 安全政策

## Supported versions · 支援版本

| Version | Supported |
|---|---|
| 1.0.x | Yes |
| 0.1.x | No |

## Reporting · 回報方式

**English.** Report vulnerabilities privately to **yhlai@mail.dyu.edu.tw**, or
through GitHub's private vulnerability reporting on this repository. Please do
not open a public issue for a security problem. Expect an acknowledgement within
seven days.

**繁體中文。** 請以私下方式回報至 **yhlai@mail.dyu.edu.tw**，或使用本 repository 的
GitHub private vulnerability reporting。請勿為安全性問題開立公開 issue。七日內會收到確認回覆。

## Scope · 範圍

RACER-GT reads research data files and writes result files. It does not perform
network requests, and it embeds no Google Trends client. The realistic risk
surface is therefore parsing untrusted input:

- crafted CSV, Parquet, or Excel input to `racergt.io.read_table`;
- crafted YAML passed to `RacerGTConfig.load_yaml` (parsed with `yaml.safe_load`,
  so arbitrary object construction is already excluded);
- resource exhaustion from adversarially large or pathological inputs.

Findings that require the attacker to already control the machine running the
analysis are out of scope.

RACER-GT 讀取研究資料檔並寫出結果檔，不發出網路請求，也不內含任何 Google Trends
client。實際的風險面因此在於解析不可信輸入：`read_table` 的惡意 CSV/Parquet/Excel、
傳入 `load_yaml` 的惡意 YAML（已使用 `yaml.safe_load`，故排除任意物件建構），
以及超大或病態輸入造成的資源耗盡。若攻擊者已能控制執行分析的機器，則不在範圍內。
