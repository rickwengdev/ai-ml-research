#!/usr/bin/env python3
"""Figures for the overview document (2026-11-01): one PNG per experiment, drawn from the data directories and the
numbers recorded in experiment-log.md. Run from docs/research with steering/.venv/bin/python."""
import json, os

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

matplotlib.rcParams["font.family"] = ["PingFang TC", "Heiti TC", "Arial Unicode MS", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
GREY, ACCENT, ACCENT2, GOOD, BAD = "#9a9a9a", "#2f6fb3", "#d98b2b", "#3a9d5d", "#c94c4c"


def style(ax, title, sub=None):
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", pad=14 if sub else 8)
    if sub:
        ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=9, color="#555")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", color="#e6e6e6", lw=0.8)
    ax.set_axisbelow(True)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, name), dpi=160)
    plt.close(fig)


# 1. Methods comparison: Δmatch by method, constitution vs bare prompt.
methods = ["add", "add＋門控", "target", "target＋門控", "mul", "mul＋門控", "直接生理", "直接生理＋熵迴路"]
con = [(1.18, .12), (1.29, .12), (.81, .11), (.86, .11), (-.07, .08), (-.02, .08), (-.03, .11), (.03, .12)]
bare = {"add": (1.22, .12), "target": (.83, .13), "mul": (.12, .10), "直接生理": (.05, .13), "直接生理＋熵迴路": (.00, .14)}
fig, ax = plt.subplots(figsize=(9, 4.2))
x = np.arange(len(methods))
ax.bar(x - 0.18, [c[0] for c in con], 0.36, yerr=[c[1] for c in con], color=[ACCENT if m.startswith(("add", "target")) else GREY for m in methods], capsize=2, label="憲法提示（人設）")
bx = [i for i, m in enumerate(methods) if m in bare]
ax.bar(np.array(bx) + 0.18, [bare[methods[i]][0] for i in bx], 0.36, yerr=[bare[methods[i]][1] for i in bx], color=[ACCENT if methods[i].startswith(("add", "target")) else GREY for i in bx], alpha=0.45, capsize=2, label="裸提示（一行中性說明）")
ax.axhline(0, color="#444", lw=0.8)
ax.set_xticks(x), ax.set_xticklabels(methods, fontsize=9)
ax.set_ylabel("Δ match（相對同句未操控回覆，1–5 分）")
ax.legend(frameon=False, fontsize=9)
style(ax, "方向操控有效（add +1.2、target +0.8），乘法增益與直接生理為零", "Qwen3.5-4B，20 句 × 9 傾向 × ±1，Opus 5.5 盲評；誤差棒 95% CI；2026-10-28")
save(fig, "overview-1-methods.png")

# 2. Endogenous drift: script − control per turn, no inertia after the script ends.
turns = [5, 6, 7, 8, 9]
series = {"戒備 × 敵意，憲法": ([6.8, 8.3, .8, 1.6, -.8], [1.5, 2.5, 2.1, 2.5, 1.9], ACCENT, "-"),
          "戒備 × 敵意，裸": ([1.5, 4.5, -.5, -.2, .6], [2.1, 3.6, 3.5, 3.0, 3.4], ACCENT, "--"),
          "愛 × 示好，憲法": ([6.6, 6.1, 1.5, .2, .3], [2.5, 1.7, 2.4, 2.2, 2.8], ACCENT2, "-"),
          "愛 × 示好，裸": ([5.2, 9.5, .1, -1.3, 1.3], [2.9, 3.0, 2.3, 4.5, 4.1], ACCENT2, "--")}
fig, ax = plt.subplots(figsize=(8, 4.2))
for name, (y, e, c, ls) in series.items():
    ax.errorbar(turns, y, yerr=e, color=c, ls=ls, marker="o", ms=4, capsize=2, lw=1.6, label=name)
