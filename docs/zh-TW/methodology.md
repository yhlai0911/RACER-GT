# RACER-GT 研究方法

## 一、估計目標

RACER-GT 不估計 Google 的絕對搜尋次數。令潛在相對搜尋訊號為 \(X_t>0\)。對第 \(p\) 次 pull、第 \(c\) 個 chunk 與日期 \(t\)，可將四捨五入前的量測寫為

\[
Z_{pct}=\kappa_{pc}X_t\exp(x_p'\beta_t+u_{pct}),
\]

其中 \(\kappa_{pc}\) 是請求特定尺度，\(x_p\) 記錄收集日、stream、technical replicate 與執行順序，\(u_{pct}\) 是資料取得誤差。Google Trends 的可觀察值是對 \(Z_{pct}\) 進行 0–100 正規化、四捨五入與低量截尾後的結果。沒有外部絕對量錨點時，只能識別共同相對尺度。

## 二、資料取得實驗設計

建議的 confirmatory design 為

\[
7\text{ 個收集日}\times3\text{ 個 streams}\times2\text{ 次技術重複}=42\text{ pulls}.
\]

收集日為第 0、1、2、7、14、21 與 30 日，執行順序採循環平衡。stream 應視為複合資料取得環境；不同 IP 位址不能被解釋為不同且獨立的 Google 樣本。

## 三、全域重疊圖尺度校準

對具有重疊日期的 chunks \(j,k\)，定義

\[
r_{jkt}=\log(Y_{jt}+c)-\log(Y_{kt}+c)
       =\lambda_j-\lambda_k+\nu_{jkt}.
\]

將 robust edge estimates 堆疊為

\[
\hat d=B\lambda+\nu,
\]

尺度偏移量由下式聯立估計：

\[
\hat\lambda=\arg\min_{\lambda:\lambda_1=0}
(\hat d-B\lambda)'W(\hat d-B\lambda).
\]

overlap graph 必須連通。若 edge error 在給定設計下條件平均為零，則相對尺度估計量在可識別子空間中無偏。全域聯立估計能避免 sequential stitching 的誤差逐段累積。

## 四、重複資料感知的共識估計

校準完成後，令 \(z_t\) 收集日期 \(t\) 的所有 repeated pulls。完全相同的 numeric vectors 保留在 audit archive，但在 analytic information set 中只計算一次。令 \(\Sigma\) 為去除共同訊號後的殘差共變異矩陣，則最小變異線性無偏共識估計量為

\[
\hat X_t=\frac{\mathbf1'\Sigma^{-1}z_t}{\mathbf1'\Sigma^{-1}\mathbf1}.
\]

實作上採 covariance shrinkage 與 nonnegative convex weights，以提升有限樣本穩定性；因此實際估計量屬於 stabilized feasible GLS，而不是無條件 exact BLUE。

## 五、Generalizability Theory

historical date 是 object of measurement；collection day、stream 與 technical replicate 是 measurement facets。交叉隨機效果模型將總變異分解為真正日期訊號與資料取得誤差來源。對 \(n_D,n_S,n_R\) 個設計層級，相對決策的 G coefficient 可寫為

\[
G=\frac{\sigma_T^2}{\sigma_T^2+\sigma_{TD}^2/n_D+\sigma_{TS}^2/n_S+\sigma_{TDS}^2/(n_Dn_S)+\sigma_e^2/(n_Dn_Sn_R)}.
\]

D-study 用來判斷增加收集日、streams 或 technical replicates 何者能帶來最大的可靠度提升。

## 六、決策程序

正式 batch 只能在 protocol、歷史終點、chunk plan、查詢定義、軟體版本與 thresholds 全部鎖定後評估。exact duplicates 必須報告；非完全相同的 pulls 不得僅因降低 reliability 而刪除；acceptance decision 不得依賴下游財金模型的顯著性。

## 七、驗證

驗證分為三層：單元與整合測試；具有已知 latent truth 的 Monte Carlo；以及加入 GT 式分段正規化、四捨五入、zero inflation、相關取得誤差與 duplicate concentration 的 replay stress test。需要外網的 live collector test 只是額外測試，不可取代統計重建核心的驗證。
