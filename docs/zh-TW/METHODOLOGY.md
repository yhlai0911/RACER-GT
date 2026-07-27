# RACER-GT 方法論

## 估計目標

RACER-GT 不宣稱還原絕對搜尋次數。令潛在搜尋強度為 \(Q_t>0\)，第 \(p\) 個完整 pull、第 \(c\) 個分段的潛在量測為

\[
Z_{pct}=\kappa_{pc}Q_t\exp(x_p'\beta_t+u_{pct}),
\]

其中 \(\kappa_{pc}\) 是分段特有尺度。估計目標為 \(X_t=aQ_t\)，即固定查詢協定下、位於共同相對尺度的潛在搜尋興趣訊號。

## 隨機化資料取得

建議正式設計為 7 個 collection days × 3 個固定 streams × 2 次 technical replicates，共 42 個完整 pulls。stream 的時段與執行順位必須平衡。stream 是複合取得環境，除非另做 crossover factorial design，否則不能把 stream effect 解釋成 IP effect。

## 全域重疊圖校準

對重疊 chunks \(j,k\)：

\[
r_{jkt}=\log(Y_{jt}+c)-\log(Y_{kt}+c)=\lambda_j-\lambda_k+\nu_{jkt}.
\]

由 robust edge estimates 建立 \(\hat d=B\lambda+\nu\)，並估計

\[
\hat\lambda=\arg\min_{\lambda:\lambda_1=0}(\hat d-B\lambda)'W(\hat d-B\lambda).
\]

重疊圖連通是共同尺度識別的必要且充分條件。在 edge errors 條件平均為零時，WLS 在固定參考尺度的子空間內無偏；使用 inverse-covariance weights 時，具有線性無偏估計量中的最小變異性。

## 重複與相依性

精確相同向量保留於 audit archive，但在 analytic information set 中只計一次。near-duplicate 應比較移除共同歷史訊號後的 residual similarity，而不是只使用 raw correlation。connected component 只是相依性診斷，不表示群內每一對皆為 near duplicates。

## Generalizability Theory

令歷史日期 \(t\) 為量測對象，collection day \(d\)、stream \(s\) 與 replicate \(r\) 為 facets：

\[
Y_{tdsr}=\mu+T_t+D_d+S_s+(TD)_{td}+(TS)_{ts}+\cdots+\varepsilon_{tdsr}.
\]

D-study reliability 可寫成

\[
G=\frac{\sigma_T^2}{\sigma_T^2+\sigma_{TD}^2/n_D+\sigma_{TS}^2/n_S+\sigma_{TDS}^2/(n_Dn_S)+\sigma_\varepsilon^2/(n_Dn_Sn_R)}.
\]

level、daily innovation 與 zero/nonzero detection 必須分別估計。

## 共識估計

對校準後量測 \(y_t\)，在 \(1'w=1\) 與 \(H'w=0\) 的設計平衡限制下，最小變異權重為

\[
w^*=\Sigma^{-1}C(C'\Sigma^{-1}C)^{-1}c.
\]

實務版本使用 shrinkage covariance 的 feasible estimator，並同時報告 mean、median 與 constrained GLS 敏感度結果。

## 頻率基準化

日頻指標可向週頻／月頻 benchmark 軟性對齊：

\[
\hat x=(Q+A'WA)^{-1}(Qz+A'Wb).
\]

只有在低頻 benchmark 被視為權威真值時才使用 exact benchmarking。

## 下游測量誤差

若財金模型使用 \(W_t=X_t+u_t\)，則 classical measurement error 會造成 attenuation：

\[
\operatorname{plim}\hat\beta_{OLS}=\beta\frac{\sigma_X^2}{\sigma_X^2+\sigma_u^2}.
\]

RACER-GT 提供 reliability diagnostics、SIMEX 與 multiple-imputation regression。量測 protocol 通過不代表構念效度、因果性或即時可交易性成立。
