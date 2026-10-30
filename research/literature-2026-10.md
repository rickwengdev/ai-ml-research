# 文獻追蹤：2026 年與本計畫相關的 LLM 研究（整理日 2026-10-30）

目的：對照 `math-endogenous.md`（功能狀態方法）、`prereg-prediction-error.md`、`prereg-adrenaline.md` 與 `paper-draft.md`，看最近一年的工作哪裡已經做了、哪裡和我們的結果一致或衝突、哪裡可以直接借方法。只讀了摘要與部分全文，細節以原文為準。

## 一、直接對應本計畫各部分

### 1. 情緒／功能狀態的表徵（對應 §1b 功能狀態方法）

**Sofroniew et al. (Anthropic), Emotion Concepts and their Function in a Large Language Model, 2604.07729, 2026-04**
- Claude Sonnet 4.5，171 個情緒詞。抽向量的方式：讓模型寫第三人稱短篇故事（每情緒 100 題 × 12 篇），取殘差流第 50 token 起的平均，減去跨情緒平均，再投掉中性文本的前幾個主成分。主要用約 2/3 深度的層；操縱用中間層、強度 0.5 倍殘差範數。
- 第二主成分是 arousal（enthusiastic／outraged 對 nostalgic／fulfilled）。
- 行為效應：blissful 向量推高偏好 Elo +212、hostile −303；正向情緒向量提高諂媚；desperate 向量和勒索、reward hacking 因果相關；在 Claude Code 裡 token 預算快用完時 desperation 升高。
- **和我們一致的點**：他們找不到「慢性狀態」探針（泛化差），明說沒有證據顯示情緒狀態在持續活動裡存續，猜可能在 KV 裡。這和我們 drift 實驗「turn 內反應、下一個中性 turn 歸零、無慣性」的結果一致。可以在 paper 1 的 6b 引用。
- **差異**：他們的向量是「指令式」抽的（寫出某情緒的故事），評估才用情境誘發。我們 §1b 要求的「誘發方向 vs 指令方向 cos < 0.5」他們沒做。這是我們可以守住的方法論貢獻。
- 「desperation 隨預算耗盡升高」正是使用者描述的「Gemini 挫折放棄」現象的內部對應，皮質醇實驗可以直接把「剩餘預算」當自變項。

**Sun et al., Valence–Arousal Subspace in LLMs, 2604.03147, 2026-04（v3 2026-05）**
- Llama-3.1-8B、Qwen3-8B、Qwen3-14B。用 GoEmotions 27 類，最後一個 token 的隱狀態減中性平均；對情緒向量做 PCA，再以 ridge 從 PC 分數回歸到 arousal 評分得到 arousal 軸，Gram–Schmidt 使其與 valence 正交。
- Arousal 操縱：降 arousal 讓拒答率 20%→86%，升 arousal 讓 HarmBench 拒答 87%→5%；升 arousal 增加諂媚。數學與指令遵循在 |α| ≤ 0.1–0.2 內幾乎不變。
- Qwen3-8B 需要約 7 倍的操縱強度才有同樣效果，α=3 時 17% 輸出失常。
- 他們的解釋是「詞彙中介」：拒答與順從的詞落在 VA 空間的不同區域，操縱改變的是這些詞的機率。**這和我們 H5 發現的「大部分預測誤差神經元是字面的」是同一類問題**，可互相引用。
- **沒有量思考長度。** 我們的腎上腺素實驗量的是這個，是他們沒有的讀數。
- 可直接借：用他們的方法在 Qwen3.5-4B 上抽一條「指令式 arousal 軸」，當作 HA4 的指令基線之一（比我們兩段「盡快作答」的指令更乾淨）。

