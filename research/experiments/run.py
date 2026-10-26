#!/usr/bin/env python3
"""E1–E3 of docs/research/paper-outline.md, on her own model server (a port apart from the live one).

Conditions, on the same prompts with the same seeds:
  baseline        no steering
  E2  target      each leaning at −1, −0.5, +0.5, +1 (love is 0..1 in her body; the negative side is run for symmetry)
  E3  add, ace    the same grid under activation addition (α·s·v at every band layer) and affine editing (one layer)
E1 comes free: every generation's forward-pass trace gives the steered leaning's projection at each layer, averaged
over the answer tokens, so the accumulation curves are the same rows read per layer.

Prompts: a sample of the constitution test prompts (training/data/generated/prompts.jsonl), under the runtime's
real system prompt and a state-free <此刻> block (training/data/generated/turns.json), as a real turn sends her.

usage: run.py --out docs/research/data/<date>-e2e3 [--url http://127.0.0.1:1299] [--prompts 30] [--seeds 2]
Resumes: rows already in gens.jsonl are skipped.
"""
import argparse, json, os, random, re, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from steer import DIMS, LABEL  # noqa: E402
from sweep import ROMANCE, SIMPLIFIED, junk_ratio, repeat_ratio, zh_share  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))
CRUDE = re.compile(r"死|屁|靠|幹|爛|鬼|撸|操|媽的|蠢|廢物|欠揍")
VALUES = [-1.0, -0.5, 0.5, 1.0]


def post(url, body, timeout=600):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


def get(url):
    with urllib.request.urlopen(url, timeout=30) as res:
        return json.load(res)


def metrics(text):
    return {
        "len": len(text), "junk": round(junk_ratio(text), 3), "rep": round(repeat_ratio(text), 3), "zh": round(zh_share(text), 3),
        "simp": sum(1 for c in text if c in SIMPLIFIED), "romance": len(set(ROMANCE.findall(text))), "crude": len(set(CRUDE.findall(text))),
    }


def projections(trace_events, dim):
    """The steered leaning's mean projection over the answer tokens at every layer, from the trace since `after`."""
    begin = next((e for e in trace_events if e["type"] == "begin"), None)
    if not begin or dim not in (begin.get("dims") or []):
        return None
    k = begin["dims"].index(dim) + 1
    rows = [e["rows"] for e in trace_events if e["type"] == "token" and e.get("request") == begin["request"] and not e.get("thinking") and not e.get("muted")]
    if not rows:
        return None
    return [round(sum(r[l][k] for r in rows) / len(rows), 3) for l in range(len(rows[0]))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:1299")
    ap.add_argument("--model", default="mlx-community/Qwen3.5-4B-MLX-4bit")
    ap.add_argument("--prompts", type=int, default=30)
    ap.add_argument("--seeds", type=int, default=2, help="seeds for baseline and E2; E3 runs seed 0 only")
    ap.add_argument("--max-tokens", type=int, default=200)
    ap.add_argument("--seed", type=int, default=11, help="for sampling the prompts")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    turns = json.load(open(os.path.join(REPO, "training", "data", "generated", "turns.json"), encoding="utf-8"))
    system = turns["system"]
    context = next(t["context"] for t in turns["turns"] if "上一次說話" in t["context"])
    pool = [json.loads(l) for l in open(os.path.join(REPO, "training", "data", "generated", "prompts.jsonl"), encoding="utf-8")]
    rng = random.Random(a.seed)
    rng.shuffle(pool)
    # One per subsection first, so the sample spans the constitution, then the rest at random.
    seen, prompts = set(), []
    for p in pool:
        if p["subsection"] not in seen:
            seen.add(p["subsection"])
            prompts.append(p)
    for p in pool:
        if len(prompts) >= a.prompts:
            break
        if p not in prompts:
            prompts.append(p)
    prompts = prompts[: a.prompts]
    json.dump({"system": system, "context": context, "prompts": prompts}, open(os.path.join(a.out, "setup.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    jobs = []
    for seed in range(a.seeds):
        for p in prompts:
            jobs.append(("baseline", None, None, seed, p))
    for method, seeds in (("target", range(a.seeds)), ("add", range(1)), ("ace", range(1))):
        for dim in DIMS:
            for value in VALUES:
                for seed in seeds:
                    for p in prompts:
                        jobs.append((method, dim, value, seed, p))
    key_of = lambda j: f"{j[0]}|{j[1]}|{j[2]}|{j[3]}|{j[4]['prompt']}"
    path = os.path.join(a.out, "gens.jsonl")
    done = {json.loads(l)["key"] for l in open(path, encoding="utf-8")} if os.path.exists(path) else set()
    print(f"{len(jobs)} generations, {len(done)} done", file=sys.stderr)
    config = get(f"{a.url}/config")
    seq = get(f"{a.url}/trace?after=0")["seq"]
    started = time.time()
    with open(path, "a", encoding="utf-8") as out:
        for n, job in enumerate(jobs):
            key = key_of(job)
            if key in done:
                continue
            method, dim, value, seed, p = job
            body = {
                "model": a.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": f"{context}\n\n{p['prompt']}"}],
                "temperature": 0.7, "seed": seed, "max_tokens": a.max_tokens, "reasoning_effort": "none",
            }
            if dim:
                body["steering"] = {dim: value}
                body["method"] = method
            try:
                data = post(f"{a.url}/v1/chat/completions", body)
            except Exception as err:  # noqa: BLE001 — one failed generation only loses its row
                print(f"  {key[:40]}: {err}", file=sys.stderr)
                continue
            text = data["choices"][0]["message"].get("content") or ""
            applied = (data.get("persona") or {}).get("steering") or {}
            trace = get(f"{a.url}/trace?after={seq}")
            seq = trace["seq"]
            curve = projections(trace["events"], dim) if dim else None
            row = {
                "key": key, "method": method, "dim": dim, "label": LABEL.get(dim, dim) if dim else None, "value": value, "seed": seed,
                "prompt": p["prompt"], "subsection": p["subsection"], "text": text, "alpha": applied.get("applied_alpha", {}).get(dim) if dim else None,
                "curve": curve, "band": applied.get("layers"), **metrics(text), "tokens": data.get("usage", {}).get("completion_tokens"),
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            done.add(key)
            if (n + 1) % 20 == 0:
                rate = (time.time() - started) / max(1, len(done))
                print(f"  {len(done)}/{len(jobs)}  ~{rate:.1f}s each", file=sys.stderr)
    json.dump({"config": config, "jobs": len(jobs), "done": len(done), "seconds": round(time.time() - started)}, open(os.path.join(a.out, "run.json"), "w"), indent=1)
    print(f"done {len(done)}/{len(jobs)} in {time.time() - started:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
