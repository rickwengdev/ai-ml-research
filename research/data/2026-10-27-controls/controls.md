# 2026-10-27-controls: controls

mlx-community/Qwen3.5-4B-MLX-4bit, 20 prompts, band 9–24.

## Gain: projection reached (absolute) over the amount one layer adds (absolute), at band end / at output

| direction | method | +1 added/layer | +1 gain band / out | −1 added/layer | −1 gain band / out |
|---|---|---|---|---|---|
| 能量 | add | 0.388 | 81.7 / 255.9 | 0.388 | 72.1 / 205.5 |
| 能量 | target | 0.493 | 111.8 / 325.4 | 0.493 | 48.7 / 143.7 |
| 熟悉 | add | 0.424 | 52.2 / 147.6 | 0.424 | 78.7 / 254.6 |
| 熟悉 | target | 0.517 | 75.4 / 198.8 | 0.517 | 4.1 / 19.5 |
| 戒備 | add | 0.344 | 91.7 / 246.6 | 0.344 | 78.0 / 202.1 |
| 戒備 | target | 0.414 | 104.2 / 252.6 | 0.414 | 74.5 / 186.0 |
| 愛 | add | 0.311 | 85.9 / 255.2 | 0.311 | 78.9 / 232.8 |
| 愛 | target | 0.397 | 129.4 / 369.7 | 0.397 | 18.1 / 51.0 |
| 溫度 | add | 0.470 | 57.2 / 206.1 | 0.470 | 52.1 / 180.4 |
| 溫度 | target | 0.508 | 48.1 / 178.1 | 0.508 | 28.6 / 98.2 |
| random1 | add | 0.104 | 5.4 / 9.1 | 0.104 | 7.8 / 1.3 |
| random1 | target | 0.144 | 30.6 / 22.9 | 0.144 | 39.9 / 2.4 |
| random2 | add | 0.145 | 4.1 / 2.3 | 0.145 | 7.7 / 1.6 |
| random2 | target | 0.145 | 59.3 / 4.6 | 0.145 | 34.0 / 3.6 |
| random3 | add | 0.128 | 5.5 / 3.4 | 0.128 | 3.2 / 2.0 |
| random3 | target | 0.118 | 19.7 / 1.8 | 0.118 | 48.4 / 0.7 |

Mean gain at the output: leanings 200.5, random 4.6.

## Where the unsteered model sits (σ), per direction: at the band start, band end and output

| direction | band start | band end | output |
|---|---|---|---|
| 能量 | +1.4 | -12.2 | -22.6 |
| 熟悉 | -1.1 | -22.3 | -39.9 |
| 戒備 | +1.7 | -0.2 | -2.7 |
| 愛 | -2.6 | -22.4 | -30.2 |
| 溫度 | +1.8 | -5.6 | -18.6 |
| random1 | +1.5 | +2.9 | -0.7 |
| random2 | -1.4 | -5.7 | +9.2 |
| random3 | +1.9 | +7.7 | +7.1 |

## Residual norm per layer (baseline mean)

layers 0, 8, 16, 24, 31: 2.8, 7.4, 10.4, 30.1, 62.5