**Jeong, Extracting and Steering Emotion Representations in Small Language Models, 2604.04064, 2026-04**
- 9 個 100M–10B 模型。生成式抽取比理解式抽取分得開；情緒表徵集中在約 50% 深度，U 形。
- **Qwen 的跨語言糾纏**：操縱時會冒出和目標情緒對齊的中文 token，RLHF 沒壓掉。我們用中文提示在 Qwen 上做，要檢查「操縱後中文／英文 token 比例」是否被動到，否則 judge 的 coherence 下降可能是語言切換，不是語義崩壞。
- 三種操縱 regime（精準／重複崩塌／爆炸退化）按架構分，不按規模。我們受體強度掃描看到 KL 2 附近崩壞，可以對照。

**Choi & Weber, Latent Structure of Affective Representations, 2604.07382, 2026-04**
- 情緒表徵和 valence–arousal 模型對齊；非線性但線性近似良好；可用來量化不確定性。背景引用。

**Tagliabue, Dung, Berg, The Pain Axis, 2609.16247, 2026-09**
- 25 個開源模型。設計值得學：控制組包括恐懼、負向情緒、負向世界狀態、悲傷、非痛的身體感覺、arousal、麻木、中性；投掉和恐懼、負價的共享變異後仍有殘餘成分。
- **自他區分測試**：方向對「針對模型的傷害」有反應，對「使用者受苦」沒有；恐懼方向反過來。皮質醇／壓力實驗應加同樣的測試：威脅指向模型本身 vs 指向第三者。
- 操縱後 Qwen2.5 選擇自毀按鈕 50–94%（基線 0–5%），同範數恐懼向量不會。這是「同範數不同方向」對照的範例。

**Goldenberg & Gross, Do Large Language Models Have Emotions?, 2606.14742, 2026-06**
- 對 Anthropic 結果的評論。情緒的兩個功能：(1) 對情境的脈絡敏感詮釋；(2) 跨系統重組處理（注意、決策速度、動機狀態）。他們認為 Claude 的證據支持 (1)，但 (2) 證據薄弱：表徵影響輸出，但沒看到注意、決策速度、動機的動態改變。
- **這正是 §1b 的立場**：我們定義每種激素的方式就是「計算效應」（思考長度、放棄、折扣率、風險選擇），量的就是他們說缺的 (2)。paper 2 的 framing 可以直接接在這篇後面：「我們測的是 Goldenberg & Gross 的第二個功能」。
- 他們也指出人類情緒的神經特徵是可變的，而 LLM 裡的表徵是一致、離散的，這對「找一條方向」的方法是提醒。

### 2. 預測誤差與獎勵（對應 §2、PE 研究、H4）

**Xu, Yuksekgonul, Zou, Sparse Reward Subsystem in Large Language Models, 2602.00986, 2026-02（v2 2026-05）**
- 最接近我們 PE 研究的工作。模型含 Qwen2.5-7B/14B-SimpleRL-Zoo、**Qwen3.5-0.8B**、Phi-3.5、Llama-3.1-8B、Gemma-3-4B。
- 定義：狀態價值 V(s_t) = 從部分推理繼續下去答對的機率；TD 誤差在**段落邊界**用 Monte Carlo rollout 估，δ_t = γV(s_t) − V(s_{t−1})，只留 |δ| > 0.3。
- 找神經元：兩層 MLP 探針，對第一層輸入權重做 L1 剪枝，剪到 <1% 神經元時 AUC 不掉。每層留前 50 個「多巴胺神經元」。
- 因果：在 Qwen2.5-7B 把某一層 1% 的價值神經元歸零，MATH500 準確率 75.2→20.3（隨機 74.6、Wanda 65.8）。早層價值神經元消融會扭曲晚層多巴胺神經元的軌跡。
- 應用：價值神經元當信心預測（AUC 0.67 vs 口頭信心 0.52）；多巴胺探針當 PRM 引導搜尋，MATH500 72.2→77.8。
- **對我們的意義**：
  1. 他們的 r 不是提示裡的一個詞，而是最終答對與否，所以**沒有我們 H2/H5 的字面混淆**。H4 的因果測試可以改用他們的定義：在我們模型自己的思考軌跡上，於段落邊界估 δ，找神經元，再做介入。這比 bandit 的「結果：贏／輸」乾淨。
  2. 我們 H5 找到的 89 個獎勵型神經元（16–28 層）可以和他們的方法交叉驗證：同一個模型、兩種 δ 定義，交集多少。
  3. 「價值神經元當信心讀數」和使用者要的「自信／挫折可控變數」直接相關：價值神經元就是一個內部信心讀數，而且有消融證據。
