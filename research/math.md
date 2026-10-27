# 用到的數學

符號：`d` 隱藏維度（Qwen3.5-4B 為 2560），`L` 層數（32），操控段 band = [⌊0.3L⌋, ⌊0.8L⌋) = 第 9–24 層。`h_l ∈ ℝ^d` 是第 `l` 層輸出的殘差流（在最後一個位置）。傾向集合 `D` = {能量、溫度、戒備、專注、玩心、耐心、主動、熟悉、愛}。

## 1. 殘差流

每一層只在同一條向量上加東西：

```
h_{l+1} = h_l + Δ_l,    Δ_l = Attn_l(Norm(h_l)) + MLP_l(Norm(h_l + Attn_l(…)))
```

所有介入都作用在 `h_{l+1}` 或 `Δ_l` 上；Norm 在每個子層內部，所以乘在 `Δ_l` 上的增益不會被正規化抵銷。

## 2. 方向抽取（`extract.py`）

- 中性激活：同樣 20 句話在中性系統提示下，取最後一個提示 token 的每層殘差，`N ∈ ℝ^{P×L×d}`。
- 對比：同樣 20 句在兩個相反指令下，`A⁺, A⁻ ∈ ℝ^{P×L×d}`。
- 方向（mean-difference）：`δ_l = mean_p A⁺_{p,l} − mean_p A⁻_{p,l}`，`v_l = δ_l / ‖δ_l‖`。
- 干擾軸：語言、簡繁、長度、emoji、戀愛／性、粗俗，各用同樣方法抽出 `u_{k,l}`，逐層 Gram–Schmidt 成正交；成分 `c_k = (v_l·u_{k,l})`，分享 = band 平均的 `c_k²`，cosine = `√分享`。
- 投影掉（除了保留的，如愛保留戀愛軸、戒備與耐心保留粗俗軸）：`v ← v − Σ_k (v·u_k) u_k`，再正規化。
- 每層統計：中性平均 `μ_{d,l} = mean_p (N_{p,l}·v_l)`，中性標準差 `σ_{d,l} = std_p (N_{p,l}·v_l)`，尺度 `s_d = median_{l∈band} σ_{d,l}`。
- 極點距離（reach）：`r⁺_{d,l} = mean A⁺·v − μ`，`r⁻_{d,l} = μ − mean A⁻·v`。
- 分離度 `= median_{l∈band} (δ_l·v_l)/σ_{d,l}`；傾向重疊 `cos(a,b) = mean_{l∈band} v_{a,l}·v_{b,l}`。
- 預設位置 `= r⁻ / (r⁺ + r⁻)`（0 為負極、1 為正極）。
- 隨機對照方向（`random_dirs.py`）：每層獨立的高斯向量正規化，`μ、σ` 照樣算，reach 取各傾向 reach（以各自 σ 為單位）的中位數。

## 3. 從化學到傾向（runtime）

- 偏離：`state_c = clip((perceived_c − temperament_c)/50, −1, 1)`，六種物質 `c`。
- 投影：`behavior_d = clip(Σ_c W_{d,c}·state_c, −1, 1)`，`W` 手設或擬合（`fit_projection.py`）。
- 熟悉：三項各自飽和 `f(x; τ) = 1 − e^{−x/τ}`（認識天數 τ=30、訊息數 τ=200、不同日子數 τ=14），`familiarity = −1 + 2(0.3 f₁ + 0.4 f₂ + 0.3 f₃)`。
- 愛：`love = clip(stage + 0.35·max(0,OXY) + 0.15·max(0,END) − 0.4·max(0,CORT) − 0.3·max(0,guard), 0, 1) × gate`，`gate = (familiarity + 1)/2`，`stage ∈ {0, 0, 0.15, 0.45, 0.75}` 依關係階段。

## 4. 有效強度 α（`steer.py`）

- 線性：`raw_d = value_d × strength × damping_d`（strength 預設 2.5；折扣：耐心 0.6、戒備 0.8、熟悉 0.8、愛 0.8），`α_d = clip(raw_d, ±MAX)`，MAX = 3.5。
- Hill 門控（可選）：`α_d = sign(raw)·MAX·|raw|^n / (K^n + |raw|^n)`，n = 2，K = 1.5。有門檻、會飽和。
- 總預算：若 `Σ_d |α_d| > TOTAL`（5.0），全部乘 `TOTAL / Σ|α|`。

## 5. 四種作用方式

對 band 裡每一層 `l`，每個生成的 token：

**add**（激活加法，CAA 式）
```
h_{l+1} ← h_{l+1} + Σ_d α_d · s_d · v_{d,l}
```

**target**（單向補差；和 Assistant Axis 的 activation capping 同一運算，門檻動態）
```
p_d = v_{d,l}·h_{l+1} − μ_{d,l}                     現在偏了多少
t_d = α_d · min( r^{sign(α_d)}_{d,l} / FULL , K_σ · σ_{d,l} )     FULL = 2.5，K_σ = 1.5
h_{l+1} ← h_{l+1} + Σ_d [ max(0, t_d − p_d) ]⁺ · v_{d,l}   （t_d < 0 時取 min(0, t_d − p_d)）
```
只補差距，超過目標的不拉回。