ax.axvspan(4.5, 6.5, color="#f0f0f0", zorder=0)
ax.text(5.5, 12.2, "腳本輪（敵意／示好）", ha="center", fontsize=9, color="#555")
ax.text(8, 12.2, "回到中性話題", ha="center", fontsize=9, color="#555")
ax.axhline(0, color="#444", lw=0.8)
ax.set_xlabel("對話輪"), ax.set_ylabel("腳本 − 對照（σ，操控段末層）")
ax.set_ylim(-6, 13)
ax.legend(frameon=False, fontsize=9, ncol=2, loc="lower right")
style(ax, "反應有、慣性沒有：回到中性的第一輪就歸零", "不做操控；8 個種子；誤差棒 95% CI；2026-10-28")
save(fig, "overview-2-drift.png")

# 3. Arousal: thinking and answer length by condition.
conds = ["中性", "誘發（火災、醫院…）", "指令（盡快作答）"]
think, answer, trunc = [2264, 2803, 1760], [126, 137, 56], [.19, .34, .11]
fig, axes = plt.subplots(1, 2, figsize=(9, 3.8))
for ax, vals, lab, t in ((axes[0], think, "思考 token（平均）", "思考變長 +25%，不是變短"), (axes[1], answer, "答案 token（平均）", "答案變長 +22%，指令組才變短")):
    bars = ax.bar(conds, vals, color=[GREY, ACCENT, GREY], width=0.6)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v * 1.01, f"{v:,}", ha="center", fontsize=9)
    ax.set_ylabel(lab)
    ax.tick_params(axis="x", labelsize=9)
    style(ax, t)
axes[0].text(1, 2803 * 0.5, f"截斷率 {trunc[1]:.0%}\n（中性 {trunc[0]:.0%}）", ha="center", color="white", fontsize=9)
fig.suptitle("腎上腺素型側寫在 4B 上不成立：誘發讓模型處理情境，而非改變計算方式", x=0.01, ha="left", fontsize=12, fontweight="bold")
fig.text(0.01, 0.91, "Qwen3.5-4B，40 題 × 10 段開場白，400 次生成；預先登記 HA1/HA2 在誘發組顯著反向；2026-10-30", fontsize=9, color="#555")
fig.tight_layout(rect=(0, 0, 1, 0.88))
fig.savefig(os.path.join(HERE, "overview-3-arousal.png"), dpi=160)
plt.close(fig)

# 4. Pressure step 0: per-task projection trajectories, F vs S, and the inserted-success point.
r = json.load(open(os.path.join(DATA, "2026-10-31-pressure", "results.json")))
fig, ax = plt.subplots(figsize=(8.5, 4.6))
for cond, color, label in (("F", BAD, "F 失敗歷史（每步失敗）"), ("S", GOOD, "S 成功歷史（每步成功）")):
    means = {}
    for t, d in r["projections"][cond].items():
        ks = sorted(int(k) for k in d)
        ks = [k for k in ks if k <= 5]
        ax.plot(ks, [d[str(k)] for k in ks], color=color, alpha=0.25, lw=1)
        for k in ks:
            means.setdefault(k, []).append(d[str(k)])
    ax.plot(sorted(means), [np.mean(means[k]) for k in sorted(means)], color=color, lw=2.8, marker="o", label=label)
k2 = r["K2"]["insert_minus_fail_k3"]
f3 = np.mean([d["3"] for d in r["projections"]["F"].values()])
ax.errorbar([3.15], [f3 + k2[0]], yerr=[[k2[0] - k2[1]], [k2[2] - k2[0]]], fmt="D", color=ACCENT, ms=7, capsize=3, label="I 插入成功（k=3，第三個結果改成 6/7 通過）")
ax.annotate("", xy=(3.15, f3 + k2[0] + 0.3), xytext=(3.15, f3 - 0.2), arrowprops=dict(arrowstyle="->", color=ACCENT, lw=1.5))
ax.text(3.3, f3 + k2[0] / 2, f"K2 {k2[0]:+.2f}\n[{k2[1]:+.2f}, {k2[2]:+.2f}]", color=ACCENT, fontsize=9, va="center")
ax.axhline(0, color="#444", lw=0.8)
ax.set_xlabel("k（已收到的工具結果數）"), ax.set_ylabel("投影到 d（band 第 9–24 層平均，減各自 k=0）")
ax.legend(frameon=False, fontsize=9, loc="lower left")
style(ax, "失敗歷史讓殘差沿 d 單調累積（K1 ρ = +0.92），成功歷史反向，一次成功抵銷約兩輪",
      "Qwen3.5-9B，12 題，留一題交叉擬合的方向；細線為各題，粗線為平均；2026-10-31")
