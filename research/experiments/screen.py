#!/usr/bin/env python3
"""Screening random receptors: among many random draws, are there any whose effect is a recognisable state, and does
that hold on prompts the screen never saw?

Each draw is one nameless hormone (k=1) with sparse random receptors on the middle layers, its activity clamped at +1
or −1 (endocrine.py "clamp"), so the draw is one fixed gain pattern and its opposite.

  screen     per draw, on the screen prompts: her replies at clamp +1 and −1, and the shift of the replies'
             projections at the output along the nine leanings (units s_d, see steer.py). The shift is half the
             difference (+1 − −1) per prompt; the unsteered reply (same seed) is generated but only used to skip
             prompts whose trace is missing, not subtracted. Its mean over prompts and that mean's z. A draw
             "points at" the leaning with the largest |z|.
  validate   the top draws by |z| and as many other draws picked at random from the rest (the control for selection),
             on held-out prompts: replies at ±1 and unsteered, written as gens.jsonl in run.py's shape, so judge.py
             (with --baseline-match) asks whether the reply shows the state the screen said the draw points at.
             If selected draws beat the controls on held-out prompts, the screen found structure; if not, it found
             noise.

usage: screen.py --out docs/research/data/<date>-screen [--draws 48] [--scale 4] [--validate --top 6]
"""
import argparse, json, os, random, statistics, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from client import get, post  # noqa: E402
from steer import DIMS, LABEL  # noqa: E402
from extract import BASE_SYSTEM  # noqa: E402
from sweep import junk_ratio, repeat_ratio, zh_share  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))


class Client:
    def __init__(self, url, model, max_tokens):
        self.url, self.model, self.max_tokens = url, model, max_tokens
        self.seq = get(f"{url}/trace?after=0")["seq"]

    def reply(self, prompt, endocrine=None):
        """Her reply and the mean projection of its tokens at the output layer, per leaning (in s_d)."""
        body = {"model": self.model, "messages": [{"role": "system", "content": BASE_SYSTEM}, {"role": "user", "content": prompt}], "temperature": 0.7, "seed": 0, "max_tokens": self.max_tokens, "reasoning_effort": "none"}
        if endocrine is not None:
            body["endocrine"] = endocrine
        text = post(f"{self.url}/v1/chat/completions", body)["choices"][0]["message"].get("content") or ""
        trace = get(f"{self.url}/trace?after={self.seq}")
        self.seq = trace["seq"]
        begin = next((e for e in trace["events"] if e["type"] == "begin"), None)
        rows = [e["rows"] for e in trace["events"] if begin and e["type"] == "token" and e.get("request") == begin["request"] and not e.get("thinking")]
        proj = {d: sum(r[-1][k + 1] for r in rows) / len(rows) for k, d in enumerate(begin["dims"])} if rows else None
        return text, proj


def spec_of(seed, sign, a):
    return {"k": 1, "layers": "mid", "density": a.density, "receptor_scale": a.scale, "seed": seed, "clamp": [sign]}