**ace**（仿射概念編輯）：只在 band 中間一層，雙向：`h ← h + (t_d − p_d) v`。

**mul**（乘法增益，乘在這一層寫的量上）
```
g_d = 2^{α_d / MAX}
w_d = v_{d,l} · Δ_l                                 這層更新量在方向上的分量
h_{l+1} ← h_{l+1} + Σ_d (g_d − 1) · w_d · v_{d,l}
```
乘在 `Δ_l` 不乘在 `h` 上，所以不會跨層複利（第一版乘殘差偏離量，16 層後直接崩）。

## 6. 直接生理（`physio_of`）

輸入六種物質的偏離 `x_c ∈ [−1,1]` 和壓力 `stress ≥ 0`。Hill 門：`g(x) = sign(x)·|x|^2 / (0.5² + |x|^2)`。

```
arousal     = g( NE + 0.5·ADR − 0.5·END )
strain      = g( max(0,CORT) + max(0,stress) )
band_gain   = 1 + 0.5·arousal           Δ_l ← band_gain·Δ_l，l ∈ band
late_gain   = 1 − 0.4·strain            Δ_l ← late_gain·Δ_l，l ∈ [⌊0.8L⌋, L)
social_gain = 1 + 0.6·g(OXY)            Δ_l ← Δ_l + (social_gain − 1)·Q Qᵀ Δ_l，l ∈ band
temperature ×= (1 + 0.4·max(0,g(DA))) / (1 + 0.5·max(0,g(ADR+NE)))
```
`Q ∈ ℝ^{d×3}` 是 {溫度, 愛, 熟悉} 三個方向在該層的正交基（QR）。均勻增益對照就是只開 `band_gain`。

熵回饋（每個生成 token）：
```
H_t = −Σ_v p_t(v) log p_t(v)
stress_{t+1} = 0.9·stress_t + 0.3·(H_t − usual_t)
usual_{t+1}  = usual_t + 0.05·(H_t − usual_t)        起點為該模型基線回覆的平均熵（4B：2.6 nats）
```

## 7. 無名內分泌（`endocrine.py`）

```
s_t = [ H_t − b_H ,  −log p_t(token) − b_s ,  ‖h^{(l₀)}_t‖ / running_mean − 1 ,  H_t − H_{t−1} ]
h_{t+1} = D·h_t + W·s_t + C·tanh(h_t)          h ∈ ℝ^k，D 對角（各自衰減），C 零對角
gain_l  = 1 + R_l · tanh(h)                     R_l ∈ ℝ^{d×k}，稀疏（密度 2–20%）
Δ_l ← Δ_l ⊙ gain_l
```
大小：`RMS(gain − 1)` 分全部單元與有受體的單元，用來和均勻增益對齊。

## 8. 前向傳播 trace 與放大的量法

每個 token、每層記 `‖h_l‖` 和 `(v_{d,l}·h_l − μ_{d,l}) / s_d`（注意單位是 band 中位尺度 `s_d`，不是該層的 `σ_{d,l}`）。

對照分析（`controls.py`）三種單位：
- σ 單位：trace 的值。
- 絕對：`trace × s_d`。
- 佔殘差範數比例：`絕對 / ‖h_l‖`。

增益：`G = |proj_out − default_out| / added`，`added` 是每層加入的絕對量（add：`α·s_d`；target：`α·K_σ·median_{band} σ`），`default` 是不操控時的位置。

## 9. 歸因圖（`attribute.py`）

目標 token 的 log 機率對每層零探針的梯度 `g_l = ∂ log p(target) / ∂ε_l`（只對最後 24 個 token 微分）：
```
傾向節點 (l,d)： (g_l·v_{d,l}) · (v_{d,l}·h_l − μ_{d,l})
steering 節點 l： g_l · shift_l
層更新節點 l：   g_l · (h_l − h_{l−1})
輸入字 j：       Σ_i g_in[j,i] · x_in[j,i]
```
邊：對目標節點 `(l,d)` 改用 `v_{d,l}·h_l` 當目標函數求梯度 `g'`；來源 `(l₂,d₂)`，先去掉和目標方向重疊的部分 `v₂' = normalize(v₂ − (v₂·v)v)`，權重 `(g'_{l₂}·v₂')·(v₂'·(h_{l₂} − h_{l₂−1}))`：只算該層寫的量，不算殘差帶下去的。

## 10. KL 探針（`/divergence`）

沿固定回覆 teacher-forced，每個位置的原始分佈 `p` 和介入後 `q`：
```
KL(p‖q) = Σ_v p(v)(log p(v) − log q(v))
溫度匹配： p_T ∝ p^{1/T}，T ∈ {0.5,…,2.5}；殘差 = min_T KL(q‖p_T)，擬合 T = argmin
```
殘差是溫度解釋不了的部分；純調溫在各 T 下的 `KL(p‖p_T)` 也回報，供匹配。

## 11. 統計

平均、標準誤 `s/√n`、95% CI `±1.96 s.e.`；長度共變量用 Pearson 相關；評審與人工的一致性用 Pearson 和「差距 ≤ 1 的比例」。

## 12. 訓練資料裡的 budget forcing

思考超過 `max_tokens/2` 時插入 `</think>`，從提示的快取接續生成；這是推論工程，不是本文貢獻。