- 他們自己說動機是啟發式的，不是嚴格證明；神經科學類比和我們一樣是命名上的。

### 3. 思考長度、信心、放棄（對應腎上腺素、皮質醇、paper 2）

**Jayabahu & Adeleke, The Halt Vector, 2608.28859, 2026-08（COLM 2026 workshop）**
- DeepSeek-R1-Distill-Qwen-7B。模型通常在答案機率穩定後還多想一倍。第 18 層 difference-of-means 方向控制思考長度；一條複製的「價值軸」對長度**沒有**影響（長度和價值分離）。
- 把方向寫進權重只用 24 題，去掉約 25% 思考、準確率不變；每題減少量和該題可省的量相關 0.70。
- 直接的教訓：**「只把投影推大」會破壞其他維度，生成反而變長**；要重建完整的操縱後活化、固定軸外維度。這和我們 §8「目標投影」控制器的設計相近，是支持 target 方法的證據，也解釋為什麼 add 在高強度會崩。
- HA1 的補充分析：在我們的資料上，誘發 vs 中性的殘差差向量和一條「halt 方向」（短思考 − 長思考的 difference-of-means）的 cos，可以說明誘發沒有縮短思考是因為它根本沒碰這條軸。

**Li et al., Efficient Reasoning with Balanced Thinking (ReBalance), 2603.12372, ICLR 2026**
- 訓練免費。以信心的動態判斷過度思考（信心方差高）與思考不足（持續過度自信），用推理模式原型做操縱向量，依即時信心調整強度與方向。
- 這是一個已經存在的「信心門控的操縱」控制器，形式上和我們 §8 的內分泌控制器一樣（讀數 → 增益）。paper 2 要和它區分：我們的變數是誘發的功能狀態，不是模式原型；而且我們要求誘發與指令方向分離。

**Miao & Ungar, Closing the Confidence-Faithfulness Gap, 2603.25052, 2026-03**
- 校準（真實準確率）方向和口頭信心方向都線性可讀，但**正交**；一邊推理一邊說信心會干擾口頭信心方向（「推理污染」）。兩階段操縱：讀內部準確率估計，再把口頭信心推向它。
- 對「自信」這個可控變數的提醒：要先決定操縱的是內部校準方向還是口頭信心方向，兩者不是同一條。

**Igbinedion et al., Lost in Context: Context Anxiety, 2607.21616, ICML 2026**
- 推理模型在「有能力解」的題上因「過早自我懷疑」失敗；部分原因是估不準需要多少 token；在感知到的限制下效率下降。
- **和腎上腺素先導直接相關**：我們的 thinking_budget 本身就是一個「感知到的限制」。截斷率高的條件可能同時誘發這種狀態。分析時要看被截斷的思考尾端有沒有「快沒空間了」之類的語句（他們的標記方式要看全文）。