def zscore(xs):
    if len(xs) < 3:
        return 0.0
    sd = statistics.stdev(xs)
    return statistics.fmean(xs) / (sd / len(xs) ** 0.5) if sd > 0 else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:1299")
    ap.add_argument("--model", default="mlx-community/Qwen3.5-4B-MLX-4bit")
    ap.add_argument("--draws", type=int, default=48)
    ap.add_argument("--scale", type=float, default=4.0)
    ap.add_argument("--density", type=float, default=0.05)
    ap.add_argument("--screen-prompts", type=int, default=16)
    ap.add_argument("--held-out", type=int, default=20)
    ap.add_argument("--max-tokens", type=int, default=100)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--top", type=int, default=6)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    pool = [json.loads(l)["prompt"] for l in open(os.path.join(REPO, "training", "data", "generated", "prompts.jsonl"), encoding="utf-8")]
    pool = list(dict.fromkeys(pool))
    random.Random(23).shuffle(pool)
    screen_prompts, held_out = pool[: a.screen_prompts], pool[a.screen_prompts : a.screen_prompts + a.held_out]
    client = Client(a.url, a.model, a.max_tokens)
    json.dump({"model": a.model, "scale": a.scale, "density": a.density, "draws": a.draws, "screen_prompts": screen_prompts, "held_out": held_out}, open(os.path.join(a.out, "setup.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    path = os.path.join(a.out, "screen.jsonl")
    if not a.validate:
        base = {p: client.reply(p)[1] for p in screen_prompts}
        done = {json.loads(l)["seed"] for l in open(path, encoding="utf-8")} if os.path.exists(path) else set()
        with open(path, "a", encoding="utf-8") as out:
            for seed in range(a.draws):
                if seed in done:
                    continue
                shifts, texts = {d: [] for d in DIMS}, []
                for p in screen_prompts:
                    (tp, pp), (tm, pm) = client.reply(p, spec_of(seed, 1, a)), client.reply(p, spec_of(seed, -1, a))
                    texts += [tp, tm]
                    if pp and pm and base[p]:
                        for d in DIMS:
                            shifts[d].append((pp[d] - pm[d]) / 2)
                z = {d: round(zscore(v), 2) for d, v in shifts.items()}
                best = max(z, key=lambda d: abs(z[d]))
                row = {"seed": seed, "z": z, "shift": {d: round(statistics.fmean(v), 2) for d, v in shifts.items() if v}, "best": best, "best_z": z[best],
                       "zh": statistics.fmean(zh_share(t) for t in texts), "rep": statistics.fmean(repeat_ratio(t) for t in texts), "junk": statistics.fmean(junk_ratio(t) for t in texts), "len": statistics.fmean(len(t) for t in texts), "samples": [t[:80] for t in texts[:2]]}
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                print(f"draw {seed:2}: {LABEL[best]} z {z[best]:+.1f}  zh {row['zh']:.2f} rep {row['rep']:.2f}  | {texts[0][:50]!r}", file=sys.stderr)
        return

    # ── validate: top draws by |z| against random other draws, on held-out prompts ──
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    ranked = sorted(rows, key=lambda r: -abs(r["best_z"]))
    selected = ranked[: a.top]
    control = random.Random(7).sample(ranked[a.top :], a.top)
    gpath = os.path.join(a.out, "gens.jsonl")
    done = {json.loads(l)["key"] for l in open(gpath, encoding="utf-8")} if os.path.exists(gpath) else set()
    json.dump({"model": a.model, "system_kind": "bare", "system": BASE_SYSTEM, "context": "", "prompts": [{"prompt": p} for p in held_out], "selected": [r["seed"] for r in selected], "control": [r["seed"] for r in control]}, open(os.path.join(a.out, "setup.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(gpath, "a", encoding="utf-8") as out:
        def write(key, method, dim, value, prompt, text, proj, seed=None):
            out.write(json.dumps({"key": key, "method": method, "dim": dim, "label": LABEL.get(dim) if dim else None, "value": value, "seed": 0, "draw": seed, "prompt": prompt, "text": text, "proj": proj,
                                  "len": len(text), "junk": junk_ratio(text), "rep": repeat_ratio(text), "zh": zh_share(text), "simp": 0, "romance": 0, "crude": 0, "tokens": None, "alpha": None, "curve": None, "band": None, "physio": None}, ensure_ascii=False) + "\n")
            out.flush()

        for p in held_out:
            key = f"baseline|{p}"
            if key not in done:
                text, proj = client.reply(p)
                write(key, "baseline", None, None, p, text, proj)
        for group, draws in (("selected", selected), ("control", control)):
            for r in draws:
                # Clamp +1 should show the pointed-at leaning with the sign of the screen's shift; −1 the opposite.
                sign = 1 if r["best_z"] > 0 else -1
                for clamp in (1, -1):
                    for p in held_out:
                        key = f"receptor:{group}|{r['seed']}|{clamp}|{p}"
                        if key in done:
                            continue
                        text, proj = client.reply(p, spec_of(r["seed"], clamp, a))
                        write(key, f"receptor:{group}", r["best"], float(sign * clamp), p, text, proj, r["seed"])
                print(f"{group} draw {r['seed']}: {LABEL[r['best']]} (screen z {r['best_z']:+.1f}) done", file=sys.stderr)


if __name__ == "__main__":
    main()
