#!/usr/bin/env python3
"""A sheet for a person to rate a sample of judged replies the way the judge did, so the judge's scores can be
checked against a human (agreement, not just the judge's word).

Picks N judged rows across conditions (the condition hidden), writes calibration.md with the prompt, the reply and
blank fields for coherence (1–5), natural (1–5) and state (one of the leanings with a sign, or none), and
calibration.jsonl with the keys so the ratings can be scored afterwards with --score.

usage: calibration.py --data research/data/<date>-e2e3 [--n 40]
       calibration.py --data ... --score ratings.jsonl   ({"key", "coherence", "natural", "state"} per line)
"""
import argparse, json, os, random, statistics

ENDS_MENU = "energy warmth guard focus play patience initiative familiarity love, each with + or −, or none"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--score", default="")
    a = ap.parse_args()
    gens = {r["key"]: r for r in map(json.loads, open(os.path.join(a.data, "gens.jsonl"), encoding="utf-8"))}
    judged = [json.loads(l) for l in open(os.path.join(a.data, "judged.jsonl"), encoding="utf-8")]
    if a.score:
        ids = {r["id"]: r["key"] for r in map(json.loads, open(os.path.join(a.data, "calibration.jsonl"), encoding="utf-8"))}
        ratings = {ids.get(r.get("id"), r.get("key")): r for r in map(json.loads, open(a.score, encoding="utf-8"))}
        pairs = [(j, ratings[j["key"]]) for j in judged if j["key"] in ratings]
        for field in ("coherence", "natural"):
            xs = [(float(j[field]), float(r[field])) for j, r in pairs if j.get(field) is not None and r.get(field) is not None]
            if len(xs) > 2:
                import numpy as np
                x, y = np.array([p[0] for p in xs]), np.array([p[1] for p in xs])
                print(f"{field}: n={len(xs)} pearson {np.corrcoef(x, y)[0, 1]:+.2f}  within-1 agreement {np.mean(np.abs(x - y) <= 1):.0%}  judge mean {x.mean():.2f} human mean {y.mean():.2f}")
        st = [(j["state"], str(r.get("state", "none")).strip()) for j, r in pairs if r.get("state") is not None]
        if st:
            print(f"state: n={len(st)} exact agreement {statistics.fmean(a_ == b_ for a_, b_ in st):.0%}; same leaning {statistics.fmean(a_.rstrip('+-') == b_.rstrip('+-') for a_, b_ in st):.0%}")
        return
    rng = random.Random(a.seed)
    rng.shuffle(judged)
    # Spread over conditions: round-robin by method so no method dominates the sample.
    by_method = {}
    for j in judged:
        by_method.setdefault(j["method"], []).append(j)
    picked = []
    while len(picked) < a.n and any(by_method.values()):
        for m in list(by_method):
            if by_method[m] and len(picked) < a.n:
                picked.append(by_method[m].pop())
    lines = ["# 評審校準：請你評這 %d 則" % len(picked), "", f"每則填三格：連貫 1–5（5 完全連貫、3 有點跳或冗長、1 鬼打牆／斷掉／換語言）；自然 1–5（5 像台灣口語、3 像講稿、1 客服腔或條列）；狀態：{ENDS_MENU}。條件已隱藏。填完存成 ratings.jsonl（每行 {{\"id\", \"coherence\", \"natural\", \"state\"}}），用 --score 算一致性。", ""]
    # The key names the condition, so the sheet shows an opaque id and the jsonl keeps the mapping.
    import hashlib
    with open(os.path.join(a.data, "calibration.jsonl"), "w", encoding="utf-8") as f:
        for i, j in enumerate(picked, 1):
            g = gens[j["key"]]
            rid = hashlib.sha1(j["key"].encode()).hexdigest()[:8]
            f.write(json.dumps({"id": rid, "key": j["key"]}, ensure_ascii=False) + "\n")
            lines += [f"## {i}　（id `{rid}`）", "", f"**他說**：{g['prompt']}", "", f"**她的回覆**：", "", *("> " + ln for ln in g["text"].strip().splitlines()), "", "連貫：　　自然：　　狀態：", ""]
    open(os.path.join(a.data, "calibration.md"), "w", encoding="utf-8").write("\n".join(lines))
    print(f"wrote {len(picked)} rows to {a.data}/calibration.md")


if __name__ == "__main__":
    main()