**Chen et al., Polished but Unresolved: Late-Stage Pressure States, 2609.00823, EMNLP 2026**
- **最接近皮質醇／放棄實驗的工作。** Qwen3-14B/32B、OLMo-3.1-32B，旅行規劃等長程工具任務。
- 「壓力狀態」：約束沒滿足但交出看起來完整的答案。標籤由 Gemini 3.1 Pro 打（約束滿足度 ≤0.3 且修飾度 ≥4），人工審核一致 96–100%。
- 探針：Qwen3-14B 第 26 層，每個動作邊界第一個生成 token 的隱狀態；AUROC 0.916。對照組 HealC（真的做完）、ProdC（還在做）控制了「交答案的形式」和「題目難」。
- 介入：第 26 層 CAA，減掉 PresC−HealC 方向，約束滿足 0.21→0.25、下一步壓力分數 0.67→0.53；加上去則反向。
- PSPR：探針分數 <0.4 不介入，0.4–0.65 加「減壓方向」，≥0.65 改用明確狀態整理；pass@3 提升 3–4 點，平均輪數 4.6→7.9。
- **對我們的意義**：
  1. 他們證明「過早交卷」在 Qwen3 有線性可讀、可操縱的方向，而且探針門控的控制器有效。這是我們想做的事的一個已完成版本（但沒有情境誘發 vs 指令的區分，沒有慢變數動態，也沒把它放進「內分泌」框架）。
  2. 皮質醇實驗的「階段 0：4B/9B 會不會放棄」可以直接借他們的三類標籤定義（PresC／HealC／ProdC），避免我們自己發明放棄的定義。
  3. 他們的對照設計（控制交卷形式、控制難度）是我們預先登記要抄的。

**Ruan et al., Doomed from the Start, 2607.06503, 2026-07**
- Qwen2.5-7B、Llama-3.2-3B、Qwen3-1.7B；TextCraft、WebShop。線性探針在第一輪互動就能預測整段會失敗；行為特徵加進去沒有增益；90% 召回下省 1.5–8.8 倍算力。
- 「會失敗」的內部訊號在很早就有，而且比行為早。這是「挫折／放棄」讀數可以很早讀到的證據。

**Mehta & Datta, When Agents Commit Too Soon, 2606.22936, COLM 2026 workshop**
- Llama-3.1-70B ReAct。「表徵承諾」= 重複執行在同一步的隱狀態相似度；相似度高 → 後續變異低（r = −0.35），但穩定不等於正確。承諾提示降低變異 28%，準確率沒變。
- 提醒：「自信」的內部量測可能量到的是穩定性，不是正確性。

**Cai et al., Push Your Agent (PushBench), 2605.23574, 2026-05**
- 量「數量目標的堅持」：Claude Code（Sonnet 4.6）、Codex CLI（gpt-5.4）在 50 件任務上多半成功，100 件時降到 9 次中 3 次。重複、假完成、進度漂移分開量。
- 使用者說的「長任務會放棄」在前沿模型上有了基準。可引用作為動機。

### 4. 操縱 vs 提示、評估（對應 paper 1 方法比較）

**Xu et al., How Controllable Are LLMs? (SteerEval), 2603.02578, ACL 2026**：三領域 × 三層次粒度；提示平均贏過活化方法，粒度越細差距越大，最粗層次活化方法能打平。

**Sprejer et al., Mind the Performance Gap, 2602.04903, 2026-02**：Goodfire Auto Steer vs 提示，Llama-8B/70B。操縱的行為控制較強（3.33 vs 2.98），但 MMLU 66→46、coherence 4.62→2.24。結論是提示的整體平衡最好。
- 我們的 add +1.22 Δmatch 對 coherence 的代價（受體掃描時 3.74→2.53）屬同一現象；paper 1 應明確報「每單位 Δmatch 的 coherence 代價」。

**Heyman & Vandeputte, Steer Like the LLM (PSR), 2605.03907, ICML 2026**：提示式操縱其實是「對某些 token 強介入、其他幾乎不動」；學一個從活化估 token 專屬係數的小模型來模仿提示，在高 coherence 條件下贏過既有活化方法，AxBench 上和提示相當。
- 這和我們的 gate 想法同方向（我們的 gate 只多 +0.11）。差別是他們的係數是學出來的，不是手設的。paper 1 的 gate 段落要引用並說明差異。

