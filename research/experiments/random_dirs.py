#!/usr/bin/env python3
"""Random-direction controls for the accumulation experiment: N random unit directions per layer, given the same
per-layer statistics the leanings have (neutral mean and spread along them, and a reach set to the median of the
leanings' reach in σ), appended to the model's vector file as dims random1..N.

Steered with the same α, a random direction adds the same number of σ per layer as a leaning. If its projection grows
through the layers the way a leaning's does, the growth is a property of the residual stream (its norm rising with
depth, say), not of the concept; if only the leanings grow, downstream layers are writing more of the feature they
recognise.

usage: random_dirs.py [--model mlx-community/Qwen3.5-4B-MLX-4bit] [--n 3] [--seed 0]
"""
import argparse, logging, os, sys

import numpy as np
from mlx_lm import load

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "services", "model-server"))
from extract import BASE_SYSTEM, PROMPTS, band_of, last_token_states  # noqa: E402
from steer import Steering, Vectors, vectors_path_for  # noqa: E402

log = logging.getLogger("random")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="mlx-community/Qwen3.5-4B-MLX-4bit")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    path = vectors_path_for(a.model)
    vectors = Vectors.load(path)
    if not vectors.targeted:
        raise SystemExit(f"{path} has no per-layer stats; run extract.py first")
    model, tokenizer = load(a.model)
    steering = Steering()
    steering.attach(model)
    n_layers = len(steering.layers)
    band = band_of(n_layers)
    neutral = np.stack([last_token_states(model, tokenizer, steering, BASE_SYSTEM, p) for p in PROMPTS])  # [prompts, layers, hidden]
    hidden = neutral.shape[-1]
    rng = np.random.default_rng(a.seed)
    # The leanings' reach in units of their own spread, per layer and sign; a random direction gets the median.
    leanings = [d for d in vectors.directions if not d.startswith("random")]
    reach_sigma = np.median(np.stack([vectors.reach[d] / np.maximum(vectors.spreads[d], 1e-6) for d in leanings]), axis=0)  # [2, layers]
    for k in range(1, a.n + 1):
        name = f"random{k}"
        direction = rng.standard_normal((n_layers, hidden)).astype(np.float32)
        direction /= np.linalg.norm(direction, axis=1, keepdims=True)
        proj = np.einsum("plh,lh->pl", neutral, direction)
        spread = proj.std(axis=0)
        spread[spread == 0] = 1.0
        vectors.directions[name] = direction
        vectors.means[name] = proj.mean(axis=0).astype(np.float32)
        vectors.spreads[name] = spread.astype(np.float32)
        vectors.reach[name] = (reach_sigma * spread[None, :]).astype(np.float32)
        vectors.scales[name] = float(np.median(spread[band]))
        log.info("%s: scale %.3f, reach in the band +%.1fσ / −%.1fσ", name, vectors.scales[name], float(np.median(reach_sigma[0][band])), float(np.median(reach_sigma[1][band])))
    vectors.save(path)
    log.info("written %s with %s", path, ", ".join(vectors.directions))


if __name__ == "__main__":
    main()
