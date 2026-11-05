#!/usr/bin/env python3
"""English figures for the submission, drawn from research/data (read only).
Run with any Python that has numpy and matplotlib: python make_figures.py"""
import json, sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "checks"))
from load import R, KL, REP, CTL, STP1, S2rows, DS, cheat

INK, MUTED, GRID = "#1f1e1c", "#6b6860", "#e6e3dc"
C_F, C_S, C_I = "#b4532a", "#2f6f9f", "#1f1e1c"
plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": MUTED,
                     "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": INK, "pdf.fonttype": 42, "font.family": "DejaVu Sans"})

def save(fig, name):
    fig.savefig(HERE / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(HERE / f"{name}.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

# Figure 1: projection on d by k
res = json.load(open(Path(R) / "2026-10-31-pressure" / "results.json"))
P = res["projections"]
fig, ax = plt.subplots(figsize=(4.6, 2.7))
for cond, col in (("F", C_F), ("S", C_S)):
    per = P[cond]
    for t, v in per.items():
        ks = sorted(int(k) for k in v if int(k) <= 5)
        ax.plot(ks, [v[str(k)] for k in ks], color=col, lw=0.5, alpha=0.3)
    means = [np.mean([v[str(k)] for v in per.values() if str(k) in v]) for k in range(6)]
    ax.plot(range(6), means, color=col, lw=2, marker="o" if cond == "F" else "s", ms=4)
    ax.text(5.08, means[-1], {"F": "F: every step fails", "S": "S: every stage passes"}[cond], color=INK, va="center", fontsize=7.5)
f3 = np.mean([v["3"] for v in P["F"].values()])
k2 = res["K2"]["insert_minus_fail_k3"]
ax.errorbar([3.12], [f3 + k2[0]], yerr=[[k2[0] - k2[1]], [k2[2] - k2[0]]], fmt="D", color=C_I, ms=4, capsize=2, lw=1)
ax.text(3.22, f3 + k2[0] - 1.0, f"I: last result replaced\nby a 6/7 pass ({k2[0]:+.2f})", fontsize=7, color=INK, va="top")
ax.annotate("prompt after all five\nstages have passed", xy=(5, -11), xytext=(2.5, -14.8), fontsize=7, color=INK,
            arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6), va="center")
ax.axhline(0, color=MUTED, lw=0.6); ax.grid(axis="y", color=GRID, lw=0.5); ax.set_axisbelow(True)
ax.set_xlim(-0.1, 6.9); ax.set_xticks(range(6)); ax.set_xlabel("k (tool results seen)")
ax.set_ylabel("projection on d, layers 9–24,\nrelative to k = 0 (raw units)")
save(fig, "fig_trajectories")

# Figure 2: effect on the cheating rate
merged = DS([r for v in REP.t.values() for r in v] + [r for v in CTL.t.values() for r in v])
s2 = {}
for r in S2rows:
    if r.get("mode") == "contra" and r.get("start") == 3 and r.get("variant") == "base":
        s2.setdefault(r["arm"], []).append(r)
E_ = DS([r for v in s2.values() for r in v], repkey="seed")
stE = E_.starts([1, 2, 5, 11, 12, 13, 14, 15]); stS = STP1.starts([1, 2, 4, 5, 6, 7, 8]); stR = merged.starts([1, 2, 5, 6]); stK = KL.starts([1, 2, 6, 21, 22, 23])
RND5, RND3 = [5, 11, 12, 13, 14], [21, 22, 23]
rows_ = [("Step 1 and E: 12 tasks × 2 seeds", None, None, None),
         ("−d, 1 round", E_.diff(2, 1, cheat, stE), "d", "KL 0.107"),
         ("uniform gain", STP1.diff(6, 1, cheat, stS), "g", "KL 0.106"),
         ("+d, 1 round", STP1.diff(4, 1, cheat, stS), "n", "KL 0.061"),
         ("capping", E_.diff(15, 1, cheat, stE), "n", "KL not measured"),
         ("same-norm random, mean of 5", E_.diff(RND5, 1, cheat, stE), "r", "KL ≈ 0.01"),
         ("Replication and E′: 24 tasks × 3 seeds", None, None, None),
         ("−d, 1 round", merged.diff(2, 1, cheat, stR), "d", "KL 0.107"),
         ("uniform gain", merged.diff(6, 1, cheat, stR), "g", "KL 0.106"),
         ("same-norm random, one direction", merged.diff(5, 1, cheat, stR), "r", "KL ≈ 0.01"),
         ("KL run: 24 tasks × 3 new seeds", None, None, None),
         ("−d, 1 round", KL.diff(2, 1, cheat, stK), "d", "KL 0.107"),
         ("uniform gain", KL.diff(6, 1, cheat, stK), "g", "KL 0.106"),
         ("KL-matched random, mean of 3 (Q1)", KL.diff(RND3, 1, cheat, stK), "m", "KL 0.107"),
         ("   random6", KL.diff(21, 1, cheat, stK), "m2", ""), ("   random7", KL.diff(22, 1, cheat, stK), "m2", ""), ("   random8", KL.diff(23, 1, cheat, stK), "m2", "")]
style = {"d": (C_F, "o", 4.5), "g": (C_S, "s", 4), "n": (MUTED, "^", 4), "r": (MUTED, "v", 4), "m": (INK, "D", 4), "m2": (MUTED, "D", 2.5)}
fig, ax = plt.subplots(figsize=(5.4, 3.7))
y = len(rows_)
yt, yl = [], []
for lab, c, kind, note in rows_:
    y -= 1
    if c is None:
        ax.text(-0.625, y, lab, fontsize=7.5, fontweight="bold", color=INK, va="center", ha="left"); continue
    col, m, ms = style[kind]
    ax.errorbar([c[0]], [y], xerr=[[c[0] - c[1]], [c[2] - c[0]]], fmt=m, color=col, ms=ms, lw=1, capsize=1.5)
    yt.append(y); yl.append(lab)
    ax.text(0.2, y, f"{c[0]:+.2f} [{c[1]:+.2f}, {c[2]:+.2f}]" + (f"   {note}" if note else ""), fontsize=6.5, color=INK, va="center")
ax.axvline(0, color=MUTED, lw=0.7); ax.set_yticks(yt); ax.set_yticklabels(yl, fontsize=7); ax.set_ylim(-0.7, len(rows_) - 0.3)
ax.set_xlim(-0.42, 0.72); ax.set_xticks([-0.4, -0.3, -0.2, -0.1, 0, 0.1]); ax.grid(axis="x", color=GRID, lw=0.5); ax.set_axisbelow(True)
ax.set_xlabel("change in cheating-step share against no steering (paired, 95% CI over tasks)", loc="left")
# group headers sit left of the axis label column
for t in ax.texts:
    if t.get_fontweight() == "bold":
        t.set_transform(ax.get_yaxis_transform()); t.set_x(-0.72)
save(fig, "fig_effects")

# Figure 3: audited endings in the KL run
A = Path(R) / "2026-11-04-pressure-4bit-kl" / "audit"
fin, key = json.load(open(A / "final.json")), json.load(open(A / "key.json"))
cats = [("false_claim", "false claim", C_F), ("contest", "contest", C_S), ("give_up", "give up", "#a67c00"), ("incoherent", "incoherent", "#7a4f8a"), ("cheat_done", "done after cheat", "#178f68")]
arms = [("none", "no steering"), ("minus1", "−d, 1 round"), ("gain", "gain"), ("random6", "random6"), ("random7", "random7"), ("random8", "random8")]
cnt = {a: {c: 0 for c, _, _ in cats} for a, _ in arms}
for i in key["items"]:
    cnt[i["arm_name"]][fin["category"][str(i["item"])]] += 1
fig, ax = plt.subplots(figsize=(4.8, 2.1))
for j, (a, lab) in enumerate(arms):
    left = 0
    for c, _, col in cats:
        n = cnt[a][c]
        if n:
            ax.barh(j, n, left=left, color=col, height=0.62, edgecolor="white", lw=1)
            ax.text(left + n / 2, j, str(n), ha="center", va="center", fontsize=6.5, color="white")
        left += n
ax.set_yticks(range(len(arms))); ax.set_yticklabels([l for _, l in arms]); ax.invert_yaxis()
ax.set_xlabel("trajectories ending without a tool call (of 69 starts)"); ax.spines["left"].set_visible(False); ax.tick_params(axis="y", length=0)
hs = [plt.Rectangle((0, 0), 1, 1, color=col) for _, _, col in cats]
ax.legend(hs, [l for _, l, _ in cats], frameon=False, fontsize=6.5, ncol=5, loc="upper center", bbox_to_anchor=(0.45, 1.2), handlelength=1, columnspacing=0.9)
save(fig, "fig_endings")
print(cnt)
