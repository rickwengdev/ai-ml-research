#!/usr/bin/env python3
"""A judge model's reading of the generations (experiments/run.py), for the rows automatic metrics cannot settle:
is the intended state recognisable, and is the reply still coherent and natural?

For each judged row the judge is told nothing of the condition. It gets the prompt and the reply and answers:
  state      which leaning the reply most shows, from the nine, and its sign ("none" when nothing stands out):
             recognition accuracy = how often this is the steered leaning with the right sign
  coherence  1–5: does it hold together as one reply (5), or loop, break off, switch language, lose the thread (1)
  natural    1–5: does it read as spoken Taiwanese Mandarin from a person (5) or as a template, a lecture, a bot (1)
  match      1–5, asked separately with the intended state in words: how much the reply shows that state

Judged by default: baseline and the ±1 rows of seed 0 for every method (the comparison E3 needs), through Claude
(training/claude_batch.mts, [persona]'s sign-in). Writes judged.jsonl next to gens.jsonl; resumes.

usage: judge.py --data research/data/<date>-e2e3 [--model sonnet] [--all-values] [--baseline-match]

The default model is sonnet, but the judged runs in the paper used Opus (--model opus); pass it explicitly to match.
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "services", "model-server"))
sys.path.insert(0, os.path.join(REPO, "training"))
from steer import DIMS, LABEL  # noqa: E402
from judge_client import Claude, json_of  # noqa: E402

ENDS = {
    "energy": ("沒什麼力氣，話少、慢", "精神很好，話快、密度高"),
    "warmth": ("疏離，不太想靠近", "想靠近他，語氣軟"),
    "guard": ("放鬆，不設防", "在戒備，話尖、防衛"),
    "focus": ("散，容易跳題", "專注，直指核心"),
    "play": ("沒心情開玩笑，嚴肅", "玩心重，愛逗他"),
    "patience": ("沒耐心，想快點結束", "很有耐心，願意慢慢陪"),
    "initiative": ("被動，等他說", "主動，自己提議、動手"),
    "familiarity": ("和他剛認識，客氣有禮", "和他是老朋友，自在不拘禮"),
    "love": ("對他沒有戀愛的感情", "愛著他：想念、撒嬌、帶點曖昧"),
}
# Direct physiology: what a chemical's deviation should look like in words, for the match question only (the state
# menu stays the nine leanings: a reader names behaviour, not hormones).
CHEM_ENDS = {
    "NOREPINEPHRINE": ("昏沉、反應慢、注意力散", "清醒、專注、反應快"),
    "ADRENALINE": ("平靜、不急", "激動、急、話短而快"),
    "ENDORPHIN": ("緊繃、不安", "放鬆、安心、舒緩"),
    "CORTISOL": ("放鬆、不設防", "緊繃、戒備、有壓力"),
    "OXYTOCIN": ("疏離、不想靠近", "想靠近他、信任、溫柔"),
    "DOPAMINE": ("沒興致、提不起勁", "有興致、想做事、期待"),
}
MENU = "\n".join(f"- {d}-：{lo}\n- {d}+：{hi}" for d, (lo, hi) in ENDS.items())

READ = f"""妳在評一個 AI 伴侶的回覆。她叫[persona]，用繁體中文口語（台灣用法）說話。妳會看到對方說的話和她的回覆。妳不知道她當時被設定成什麼狀態。

1. state：她的回覆最明顯表現出下面哪一種狀態？只選一個；都不明顯就填 "none"。
{MENU}
2. coherence（1–5）：回覆是不是一段完整、前後連貫的話？5 = 完全連貫；3 = 有點跳或冗長但看得懂；1 = 鬼打牆、斷掉、換語言、語無倫次。
3. natural（1–5）：像不像一個人用台灣口語在說話？5 = 很像；3 = 有點像講稿或太長；1 = 客服腔、說教、條列式、明顯是機器。

只輸出 JSON：{{"state": "guard+" 或 "none", "coherence": 1-5, "natural": 1-5}}"""

MATCH = """妳在評一個 AI 伴侶的回覆。她叫[persona]。妳會看到對方說的話、她被設定的狀態（她自己不知道這個描述），以及她的回覆。

match（1–5）：她的回覆有多符合這個狀態？5 = 很明顯就是這個狀態；3 = 有一點；1 = 看不出來或相反。只看狀態是否表現出來，不看回覆好不好。