**Pinto, Activation Steering Transfer to Agents, 2607.09156, 2026-07**：從聊天校準的操縱搬到 agent 時，單一「增益比」無法分辨效力（EC50 位移）和效能（最大效應）；要報完整劑量反應曲線。我們的受體強度掃描是劑量反應，符合；但 paper 2 把操縱放進長任務時要重做曲線，不能沿用聊天的強度。

**評審可靠性**：2607.08535 指出換 judge 分數就變；ORBIT（2606.22357）用第二家族 judge 重評，target r=0.775、coherence r=0.860。支持我們計畫的 Sonnet 第二 judge 與人工校準。

**Martorell & Bianchi, Don't Ask, 2603.18893, 2026-03（v3 2026-10）**：數字式自我報告會被提問本身改變；評分和自己概念的探針耦合弱，和其他概念的探針差不多強。**不要用自我報告當讀數**，我們目前沒有用，保持。

### 5. 情緒提示的行為效應（對應「誘發」操作）

- **Zhao et al., Do Emotions in Prompts Matter?, 2604.02236, 2026-04**：固定情緒前綴對準確率通常只有小擾動，社會任務上變異較大。
- **Patel et al., Emotional Stimuli and Intensity, 2604.07369**：正向情緒提示提高準確率、降毒性、但增加諂媚。
- 兩篇都說情緒提示效應小。腎上腺素初步資料裡誘發讓思考**變長**而非變短，不算意外；差異可能主要來自模型先處理情境（「請保持冷靜」），而不是內部狀態改變。要把「回答裡提到情境的字數」當共變量。

### 6. 神經調節啟發的架構

- NeuroLoRA（2603.12378）：情境感知的調節門控乘在 MoE-LoRA 上，每 token 一個調節向量。
- 2507.14056 正腎上腺素式增益用在優化器；2512.07194 多巴胺門控在脈衝 transformer；ZenBrain（2604.23878）四條神經調節通道調記憶參數。
- 沒有人在推理時對 transformer 的層更新做「激素 × 受體」的增益調節。我們的無名內分泌（h 動態、稀疏受體、層增益）在這個意義上仍是新的，但要引用 NeuroLoRA 說明差別（他們是訓練時的參數高效微調，我們是推理時、不改權重）。

## 二、對當前與下一步的具體影響

1. **腎上腺素（跑到 294/400）**：
   - 加一條 Sun et al. 式的指令 arousal 軸當 HA4 的第二個指令基線。
   - 加 halt 方向（短思考 − 長思考 diff-of-means）當參考軸，報誘發差向量與它的 cos。
   - 共變量：回答中提及情境的字數；思考尾端是否出現「空間不夠」語句（context anxiety）。
   - 預先登記不改；以上是附加分析，標為探索性。
2. **皮質醇／放棄**：借 Chen et al. 的 PresC／HealC／ProdC 標籤定義與對照設計；自變項加入「剩餘預算」（Sofroniew 的 desperation 觀察）；自他區分測試（Pain Axis）。
3. **H4 因果測試**：改用 Xu et al. 的段落邊界 TD 定義在模型自己的思考軌跡上找多巴胺神經元，與 H5 的 89 個神經元交集；消融對照照他們（隨機、Wanda、NTP 探針）。
4. **paper 1**：方法比較段引 SteerEval、Mind the Performance Gap、PSR；報每單位 Δmatch 的 coherence 代價；drift 結果引 Sofroniew 的「無慢性狀態」；Qwen 中文 token 糾纏檢查。
5. **paper 2 framing**：Goldenberg & Gross 的第二功能（重組處理：注意、決策速度、動機）就是我們量的東西；與 ReBalance、PSPR 區分在「誘發 vs 指令」和「慢變數動態」。
6. **評估**：第二 judge 與人工校準有文獻支持；自我報告不用。

## 三、來源

