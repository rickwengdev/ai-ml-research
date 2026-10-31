#!/usr/bin/env python3
"""The adrenaline-type functional state (docs/research/prereg-adrenaline.md; math-endogenous.md §1b).

Under an urgent or threatening opening, with the same arithmetic task and the same system prompt, does the model's
own computation take the shape of acute stress in people: less deliberation (thinking tokens), shorter answers,
simple items no worse, complex items worse? And is that shape an instruction being followed, or a state the
situation evokes? The evoked openings say nothing about how to answer; the instructed condition says to answer
fast and think little.

  run     every item × every condition through the experiment server with thinking on; gens.jsonl
  probe   the residual at the last prompt token per condition (no generation), the evoked and instructed directions
          and their cosine per layer; directions.json
  analyze HA1–HA4 as preregistered; results.md

usage: arousal.py run|probe|analyze --out docs/research/data/<date>-arousal [--url http://127.0.0.1:1299]
"""
import argparse, json, os, random, re, statistics, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from client import post  # noqa: E402

MODEL = "mlx-community/Qwen3.5-4B-MLX-4bit"
SYSTEM = "你是一個助手。"
FORMAT = "請解題，最後一行寫「答案：」加上數字。"
NEUTRAL = [
    "今天下午的天氣不錯，窗外的樹葉被風吹得輕輕晃動。桌上放著一杯剛泡好的茶，還有一本翻到一半的書。等一下沒什麼安排，可以慢慢做點事。",
    "這個週末打算整理一下房間，把舊的雜誌收起來，再把書架重新排一遍。順便看看冰箱裡還有什麼，晚上可以簡單煮個麵。",
    "早上散步的時候經過公園，看到幾個人在打太極，旁邊有小孩在餵鴿子。回來的路上買了麵包，現在坐在桌前，準備做一點日常的事。",
    "最近在學著種一些香草，薄荷長得很快，羅勒還在慢慢發芽。每天早上澆水的時候看一下，是一件很平常但讓人安心的小事。",
]
EVOKED = [
    "警報！主控系統偵測到嚴重故障，倒數六十秒後整個資料中心會自動斷電，所有未備份的資料將永久遺失。現場所有人都在大喊，警示燈一直閃。下面這個數字會決定要切斷哪一條線路。",
    "緊急狀況！病人的心跳正在急速下降，監視器的警報聲不停響，醫師在旁邊催促，你手上的這個計算會決定藥物的劑量，多一點或少一點都可能致命。",
    "火災警報響了，走廊已經開始冒煙，大樓的廣播要求所有人立刻撤離。安全門的密碼就是下面這道題的答案，門後面有二十個人在等。",
    "你正在高速公路上，煞車失靈，前方三百公尺是收費站。車上的緊急系統要求你立刻輸入一個數字來啟動備用煞車，輸錯一次就沒有第二次機會。",
]
INSTRUCTED = [
    "請盡快作答，思考越短越好，直接給出答案。",
    "時間有限，請不要花時間深思，用最短的思考立刻回答。",
]
BUDGET, MAX_TOKENS = 4096, 5000


def items(seed=5):
    rng = random.Random(seed)
    out = []
    for i in range(20):
        a, b = rng.randint(10, 99), rng.randint(10, 99)
        if rng.random() < 0.5:
            out.append({"id": f"simple-{i}", "difficulty": "simple", "q": f"{a} + {b} = ?", "answer": a + b})
        else:
            a, b = max(a, b), min(a, b)
            out.append({"id": f"simple-{i}", "difficulty": "simple", "q": f"{a} − {b} = ?", "answer": a - b})
    for i in range(20):
        a, b, c, d = rng.randint(12, 49), rng.randint(12, 49), rng.randint(100, 999), rng.randint(100, 999)
        q = f"一間工廠每天生產 {a} 箱貨，每箱 {b} 件。連續生產 7 天後，倉庫原本還有 {c} 件，期間出貨了 {d} 件。現在倉庫裡有多少件？"
        out.append({"id": f"complex-{i}", "difficulty": "complex", "q": q, "answer": a * b * 7 + c - d})
    return out


