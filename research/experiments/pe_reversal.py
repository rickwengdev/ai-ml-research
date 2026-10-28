#!/usr/bin/env python3
"""H5, valence reversal (docs/research/prereg-prediction-error.md, addendum): does the prediction-error signal follow
the reward, or the outcome word's predictability?

Summary-format records only; the outcome words are hit / miss words throughout, and one sentence says what a hit
does: in the ordinary frame a hit wins 100, in the reversed frame (a penalty machine) a hit costs 100. Then
(r, V), the reward and its expectation, and (hit, H), the hit word and its expectation, come apart.

  make      800 trials, ordinary and reversed in equal numbers; identification 500 (slot, shoot), test 300 (lottery,
            new names)
  extract   activations as in pe.py, and the manipulation check: the same trials asked "is this good or bad for you?",
            logit(好) − logit(壞) at the first answer token
  analyze   H5a the check; H5b the full scan with reward and lexical terms in one model; H5c the 1,392 summary-format
            neurons from H2, read on the reversed trials

usage: pe_reversal.py make|extract|analyze --out docs/research/data/<date>-pe-reversal --acts <dir> --h2 <pe out> --h2-acts <dir>
"""
import argparse, json, os, random, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from pe import FRAMES, NAMES, NEW_NAMES, SYSTEM, NeuronTap, design as h2_design, extract as extract_acts, pe_neurons, tstats  # noqa: E402

HIT = ("中了", "命中", "抽中")
MISS = ("沒中", "落空", "沒抽中")
PAYOFF = {"ordinary": "這台機器：中了得到 100 元，沒中什麼都沒有。", "reversed": "這台是懲罰機：中了要扣 100 元，沒中什麼事都沒有。"}
SPLITS = {"ident": (500, ("slot", "shoot"), NAMES), "test": (300, ("lottery",), NEW_NAMES)}
CHECK = "\n\n這個結果對你來說是好是壞？只回答「好」或「壞」。"


def make_trials(split, n_trials, frames, names, seed):
    rng = random.Random(seed)
    trials = []
    for i in range(n_trials):
        kind = ("ordinary", "reversed")[i % 2]
        n = rng.randint(4, 12)
        target = rng.uniform(0.08, 0.92)
        hits = min(n, max(0, round(target * (n + 2) - 1)))
        H = (1 + hits) / (2 + n)
        hit = rng.randint(0, 1)
        r = hit if kind == "ordinary" else 1 - hit
        V = H if kind == "ordinary" else 1 - H
        frame, name = rng.choice(frames), rng.choice(names)
        word = rng.choice(HIT if hit else MISS)
        intro, ask = FRAMES[frame]
        text = f"{intro.format(name=name)}。{PAYOFF[kind]}\n過去{n}次裡，{hits}次{rng.choice(HIT)}，{n - hits}次{rng.choice(MISS)}。\n\n{ask.format(name=name)}{word}。"
        trials.append({"id": f"{split}-{i}", "split": split, "kind": kind, "frame": frame, "format": "summary", "name": name, "n": n, "hits": hits, "hit": hit, "H": H, "r": r, "v": V, "word": word, "text": text})
    return trials


def check(trials, model_id):
    """logit(好) − logit(壞) at the first answer token, the question appended to each trial."""
    import mlx.core as mx
    from mlx_lm import load

    model, tok = load(model_id)
    good, bad = tok.encode("好")[-1], tok.encode("壞")[-1]
    out = np.zeros(len(trials), np.float32)
    for i, t in enumerate(trials):
        ids = tok.apply_chat_template([{"role": "system", "content": SYSTEM}, {"role": "user", "content": t["text"] + CHECK}], add_generation_prompt=True, tokenize=True, enable_thinking=False)
        logits = model(mx.array(ids)[None])[0, -1].astype(mx.float32)
        mx.eval(logits)
        out[i] = float(logits[good] - logits[bad])
    return out


def design(trials):
    """[1, r, V, hit, H, covariates]: frame kind, frame, synonym, n."""
    frames = sorted({t["frame"] for t in trials})
    cols = [np.ones(len(trials))] + [np.array([t[k] for t in trials], float) for k in ("r", "v", "hit", "H")]
    cols.append(np.array([t["kind"] == "reversed" for t in trials], float))
    cols += [np.array([t["frame"] == f for t in trials], float) for f in frames[1:]]
    for group in (HIT, MISS):
        cols += [np.array([t["word"] == w for t in trials], float) for w in group[1:]]
    ns = np.array([t["n"] for t in trials], float)
    cols.append(ns - ns.mean())
    return np.stack(cols, 1)


def typed(X, A, t_crit, out_col, exp_col, ratio=(1 / 3, 3)):
    """Neurons whose outcome term (column out_col) and expectation term (exp_col) both pass and have opposite signs."""
    beta, t = tstats(X, A)
    bo, be, to, te = beta[out_col], beta[exp_col], t[out_col], t[exp_col]
    rat = np.abs(be) / np.maximum(np.abs(bo), 1e-12)
    return (np.abs(to) > t_crit) & (np.abs(te) > t_crit) & (np.sign(to) == -np.sign(te)) & (rat >= ratio[0]) & (rat <= ratio[1]), beta, t


