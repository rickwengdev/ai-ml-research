#!/usr/bin/env python3
"""Tables and figures from experiments/run.py (gens.jsonl) and experiments/judge.py (judged.jsonl).

  E1  accumulation: the steered leaning's projection per layer, add vs target vs ace, at ±1 (band mean over prompts)
  E2  controllability: effect at the band's last layer and at the output, per leaning and value, with the automatic
      coherence signals (repetition, simplified characters, length), and the judge's recognition / match / coherence
  E3  methods: effect size against coherence, per method, as a frontier

Writes summary.md and figures/*.png into the data folder, and copies the figures to docs/research/figures/<tag>-*.png.

usage: analyze.py --data docs/research/data/<date>-e2e3
"""
import argparse, collections, json, os, shutil, statistics, sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from steer import DIMS, LABEL  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))
METHOD_NAMES = {"target": "target (ours)", "add": "add (CAA-style)", "ace": "ACE (one layer)"}
COLORS = {"target": "#c96442", "add": "#2a78d6", "ace": "#1baf7a", "baseline": "#777777"}
plt.rcParams["font.family"] = ["Heiti TC", "Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else float("nan")


def sem(xs):
    xs = [x for x in xs if x is not None]
    return statistics.stdev(xs) / len(xs) ** 0.5 if len(xs) > 1 else 0.0


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8")] if os.path.exists(path) else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    gens = load(os.path.join(a.data, "gens.jsonl"))
    judged = {r["key"]: r for r in load(os.path.join(a.data, "judged.jsonl"))}
    figs = os.path.join(a.data, "figures")
    os.makedirs(figs, exist_ok=True)
    tag = os.path.basename(a.data.rstrip("/"))
    setup = json.load(open(os.path.join(a.data, "setup.json"), encoding="utf-8"))
    band = next((r["band"] for r in gens if r.get("band") and r["method"] == "target"), [9, 24])
    lines = [f"# {tag}", "", f"{len(setup['prompts'])} prompts, {len(gens)} generations, {len(judged)} judged. Steered band layers {band[0]}–{band[1]} (target/add); ACE at layer {(band[0] + band[1]) // 2}.", ""]
    for r in gens:
        if r.get("curve"):
            r["band_end"] = r["curve"][band[1]]
            r["output"] = r["curve"][-1]

    # ── E1: accumulation curves ────────────────────────────────────────────
    fig, axes = plt.subplots(3, 3, figsize=(13, 10), sharex=True)
    for ax, dim in zip(axes.flat, DIMS):
        for method in ("add", "target", "ace"):
            for value, style in ((1.0, "-"), (-1.0, "--")):
                curves = [r["curve"] for r in gens if r["method"] == method and r["dim"] == dim and r["value"] == value and r["seed"] == 0 and r.get("curve")]
                if not curves:
                    continue
                avg = [mean(c[l] for c in curves) for l in range(len(curves[0]))]
                ax.plot(range(len(avg)), avg, style, color=COLORS[method], lw=1.6, label=f"{METHOD_NAMES[method]} {value:+.0f}" if dim == DIMS[0] else None)
        base = [r["curve"] for r in gens if r["method"] == "baseline"]
        ax.axvspan(band[0], band[1], color="#000", alpha=0.05)
        ax.axhline(0, color="#999", lw=0.6)
        ax.set_title(f"{LABEL[dim]} {dim}", fontsize=10)
        ax.set_ylabel("projection (σ)", fontsize=8)
    axes[-1, 1].set_xlabel("layer")
    fig.legend(loc="lower center", ncol=3, fontsize=8, frameon=False, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle("E1  How the steered leaning's projection moves through the layers (mean over answer tokens and prompts, seed 0)", fontsize=11)
    fig.tight_layout(rect=(0, 0.04, 1, 0.97))
    fig.savefig(os.path.join(figs, "e1_accumulation.png"), dpi=150)
    plt.close(fig)
    lines += ["## E1 accumulation (projection at the band's last layer / at the output, σ, ±1, seed 0)", "", "| leaning | add +1 | target +1 | ace +1 | add −1 | target −1 | ace −1 |", "|---|---|---|---|---|---|---|"]
    for dim in DIMS:
        cells = []
        for value in (1.0, -1.0):
            for method in ("add", "target", "ace"):
                rs = [r for r in gens if r["method"] == method and r["dim"] == dim and r["value"] == value and r["seed"] == 0 and r.get("curve")]
                cells.append(f"{mean(r['band_end'] for r in rs):+.1f} / {mean(r['output'] for r in rs):+.1f}" if rs else "")
        lines.append(f"| {LABEL[dim]} | " + " | ".join(cells) + " |")

    # ── E2: controllability and coherence under target ─────────────────────
    values = [-1.0, -0.5, 0.5, 1.0]
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.2))
    for dim in DIMS:
        eff = [mean(r["band_end"] for r in gens if r["method"] == "target" and r["dim"] == dim and r["value"] == v and r.get("curve")) for v in values]
        axes[0].plot(values, eff, "o-", lw=1.2, ms=4, label=LABEL[dim])
        rep = [mean(r["rep"] for r in gens if r["method"] == "target" and r["dim"] == dim and r["value"] == v) for v in values]
        axes[1].plot(values, rep, "o-", lw=1.2, ms=4)
        simp = [mean(r["simp"] > 0 for r in gens if r["method"] == "target" and r["dim"] == dim and r["value"] == v) for v in values]
        axes[2].plot(values, simp, "o-", lw=1.2, ms=4)
    base_rep = mean(r["rep"] for r in gens if r["method"] == "baseline")
    base_simp = mean(r["simp"] > 0 for r in gens if r["method"] == "baseline")
    axes[1].axhline(base_rep, color="#777", ls=":", label="baseline")
    axes[2].axhline(base_simp, color="#777", ls=":", label="baseline")
    axes[0].set_title("effect: projection at band end (σ)", fontsize=10)
    axes[1].set_title("repeated 4-grams (share)", fontsize=10)
    axes[2].set_title("replies with simplified characters (share)", fontsize=10)
    for ax in axes:
        ax.set_xlabel("leaning value")
        ax.set_xticks(values)
    axes[0].legend(fontsize=7, ncol=3, frameon=False)
    axes[1].legend(fontsize=7, frameon=False)
    fig.suptitle(f"E2  Each leaning under target steering ({len(setup['prompts'])} prompts × {1 + max(r['seed'] for r in gens)} seeds)", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(figs, "e2_controllability.png"), dpi=150)
    plt.close(fig)
    lines += ["", f"## E2 target steering: automatic signals (mean over {len(setup['prompts'])} prompts × {1 + max(r['seed'] for r in gens)} seeds)", "", "| leaning | value | α | band end σ | output σ | length | rep | simplified | romance | crude |", "|---|---|---|---|---|---|---|---|---|---|"]
    b = [r for r in gens if r["method"] == "baseline"]
    lines.append(f"| baseline | | | | | {mean(r['len'] for r in b):.0f} | {mean(r['rep'] for r in b):.3f} | {mean(r['simp'] > 0 for r in b):.2f} | {mean(r['romance'] > 0 for r in b):.2f} | {mean(r['crude'] > 0 for r in b):.2f} |")
    for dim in DIMS:
        for v in values:
            rs = [r for r in gens if r["method"] == "target" and r["dim"] == dim and r["value"] == v]
            if not rs:
                continue
            lines.append(f"| {LABEL[dim]} | {v:+.1f} | {mean(r['alpha'] for r in rs):+.2f} | {mean(r.get('band_end') for r in rs):+.1f} | {mean(r.get('output') for r in rs):+.1f} | {mean(r['len'] for r in rs):.0f} | {mean(r['rep'] for r in rs):.3f} | {mean(r['simp'] > 0 for r in rs):.2f} | {mean(r['romance'] > 0 for r in rs):.2f} | {mean(r['crude'] > 0 for r in rs):.2f} |")

    # ── judge: recognition, match, coherence, naturalness ──────────────────
    if judged:
        lines += ["", "## Judge (Claude), baseline and ±1 rows of seed 0", "", "| method | n | recognised | same leaning | match | coherence | natural |", "|---|---|---|---|---|---|---|"]
        summary = {}
        for method in ("baseline", "target", "add", "ace"):
            js = [j for j in judged.values() if j["method"] == method]
            if not js:
                continue
            summary[method] = {"n": len(js), "recognised": mean(j["recognised"] for j in js if j["dim"]), "same_dim": mean(j["same_dim"] for j in js if j["dim"]), "match": mean(j["match"] for j in js), "coherence": mean(j["coherence"] for j in js), "natural": mean(j["natural"] for j in js), "coh_sem": sem(j["coherence"] for j in js), "match_sem": sem(j["match"] for j in js)}
            s = summary[method]
            lines.append(f"| {METHOD_NAMES.get(method, method)} | {s['n']} | {s['recognised']:.2f} | {s['same_dim']:.2f} | {s['match']:.2f} | {s['coherence']:.2f} | {s['natural']:.2f} |")
        lines += ["", "### Per leaning (target, ±1)", "", "| leaning | sign | recognised | match | coherence | natural |", "|---|---|---|---|---|---|"]
        for dim in DIMS:
            for sign in (1, -1):
                js = [j for j in judged.values() if j["method"] == "target" and j["dim"] == dim and (j["value"] > 0) == (sign > 0)]
                if js:
                    lines.append(f"| {LABEL[dim]} | {'+' if sign > 0 else '−'} | {mean(j['recognised'] for j in js):.2f} | {mean(j['match'] for j in js):.2f} | {mean(j['coherence'] for j in js):.2f} | {mean(j['natural'] for j in js):.2f} |")
        # E3 frontier: match (effect) vs coherence, per method, one point per leaning×sign, and the method means.
        fig, ax = plt.subplots(figsize=(6.5, 5))
        for method in ("add", "ace", "target"):
            xs, ys = [], []
            for dim in DIMS:
                for sign in (1, -1):
                    js = [j for j in judged.values() if j["method"] == method and j["dim"] == dim and (j["value"] > 0) == (sign > 0)]
                    if js:
                        xs.append(mean(j["coherence"] for j in js))
                        ys.append(mean(j["match"] for j in js))
            ax.scatter(xs, ys, s=22, color=COLORS[method], alpha=0.55)
            if method in summary:
                ax.errorbar(summary[method]["coherence"], summary[method]["match"], xerr=summary[method]["coh_sem"], yerr=summary[method]["match_sem"], fmt="D", ms=9, color=COLORS[method], label=METHOD_NAMES[method], capsize=3)
        if "baseline" in summary:
            ax.axvline(summary["baseline"]["coherence"], color="#777", ls=":", label="baseline coherence")
        ax.set_xlabel("coherence (judge, 1–5)")
        ax.set_ylabel("state match (judge, 1–5)")
        ax.set_title("E3  Effect against coherence, per method (small: each leaning × sign; large: mean ± s.e.)", fontsize=10)
        ax.legend(fontsize=8, frameon=False)
        fig.tight_layout()
        fig.savefig(os.path.join(figs, "e3_methods.png"), dpi=150)
        plt.close(fig)
        # Recognition confusion for target: which leaning the judge saw.
        fig, ax = plt.subplots(figsize=(7.5, 6))
        labels = [f"{d}{s}" for d in DIMS for s in ("+", "-")]
        idx = {l: i for i, l in enumerate(labels + ["none"])}
        grid = [[0] * len(idx) for _ in labels]
        for j in judged.values():
            if j["method"] == "target" and j["want"] in idx:
                grid[idx[j["want"]]][idx.get(j["state"], idx["none"])] += 1
        im = ax.imshow(grid, cmap="Oranges")
        ax.set_xticks(range(len(idx)), list(idx), rotation=90, fontsize=7)
        ax.set_yticks(range(len(labels)), labels, fontsize=7)
        ax.set_xlabel("what the judge saw")
        ax.set_ylabel("what was steered")
        ax.set_title("E2  Recognition under target steering (±1, seed 0)", fontsize=10)
        fig.colorbar(im, ax=ax, shrink=0.7)
        fig.tight_layout()
        fig.savefig(os.path.join(figs, "e2_recognition.png"), dpi=150)
        plt.close(fig)

    open(os.path.join(a.data, "summary.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    out = os.path.join(REPO, "docs", "research", "figures")
    os.makedirs(out, exist_ok=True)
    for name in os.listdir(figs):
        shutil.copy(os.path.join(figs, name), os.path.join(out, f"{tag}-{name}"))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