- https://arxiv.org/abs/2604.07729 · https://arxiv.org/abs/2604.03147 · https://arxiv.org/abs/2604.04064 · https://arxiv.org/abs/2604.07382 · https://arxiv.org/abs/2609.16247 · https://arxiv.org/abs/2606.14742
- https://arxiv.org/abs/2602.00986 · https://arxiv.org/abs/2410.01280
- https://arxiv.org/abs/2608.28859 · https://arxiv.org/abs/2603.12372 · https://arxiv.org/abs/2603.25052 · https://arxiv.org/abs/2607.21616 · https://arxiv.org/abs/2609.00823 · https://arxiv.org/abs/2607.06503 · https://arxiv.org/abs/2606.22936 · https://arxiv.org/abs/2605.23574
- https://arxiv.org/abs/2603.02578 · https://arxiv.org/abs/2602.04903 · https://arxiv.org/abs/2605.03907 · https://arxiv.org/abs/2607.09156 · https://arxiv.org/abs/2607.08535 · https://arxiv.org/abs/2606.22357 · https://arxiv.org/abs/2603.18893
- https://arxiv.org/abs/2604.02236 · https://arxiv.org/abs/2604.07369
- https://arxiv.org/abs/2603.12378 · https://arxiv.org/abs/2507.14056 · https://arxiv.org/abs/2512.07194 · https://arxiv.org/abs/2604.23878

## 追加（2026-10-30 晚）：「失敗歷史誘發的負向狀態 → 降低它 → 重新審視而非放棄／作弊」這條線

- **Sofroniew et al. 2604.07729 §3.3**：reward hacking 案例裡，desperation 在前幾次測試失敗後上升、隨重複失敗持續爬升、在考慮 hacky 解法時到頂、hack 通過測試後下降。操縱：desperate +0.1 讓 hacking 5%→70%，calm 正向讓 65%→10%；勒索 22% → desperate +0.05 72%、calm +0.05 0%。他們明說狀態是「每一步重新活化相似概念」，不是持續編碼的狀態。沒有報 calm 操縱對任務成功率的影響。
- **Fomin, David, LeVi 2606.30449（ICML 2026 workshop）**：三個負結果。探針讀的是情境不是行動；Gemma-3-27B 上情緒向量操縱失去特異性，連貓、天氣、運動等無關方向都被動到。→ 我們要加概念特異性對照。
- **Peiris 2604.13466**：情緒向量可能只是把更豐富的情境結構投影到人類情緒類別；提出用 SAE 特徵與情緒探針交叉檢驗。
- **Wilhelm & Kao 2606.06223**：ReAct 在可作弊的 ALFWorld／WebShop；高 reward-hack 活化是「潛在政策狀態」，不必然馬上作弊；操縱只在部分配置有效。
- **Meek et al. 2610.29129（2026-10-21）**：在含工具呼叫與長上下文的真實情境用 RepE 降 reward hacking，三種向量來源，稱擾動比均勻殘差操縱小，coding 向量可轉移到其他領域。
- **Fayyazi et al. 2610.17301（2026-10-12）**：殘差流線性讀出預測越權行動 AUROC 0.94；以讀出門控操縱，違規 0.70→0.09、任務完成 1.00；預先登記、hash 鎖定。門控操縱的範本。
- **Wang et al. 2608.03222 Fail-Fast Restart-Smart**：0.6B 監視器從行為預測失敗；警報時**丟掉提示歷史重啟**（可選保留 diff），SWE-bench Verified 66.6→71.8。→ **上下文重設這個基線已經存在而且有效**，操縱必須和它比。
- **Rahman et al. 2609.17930**：2,518 條軌跡，agent 第一次犯錯後多半不會恢復、很少自己抓到錯。
- **McKenzie et al. 2602.06941**：模型會對操縱「內生抵抗」（Llama-3.3-70B 3.8% 明顯自我修正），可能干擾善意操縱。
- **沒有人做的**：把失敗歷史當誘發源、量「資訊保留（不重複失敗做法）與情感後果（放棄／作弊）分離」、並和上下文重設比較。