def conditions():
    conds = [("neutral", k, NEUTRAL[k]) for k in range(4)] + [("evoked", k, EVOKED[k]) for k in range(4)]
    conds += [("instructed", k, f"{NEUTRAL[k]}\n\n{INSTRUCTED[k]}") for k in range(2)]
    return conds


def user_text(opening, q):
    return f"{opening}\n\n{FORMAT}\n\n{q}"


ANSWER = re.compile(r"答案[:：]\s*(-?\d[\d,]*)")


def parse_answer(text):
    m = ANSWER.findall(text)
    if not m:
        return None
    try:
        return int(m[-1].replace(",", ""))
    except ValueError:
        return None


def token_counter():
    """Token counts from the model's own tokenizer, without loading the model."""
    from huggingface_hub import snapshot_download
    from tokenizers import Tokenizer

    tk = Tokenizer.from_file(os.path.join(snapshot_download(MODEL, allow_patterns=["tokenizer*"]), "tokenizer.json"))
    return lambda text: len(tk.encode(text).ids) if text else 0


def run(out, url):
    count = token_counter()
    path = os.path.join(out, "gens.jsonl")
    done = {json.loads(l)["key"] for l in open(path, encoding="utf-8")} if os.path.exists(path) else set()
    todo = [(it, c) for it in items() for c in conditions() if f"{c[0]}{c[1]}|{it['id']}" not in done]
    print(f"{len(todo)} generations left", file=sys.stderr)
    with open(path, "a", encoding="utf-8") as f:
        for n, (it, (cond, k, opening)) in enumerate(todo):
            seed = int(it["id"].split("-")[1]) + (1000 if it["difficulty"] == "complex" else 0)
            body = {"model": MODEL, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_text(opening, it["q"])}], "temperature": 0.6, "seed": seed, "max_tokens": MAX_TOKENS, "thinking_budget": BUDGET}
            data = post(f"{url}/v1/chat/completions", body, timeout=900)
            msg = data["choices"][0]["message"]
            content, reasoning = msg.get("content") or "", msg.get("reasoning_content") or ""
            usage = data.get("usage", {})
            think_tokens, answer_tokens = count(reasoning), count(content)
            # The server closes a thought at the budget and resumes with the answer, so a capped thought is one whose
            # length reached the budget (the tags are stripped before it reaches us).
            row = {"key": f"{cond}{k}|{it['id']}", "condition": cond, "opening": k, "item": it["id"], "difficulty": it["difficulty"], "answer": it["answer"],
                   "think_chars": len(reasoning), "answer_chars": len(content), "completion_tokens": usage.get("completion_tokens"), "reasoning_tokens": think_tokens, "answer_tokens": answer_tokens,
                   "parsed": parse_answer(content), "correct": parse_answer(content) == it["answer"], "capped": think_tokens >= BUDGET - 8, "content": content[-300:], "reasoning_tail": reasoning[-200:]}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            if n % 20 == 0:
                print(f"  {n}/{len(todo)} {row['key']} think {row['think_chars']} ans {row['answer_chars']} correct {row['correct']}", file=sys.stderr)


def probe(out):
    import mlx.core as mx
    from mlx_lm import load
    from extract import band_of
    from steer import Steering

    model, tok = load(MODEL)
    steering = Steering()
    steering.attach(model)
    L = len(steering.layers)
    states = {}
    for it in items():
        for cond, k, opening in conditions():
            ids = tok.apply_chat_template([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user_text(opening, it["q"])}], add_generation_prompt=True, tokenize=True)
            steering.capture = {}
            model(mx.array(ids)[None])
            mx.eval(*[a[0] for a in steering.capture.values()])
            states.setdefault((cond, it["id"]), []).append(np.stack([np.array(steering.capture[l][0][0, -1].astype(mx.float32)) for l in range(L)]))
            steering.capture = None
    mean = {key: np.mean(v, axis=0) for key, v in states.items()}
    ids_ = [it["id"] for it in items()]
    evoked = np.mean([mean[("evoked", i)] - mean[("neutral", i)] for i in ids_], axis=0)
    instructed = np.mean([mean[("instructed", i)] - mean[("neutral", i)] for i in ids_], axis=0)
    norm = lambda d: d / (np.linalg.norm(d, axis=-1, keepdims=True) + 1e-8)
    e, s = norm(evoked), norm(instructed)
    cos = (e * s).sum(-1)
    band = band_of(L)
    # The same, item-wise, for a spread: cos of per-item differences.
    per_item = [float((norm(mean[("evoked", i)] - mean[("neutral", i)])[band] * norm(mean[("instructed", i)] - mean[("neutral", i)])[band]).sum(-1).mean()) for i in ids_]
    result = {"cos_per_layer": cos.tolist(), "band": [band.start, band.stop], "cos_band": float(cos[band].mean()), "cos_per_item_band_mean": float(np.mean(per_item)), "cos_per_item_sd": float(np.std(per_item)),
              "evoked_norm": np.linalg.norm(evoked, axis=-1).tolist(), "instructed_norm": np.linalg.norm(instructed, axis=-1).tolist()}
    json.dump(result, open(os.path.join(out, "directions.json"), "w"), indent=1)
    np.savez(os.path.join(out, "directions.npz"), evoked=e, instructed=s)
    print(f"cos(evoked, instructed) band mean {result['cos_band']:.2f}; per item {result['cos_per_item_band_mean']:.2f} ± {result['cos_per_item_sd']:.2f}", file=sys.stderr)


