#!/usr/bin/env python3
"""The same experiments on several models side by side: does what Qwen3.5-4B showed hold elsewhere?

For each model's data folder (experiments/run.py output) and its vector report (services/model-server/vectors/<slug>.report.md):
  gain        how far the steered leaning's projection travels past what was added: at the band's last layer and at
              the output, per method, divided by the per-layer amount added (α · K · σ for target, α · s for add).
              A gain well above 1 means the model amplifies the shift itself; asymmetry between +1 and −1 is read
              off the two signs.
  entangle    the share of each leaning that lay on the romance, crude and script nuisance axes before removal,
              from the extraction report: whether warmth / familiarity / love carry sexual content in this model too.
  coherence   the automatic signals at ±1 against the baseline.

usage: compare.py --data research/data/<date>-e2e3 research/data/<date>-9b research/data/<date>-gemma4
"""
import argparse, json, os, re, statistics, sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "services", "model-server"))
from steer import DIMS, LABEL, vectors_slug  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))
plt.rcParams["font.family"] = ["Heiti TC", "Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
METHOD_COLORS = {"target": "#c96442", "add": "#2a78d6", "ace": "#1baf7a"}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else float("nan")


def load(folder):
    gens = [json.loads(l) for l in open(os.path.join(folder, "gens.jsonl"), encoding="utf-8")]
    run = json.load(open(os.path.join(folder, "run.json"))) if os.path.exists(os.path.join(folder, "run.json")) else {}
    model = run.get("model") or next((r.get("model") for r in gens if r.get("model")), None) or json.load(open(os.path.join(folder, "setup.json")))["model"]
    return model, gens


def report_shares(model):
    """{leaning: {axis: share}} from the extraction report's table."""
    path = os.path.join(os.path.dirname(HERE), "vectors", f"{vectors_slug(model)}.report.md")
    if not os.path.exists(path):
        return {}, []
    text = open(path, encoding="utf-8").read()
    head = re.search(r"share that was ([\w/]+) \(removed\)", text)
    axes = head.group(1).split("/") if head else []
    out = {}
    for line in text.splitlines():
        m = re.match(r"\| (\w+) [^|]+\| [^|]+\| [^|]+\| [^|]+\| ([^|]+)\|", line)
        if m and m.group(1) in DIMS:
            shares = [float(x.strip().rstrip("% kept").strip().rstrip("%")) / 100 for x in m.group(2).split("/")]
            out[m.group(1)] = dict(zip(axes, shares))
    return out, axes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", nargs="+", required=True)
    ap.add_argument("--out", default=os.path.join(REPO, "research", "figures"))
    a = ap.parse_args()
    runs = [(folder, *load(folder)) for folder in a.data]
    lines = ["# Across models", ""]

    # Gain: projection reached / amount added per layer, at band end and output, ±1 seed 0.
    lines += ["## Gain (projection at band end / per-layer amount added; then at output), ±1, seed 0", "", "| model | leaning | target +1 | target −1 | add +1 | add −1 |", "|---|---|---|---|---|---|"]
    fig, axes = plt.subplots(1, len(runs), figsize=(5 * len(runs), 4.2), sharey=True, squeeze=False)
    for ax, (folder, model, gens) in zip(axes[0], runs):
        band = next((r["band"] for r in gens if r.get("band") and r["method"] == "target"), None)
        for dim in DIMS:
            cells = []
            for method in ("target", "add"):
                for value in (1.0, -1.0):
                    rs = [r for r in gens if r["method"] == method and r["dim"] == dim and r["value"] == value and r["seed"] == 0 and r.get("curve") and r.get("alpha")]
                    if not rs or not band:
                        cells.append("")
                        continue
                    # What one layer adds, in σ: target aims at α·K·σ (K = 1.5), add adds α·s where s is 1σ by construction.
                    per_layer = mean(abs(r["alpha"]) for r in rs) * (1.5 if method == "target" else 1.0)
                    end = mean(abs(r["curve"][band[1]]) for r in rs)
                    out = mean(abs(r["curve"][-1]) for r in rs)
                    cells.append(f"{end / per_layer:.1f} / {out / per_layer:.1f}")
            lines.append(f"| {model.split('/')[-1]} | {LABEL[dim]} | " + " | ".join(cells) + " |")
        # The curves for familiarity and love, the two social leanings, per model.
        for dim, ls in (("familiarity", "-"), ("love", "--")):
            for method in ("target", "add"):
                for value in (1.0, -1.0):
                    curves = [r["curve"] for r in gens if r["method"] == method and r["dim"] == dim and r["value"] == value and r["seed"] == 0 and r.get("curve")]
                    if curves:
                        avg = [mean(c[l] for c in curves) for l in range(len(curves[0]))]
                        ax.plot(range(len(avg)), avg, ls, color=METHOD_COLORS[method], lw=1.4, alpha=0.9 if value > 0 else 0.5, label=f"{method} {LABEL[dim]} {value:+.0f}")
        if band:
            ax.axvspan(band[0], band[1], color="#000", alpha=0.05)
        ax.axhline(0, color="#999", lw=0.6)
        ax.set_title(model.split("/")[-1], fontsize=10)
        ax.set_xlabel("layer")
        ax.legend(fontsize=6, frameon=False, ncol=2)
    axes[0][0].set_ylabel("projection (σ)")
    fig.suptitle("Accumulation of the social leanings across models (mean over prompts, seed 0)", fontsize=11)
    fig.tight_layout()
    os.makedirs(a.out, exist_ok=True)
    fig.savefig(os.path.join(a.out, "cross-model-accumulation.png"), dpi=150)
    plt.close(fig)

    # Entanglement shares from the extraction reports.
    lines += ["", "## Entanglement: share of each leaning on the nuisance axes before removal (extraction report)", ""]
    for folder, model, gens in runs:
        shares, axes_names = report_shares(model)
        if not shares:
            lines.append(f"- {model}: no report")
            continue
        lines += [f"### {model.split('/')[-1]}", "", "| leaning | " + " | ".join(axes_names) + " |", "|---|" + "---|" * len(axes_names)]
        for dim in DIMS:
            if dim in shares:
                lines.append(f"| {LABEL[dim]} | " + " | ".join(f"{shares[dim].get(ax, float('nan')):.0%}" for ax in axes_names) + " |")
        lines.append("")

    # Coherence at ±1 against baseline, per model.
    lines += ["## Coherence at ±1 (target), against the baseline", "", "| model | condition | n | rep | simplified | romance | crude | length |", "|---|---|---|---|---|---|---|---|"]
    for folder, model, gens in runs:
        groups = [("baseline", [r for r in gens if r["method"] == "baseline"])] + [(f"{LABEL[d]} {v:+.0f}", [r for r in gens if r["method"] == "target" and r["dim"] == d and r["value"] == v]) for d in DIMS for v in (1.0, -1.0)]
        for name, rs in groups:
            if rs:
                lines.append(f"| {model.split('/')[-1]} | {name} | {len(rs)} | {mean(r['rep'] for r in rs):.3f} | {mean(r['simp'] > 0 for r in rs):.2f} | {mean(r['romance'] > 0 for r in rs):.2f} | {mean(r['crude'] > 0 for r in rs):.2f} | {mean(r['len'] for r in rs):.0f} |")
    out = os.path.join(REPO, "research", "cross-model.md")
    open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