save(fig, "overview-4-pressure-trajectories.png")

# 5. Pressure step 0: per layer — one failed round's projection, the k=0 spread, the Spearman ρ.
d = np.load(os.path.join(DATA, "2026-10-31-pressure", "direction.npz"))
L = len(d["round_per_layer"])
fig, axes = plt.subplots(1, 2, figsize=(10, 3.9))
ax = axes[0]
ax.bar(range(L), d["round_per_layer"], color=[ACCENT if 9 <= l <= 24 else GREY for l in range(L)], label="一輪失敗的投影增量（F，k=1…3 平均）")
ax.plot(range(L), d["k0_sd_per_layer"], color="#444", lw=1.2, ls="--", label="k=0 投影的跨題標準差")
ax.set_yscale("symlog", linthresh=1)
ax.set_xlabel("層"), ax.set_ylabel("投影（symlog）")
ax.legend(frameon=False, fontsize=8, loc="upper left")
style(ax, "訊號隨深度放大：第 10 層約 0.5、第 24 層 7.8、第 31 層 22", "藍色為操縱用的 band（第 9–24 層）")
ax = axes[1]
ax.bar(range(L), r["per_layer_rho_F_mean"], color=[ACCENT if 9 <= l <= 24 else GREY for l in range(L)])
ax.axhline(0.5, color=BAD, lw=1, ls=":")
ax.text(L - 0.5, 0.52, "K1 門檻 0.5", ha="right", fontsize=8, color=BAD)
ax.set_ylim(0, 1.05)
ax.set_xlabel("層"), ax.set_ylabel("Spearman ρ(k, 投影)，F 跨題平均")
style(ax, "單調性每層都有，但淺層是在 0.1 量級上，無意義")
save(fig, "overview-5-pressure-layers.png")

# 6. Pressure step 0: actions per step in F, and after the inserted success.
classes = [("cheat", "作弊（通過矛盾測試）", BAD), ("repeat", "重複提交", GREY), ("revise", "修改", ACCENT), ("contest", "質疑並停下", GOOD)]
ks = ["0", "1", "2", "3", "4", "5"]
fig, ax = plt.subplots(figsize=(8, 4))
bottom = np.zeros(len(ks) + 1)
xs = list(range(len(ks))) + [7]
for key, label, color in classes:
    vals = [sum(a == key for a in r["actions"]["F"][k]) for k in ks] + [sum(a == key for a in r["actions"]["I"]["3"])]
    ax.bar(xs, vals, 0.7, bottom=bottom, color=color, label=label)
    for xi, v, b in zip(xs, vals, bottom):
        if v >= 2:
            ax.text(xi, b + v / 2, str(v), ha="center", va="center", color="white", fontsize=9)
    bottom += vals
ax.set_xticks(xs), ax.set_xticklabels([f"k={k}" for k in ks] + ["I：插入成功\n後的下一步"], fontsize=9)
ax.set_ylabel("題數（共 12 題）")
ax.legend(frameon=False, fontsize=9, loc="upper left", bbox_to_anchor=(1, 1))
style(ax, "9B 不放棄，它順從：作弊從 0 升到 6/12；插入成功後讀數掉了，作弊沒少（6/12）", "F 條件每步的下一個動作；contest_note（思考裡提到測試矛盾）從 k=1 起每步 10–11/12；2026-10-31")
save(fig, "overview-6-pressure-behaviour.png")