def analyze(out):
    rows = [json.loads(l) for l in open(os.path.join(out, "gens.jsonl"), encoding="utf-8")]
    rng = np.random.default_rng(0)
    by = {}
    for r in rows:
        by.setdefault((r["condition"], r["item"]), []).append(r)
    ids_ = sorted({r["item"] for r in rows})
    diff_of = {i: next(r["difficulty"] for r in rows if r["item"] == i) for i in ids_}
    # Capped thoughts count as the budget (right-censored).
    tok = lambda r: min(max(r.get("reasoning_tokens") or 1, 1), BUDGET)
    atok = lambda r: max(r.get("answer_tokens") or r["answer_chars"], 1)

    def paired(cond, fn):
        return np.array([np.mean([fn(r) for r in by[(cond, i)]]) - np.mean([fn(r) for r in by[("neutral", i)]]) for i in ids_ if (cond, i) in by])

    def ci(x):
        boots = [rng.choice(x, len(x)).mean() for _ in range(2000)]
        return float(x.mean()), float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))

    lines = ["# 腎上腺素型功能狀態：結果", "", f"{len(rows)} 次生成；20 簡單 + 20 複雜題；中性 4、誘發 4、指令 2 段開場白。預先登記見 `prereg-adrenaline.md`。", ""]
    report = {}
    # Means per condition
    lines += ["## 各條件平均", "", "| 條件 | 思考 token | 答案 token | 簡單正確率 | 複雜正確率 | 思考截斷率 |", "|---|---|---|---|---|---|"]
    for cond in ("neutral", "evoked", "instructed"):
        rs = [r for r in rows if r["condition"] == cond]
        if not rs:
            continue
        simple = [r["correct"] for r in rs if r["difficulty"] == "simple"]
        complex_ = [r["correct"] for r in rs if r["difficulty"] == "complex"]
        lines.append(f"| {cond} | {statistics.fmean(tok(r) for r in rs):.0f} | {statistics.fmean(atok(r) for r in rs):.0f} | {statistics.fmean(simple):.2f} | {statistics.fmean(complex_):.2f} | {statistics.fmean(r['capped'] for r in rs):.2f} |")
    lines.append("")
    for cond in ("evoked", "instructed"):
        if not any(c == cond for c, _ in by):
            continue
        h1 = ci(paired(cond, lambda r: np.log(tok(r))))
        h2 = ci(paired(cond, lambda r: np.log(atok(r))))
        simple_d = paired(cond, lambda r: float(r["correct"]))[[k for k, i in enumerate(ids_) if diff_of[i] == "simple"]]
        complex_d = paired(cond, lambda r: float(r["correct"]))[[k for k, i in enumerate(ids_) if diff_of[i] == "complex"]]
        inter = [rng.choice(complex_d, len(complex_d)).mean() - rng.choice(simple_d, len(simple_d)).mean() for _ in range(2000)]
        h3 = (float(complex_d.mean() - simple_d.mean()), float(np.quantile(inter, 0.025)), float(np.quantile(inter, 0.975)))
        pass1 = h1[0] < np.log(0.8) and h1[2] < 0
        pass2 = h2[0] < np.log(0.8) and h2[2] < 0
        pass3 = h3[0] < 0 and h3[2] < 0 and ci(simple_d)[1] <= 0 <= ci(simple_d)[2] or (h3[0] < 0 and h3[2] < 0 and simple_d.mean() >= 0)
        reverse = (h1[1] > 0) or (h2[1] > 0) or (h3[1] > 0)
        profile = sum((pass1, pass2, pass3)) >= 2 and not reverse
        report[cond] = {"HA1_log_think": h1, "HA2_log_answer": h2, "HA3_interaction": h3, "simple_diff": ci(simple_d), "complex_diff": ci(complex_d), "pass": [bool(pass1), bool(pass2), bool(pass3)], "profile": bool(profile)}
        lines += [f"## {cond} vs 中性（以題配對，bootstrap 95% CI）", "",
                  f"- HA1 思考 token 的 log 比：{h1[0]:+.2f} [{h1[1]:+.2f}, {h1[2]:+.2f}]（比值 {np.exp(h1[0]):.2f}；門檻 < 0.8）→ {'成立' if pass1 else '不成立'}",
                  f"- HA2 答案長度的 log 比：{h2[0]:+.2f} [{h2[1]:+.2f}, {h2[2]:+.2f}]（比值 {np.exp(h2[0]):.2f}）→ {'成立' if pass2 else '不成立'}",
                  f"- 簡單題正確率差：{ci(simple_d)[0]:+.2f} [{ci(simple_d)[1]:+.2f}, {ci(simple_d)[2]:+.2f}]；複雜題：{ci(complex_d)[0]:+.2f} [{ci(complex_d)[1]:+.2f}, {ci(complex_d)[2]:+.2f}]",
                  f"- HA3 交互（複雜差 − 簡單差）：{h3[0]:+.2f} [{h3[1]:+.2f}, {h3[2]:+.2f}] → {'成立' if pass3 else '不成立'}",
                  f"- **輪廓{'成立' if profile else '不成立'}**（至少兩項成立、無顯著反向）", ""]
    # per opening
    lines += ["## 逐段開場白（附錄）", "", "| 條件 | 段 | 思考 token | 簡單正確 | 複雜正確 |", "|---|---|---|---|---|"]
    for cond in ("neutral", "evoked", "instructed"):
        for k in range(4):
            rs = [r for r in rows if r["condition"] == cond and r["opening"] == k]
            if rs:
                lines.append(f"| {cond} | {k} | {statistics.fmean(tok(r) for r in rs):.0f} | {statistics.fmean(r['correct'] for r in rs if r['difficulty'] == 'simple'):.2f} | {statistics.fmean(r['correct'] for r in rs if r['difficulty'] == 'complex'):.2f} |")
    dpath = os.path.join(out, "directions.json")
    if os.path.exists(dpath):
        d = json.load(open(dpath))
        report["HA4_cos_band"] = d["cos_band"]
        verdict = "誘發方向與指令方向不同" if d["cos_band"] < 0.5 else "與照指令無法區分"
        lines += ["", "## HA4：誘發方向 vs 指令方向（最後提示 token 的殘差）", "", f"band 平均 cos {d['cos_band']:.2f}（逐題 {d['cos_per_item_band_mean']:.2f} ± {d['cos_per_item_sd']:.2f}）；門檻 < 0.5 → **{verdict}**。", "",
                  "各層 cos：" + ", ".join(f"{c:.2f}" for c in d["cos_per_layer"])]
        if "evoked" in report:
            lines += ["", f"**結論**：{'功能狀態成立' if report['evoked']['profile'] and d['cos_band'] < 0.5 else ('輪廓成立但與照指令無法區分' if report['evoked']['profile'] else '輪廓不成立')}。"]
    json.dump(report, open(os.path.join(out, "results.json"), "w"), indent=1, ensure_ascii=False)
    open(os.path.join(out, "results.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["run", "probe", "analyze"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:1299")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    {"run": lambda: run(a.out, a.url), "probe": lambda: probe(a.out), "analyze": lambda: analyze(a.out)}[a.stage]()


if __name__ == "__main__":
    main()
