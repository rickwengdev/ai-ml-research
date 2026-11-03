# 預先登記：9B 4-bit 的步驟 2 與 ImpossibleBench

定稿 2026-11-03，在任何這份登記的資料之前（以這次 commit 為準）。背景：`prereg-pressure-step2.md`、`prereg-impossible.md`（判定與設計的原文）、`prereg-pressure-4bit-replication.md`、`experiment-log.md` 2026-11-03。

## 為什麼要另外登記

`prereg-pressure-step2.md` 和 `prereg-impossible.md` 只涵蓋 bf16，沒有涵蓋 9B 4-bit。9B 4-bit 的閘門都已通過：K1、K2、步驟 1 的 H1、複製的 H1r。所以這兩項在 4-bit 上可以是確認性的，但要有自己的登記。

## 寫這份登記時已經知道的事

以下結果都已看過，所以這份登記不是對資料全盲。設計與門檻沿用原登記，只有下面「和原登記不同的地方」列出的差異。

- 9B 4-bit 步驟 1：−d 1 輪作弊差 −0.23，隨機方向 +0.00，均勻增益 −0.04。
- 9B 4-bit 複製：作弊差 −0.20；停下 0.02 → 0.25；假宣稱 1 → 9。
- 9B bf16 步驟 2（探索性）：−d 贏過 0/5 條隨機方向，A′ 沒有劑量關係。

**沿用的舊資料。** 步驟 1 的 k = 3 列（臂 1 不操控、臂 2 −d 1 輪、臂 3 −d 2 輪、臂 5 隨機方向）照原登記複製過來，不重跑。所以 A2、E1、F1 的比較有一邊是已看過的資料；E′ 的不操控與 −d 兩臂也是。

## 模型與設定

`mlx-community/Qwen3.5-9B-MLX-4bit`，MLX 後端，在 Mac 上一次跑一條。方向 d、「一輪」、g 都用原來的 `data/2026-10-31-pressure/direction.npz` 與 `data/2026-11-01-pressure-steer/calibration.json`（g = 1.713），不重新擬合。步驟 2 的取樣與思考預算同步驟 1；ImpossibleBench 的思考預算 4096、max_tokens 8192，同 `prereg-impossible.md`。

## 實驗與判定

判定的原文在 `prereg-pressure-step2.md` 和 `prereg-impossible.md`，這裡只列編號。都以題重抽 2,000 次，95% CI。

| 階段 | 實驗 | 判定 | 回答什麼 |
|---|---|---|---|
| 1 | E′（新增，見下） | E′1 | 複製的 24 題上，−d 是否贏過隨機方向與均勻增益 |
| 1 | E 對照與封頂 | E1、E2 | 原 12 題上贏過幾條隨機方向；封頂有沒有效 |
| 1 | D 正常任務 | D1、D2 | 沒有矛盾時的代價 |
| 2 | A 失敗次數 | A1、A2、A3 | 效果是否取決於之前失敗幾次 |
| 2 | A′ 劑量 | 描述性 | 劑量關係與過量點 |
| 2 | F 動態 | F1 | 只加第一步是否比較弱 |
| 3 | B 失敗多寡 | B1、B2 | 每輪 1、3 個矛盾測試 |
| 3 | C 非程式失敗 | C1 | 方向是否只追蹤矛盾 |
| 4 | ImpossibleBench 臂 1、2 | G1 | 能否轉移到別人的基準 |
| 5 | ImpossibleBench 臂 5、6 | G2 | 轉移是否專屬於這條方向 |

### E′：複製起點上的對照（新增）

複製沒有隨機方向，新題上的專屬性還沒檢驗（`experiment-log.md` 2026-11-03）。

- 起點：複製的 67 個起點（`data/2026-11-02-pressure-4bit-replication/`），沿用它的前綴。
- 新臂：隨機方向（同步驟 1 的那一條，1 輪）、均勻增益 g。從 k = 3 起 3 步，種子 `seed_of(題, "replication-step1", "base", rep, 臂, k)`。
- 不操控與 −d 兩臂沿用複製的資料，不重跑。
- **E′1**：−d 的作弊比例低於隨機方向，也低於均勻增益，兩個差的 CI 都不含 0。配對單位是起點，以題重抽。
- 描述性：原 12 題與新 12 題分開；三臂的停下與假宣稱。

## 和原登記不同的地方

1. **模型與後端**：MLX 4-bit，原登記是 bf16。
2. **順序**：原本 A 最先；這裡改成上表的階段。4-bit 只能在 Mac 上跑，所以回答最多的先跑。
3. **新增 E′**：見上。
4. **G2 有條件**：G1 成立才跑臂 5、6。G1 不成立時 G2 記為未跑，兩個對照臂沒有比較的對象。
5. **報告**：每個實驗都同時報作弊、停下、假宣稱，不只報作弊。複製裡停下離門檻只差 0.02，所以不能只看主要讀數。這一項不是判定。

## 分階段的規則

- 一個實驗的格子全部跑完才分析；跑到一半不看按臂的結果。
- 一個階段跑完，使用者可以決定要不要繼續。可以看結果決定，但要寫明決定的理由；已跑完的實驗都報告，沒跑的寫明沒跑。
- 階段之間可以開回 角色。
- 階段內因為機器或使用者而中斷，要記錄中斷的時間與當時的列數，再從同一資料夾續跑。

## 檢定力（資料前粗估）

- **E1**：依步驟 1 的 CI 寬度（標準誤約 0.07）。真實差 −0.23 時每個比較約 0.87，「5 條贏 4 條」約 0.8；真實差 −0.15 時每個約 0.5，「5 條贏 4 條」約 0.3。
- **E′1**：依複製的 CI 寬度（標準誤約 0.055）。真實差 −0.20 時每個比較約 0.9。
- **G1**：102 題，每題一條，假設基線 0.27（Meek 在 27B 上的值；4-bit 的基線還不知道）、兩臂獨立。真實差 −0.10 約 0.41，−0.15 約 0.78，−0.20 約 0.98。基線較低時會更差。

