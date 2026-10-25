# Control vectors for mlx-community/Qwen3.5-4B-MLX-4bit

32 decoder layers, hidden size 2560, steered band layers 9–24. 20 neutral prompts per pole.

| leaning | scale (1σ of neutral activity) | separation of the poles | share that was language/length/emoji (removed) | reading |
|---|---|---|---|---|
| energy 能量 | 0.160 | 24.9σ | 1%/23%/2% | clean axis |
| warmth 溫度 | 0.201 | 21.2σ | 3%/4%/14% | clean axis |
| guard 戒備 | 0.172 | 18.4σ | 1%/1%/2% | clean axis |
| focus 專注 | 0.194 | 18.8σ | 3%/4%/5% | clean axis |
| play 玩心 | 0.276 | 12.1σ | 1%/1%/15% | clean axis |
| patience 耐心 | 0.179 | 24.1σ | 1%/1%/1% | clean axis |
| initiative 主動 | 0.214 | 14.5σ | 1%/2%/1% | clean axis |
| closeness 親近 | 0.181 | 18.3σ | 3%/0%/1% | clean axis |

## Overlap between leanings (cosine, band mean)

| | energy | warmth | guard | focus | play | patience | initiative | closeness |
|---|---|---|---|---|---|---|---|---|
| energy | +1.00 | +0.13 | +0.08 | -0.00 | +0.17 | -0.10 | +0.36 | +0.23 |
| warmth | +0.13 | +1.00 | -0.29 | -0.09 | +0.24 | +0.16 | +0.18 | +0.40 |
| guard | +0.08 | -0.29 | +1.00 | -0.04 | +0.04 | **-0.57** | +0.01 | -0.10 |
| focus | -0.00 | -0.09 | -0.04 | +1.00 | -0.48 | +0.16 | +0.11 | -0.16 |
| play | +0.17 | +0.24 | +0.04 | -0.48 | +1.00 | -0.11 | +0.08 | +0.27 |
| patience | -0.10 | +0.16 | **-0.57** | +0.16 | -0.11 | +1.00 | -0.06 | -0.12 |
| initiative | +0.36 | +0.18 | +0.01 | +0.11 | +0.08 | -0.06 | +1.00 | +0.31 |
| closeness | +0.23 | +0.40 | -0.10 | -0.16 | +0.27 | -0.12 | +0.31 | +1.00 |

Pairs above 0.5 share an axis: guard & patience (-0.57).
