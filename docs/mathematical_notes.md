# RACER-GT 數學摘要

## 1. Estimand

令 `R` 表示預先指定的 retrieval design distribution，網站回傳向量為 `Y(R)`。RACER-GT 的第一個可識別 estimand 是：

```text
theta_t = E_R[Y_t(R) | locked query protocol].
```

若 `R_1,...,R_m` 具有相同鎖定邊際分配，則 `m^{-1} sum_i Y_t(R_i)` 對 `theta_t` design-unbiased；pulls 之間的相關性影響變異數，但不影響期望。

實際上通常採 day × stream × replicate 的分層設計。令 cell `h` 的條件平均為 `theta_th`、預先指定權重為 `pi_h`，則：

```text
theta_t^pi = sum_h pi_h theta_th,
theta_hat_t^pi = sum_h pi_h mean_i(Y_thi).
```

只要納入／缺漏規則不依賴未觀察回傳值，`theta_hat_t^pi` 對 `theta_t^pi` 無偏；這同樣不要求 cells 或 replicates 相互獨立。若 failed requests 或事後刪除與回傳值相關，則可能產生 informative-missingness bias。上述 estimand 不等同絕對搜尋量。

## 2. Overlap graph

對 chunk `j,k` 的 usable overlap：

```text
r_jkt = log Y_jt - log Y_kt = ell_j - ell_k + nu_jkt.
```

將 robust edge estimates 堆疊：

```text
r = B ell + nu,
E(nu | B)=0,
Var(nu | B)=Omega.
```

固定一個 reference scale 後：

```text
ell_hat = (B' W B)^{-1} B' W r.
```

若圖連通且 `W=Omega^{-1}`，此為 relative log scales 的 GLS／BLUE。若 `ell_hat_j` 近似常態，若要估計反尺度 `a_j^{-1}` 並將 `Y_jt` 校準回共同尺度，可用 `exp(-ell_hat_j - Var(ell_hat_j)/2)` 進行一階 lognormal bias correction。

## 3. Crossed-facet G-theory

```text
Y_tdsr = mu + T_t + D_d + S_s + TD_td + TS_ts + DS_ds + TDS_tds + E_tdsr.
```

相對決策誤差：

```text
sigma_delta^2 = sigma_TD^2/n_D + sigma_TS^2/n_S
              + sigma_TDS^2/(n_D n_S)
              + sigma_E^2/(n_D n_S n_R).
```

絕對決策誤差再加入 `D,S,DS` 主效果。Generalizability coefficient：

```text
G = sigma_T^2 / (sigma_T^2 + sigma_delta^2).
```

Dependability coefficient：

```text
Phi = sigma_T^2 / (sigma_T^2 + sigma_Delta^2).
```

若 `n_R=1`，純 technical error 與 `TDS` 不可分離；套件將 `E=0` 並把不可分離部分留在 `TDS`，且在 diagnostics 中標明。

## 4. Covariance-adjusted consensus

```text
Z_t = 1 X_t + e_t,
E(e_t)=0,
Var(e_t)=Sigma.
```

所有線性無偏估計量需滿足 `1'w=1`。最小化 `w'Sigma w` 得：

```text
w_GLS = Sigma^{-1}1 / (1'Sigma^{-1}1).
```

0.1.0 預設再加上 `w_i>=0` 與 `w_i<=cap`。此時仍保持 sum-to-one，但嚴格 BLUE 性質只屬於無限制解；受限解是穩定化後的最小變異凸組合。

## 5. Spectral effective pull count

殘差相關矩陣 `R` 的 participation ratio：

```text
m_eff = tr(R)^2 / tr(R^2).
```

完全獨立時接近 nominal pull count；高度同質時接近 1。它是資訊濃度診斷，不是正式獨立樣本數。

## 6. Temporal benchmarking

Soft estimator：

```text
x_hat = argmin_x (x-z)'Q(x-z) + (Ax-b)'W(Ax-b),
```

閉式解：

```text
x_hat = z + (Q + A'WA)^{-1} A'W(b-Az).
```

Exact mode 以 KKT system 解 `Ax=b`。`Q=lambda_I I + lambda_D D'D + ridge I`。

## 7. Downstream attenuation correction

```text
W_t = X_t + u_t,
Y_t = alpha + beta X_t + gamma'Z_t + epsilon_t.
```

對 controls residualize 後，naive OLS denominator 為 `W'MW`。若 `Omega_u` 已知：

```text
beta_hat_RC = W'MY / [W'MW - tr(M Omega_u)].
```

分母非正時，表示在該假設下訊號變異不足以識別 beta，套件將拒絕回傳看似精確的係數。