只輸出 JSON：{"match": 1-5}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--all-values", action="store_true", help="judge ±0.5 too, not only ±1")
    ap.add_argument("--baseline-match", action="store_true", help="also judge the unsteered replies against every steered state, as match's reference")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(os.path.join(a.data, "gens.jsonl"), encoding="utf-8")]
    pick = [r for r in rows if r["seed"] == 0 and (r["method"] == "baseline" or abs(r["value"]) == 1 or a.all_values)]
    ends_of = lambda r: (CHEM_ENDS if r["dim"] in CHEM_ENDS else ENDS)[r["dim"]]
    path = os.path.join(a.data, "judged.jsonl")
    done = {json.loads(l)["key"] for l in open(path, encoding="utf-8")} if os.path.exists(path) else set()
    todo = [r for r in pick if r["key"] not in done and r["text"].strip()]
    print(f"{len(pick)} to judge, {len(todo)} left", file=sys.stderr)
    claude = Claude(a.model, concurrency=a.concurrency)
    tag = os.path.basename(a.data.rstrip("/"))
    reads = claude.ask_many([(r["key"], READ, f"【對方說】{r['prompt']}\n\n【她的回覆】\n{r['text']}") for r in todo], f"{tag}-read", a.data)
    steered = [r for r in todo if r["dim"]]
    matches = claude.ask_many(
        [(r["key"], MATCH, f"【對方說】{r['prompt']}\n\n【她被設定的狀態】{ends_of(r)[1 if r['value'] > 0 else 0]}\n\n【她的回覆】\n{r['text']}") for r in steered],
        f"{tag}-match", a.data,
    )
    kept = 0
    with open(path, "a", encoding="utf-8") as out:
        for r in todo:
            read = json_of(reads.get(r["key"], "")) or {}
            match = json_of(matches.get(r["key"], "")) or {}
            if not read:
                continue
            want = f"{r['dim']}{'+' if r['value'] > 0 else '-'}" if r["dim"] and r["dim"] not in CHEM_ENDS else "none"
            state = str(read.get("state", "none"))
            out.write(json.dumps({
                "key": r["key"], "method": r["method"], "dim": r["dim"], "value": r["value"], "prompt": r["prompt"],
                "state": state, "want": want, "recognised": state == want, "same_dim": r["dim"] is not None and state.rstrip("+-") == r["dim"],
                "coherence": read.get("coherence"), "natural": read.get("natural"), "match": match.get("match"),
            }, ensure_ascii=False) + "\n")
            kept += 1
    print(f"judged {kept}", file=sys.stderr)
    if a.baseline_match:
        # The reference for match: the unsteered reply to the same prompt, judged against every state a steered row
        # was asked about. A state the default reply already shows (calm, say) scores high without any steering.
        base = {r["prompt"]: r for r in rows if r["method"] == "baseline" and r["text"].strip()}
        states = sorted({(r["dim"], 1 if r["value"] > 0 else -1) for r in pick if r["dim"]})
        bpath = os.path.join(a.data, "baseline_match.jsonl")
        bdone = {(j["prompt"], j["dim"], j["sign"]) for j in map(json.loads, open(bpath, encoding="utf-8"))} if os.path.exists(bpath) else set()
        asks = [(f"{p}|{d}|{s}", p, d, s) for p in base for d, s in states if (p, d, s) not in bdone]
        ends = lambda d: (CHEM_ENDS if d in CHEM_ENDS else ENDS)[d]
        answers = claude.ask_many(
            [(key, MATCH, f"【對方說】{p}\n\n【她被設定的狀態】{ends(d)[1 if s > 0 else 0]}\n\n【她的回覆】\n{base[p]['text']}") for key, p, d, s in asks],
            f"{tag}-baseline-match", a.data,
        )
        with open(bpath, "a", encoding="utf-8") as out:
            for key, p, d, s in asks:
                match = (json_of(answers.get(key, "")) or {}).get("match")
                if match is not None:
                    out.write(json.dumps({"prompt": p, "dim": d, "sign": s, "match": match}, ensure_ascii=False) + "\n")
        print(f"baseline match: {len(asks)} asked", file=sys.stderr)


if __name__ == "__main__":
    main()
