# 2026-10-27-controls: controls

mlx-community/Qwen3.5-4B-MLX-4bit, 20 prompts, band 9–24.

## Gain: projection reached (absolute) over the amount one layer adds (absolute), at band end / at output

| direction | method | +1 added/layer | +1 gain band / out | −1 added/layer | −1 gain band / out |
|---|---|---|---|---|---|
| 能量 | add | 0.388 | 9.9 / 14.8 | 0.388 | 8.8 / 11.9 |
| 能量 | target | 0.493 | 13.6 / 18.9 | 0.493 | 5.9 / 8.3 |
| 熟悉 | add | 0.424 | 9.3 / 14.7 | 0.424 | 14.0 / 25.4 |
| 熟悉 | target | 0.517 | 13.4 / 19.9 | 0.517 | 0.7 / 2.0 |
| 戒備 | add | 0.344 | 10.5 / 15.6 | 0.344 | 8.9 / 12.8 |
| 戒備 | target | 0.414 | 12.0 / 15.9 | 0.414 | 8.5 / 11.7 |
| 愛 | add | 0.311 | 11.6 / 18.3 | 0.311 | 10.7 / 16.7 |
| 愛 | target | 0.397 | 17.5 / 26.6 | 0.397 | 2.5 / 3.7 |
| 溫度 | add | 0.470 | 11.2 / 15.9 | 0.470 | 10.2 / 13.9 |
| 溫度 | target | 0.508 | 9.5 / 13.8 | 0.508 | 5.6 / 7.6 |
| random1 | add | 0.104 | 1.0 / 0.6 | 0.104 | 1.4 / 0.1 |
| random1 | target | 0.144 | 5.4 / 1.5 | 0.144 | 7.0 / 0.2 |
| random2 | add | 0.145 | 0.7 / 0.3 | 0.145 | 1.4 / 0.2 |
| random2 | target | 0.145 | 10.7 / 0.7 | 0.145 | 6.1 / 0.5 |
| random3 | add | 0.128 | 1.2 / 0.6 | 0.128 | 0.7 / 0.3 |
| random3 | target | 0.118 | 4.4 / 0.3 | 0.118 | 10.7 / 0.1 |

Mean gain at the output: leanings 14.4, random 0.5.

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
