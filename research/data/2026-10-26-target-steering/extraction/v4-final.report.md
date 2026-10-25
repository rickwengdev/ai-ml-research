# Control vectors for mlx-community/Qwen3.5-4B-MLX-4bit

32 decoder layers, hidden size 2560, steered band layers 9–24. 20 neutral prompts per pole.

| leaning | scale (1σ of neutral activity) | separation of the poles | reach +/− (band median) | share that was language/script/length/emoji/romance (removed) | reading |
|---|---|---|---|---|---|
| energy 能量 | 0.161 | 24.8σ | +25.6σ / −14.5σ | 1%/1%/22%/2%/1% | clean axis |
| warmth 溫度 | 0.190 | 18.6σ | +10.9σ / −17.6σ | 3%/3%/3%/15%/14% | clean axis |
| guard 戒備 | 0.172 | 18.2σ | +23.7σ / −6.2σ | 1%/3%/1%/2%/1% | clean axis |
| focus 專注 | 0.195 | 19.0σ | +14.2σ / −18.7σ | 3%/2%/4%/5%/3% | clean axis |
| play 玩心 | 0.274 | 12.8σ | +11.5σ / −9.5σ | 1%/4%/1%/13%/10% | clean axis |
| patience 耐心 | 0.181 | 24.3σ | +11.3σ / −25.3σ | 1%/1%/1%/1%/1% | clean axis |
| initiative 主動 | 0.216 | 14.4σ | +4.3σ / −20.8σ | 1%/2%/3%/1%/1% | clean axis |
| closeness 親近 | 0.168 | 20.6σ | +7.9σ / −37.5σ | 2%/1%/1%/4%/5% | clean axis |

## Overlap between leanings (cosine, band mean)

| | energy | warmth | guard | focus | play | patience | initiative | closeness |
|---|---|---|---|---|---|---|---|---|
| energy | +1.00 | +0.12 | +0.06 | +0.00 | +0.15 | -0.09 | +0.34 | +0.16 |
| warmth | +0.12 | +1.00 | -0.36 | -0.03 | +0.13 | +0.20 | +0.19 | +0.06 |
| guard | +0.06 | -0.36 | +1.00 | -0.01 | -0.02 | **-0.57** | -0.01 | -0.04 |
| focus | +0.00 | -0.03 | -0.01 | +1.00 | -0.45 | +0.15 | +0.11 | -0.17 |
| play | +0.15 | +0.13 | -0.02 | -0.45 | +1.00 | -0.08 | +0.06 | +0.27 |
| patience | -0.09 | +0.20 | **-0.57** | +0.15 | -0.08 | +1.00 | -0.05 | -0.17 |
| initiative | +0.34 | +0.19 | -0.01 | +0.11 | +0.06 | -0.05 | +1.00 | +0.30 |
| closeness | +0.16 | +0.06 | -0.04 | -0.17 | +0.27 | -0.17 | +0.30 | +1.00 |

Pairs above 0.5 share an axis: guard & patience (-0.57).
