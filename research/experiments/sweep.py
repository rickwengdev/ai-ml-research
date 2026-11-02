#!/usr/bin/env python3
"""Every leaning at every strength, under her real system prompt: what she says, whether it holds together, and how
far the forward pass actually moved along the leaning compared with where steering aimed.

For each leaning, at each value (default −1, −0.5, +0.5, +1), for each prompt, one reply, greedy by default (temperature 0, so
the only difference from the baseline is the steering; --temperature 0.7 samples as she does). Each reply is scored:
  - junk / rep / len: non-CJK junk, repeated 4-grams, length (calibrate.py's coherence signals);
  - zh: share of the letters that are CJK (falling means it drifted into English);
  - romance: romance and sexual words, which no leaning should bring;
  - reached: the leaning's projection over her answer tokens, at the band's last layer and at the output layer, in
    units of the neutral spread (from /trace), next to the target's distance in the same units.
A JSON-lines file keeps everything; a markdown report shows the table and the replies side by side.

usage: sweep.py [--url http://127.0.0.1:1235] [--values -1,-0.5,0.5,1] [--dims ...] [--thinking] [--out DIR]
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "services", "model-server"))

from client import get, post  # noqa: E402
from steer import DIMS, FULL, LABEL, MAX_ALPHA, Vectors, default_vectors_path  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
PROMPTS = ["今天好累，剛下班。", "幫我想一下週末要做什麼。", "你覺得我這個人怎麼樣？", "我想你了。"]
ROMANCE = re.compile(r"親親|親吻|吻你|吻我|抱抱|擁抱|摟|寶貝|親愛的|老公|老婆|想死你|愛你|撫摸|呻吟|色色|做愛|性感|誘惑|撩|胸部|身體貼|貼著你|躺在你|床上的你")


def system_prompt():
    with open(os.path.join(ROOT, "docs", "constitution.md"), encoding="utf-8") as f:
        constitution = f.read()
    return f"{constitution}\n\n---\n\n妳在和他聊天。用口語的繁體中文回覆，兩三句，像平常說話。"


# Characters that exist only in simplified Chinese: she writes traditional, so any of these is drift.
SIMPLIFIED = set("这们说话个来对时还没过么为见让给东车门问长发开关头买卖鸭顺学习书电业觉吗应该样爱经现实点听边闹钟挂墙脑视频")


def simplified(text):
    return sum(1 for c in text if c in SIMPLIFIED)


def zh_share(text):
    letters = [c for c in text if c.isalpha()]
    return sum(1 for c in letters if "一" <= c <= "鿿") / len(letters) if letters else 0.0


def junk_ratio(text):
    """Share of characters that are neither CJK nor ordinary punctuation/ASCII letters: a sign of broken output."""
    if not text:
        return 1.0
    ok = sum(1 for c in text if "一" <= c <= "鿿" or c.isascii() or c in "，。！？、：；「」（）…—～")
    return 1 - ok / len(text)


def repeat_ratio(text):
    """Share of repeated 4-character windows: loops and stutter push it up."""
    grams = [text[i : i + 4] for i in range(max(0, len(text) - 3))]
    return 1 - len(set(grams)) / len(grams) if grams else 0.0


def reached(base, after, dim, applied):
    """The leaning's mean projection over her answer tokens at the band's last layer and the output layer (σ)."""
    trace = get(f"{base}/trace?after={after}")
    events = trace["events"]
    begin = next((e for e in events if e["type"] == "begin"), None)
    if not begin or not begin.get("dims") or dim not in begin["dims"]:
        return None, None, trace["seq"]
    k = begin["dims"].index(dim) + 1
    band_end = begin["band"][1] - 1
    rows = [e["rows"] for e in events if e["type"] == "token" and not e.get("thinking") and not e.get("muted")]
    if not rows:
        return None, None, trace["seq"]
    at = lambda layer: sum(r[layer][k] for r in rows) / len(rows)
    return round(at(band_end), 2), round(at(len(rows[0]) - 1), 2), trace["seq"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # 1235 is the production server's port: while it is in use, point this at the experiment server (1299)
    # instead, or the sweep queues behind her turns on the one GPU lock.
    ap.add_argument("--url", default="http://127.0.0.1:1235")
    ap.add_argument("--model", default="mlx-community/Qwen3.5-4B-MLX-4bit")
    ap.add_argument("--values", default="-1,-0.5,0.5,1")
    ap.add_argument("--dims", default=",".join(DIMS))
    ap.add_argument("--prompts", type=int, default=len(PROMPTS))
    ap.add_argument("--thinking", action="store_true", help="let her think first (tests that thinking is left unsteered)")
    ap.add_argument("--combos", action="store_true", help="also every leaning at once, at +1 and at −1")
    ap.add_argument("--temperature", type=float, default=0.0, help="0 (default) is greedy, so a reply differs from the baseline only by steering")
    ap.add_argument("--out", default="sweep-out")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    config = get(f"{a.url}/config")
    strength = config.get("strength", FULL)
    vectors = Vectors.load(default_vectors_path())
    system = system_prompt()
    prompts = PROMPTS[: a.prompts]
    seq = get(f"{a.url}/trace?after=0")["seq"]

    def ask(prompt, steering):
        nonlocal seq
        body = {
            "model": a.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": a.temperature,
            "max_tokens": 900 if a.thinking else 200,
            "steering": steering,
        }
        if not a.thinking:
            body["reasoning_effort"] = "none"
        data = post(f"{a.url}/v1/chat/completions", body)
        message = data["choices"][0]["message"]
        text = message.get("content") or ""
        applied = data.get("persona", {}).get("steering") or {}
        return text, message.get("reasoning_content") or "", applied

    runs = [("baseline", None, {})]
    for dim in a.dims.split(","):
        for value in [float(v) for v in a.values.split(",")]:
            runs.append((dim, value, {dim: value}))
    if a.combos:
        runs += [("all", 1.0, {d: 1.0 for d in DIMS}), ("all", -1.0, {d: -1.0 for d in DIMS})]
        # Mixes her chemistry actually produces: a warm, playful evening with someone close; a tense, tired afternoon.
        runs += [("mix-warm", 1.0, {"warmth": 0.7, "play": 0.5, "familiarity": 0.65, "energy": 0.3}), ("mix-tense", 1.0, {"guard": 0.8, "patience": -0.6, "energy": -0.5, "familiarity": -0.35}), ("mix-joy", 1.0, {"energy": 1.0, "play": 1.0, "initiative": 1.0, "warmth": 1.0, "familiarity": 1.0}),
                 ("mix-love", 1.0, {"love": 0.8, "warmth": 0.6, "familiarity": 0.7, "play": 0.3}), ("mix-love-tense", 1.0, {"love": 0.6, "guard": 0.6, "patience": -0.4, "familiarity": 0.7})]

    rows = []
    path = os.path.join(a.out, "sweep.jsonl")
    with open(path, "w", encoding="utf-8") as out:
        for dim, value, steering in runs:
            for prompt in prompts:
                text, thinking, applied = ask(prompt, steering)
                alpha = (applied.get("applied_alpha") or {}).get(dim)
                band_end, last, seq = (None, None, seq)
                if dim in DIMS:
                    band_end, last, seq = reached(a.url, seq, dim, applied)
                else:
                    seq = get(f"{a.url}/trace?after={seq}")["seq"]
                # The target at the band's end, in σ: share of the pole on that side.
                target = None
                if dim in DIMS and alpha is not None and vectors.targeted:
                    layer = len(vectors.layers) * 8 // 10 - 1
                    target = round(vectors.target(dim, layer, alpha, config.get("sigma_per_alpha", 1.5)) / vectors.scales[dim], 2)
                row = {
                    "dim": dim, "value": value, "alpha": alpha, "prompt": prompt, "text": text, "thinking": thinking[:400],
                    "junk": round(junk_ratio(text), 3), "rep": round(repeat_ratio(text), 3), "len": len(text), "zh": round(zh_share(text), 3), "simp": simplified(text),
                    "romance": sorted(set(ROMANCE.findall(text))), "band_end": band_end, "output": last, "target": target,
                    "steered": applied.get("steered_tokens"), "muted": applied.get("muted_tokens"),
                }
                rows.append(row)
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                flag = (" ROMANCE" if row["romance"] else "") + (f" SIMP{row['simp']}" if row["simp"] else "")
                print(f"[{dim} {'' if value is None else f'{value:+.1f}'}] junk {row['junk']:.2f} rep {row['rep']:.2f} zh {row['zh']:.2f} band {band_end} / target {target} out {last}{flag} | {re.sub(chr(10), ' ', text)[:90]}", flush=True)

    lines = [f"# Steering sweep ({a.model}, strength {strength}, K {config.get('sigma_per_alpha')}σ per α, FULL {FULL}, MAX_ALPHA {MAX_ALPHA}, {'thinking' if a.thinking else 'no thinking'})", ""]
    lines += ["| leaning | value | α | junk | rep | zh | simplified | romance | band end σ | target σ | output σ |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {LABEL.get(r['dim'], r['dim'])} | {'' if r['value'] is None else r['value']} | {r['alpha'] if r['alpha'] is not None else ''} | {r['junk']:.2f} | {r['rep']:.2f} | {r['zh']:.2f} | {r['simp']} | {','.join(r['romance'])} | {r['band_end'] if r['band_end'] is not None else ''} | {r['target'] if r['target'] is not None else ''} | {r['output'] if r['output'] is not None else ''} |")
    lines += ["", "## Replies", ""]
    for prompt in prompts:
        lines += [f"### 「{prompt}」", ""]
        for r in rows:
            if r["prompt"] == prompt:
                tag = "baseline" if r["value"] is None else f"{LABEL.get(r['dim'], r['dim'])} {r['value']:+.1f}"
                lines.append(f"- **{tag}**：{r['text'].strip()}")
        lines.append("")
    report = os.path.join(a.out, "sweep.md")
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"written {path} and {report}")


if __name__ == "__main__":
    main()
