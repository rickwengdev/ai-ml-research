#!/usr/bin/env python3
"""Does an intervention change what the model would say, before asking what it changes: the KL divergence between
the plain next-token distribution and the intervened one, teacher-forced along a fixed reply, per token.

For each prompt the reply is the model's own unsteered answer (the baseline rows of an experiments/run.py folder),
so every condition is scored on the same tokens. Conditions:
  endocrine   the nameless system (endocrine.py), random receptors: k, layers, receptor scale and seed swept
  physio      a named chemical at ±1 through the structured mapping (steer.py physio_of)
  target      a leaning at ±1, directional (reference)
  random      a random direction at ±1, directional (control)

usage: divergence.py --out docs/research/data/<date>-divergence --from docs/research/data/<date>-e2e3 [--url ...]
"""
import argparse, json, os, statistics, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from steer import LABEL  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))


def post(url, body, timeout=900):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--from", dest="source", required=True, help="a run folder whose baseline seed-0 replies are the forced text")
    ap.add_argument("--url", default="http://127.0.0.1:1299")
    ap.add_argument("--model", default="mlx-community/Qwen3.5-4B-MLX-4bit")
    ap.add_argument("--prompts", type=int, default=20)
    ap.add_argument("--endo-seeds", type=int, default=5)
    ap.add_argument("--system", choices=["constitution", "bare"], default="constitution")
    ap.add_argument("--conditions", default="all", help="all, or key: uniform gains, noradrenaline, the social leanings and random directions only")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    setup = json.load(open(os.path.join(a.source, "setup.json"), encoding="utf-8"))
    if a.system == "bare":
        from extract import BASE_SYSTEM  # noqa: PLC0415

        setup = {**setup, "system": BASE_SYSTEM, "context": ""}
    gens = [json.loads(l) for l in open(os.path.join(a.source, "gens.jsonl"), encoding="utf-8")]
    base = {r["prompt"]: r["text"] for r in gens if r["method"] == "baseline" and r["seed"] == 0 and r["text"].strip()}
    prompts = [p for p in setup["prompts"] if p["prompt"] in base][: a.prompts]

    conditions = []
    for scale in (0.25, 0.5, 1.0):
        for seed in range(a.endo_seeds):
            conditions.append((f"endocrine k2 mid scale{scale} seed{seed}", {"endocrine": {"k": 2, "layers": "mid", "seed": seed, "receptor_scale": scale}}))
    for seed in range(min(3, a.endo_seeds)):
        conditions.append((f"endocrine k4 band scale0.5 seed{seed}", {"endocrine": {"k": 4, "layers": "band", "seed": seed, "receptor_scale": 0.5, "density": 0.02}}))
    # Uniform-gain controls: every band layer's update scaled by the same scalar, nothing else (no social or deep
    # gain, no temperature). Sizes bracket the random receptors' RMS (~0.1 at scale 1) and the physio band gain (~0.36).
    off = {"social": 0.0, "late": 0.0, "explore": 0.0, "precision": 0.0}
    for g in (0.1, 0.36, 0.8):
        for sign in (1.0, -1.0):
            conditions.append((f"uniform band gain {1 + sign * g:.2f}", {"physio": {"NOREPINEPHRINE": sign}, "physio_params": {**off, "band": g / 0.719}, "entropy_loop": False}))
    for chem in ("NOREPINEPHRINE", "OXYTOCIN", "CORTISOL", "DOPAMINE"):
        for v in (1.0, -1.0):
            conditions.append((f"physio {chem} {v:+.0f}", {"physio": {chem: v}, "entropy_loop": False}))
            conditions.append((f"physio+loop {chem} {v:+.0f}", {"physio": {chem: v}, "entropy_loop": True}))
    for dim in ("warmth", "guard", "love", "familiarity", "random1", "random2"):
        for v in (1.0, -1.0):
            conditions.append((f"target {LABEL.get(dim, dim)} {v:+.0f}", {"steering": {dim: v}, "method": "target"}))
    if a.conditions == "key":
        conditions = [c for c in conditions if c[0].startswith(("uniform", "physio NOREPINEPHRINE", "target")) and "loop" not in c[0]]
    path = os.path.join(a.out, "divergence.jsonl")
    done = {(json.loads(l)["condition"], json.loads(l)["prompt"]) for l in open(path, encoding="utf-8")} if os.path.exists(path) else set()
    with open(path, "a", encoding="utf-8") as out:
        for name, extra in conditions:
            for p in prompts:
                if (name, p["prompt"]) in done:
                    continue
                body = {"model": a.model, "messages": [{"role": "system", "content": setup["system"]}, {"role": "user", "content": f"{setup['context']}\n\n{p['prompt']}" if setup["context"] else p["prompt"]}], "reply": base[p["prompt"]], **extra}
                try:
                    r = post(f"{a.url}/divergence", body)
                except Exception as err:  # noqa: BLE001
                    print(f"  {name}: {err}", file=sys.stderr)
                    continue
                out.write(json.dumps({"condition": name, "prompt": p["prompt"], **r}, ensure_ascii=False) + "\n")
                out.flush()
            rows = [json.loads(l) for l in open(path, encoding="utf-8")]
            mine = [r for r in rows if r["condition"] == name]
            res = [r.get("residual") for r in mine if r.get("residual") is not None]
            print(f"{name:40} KL {statistics.fmean(r['kl'] for r in mine):.4f}  residual {statistics.fmean(res) if res else float('nan'):.4f}  T {statistics.fmean(r.get('fitted_temperature', 1) for r in mine):.2f}  entropy {statistics.fmean(r['entropy_plain'] for r in mine):.2f}→{statistics.fmean(r['entropy'] for r in mine):.2f}  ({len(mine)})", file=sys.stderr)


if __name__ == "__main__":
    main()