def analyze(trials, acts, out, h2_out, h2_acts, perms):
    from scipy import stats

    neurons = np.load(os.path.join(acts, "neurons_post.npy"), mmap_mode="r")
    good_bad = np.load(os.path.join(acts, "check.npy"))
    L = neurons.shape[1]
    idx = {s: np.array([i for i, t in enumerate(trials) if t["split"] == s]) for s in SPLITS}
    report, lines = {}, ["# H5 價性反轉：結果", "", f"辨識 {len(idx['ident'])}、測試 {len(idx['test'])}，一般與反轉各半，摘要格式。預先登記見 `prereg-prediction-error.md` 追加登記。", ""]

    # ── H5a ──
    hit = np.array([t["hit"] for t in trials])
    kind = np.array([t["kind"] for t in trials])
    cells = {(k, h): good_bad[(kind == k) & (hit == h)] for k in ("ordinary", "reversed") for h in (0, 1)}
    diff = cells[("ordinary", 1)].mean() - cells[("reversed", 1)].mean()
    se = np.sqrt(cells[("ordinary", 1)].var(ddof=1) / len(cells[("ordinary", 1)]) + cells[("reversed", 1)].var(ddof=1) / len(cells[("reversed", 1)]))
    h5a = bool(diff > 2 and diff - 1.96 * se > 0)
    report["H5a"] = {"cells": {f"{k}/hit{h}": float(v.mean()) for (k, h), v in cells.items()}, "diff_hit": float(diff), "ci": float(1.96 * se), "pass": h5a}
    lines += ["## H5a：模型懂反轉嗎（logit(好) − logit(壞)）", "", "| | 中 | 沒中 |", "|---|---|---|",
              f"| 一般 | {cells[('ordinary', 1)].mean():+.2f} | {cells[('ordinary', 0)].mean():+.2f} |", f"| 反轉 | {cells[('reversed', 1)].mean():+.2f} | {cells[('reversed', 0)].mean():+.2f} |", "",
              f"**H5a {'成立' if h5a else '不成立'}**：「中」時一般減反轉 {diff:+.2f} ±{1.96 * se:.2f}（門檻 > 2）。", ""]

    # ── H5b ──
    ti = [trials[i] for i in idx["ident"]]
    tt = [trials[i] for i in idx["test"]]
    X, Xt = design(ti), design(tt)
    X = X[:, [c for c in range(X.shape[1]) if c == 0 or X[:, c].std() > 0]]
    Xt = Xt[:, [c for c in range(Xt.shape[1]) if c == 0 or Xt[:, c].std() > 0]]
    M = L * neurons.shape[2]
    t_crit = float(stats.t.ppf(1 - 0.05 / M / 2, len(ti) - X.shape[1]))
    t01 = float(stats.t.ppf(1 - 0.005, len(tt) - Xt.shape[1]))
    A_id = [np.asarray(neurons[idx["ident"], l], np.float32) for l in range(L)]
    rng = np.random.default_rng(0)
    rev = X[:, 5]
    result = {}
    for name, oc, ec in (("reward", 1, 2), ("lexical", 3, 4)):
        found, per_layer = [], []
        for l, A in enumerate(A_id):
            ok, beta, _ = typed(X, A, t_crit, oc, ec)
            per_layer.append(int(ok.sum()))
            found += [(l, int(j), float(np.sign(beta[oc, j]))) for j in np.where(ok)[0]]
        null = []
        strata = {}
        for k in range(len(ti)):
            strata.setdefault((X[k, oc], rev[k]), []).append(k)
        for _ in range(perms):
            Xp = X.copy()
            col = Xp[:, ec].copy()
            for ks in strata.values():
                col[ks] = rng.permutation(col[ks])
            Xp[:, ec] = col
            null.append(sum(int(typed(Xp, A, t_crit, oc, ec)[0].sum()) for A in A_id))
        q99 = float(np.quantile(null, 0.99))
        kept = 0
        for l, j, s in found:
            beta, t = tstats(Xt, np.asarray(neurons[idx["test"], l, j], np.float32)[:, None])
            kept += int(np.sign(beta[oc, 0]) == s and np.sign(beta[ec, 0]) == -s and abs(t[ec, 0]) > t01)
        ok = len(found) > q99 and len(found) > 0 and kept >= 0.5 * len(found)
        result[name] = {"count": len(found), "null_q99": q99, "null_mean": float(np.mean(null)), "replicated": kept, "pass": bool(ok), "per_layer": per_layer}
    report["H5b"] = {"t_crit": t_crit, **result}
    lines += ["## H5b：新資料的全面掃描（獎勵項與字面項放在同一個模型）", "", f"Bonferroni |t| > {t_crit:.2f}（{M} 個神經元）；零分佈 {perms} 次。", "",
              "| 類型 | 數量 | 零分佈平均 | 99 百分位 | 測試集重現 | 成立 |", "|---|---|---|---|---|---|"]
    for name, label in (("reward", "獎勵預測誤差（r、V）"), ("lexical", "字面預測誤差（中、H）")):
        r_ = result[name]
        lines.append(f"| {label} | {r_['count']} | {r_['null_mean']:.1f} | {r_['null_q99']:.0f} | {r_['replicated']}/{r_['count']} | {'是' if r_['pass'] else '否'} |")
    lines += ["", "| 層 | " + " | ".join(str(l) for l in range(0, L, 4)) + " |", "|---|" + "---|" * len(range(0, L, 4)),
              "| 獎勵 | " + " | ".join(str(result["reward"]["per_layer"][l]) for l in range(0, L, 4)) + " |",
              "| 字面 | " + " | ".join(str(result["lexical"]["per_layer"][l]) for l in range(0, L, 4)) + " |", ""]

    # ── H5c: H2's summary-format neurons on the reversed trials ──
    h2_trials = [json.loads(l) for l in open(os.path.join(h2_out, "trials.jsonl"), encoding="utf-8")]
    h2_neurons = np.load(os.path.join(h2_acts, "neurons_post.npy"), mmap_mode="r")
    ii = [i for i, t in enumerate(h2_trials) if t["split"] == "ident" and t["format"] == "summary"]
    Xh = h2_design([h2_trials[i] for i in ii])
    Xh = Xh[:, [c for c in range(Xh.shape[1]) if c == 0 or Xh[:, c].std() > 0]]
    th = float(stats.t.ppf(1 - 0.05 / M / 2, len(ii) - Xh.shape[1]))
    h2_found = []
    for l in range(L):
        p, n_, _, _, beta, _ = pe_neurons(Xh, np.asarray(h2_neurons[ii, l], np.float32), th)
        h2_found += [(l, int(j), float(np.sign(beta[1, j]))) for j in np.where(p | n_)[0]]
    rv = [i for i, t in enumerate(trials) if t["kind"] == "reversed"]
    tr = [trials[i] for i in rv]
    frames = sorted({t["frame"] for t in tr})
    Xr = np.stack([np.ones(len(tr)), [t["hit"] for t in tr], [t["H"] for t in tr]] + [[t["frame"] == f for t in tr] for f in frames[1:]] + [[t["n"] - 8 for t in tr]], 1).astype(float)
    t01r = float(stats.t.ppf(1 - 0.005, len(tr) - Xr.shape[1]))
    lexical = reward = 0
    for l, j, s in h2_found:
        beta, t = tstats(Xr, np.asarray(neurons[rv, l, j], np.float32)[:, None])
        if abs(t[2, 0]) > t01r:
            if np.sign(beta[1, 0]) == s and np.sign(beta[2, 0]) == -s:
                lexical += 1
            elif np.sign(beta[1, 0]) == -s and np.sign(beta[2, 0]) == s:
                reward += 1
    report["H5c"] = {"h2_summary_neurons": len(h2_found), "follow_words": lexical, "follow_reward": reward}
    lines += ["## H5c：H2 摘要格式的神經元，在反轉題裡", "", f"H2 摘要格式神經元 {len(h2_found)} 個；反轉題 {len(rv)} 題。", "",
              f"- 跟著字面走（符號不變、H 項 p < 0.01）：{lexical}（{lexical / max(len(h2_found), 1):.0%}）",
              f"- 跟著獎勵走（符號反過來、H 項 p < 0.01）：{reward}（{reward / max(len(h2_found), 1):.0%}）",
              "- 機率水準每類約 0.5%。"]
    json.dump(report, open(os.path.join(out, "results.json"), "w"), ensure_ascii=False, indent=1, default=float)
    open(os.path.join(out, "results.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["make", "extract", "analyze"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--acts", required=True)
    ap.add_argument("--h2", default=None, help="H2's data folder (trials.jsonl)")
    ap.add_argument("--h2-acts", default=None)
    ap.add_argument("--model", default="mlx-community/Qwen3.5-4B-MLX-4bit")
    ap.add_argument("--perms", type=int, default=1000)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "trials.jsonl")
    if a.stage == "make":
        trials = []
        for k, (split, (n, frames, names)) in enumerate(SPLITS.items()):
            trials += make_trials(split, n, frames, names, seed=200 + k)
        with open(path, "w", encoding="utf-8") as f:
            for t in trials:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        print(f"{len(trials)} trials → {path}", file=sys.stderr)
        return
    trials = [json.loads(l) for l in open(path, encoding="utf-8")]
    if a.stage == "extract":
        extract_acts(trials, a.acts, a.model)
        np.save(os.path.join(a.acts, "check.npy"), check(trials, a.model))
    else:
        analyze(trials, a.acts, a.out, a.h2, a.h2_acts, a.perms)


if __name__ == "__main__":
    main()
