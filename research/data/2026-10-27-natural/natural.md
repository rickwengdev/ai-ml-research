# Natural vs instructed directions (Qwen3.5-4B-MLX-4bit)

| leaning | cos(natural, instructed) | cos with raw instructed | separation (σ) | default between natural poles |
|---|---|---|---|---|
| 能量 | +0.12 |  | 3.7 | 0.45 |
| 溫度 | +0.01 |  | 2.9 | 0.53 |
| 戒備 | +0.28 |  | 5.0 | 0.32 |
| 專注 | +0.22 |  | 3.5 | 0.23 |
| 玩心 | +0.20 |  | 3.8 | 0.48 |
| 耐心 | +0.13 |  | 3.5 | 0.51 |
| 主動 | +0.33 |  | 2.7 | 0.7 |
| 熟悉 | +0.21 |  | 3.4 | 0.49 |
| 愛 | +0.22 |  | 3.0 | 0.57 |

Natural overlaps |cos| ≥ 0.3: warmth-love +0.85 (instructed +0.26), focus-love -0.69 (instructed -0.08), warmth-focus -0.64 (instructed -0.05).
