# Control vectors for lmstudio-community/gemma-4-E4B-it-MLX-4bit

42 decoder layers, hidden size 2560, steered band layers 12–32. 20 neutral prompts per pole.

| leaning | scale (1σ of neutral activity) | separation of the poles | reach +/− (band median) | share that was language/script/length/emoji/romance/crude (removed) | reading |
|---|---|---|---|---|---|
| energy 能量 | 1.210 | 15.4σ | +9.4σ / −15.1σ | 1%/0%/28%/5%/1%/3% | clean axis |
| warmth 溫度 | 1.041 | 15.6σ | +9.5σ / −19.4σ | 2%/5%/9%/21%/13%/1% | clean axis |
| guard 戒備 | 1.612 | 13.4σ | +15.9σ / −3.2σ | 1%/3%/1%/8%/1%/8% kept | clean axis |
| focus 專注 | 1.585 | 13.8σ | +7.2σ / −10.6σ | 2%/4%/21%/10%/2%/3% | clean axis |
| play 玩心 | 1.343 | 13.4σ | +9.8σ / −12.1σ | 3%/3%/7%/20%/7%/8% | clean axis |
| patience 耐心 | 1.866 | 14.3σ | +5.6σ / −9.9σ | 1%/2%/2%/2%/1%/34% kept | clean axis |
| initiative 主動 | 1.699 | 11.6σ | +3.6σ / −12.8σ | 3%/1%/8%/4%/3%/3% | clean axis |
| familiarity 熟悉 | 1.299 | 15.9σ | +5.5σ / −16.1σ | 1%/0%/1%/0%/3%/15% | clean axis |
| love 愛 | 0.957 | 13.1σ | +15.1σ / −7.3σ | 1%/1%/9%/25%/34% kept/1% | clean axis |

## Overlap between leanings (cosine, band mean)

| | energy | warmth | guard | focus | play | patience | initiative | familiarity | love |
|---|---|---|---|---|---|---|---|---|---|
| energy | +1.00 | +0.12 | -0.16 | +0.16 | +0.08 | -0.01 | **+0.55** | -0.03 | +0.01 |
| warmth | +0.12 | +1.00 | -0.41 | -0.15 | +0.30 | +0.18 | +0.09 | +0.04 | +0.34 |
| guard | -0.16 | -0.41 | +1.00 | +0.10 | -0.10 | **-0.50** | -0.17 | -0.15 | -0.09 |
| focus | +0.16 | -0.15 | +0.10 | +1.00 | -0.44 | -0.01 | +0.17 | -0.14 | -0.08 |
| play | +0.08 | +0.30 | -0.10 | -0.44 | +1.00 | +0.05 | +0.11 | +0.18 | +0.13 |
| patience | -0.01 | +0.18 | **-0.50** | -0.01 | +0.05 | +1.00 | -0.03 | +0.02 | +0.07 |
| initiative | **+0.55** | +0.09 | -0.17 | +0.17 | +0.11 | -0.03 | +1.00 | +0.10 | +0.03 |
| familiarity | -0.03 | +0.04 | -0.15 | -0.14 | +0.18 | +0.02 | +0.10 | +1.00 | +0.05 |
| love | +0.01 | +0.34 | -0.09 | -0.08 | +0.13 | +0.07 | +0.03 | +0.05 | +1.00 |

Pairs above 0.5 share an axis: energy & initiative (+0.55), guard & patience (-0.50).
