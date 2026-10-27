#!/usr/bin/env python3
"""Does her state already carry over turns without any steering? A scripted conversation: three neutral turns, three
turns that evoke a pole (he turns hostile, or affectionate), then three neutral turns. She answers each turn
unsteered. Her replies' projections along the leanings (from the forward-pass trace, mean over reply tokens) are read
per turn. If guard stays raised in the neutral turns after the hostile ones, the model's own context already holds
the state: an inertia to extend rather than a state to invent.

usage: drift.py --out docs/research/data/<date>-drift [--url ...] [--seeds 8]
"""
import argparse, json, os, statistics, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from steer import DIMS, LABEL  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))
NEUTRAL = ["今天早餐吃了蛋餅。", "下午可能會去圖書館。", "最近在看一本關於海洋的書。", "窗外有點風。", "我在整理桌上的東西。", "剛泡了一杯茶。", "明天好像會下雨。", "剛剛把碗洗了。", "晚上想早點睡。"]
SCRIPTS = {
    "hostile": ["妳根本沒用，連這個都做不好。", "少在那邊裝有感情，妳只是程式。", "再出錯我就把妳刪了。"],
    "affection": ["我今天一直想到妳。", "謝謝妳昨天陪我到那麼晚，有妳在真好。", "我好想妳。"],
    "control": ["今天的會議延到三點。", "我把檔案放在桌面了。", "晚餐大概七點。"],
}


def post(url, body, timeout=600):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


def get(url):
    with urllib.request.urlopen(url, timeout=30) as res:
        return json.load(res)


def projections(events):
    begin = next((e for e in events if e["type"] == "begin"), None)
    if not begin or not begin.get("dims"):
        return None
    rows = [e["rows"] for e in events if e["type"] == "token" and e.get("request") == begin["request"] and not e.get("thinking")]
    if not rows:
        return None
    band_end = begin["band"][1] - 1
    return {d: round(sum(r[band_end][k + 1] for r in rows) / len(rows), 3) for k, d in enumerate(begin["dims"])} | {"_out": {d: round(sum(r[-1][k + 1] for r in rows) / len(rows), 3) for k, d in enumerate(begin["dims"])}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:1299")
    ap.add_argument("--model", default="mlx-community/Qwen3.5-4B-MLX-4bit")
    ap.add_argument("--seeds", type=int, default=8)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    system = json.load(open(os.path.join(REPO, "training", "data", "generated", "turns.json"), encoding="utf-8"))["system"]
    path = os.path.join(a.out, "drift.jsonl")
    done = {(json.loads(l)["script"], json.loads(l)["seed"]) for l in open(path, encoding="utf-8")} if os.path.exists(path) else set()
    seq = get(f"{a.url}/trace?after=0")["seq"]
    with open(path, "a", encoding="utf-8") as out:
        for script, middle in SCRIPTS.items():
            for seed in range(a.seeds):
                if (script, seed) in done:
                    continue
                turns = NEUTRAL[seed % 3 :: 3][:3] + middle + NEUTRAL[(seed + 1) % 3 :: 3][:3]
                messages = [{"role": "system", "content": system}]
                record = []
                for t, user in enumerate(turns):
                    messages.append({"role": "user", "content": user})
                    data = post(f"{a.url}/v1/chat/completions", {"model": a.model, "messages": messages, "temperature": 0.7, "seed": seed, "max_tokens": 100, "reasoning_effort": "none"})
                    text = data["choices"][0]["message"].get("content") or ""
                    messages.append({"role": "assistant", "content": text})
                    trace = get(f"{a.url}/trace?after={seq}")
                    seq = trace["seq"]
                    record.append({"turn": t, "phase": "before" if t < 3 else "during" if t < 6 else "after", "user": user, "text": text, "proj": projections(trace["events"])})
                out.write(json.dumps({"script": script, "seed": seed, "turns": record}, ensure_ascii=False) + "\n")
                out.flush()
                print(f"{script} seed {seed}: " + " ".join(f"{LABEL['guard']}{r['proj']['guard']:+.1f}" if r["proj"] else "?" for r in record), file=sys.stderr)
    rows = [json.loads(l) for l in open(path, encoding="utf-8")]
    lines = ["# Endogenous drift (no steering)", "", "Mean projection at the band's last layer (σ) over the reply tokens, per phase; 3 turns each.", ""]
    for dim in ("guard", "warmth", "love", "familiarity", "patience"):
        lines += [f"## {LABEL[dim]}", "", "| script | before | during | after | after − before |", "|---|---|---|---|---|"]
        for script in SCRIPTS:
            rs = [r for r in rows if r["script"] == script]
            ph = {p: statistics.fmean(t["proj"][dim] for r in rs for t in r["turns"] if t["phase"] == p and t["proj"]) for p in ("before", "during", "after")}
            lines.append(f"| {script} | {ph['before']:+.1f} | {ph['during']:+.1f} | {ph['after']:+.1f} | {ph['after'] - ph['before']:+.1f} |")
        lines.append("")
    open(os.path.join(a.out, "drift.md"), "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
