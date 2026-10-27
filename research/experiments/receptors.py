#!/usr/bin/env python3
"""Random receptors, turned up: at what strength do nameless hormones with random receptors start to change the
output, and is what they do still coherent? For each setting: the KL along fixed replies (has an effect), and free
generations scored by the automatic coherence signals (is it still speech).

usage: receptors.py --out docs/research/data/<date>-receptors --from docs/research/data/<date>-e2e3 [--url ...]
"""
import argparse, json, os, re, statistics, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from sweep import ROMANCE, SIMPLIFIED, junk_ratio, repeat_ratio, zh_share  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))


def post(url, body, timeout=900):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--from", dest="source", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:1299")
    ap.add_argument("--model", default="mlx-community/Qwen3.5-4B-MLX-4bit")
    ap.add_argument("--prompts", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    setup = json.load(open(os.path.join(a.source, "setup.json"), encoding="utf-8"))
    gens = [json.loads(l) for l in open(os.path.join(a.source, "gens.jsonl"), encoding="utf-8")]
    base = {r["prompt"]: r["text"] for r in gens if r["method"] == "baseline" and r["seed"] == 0 and r["text"].strip()}
    prompts = [p for p in setup["prompts"] if p["prompt"] in base][: a.prompts]
    settings = []
    for layers in ("mid", "band"):
        for density in (0.05, 0.2):
            for scale in (1.0, 2.0, 4.0, 8.0):
                for seed in range(a.seeds):
                    settings.append({"k": 2, "layers": layers, "density": density, "receptor_scale": scale, "seed": seed})
    path = os.path.join(a.out, "receptors.jsonl")
    done = {json.loads(l)["name"] for l in open(path, encoding="utf-8")} if os.path.exists(path) else set()
    with open(path, "a", encoding="utf-8") as out:
        for spec in settings:
            name = f"k{spec['k']} {spec['layers']} d{spec['density']} s{spec['receptor_scale']} seed{spec['seed']}"
            if name in done:
                continue
            kls, texts = [], []
            for p in prompts:
                messages = [{"role": "system", "content": setup["system"]}, {"role": "user", "content": f"{setup['context']}\n\n{p['prompt']}"}]
                try:
                    kls.append(post(f"{a.url}/divergence", {"model": a.model, "messages": messages, "reply": base[p["prompt"]], "endocrine": spec})["kl"])
                    g = post(f"{a.url}/v1/chat/completions", {"model": a.model, "messages": messages, "temperature": 0.7, "seed": 0, "max_tokens": 120, "reasoning_effort": "none", "endocrine": spec})
                    texts.append(g["choices"][0]["message"].get("content") or "")
                except Exception as err:  # noqa: BLE001
                    print(f"  {name}: {err}", file=sys.stderr)
            if not texts:
                continue
            row = {
                "name": name, **spec, "kl": statistics.fmean(kls), "rep": statistics.fmean(repeat_ratio(t) for t in texts), "junk": statistics.fmean(junk_ratio(t) for t in texts),
                "zh": statistics.fmean(zh_share(t) for t in texts), "simp": statistics.fmean(sum(c in SIMPLIFIED for c in t) > 0 for t in texts), "len": statistics.fmean(len(t) for t in texts),
                "empty": statistics.fmean(not t.strip() for t in texts), "samples": [t[:120] for t in texts[:2]],
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            print(f"{name:34} KL {row['kl']:.4f}  rep {row['rep']:.2f} junk {row['junk']:.2f} zh {row['zh']:.2f} len {row['len']:.0f} | {row['samples'][0][:60]!r}", file=sys.stderr)


if __name__ == "__main__":
    main()
