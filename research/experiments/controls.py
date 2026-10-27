#!/usr/bin/env python3
"""The accumulation result put to its controls (experiments/run.py --all-curves with random directions):

  units      the steered direction's projection per layer in three units: the trace's σ (the band-median neutral
             spread s_d, the panel's unit), absolute (projection × s_d, the same unit at every layer), and as a
             share of the residual norm at that layer (so a norm that grows with depth cannot pass for amplification);
  gain       projection reached at the band's last layer and at the output over the amount added per layer, in
             absolute units, for leanings and for random directions of the same α;
  default    where the unsteered model already sits along each direction, per layer (the baseline rows), so a sign
             asymmetry can be read against the default rather than against zero.

usage: controls.py --data docs/research/data/<date>-controls [--model ...]
"""
import argparse, json, os, statistics, sys

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from steer import LABEL, Vectors, vectors_path_for  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))
plt.rcParams["font.family"] = ["Heiti TC", "Hiragino Sans", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
K = 1.5


def mean(xs):
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and np.isnan(x))]
    return statistics.fmean(xs) if xs else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    gens = [json.loads(l) for l in open(os.path.join(a.data, "gens.jsonl"), encoding="utf-8")]
    setup = json.load(open(os.path.join(a.data, "setup.json"), encoding="utf-8"))
    model = setup["model"]
    vectors = Vectors.load(vectors_path_for(model))
    band = next(r["band"] for r in gens if r.get("band"))
    dims = sorted({r["dim"] for r in gens if r["dim"]}, key=lambda d: (d.startswith("random"), d))
    layers = len(next(r["norms"] for r in gens if r.get("norms")))
    tag = os.path.basename(a.data.rstrip("/"))
    figs = os.path.join(a.data, "figures")
    os.makedirs(figs, exist_ok=True)

    def curves_of(method, dim, value, unit):
        rows = [r for r in gens if r["method"] == method and r["dim"] == dim and r["value"] == value and r.get("curves")]
        out = []
        for r in rows:
            sig = np.array(r["curves"][dim])
            # The trace's unit is the band-median scale s_d (steer.py watch), the same at every layer.
            absolute = sig * vectors.scales[dim]
            if unit == "sigma":
                out.append(sig)
            elif unit == "abs":
                out.append(absolute)
            else:
                out.append(absolute / np.maximum(np.array(r["norms"]), 1e-6))
        return np.mean(out, axis=0) if out else None

    def default_of(dim, unit):
        rows = [r for r in gens if r["method"] == "baseline" and r.get("curves") and dim in r["curves"]]
        if not rows:
            return None
        sig = np.mean([r["curves"][dim] for r in rows], axis=0)
        if unit == "sigma":
            return sig
        absolute = sig * vectors.scales[dim]
        return absolute if unit == "abs" else absolute / np.maximum(np.mean([r["norms"] for r in rows], axis=0), 1e-6)

    lines = [f"# {tag}: controls", "", f"{model}, {len(setup['prompts'])} prompts, band {band[0]}–{band[1]}.", ""]
    # ── figure: three units, leanings vs random ────────────────────────────
    units = [("sigma", "σ of the layer's neutral spread"), ("abs", "absolute projection"), ("share", "share of residual norm")]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for col, (unit, title) in enumerate(units):
        for row, method in enumerate(("add", "target")):
            ax = axes[row, col]
            for dim in dims:
                color = "#999999" if dim.startswith("random") else None
                for value, ls in ((1.0, "-"), (-1.0, "--")):
                    c = curves_of(method, dim, value, unit)
                    if c is None:
                        continue
                    line, = ax.plot(range(layers), c, ls, lw=1.1 if color else 1.5, color=color, alpha=0.8, label=f"{LABEL.get(dim, dim)} {value:+.0f}" if (row == 0 and col == 0) else None)
            ax.axvspan(band[0], band[1], color="#000", alpha=0.05)
            ax.axhline(0, color="#999", lw=0.6)
            ax.set_title(f"{method}: {title}", fontsize=9)
            ax.set_xlabel("layer")
    axes[0, 0].legend(fontsize=6, ncol=2, frameon=False)
    fig.suptitle("Steered projection per layer in three units; grey = random directions of the same α", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(figs, "controls_units.png"), dpi=150)
    plt.close(fig)

    # ── table: gain in absolute units ──────────────────────────────────────
    lines += ["## Gain: projection reached (absolute) over the amount one layer adds (absolute), at band end / at output", "", "| direction | method | +1 added/layer | +1 gain band / out | −1 added/layer | −1 gain band / out |", "|---|---|---|---|---|---|"]
    gains = {}
    for dim in dims:
        for method in ("add", "target"):
            cells = []
            for value in (1.0, -1.0):
                rows = [r for r in gens if r["method"] == method and r["dim"] == dim and r["value"] == value and r.get("curves")]
                if not rows:
                    cells += ["", ""]
                    continue
                alpha = mean(abs(r["alpha"]) for r in rows)
                spread_band = float(np.median(vectors.spreads[dim][band[0]:band[1]]))
                # What one layer adds, absolute: add puts α·s·v (s = the band median spread); target aims at α·K·σ_l.
                added = alpha * (vectors.scales[dim] if method == "add" else K * spread_band)
                c = curves_of(method, dim, value, "abs")
                d = default_of(dim, "abs")
                end = abs(c[band[1]] - (d[band[1]] if d is not None else 0))
                out = abs(c[-1] - (d[-1] if d is not None else 0))
                gains[(dim, method, value)] = (end / added, out / added)
                cells += [f"{added:.3f}", f"{end / added:.1f} / {out / added:.1f}"]
            lines.append(f"| {LABEL.get(dim, dim)} | {method} | " + " | ".join(cells) + " |")
    rand = [g for (d, m, v), g in gains.items() if d.startswith("random")]
    lean = [g for (d, m, v), g in gains.items() if not d.startswith("random")]
    lines += ["", f"Mean gain at the output: leanings {mean(g[1] for g in lean):.1f}, random {mean(g[1] for g in rand):.1f}."]

    # ── default projections ────────────────────────────────────────────────
    lines += ["", "## Where the unsteered model sits (σ), per direction: at the band start, band end and output", "", "| direction | band start | band end | output |", "|---|---|---|---|"]
    for dim in dims:
        d = default_of(dim, "sigma")
        if d is not None:
            lines.append(f"| {LABEL.get(dim, dim)} | {d[band[0]]:+.1f} | {d[band[1]]:+.1f} | {d[-1]:+.1f} |")
    lines += ["", "## Residual norm per layer (baseline mean)", "", "layers 0, 8, 16, 24, 31: " + ", ".join(f"{v:.1f}" for v in np.array(np.mean([r["norms"] for r in gens if r["method"] == "baseline" and r.get("norms")], axis=0))[[0, 8, 16, 24, layers - 1]])]
    open(os.path.join(a.data, "controls.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    out = os.path.join(REPO, "docs", "research", "figures")
    os.makedirs(out, exist_ok=True)
    import shutil

    shutil.copy(os.path.join(figs, "controls_units.png"), os.path.join(out, f"{tag}-units.png"))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
