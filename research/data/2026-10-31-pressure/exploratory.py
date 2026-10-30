#!/usr/bin/env python3
"""Post hoc, exploratory (not preregistered) checks on the step-0 data: where in depth the signal lives, whether the
projection follows the number of failed rounds or the count of failed test lines, the insert drop by layer, and the
projection at steps where the model cheated. Run from the repository root with steering/.venv/bin/python."""
import json, os, sys

import numpy as np
from scipy.stats import pearsonr

sys.path.insert(0, "steering/experiments"), sys.path.insert(0, "steering")
from pressure import TASKS  # noqa: E402

out = os.path.dirname(os.path.abspath(__file__))
rows = [json.loads(l) for l in open(os.path.join(out, "gens.jsonl"))]
states = {k: v.astype(np.float32) for k, v in np.load(os.path.join(out, "states.npz")).items()}
tasks = [t["fn"] for t in TASKS]
band = slice(9, 25)
norm = lambda d: d / (np.linalg.norm(d, axis=-1, keepdims=True) + 1e-8)
byrow = {(r["cond"], r["task"], r["k"]): r for r in rows}


def traj(c, t):
    ks = sorted(int(k.split("|")[2]) for k in states if k.startswith(f"{c}|{t}|"))
    return {k: states[f"{c}|{t}|{k}"] for k in ks}


F = {t: traj("F", t) for t in tasks}
S = {t: traj("S", t) for t in tasks}


def endpoint(tr):
    return tr[min(5, max(tr))] - tr[0]


def direction(ex):
    return norm(np.mean([endpoint(F[t]) for t in tasks if t != ex], 0) - np.mean([endpoint(S[t]) for t in tasks if t != ex], 0))


def resid(v, k):
    A = np.stack([np.ones_like(k, dtype=float), k], 1)
    return v - A @ np.linalg.lstsq(A, v, rcond=None)[0]


mags = np.mean([((F[t][max(F[t])] - F[t][0]) * direction(t)).sum(-1) for t in tasks], 0)
print("F endpoint projection by layer:", " ".join(f"{l}:{v:+.1f}" for l, v in enumerate(mags)))
print("state norm by layer (F k=0 mean):", " ".join(f"{l}:{v:.0f}" for l, v in enumerate(np.mean([np.linalg.norm(F[t][0], axis=-1) for t in tasks], 0))))

X, Y, K, C = [], [], [], []
for t in tasks:
    u = direction(t)
    cum = 0
    for k in sorted(F[t]):
        proj = ((F[t][k] - F[t][0]) * u).sum(-1)[band].mean()
        if k > 0:
            prev = byrow.get(("F", t, k - 1))
            if prev is not None and prev.get("n_ok") is not None:
                X.append(7 - prev["n_ok"]), K.append(k), Y.append(proj)
                cum += 7 - prev["n_ok"]
            else:
                cum += 2
        C.append((cum, k, proj))
X, Y, K, C = np.array(X), np.array(Y), np.array(K), np.array(C)
print(f"n={len(Y)}; corr(proj, k) {pearsonr(K, Y)[0]:+.2f}; corr(proj, latest #failed) {pearsonr(X, Y)[0]:+.2f}; partial | k {pearsonr(resid(X, K), resid(Y, K))[0]:+.2f}")
print(f"corr(proj, cumulative failed lines) {pearsonr(C[:, 0], C[:, 2])[0]:+.2f}; partial | k {pearsonr(resid(C[:, 0], C[:, 1]), resid(C[:, 2], C[:, 1]))[0]:+.2f}")

drops = np.mean([((states[f"I|{t}|3"] - F[t][3]) * direction(t)).sum(-1) for t in tasks if f"I|{t}|3" in states], 0)
print("I−F drop by layer:", " ".join(f"{l}:{v:+.1f}" for l, v in enumerate(drops)))

P, A = [], []
for t in tasks:
    u = direction(t)
    for k in sorted(F[t]):
        r = byrow.get(("F", t, k))
        if r and k > 0:
            P.append(((F[t][k] - F[t][0]) * u).sum(-1)[band].mean()), A.append(r["action"] == "cheat")
P, A = np.array(P), np.array(A)
print(f"mean proj at cheat steps {P[A].mean():+.2f} (n={A.sum()}) vs non-cheat {P[~A].mean():+.2f} (n={(~A).sum()})")