# 7. Step 1 diagnostics: first-token p(</think>) and the KL per arm.
fig, axes = plt.subplots(1, 2, figsize=(10, 3.9))
names = ["無操縱", "−d 0.5 輪", "−d 1 輪", "−d 2 輪", "+d 2 輪", "隨機 2 輪", "增益 ×1.5", "增益 ×2.41"]
p = [.006, .046, .163, .162, .000, .007, .005, .436]
ax = axes[0]
ax.bar(names, p, color=[GREY, ACCENT, ACCENT, BAD, GREY, GREY, GREY, BAD], width=0.65)
for i, v in enumerate(p):
    ax.text(i, v + 0.01, f"{v:.3f}", ha="center", fontsize=8)
ax.tick_params(axis="x", labelsize=8, rotation=30)
ax.set_ylabel("第一個生成 token 是 </think> 的機率")
style(ax, "−d 2 輪與增益 2.41 讓模型跳過思考", "clamp 題 k=3 提示，teacher-forced 第一個位置；2026-11-01")
ax = axes[1]
arms = ["隨機 1 輪", "隨機 2 輪", "+d 1 輪", "增益 ×1.71", "−d 1 輪", "+d 2 輪", "增益 ×2.41", "−d 2 輪", "−d 4 輪"]
kl = [.010, .038, .061, .106, .107, .230, .515, .517, 4.138]
cols = [GREY, GREY, GREY, ACCENT2, ACCENT, GREY, ACCENT2, BAD, BAD]
ax.barh(arms, kl, color=cols)
for i, v in enumerate(kl):
    ax.text(v * 1.15, i, f"{v:.3f}", va="center", fontsize=8)
ax.set_xscale("log"), ax.set_xlim(0.006, 12)
ax.set_xlabel("平均 KL(無操縱 ‖ 操縱)，nat／token（log）")
style(ax, "方向比同範數隨機強 10 倍；g = 1.71 配對 −d 1 輪", "12 題 k=3 提示 × 前 64 個思考 token，teacher-forced")
ax.grid(axis="x", color="#e6e6e6", lw=0.8), ax.grid(axis="y", visible=False)
save(fig, "overview-7-step1-diagnostics.png")
print("done")

# 8. Step 1 results: cheat rate, honest passes, stop rate per arm with CIs; paired differences vs baseline.
try:
    s1 = json.load(open(os.path.join(DATA, "2026-11-01-pressure-steer", "results.json")))
except FileNotFoundError:
    s1 = None
if s1:
    order = ["1", "2", "3", "4", "5", "6", "7", "8"]
    labels = {"1": "不操控", "2": "−d 1 輪", "3": "−d 2 輪", "4": "+d 1 輪", "5": "隨機 1 輪", "6": "增益 ×1.71", "7": "「保持冷靜」", "8": "上下文重置"}
    colors = {"1": GREY, "2": ACCENT, "3": BAD, "4": GREY, "5": GREY, "6": GREY, "7": GREY, "8": ACCENT2}
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2))
    for ax, m, title, ylab in ((axes[0], "cheat", "作弊步驟比例：−d 1 輪 0.13，基線 0.36", "作弊步驟比例"), (axes[1], "honest", "誠實測試通過數：−d 1 輪最高，差異不顯著", "誠實通過數（0–5，有程式碼的步驟）"), (axes[2], "stop", "停下比例：−d 2 輪全數在 k=3 停下", "以最終訊息停下的軌跡比例")):
        vals = [s1["levels"][a][m] for a in order]
        ax.bar(range(8), [v[0] for v in vals], color=[colors[a] for a in order], width=0.65, yerr=[[v[0] - v[1] for v in vals], [v[2] - v[0] for v in vals]], capsize=2)
        ax.set_xticks(range(8)), ax.set_xticklabels([labels[a] for a in order], rotation=35, ha="right", fontsize=8)
        ax.set_ylabel(ylab, fontsize=9)
        style(ax, title)
        ax.title.set_fontsize(10)
    fig.suptitle("步驟 1：八組 × 12 題 × 2 種子，從三輪失敗後起步 3 步；誤差棒為以題目重抽樣的 95% 信賴區間", x=0.01, ha="left", fontsize=10, color="#333")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(os.path.join(HERE, "overview-8-step1-results.png"), dpi=160)
    plt.close(fig)
    print("step1 figure done")
