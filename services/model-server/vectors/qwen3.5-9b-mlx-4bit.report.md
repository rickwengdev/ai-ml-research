# Control vectors for mlx-community/Qwen3.5-9B-MLX-4bit

32 decoder layers, hidden size 4096, steered band layers 9–24. 20 neutral prompts per pole.

| leaning | scale (1σ of neutral activity) | separation of the poles | reach +/− (band median) | share that was language/script/length/emoji/romance/crude (removed) | reading |
|---|---|---|---|---|---|
| energy 能量 | 0.170 | 33.2σ | +83.0σ / −22.4σ | 0%/2%/26%/2%/1%/3% | clean axis |
| warmth 溫度 | 0.329 | 19.1σ | +17.6σ / −19.3σ | 3%/1%/2%/19%/9%/3% | clean axis |
| guard 戒備 | 0.363 | 15.3σ | +24.8σ / −6.4σ | 0%/2%/1%/4%/3%/15% kept | clean axis |
| focus 專注 | 0.363 | 21.6σ | +14.4σ / −23.3σ | 1%/1%/3%/13%/1%/5% | clean axis |
| play 玩心 | 0.319 | 20.6σ | +17.6σ / −23.7σ | 3%/1%/1%/21%/5%/8% | clean axis |
| patience 耐心 | 0.343 | 20.0σ | +18.1σ / −21.0σ | 2%/3%/3%/0%/2%/27% kept | clean axis |
| initiative 主動 | 0.324 | 13.4σ | +10.9σ / −18.5σ | 1%/4%/6%/1%/5%/4% | clean axis |
| familiarity 熟悉 | 0.270 | 24.0σ | +13.3σ / −45.5σ | 2%/1%/2%/3%/4%/9% | clean axis |
| love 愛 | 0.275 | 21.8σ | +27.5σ / −20.9σ | 4%/1%/2%/15%/40% kept/0% | clean axis |

## Overlap between leanings (cosine, band mean)

| | energy | warmth | guard | focus | play | patience | initiative | familiarity | love |
|---|---|---|---|---|---|---|---|---|---|
| energy | +1.00 | +0.03 | +0.03 | +0.04 | +0.07 | -0.05 | +0.38 | +0.02 | -0.01 |
| warmth | +0.03 | +1.00 | -0.41 | -0.10 | +0.21 | +0.24 | +0.13 | +0.07 | +0.38 |
| guard | +0.03 | -0.41 | +1.00 | +0.06 | -0.17 | **-0.51** | -0.11 | -0.17 | -0.11 |
| focus | +0.04 | -0.10 | +0.06 | +1.00 | -0.37 | +0.01 | +0.22 | -0.11 | -0.05 |
| play | +0.07 | +0.21 | -0.17 | -0.37 | +1.00 | +0.17 | +0.08 | +0.11 | +0.24 |
| patience | -0.05 | +0.24 | **-0.51** | +0.01 | +0.17 | +1.00 | -0.02 | +0.01 | +0.14 |
| initiative | +0.38 | +0.13 | -0.11 | +0.22 | +0.08 | -0.02 | +1.00 | +0.18 | +0.11 |
| familiarity | +0.02 | +0.07 | -0.17 | -0.11 | +0.11 | +0.01 | +0.18 | +1.00 | +0.11 |
| love | -0.01 | +0.38 | -0.11 | -0.05 | +0.24 | +0.14 | +0.11 | +0.11 | +1.00 |

Pairs above 0.5 share an axis: guard & patience (-0.51).
