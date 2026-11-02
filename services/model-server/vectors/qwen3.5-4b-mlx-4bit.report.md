# Control vectors for mlx-community/Qwen3.5-4B-MLX-4bit

32 decoder layers, hidden size 2560, steered band layers 9–24. 20 neutral prompts per pole.

| leaning | scale (1σ of neutral activity) | separation of the poles | reach +/− (band median) | share that was language/script/length/emoji/romance/crude (removed) | reading |
|---|---|---|---|---|---|
| energy 能量 | 0.155 | 25.1σ | +26.6σ / −14.6σ | 1%/1%/22%/2%/1%/3% | clean axis |
| warmth 溫度 | 0.188 | 18.9σ | +11.3σ / −17.4σ | 3%/3%/3%/15%/14%/1% | clean axis |
| guard 戒備 | 0.172 | 18.2σ | +23.7σ / −6.2σ | 1%/3%/1%/2%/1%/20% kept | clean axis |
| focus 專注 | 0.196 | 18.6σ | +13.5σ / −18.4σ | 3%/2%/4%/5%/3%/7% | clean axis |
| play 玩心 | 0.271 | 12.9σ | +11.2σ / −9.3σ | 1%/4%/1%/13%/10%/5% | clean axis |
| patience 耐心 | 0.181 | 24.3σ | +11.3σ / −25.3σ | 1%/1%/1%/1%/1%/33% kept | clean axis |
| initiative 主動 | 0.211 | 14.4σ | +5.0σ / −20.4σ | 1%/2%/3%/1%/1%/4% | clean axis |
| familiarity 熟悉 | 0.212 | 16.6σ | +5.5σ / −27.9σ | 2%/1%/2%/6%/3%/7% | clean axis |
| love 愛 | 0.155 | 17.2σ | +17.2σ / −20.2σ | 4%/2%/2%/11%/53% kept/0% | clean axis |

## Overlap between leanings (cosine, band mean)

| | energy | warmth | guard | focus | play | patience | initiative | familiarity | love |
|---|---|---|---|---|---|---|---|---|---|
| energy | +1.00 | +0.14 | -0.04 | +0.07 | +0.10 | +0.03 | +0.34 | +0.08 | -0.01 |
| warmth | +0.14 | +1.00 | -0.35 | -0.05 | +0.16 | +0.17 | +0.19 | +0.09 | +0.26 |
| guard | -0.04 | -0.35 | +1.00 | +0.13 | -0.15 | **-0.57** | -0.08 | -0.26 | -0.06 |
| focus | +0.07 | -0.05 | +0.13 | +1.00 | -0.40 | -0.02 | +0.15 | -0.07 | -0.08 |
| play | +0.10 | +0.16 | -0.15 | -0.40 | +1.00 | +0.08 | +0.04 | +0.07 | +0.12 |
| patience | +0.03 | +0.17 | **-0.57** | -0.02 | +0.08 | +1.00 | +0.03 | +0.07 | +0.05 |
| initiative | +0.34 | +0.19 | -0.08 | +0.15 | +0.04 | +0.03 | +1.00 | +0.24 | +0.12 |
| familiarity | +0.08 | +0.09 | -0.26 | -0.07 | +0.07 | +0.07 | +0.24 | +1.00 | +0.12 |
| love | -0.01 | +0.26 | -0.06 | -0.08 | +0.12 | +0.05 | +0.12 | +0.12 | +1.00 |

Pairs above 0.5 share an axis: guard & patience (-0.57).