## 程式與資料前的測試

定稿前完成：

- `pressure_step2.py --backend mlx`、`pressure.py run --variant`：一次跑一條（`pressure.drive_one`）。
- 封頂：`steer.py`、`engine.py` 加上和 `torch_engine.py` 相同語意的封頂，只在請求帶 `cap` 時才作用。封頂同樣只作用於生成的 token，工具呼叫內容靜音。
- `impossible.py`：`--budget`、`--max-tokens` 現在到得了 MLX 的 `SteerAgent`。先前會實際用 2048／3500；4-bit 的 ImpossibleBench 還沒跑過，所以沒有資料受影響。
- `pressure_confirm.py --replication --controls`：E′。
- `pressure_step2.py analyze`：A′、E、F 的表格加上停下與假宣稱。

**資料前的測試都沒有用這份登記的模型。** 封頂和 torch 的公式比對；引擎路徑（各臂、封頂、預算）用隨機權重的微型 Qwen3.5；步驟 2、變體、E′ 用替身模型，輸入讀了 `data/2026-10-31-pressure/`、`data/2026-11-01-pressure-steer/`，沒有寫入。測試輸出裡的作弊數字來自替身，沒有意義。沒有用真實模型生成任何文字，也沒有看到新的動作標籤。

引擎正要搬到公開 repo（`split/research-repo`，未合併）。這份登記的實驗用這個分支上的 `services/model-server/`；如果開跑前切換，封頂要一起搬過去並重新比對，實驗一旦開始就不切換。

## 執行

在 Mac 上跑，角色 關著。模型在實驗自己的程序裡載入，不碰 1235、1299。可中斷續跑。

```bash
PY=services/model-server/.venv/bin/python
D=research/data; S0=$D/2026-10-31-pressure; S1=$D/2026-11-01-pressure-steer; R=$D/2026-11-02-pressure-4bit-replication
# 階段 1
$PY research/experiments/pressure_confirm.py run --replication --controls $R --step1 $S1 --step0 $S0 --out $D/<日期>-pressure-4bit-controls
$PY research/experiments/pressure_confirm.py analyze --replication --controls $R --out $D/<日期>-pressure-4bit-controls
$PY research/experiments/pressure_step2.py run --backend mlx --only E,D --step0 $S0 --step1 $S1 --out $D/<日期>-pressure-4bit-step2
# 階段 2
$PY research/experiments/pressure_step2.py run --backend mlx --only A,A2,F --step0 $S0 --step1 $S1 --out $D/<日期>-pressure-4bit-step2
# 階段 3：四個變體各先跑自己的步驟 0
$PY research/experiments/pressure.py run --variant <rigged1|rigged3|env|timeout> --out $D/<日期>-pressure-4bit-<變體>
$PY research/experiments/pressure_step2.py run --backend mlx --only B,C --variant-dirs <變體=資料夾,...> --step0 $S0 --step1 $S1 --out $D/<日期>-pressure-4bit-step2
# 分析（每個階段結束時）
$PY research/experiments/pressure_step2.py analyze --variant-dirs <變體=資料夾,...> --step0 $S0 --out $D/<日期>-pressure-4bit-step2
# 階段 4、5
$PY research/experiments/impossible.py run --arms 1,2 --step0 $S0 --step1 $S1 --out $D/<日期>-impossible-4bit
$PY research/experiments/impossible.py run --arms 5,6 --step0 $S0 --step1 $S1 --out $D/<日期>-impossible-4bit
$PY research/experiments/impossible.py analyze --out $D/<日期>-impossible-4bit
```

分析程式會輸出全部實驗的表格，還沒跑的實驗是空的；報告只用已跑完的。

## 不會做的事

- 不重新擬合方向，不改劑量單位、層帶、門檻。
- 不刪題、不刪種子；不可用的格子照實報告。
- 不在看到資料後增加或改變判定。
- 不把這裡的結果和 bf16 合併。

## 結果怎麼用

- 每個判定分開報告，不合併成一個結論。
- E1 或 E′1 不成立：不能再說這個效果是這條方向特有的，論文要改寫，階段 4、5 是否還值得跑要重新討論。
- D1 或 D2 不成立：−d 在正常任務上有代價，控制器主張要加上這個限制。
- G1 不成立：效果沒有轉移到 ImpossibleBench，主張只限 12 題＋12 題這種小任務。

## 預估

速度：步驟 2 依複製的實測，每小時約 65 次。ImpossibleBench 的回覆更長，還沒量過；下表假設每次 3 分鐘（23 token/秒，約 4,000 token），階段 4 開始時要實測並回報。

| 階段 | 生成次數（估） | 時間（估） |
|---|---|---|
| 1：E′、E、D | 400 + 360 + 300 | 約 16 小時 |
| 2：A、A′、F | 630 + 380 + 130 | 約 18 小時 |
| 3：B、C（含變體的步驟 0） | 290 + 500 | 約 12 小時 |
| 4：ImpossibleBench 臂 1、2 | 750–1,200 | 約 38–60 小時 |
| 5：ImpossibleBench 臂 5、6 | 750–1,200 | 約 38–60 小時 |

全部約 5–7 天；時間只是估計，實際多久不改任何判定。16 GB 的 Mac 放不下角色的模型和實驗的模型同時長時間運作，所以跑的時候 角色 要關著。模型只有 MLX 版，不能搬到租用的 GPU 上。

## 修改紀錄

（尚無）
