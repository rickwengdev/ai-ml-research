"""A nameless endocrine system inside the forward pass: k hormones that are only numbers, secreted by the model's own
signals, decaying at their own rates, interacting, and read by receptors on each layer's hidden units.

    h_{t+1} = D · h_t + W · s_t + C · σ(h_t)           secretion, decay, interaction (once per generated token)
    gain_l  = 1 + R_l · σ(h)                            receptors: a per-unit gain at layer l   (R_l is d × k)
    update  = update ⊙ gain_l                           the layer's own update (after its norms), element-wise

A hormone means nothing in itself. What it does is fixed by three things, as in a body: what secretes it (W), where
its receptors are (R), and how fast it clears (D). Behaviour is whatever that produces. Nothing here names a trait.

Signals s_t, all from the pass itself: the output entropy (nats), the surprise of the token sampled (−log p),
the residual norm at the band's first layer (relative to its running mean), and the entropy's change from the
previous token. σ is tanh, so a hormone saturates at ±1 on its receptors.

How W, R, C are set is the experiment's question. Here they are drawn: sparse, random, from a seed (the most
"untranslated" option), or structured (receptors laid on known directions, the physio_of mapping in steer.py).
"""
from __future__ import annotations

import json
import math

import mlx.core as mx
import numpy as np

SIGNALS = ("entropy", "surprise", "norm", "d_entropy")


class Endocrine:
    def __init__(self, k=2, hidden=2560, layers=(), seed=0, receptor_density=0.05, receptor_scale=0.5, secretion_scale=0.3, decay=None, interaction_scale=0.0, baseline=None, clamp=None):
        self.k = k
        # Clamped: the hormones' activity held at fixed values (−1..1), no secretion or decay, so a draw of receptors is
        # one fixed gain pattern (for screening which draws do something recognisable).
        self.clamp = None if clamp is None else np.clip(np.array(clamp, dtype=np.float32), -1, 1)
        self.layers = list(layers)
        rng = np.random.default_rng(seed)
        self.W = (rng.standard_normal((k, len(SIGNALS))) * secretion_scale).astype(np.float32)
        self.D = np.array(decay if decay is not None else np.linspace(0.6, 0.95, k), dtype=np.float32)
        self.C = (rng.standard_normal((k, k)) * interaction_scale).astype(np.float32)
        np.fill_diagonal(self.C, 0.0)
        # Receptors: a sparse matrix per layer, most units untouched, a few with a sign and a size. Nothing bounds the
        # gain 1 + R·tanh(h) below: with receptor_scale much past 1 (screen.py uses 4, sweeps went to 8) some units
        # get a negative gain, i.e. their update is flipped, not just turned down.
        self.R = {}
        for l in self.layers:
            mask = rng.random((hidden, k)) < receptor_density
            self.R[l] = (rng.standard_normal((hidden, k)) * receptor_scale * mask).astype(np.float32)
        # The signals' typical values, so secretion reads deviations. The norm is relative to its running mean
        # (norm_mean, filled on the fly); entropy and surprise are against these fixed numbers, not adapted, and
        # entropy's 1.5 is not the entropy loop's baseline (engine.py Config.entropy_baseline, 2.6, adaptive).
        self.baseline = dict(baseline or {"entropy": 1.5, "surprise": 1.5, "norm": 1.0, "d_entropy": 0.0})
        self.norm_mean = None
        self.reset()

    def reset(self):
        self.h = np.zeros(self.k, dtype=np.float32)
        self.last_entropy = None
        self.trace = []
        self.sizes = []
        self.size = None

    def step(self, entropy, surprise, norm):
        """One generated token: secrete from the signals, decay, interact; then the receptors' gains."""
        if self.clamp is not None:
            self.trace.append([round(float(v), 3) for v in self.clamp])
            return self.gains()
        self.norm_mean = norm if self.norm_mean is None else 0.95 * self.norm_mean + 0.05 * norm
        d_entropy = 0.0 if self.last_entropy is None else entropy - self.last_entropy
        self.last_entropy = entropy
        s = np.array([entropy - self.baseline["entropy"], surprise - self.baseline["surprise"], norm / max(self.norm_mean, 1e-6) - 1.0, d_entropy], dtype=np.float32)
        act = np.tanh(self.h)
        self.h = self.D * self.h + self.W @ s + self.C @ act
        self.trace.append([round(float(v), 3) for v in self.h])
        return self.gains()

    def gains(self):
        act = self.clamp if self.clamp is not None else np.tanh(self.h)
        gains = {l: 1.0 + R @ act for l, R in self.R.items()}
        # The size of the modulation, for comparing against a uniform gain: RMS of (gain − 1) over all units of the
        # modulated layers, and over the receptor-bearing units only.
        allu = np.concatenate([g - 1.0 for g in gains.values()])
        hit = np.concatenate([(g - 1.0)[(R != 0).any(axis=1)] for g, R in zip(gains.values(), self.R.values())])
        self.size = {"rms_all": float(np.sqrt(np.mean(allu**2))), "rms_receptors": float(np.sqrt(np.mean(hit**2))) if hit.size else 0.0, "max": float(np.abs(allu).max())}
        self.sizes.append(self.size)
        return {l: mx.array(g) for l, g in gains.items()}

    def describe(self):
        mean_size = {k: round(sum(sz[k] for sz in self.sizes) / len(self.sizes), 4) for k in self.sizes[0]} if self.sizes else None
        return {"k": self.k, "layers": self.layers, "D": [round(float(v), 3) for v in self.D], "signals": list(SIGNALS), "receptors_per_layer": {l: int((R != 0).any(axis=1).sum()) for l, R in self.R.items()}, "gain_size": mean_size}


def endocrine_of(spec, hidden, n_layers):
    """An Endocrine from a request's "endocrine" field: {"k", "seed", "layers": [..] | "band" | "mid", "density",
    "receptor_scale", "secretion_scale", "interaction_scale", "decay": [..], "clamp": [..]}."""
    spec = dict(spec or {})
    layers = spec.get("layers", "mid")
    if layers == "mid":
        layers = [int(n_layers * 0.5), int(n_layers * 0.5) + 1]
    elif layers == "band":
        layers = list(range(int(n_layers * 0.3), int(n_layers * 0.8)))
    return Endocrine(
        k=int(spec.get("k", 2)), hidden=hidden, layers=layers, seed=int(spec.get("seed", 0)),
        receptor_density=float(spec.get("density", 0.05)), receptor_scale=float(spec.get("receptor_scale", 0.5)),
        secretion_scale=float(spec.get("secretion_scale", 0.3)), interaction_scale=float(spec.get("interaction_scale", 0.0)),
        decay=spec.get("decay"), baseline=spec.get("baseline"), clamp=spec.get("clamp"),
    )
