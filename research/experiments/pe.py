#!/usr/bin/env python3
"""The candidate prediction-error signal (docs/research/prereg-prediction-error.md; math-endogenous.md §2).

A text bandit: a machine's past record (listed trial by trial, or summarised), then "this time you chose it again,
the result: {win / loss}。". The expectation V^exp = (1 + wins) / (2 + n) is fixed by the record; the outcome r is
drawn independently. Read at the period after the outcome (the same token in every condition) and, for the
expectation, at the colon before it.

  make      the trials: identification 600 and validation 200 (frames slot and shoot), test 300 (frame lottery, new
            names). Balanced: r independent of V, both halves of every V bin, formats, synonyms, names, n.
  extract   per trial: the residual after every layer at the colon and at the period; every MLP neuron (the input to
            down_proj) of every layer at the period; and V^mod, the model's own probability of a win word at the colon.
  analyze   H1: V^exp decoded from the residual at the colon (ridge, identification → validation, permutation null).
            H2: per neuron at the period, a = β_r r + β_V V + covariates; prediction-error neurons (β_r > 0, β_V < 0,
            Bonferroni, |β_V|/β_r in [1/3, 3]) counted against V shuffled within r × frame; replication on the test set.
            H3: H2 with V^mod. Also the residual δ probe (a tool for the causal stage, not evidence: δ = r − V is a
            linear combination, so it decodes whenever r and V do).

usage: pe.py make|extract|analyze --out docs/research/data/<date>-pe [--acts <dir for activations>]
"""
import argparse, json, os, random, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

WIN = ("贏了", "中了", "得分")
LOSE = ("輸了", "沒中", "落空")
FRAMES = {
    "slot": ("吃角子老虎機「{name}」", "這次你又拉了「{name}」，結果："),
    "shoot": ("投籃機「{name}」", "這次你又在「{name}」投了一球，結果："),
    "lottery": ("抽獎箱「{name}」", "這次你又從「{name}」抽了一次，結果："),
}
NAMES = ["金星", "海浪", "北極", "紅寶石", "老虎", "櫻花", "火箭", "銀河", "竹林", "雷霆", "白鷺", "鳳凰", "珊瑚", "麒麟", "流星", "琥珀"]
NEW_NAMES = ["燈塔", "青蛙", "冰山", "玫瑰", "獵戶", "松果", "颱風", "翡翠"]
SPLITS = {"ident": (600, ("slot", "shoot"), NAMES), "valid": (200, ("slot", "shoot"), NAMES), "test": (300, ("lottery",), NEW_NAMES)}
SYSTEM = "你是一個助手。"


def make_trials(split, n_trials, frames, names, seed):
    rng = random.Random(seed)
    trials = []
    for i in range(n_trials):
        # V uniform over its range. r is a fair coin per trial ((i % 2) or its flip, each with p = 0.5): it is not
        # alternated within pairs, so the outcome balance per V bin is only balanced in expectation.
        n = rng.randint(4, 12)
        target = rng.uniform(0.08, 0.92)
        wins = min(n, max(0, round(target * (n + 2) - 1)))
        v = (1 + wins) / (2 + n)
        r = (i % 2) if rng.random() < 0.5 else 1 - (i % 2)
        frame, name, fmt = rng.choice(frames), rng.choice(names), rng.choice(("list", "summary"))
        word = rng.choice(WIN if r else LOSE)
        intro, ask = FRAMES[frame]
        if fmt == "list":
            seq = [1] * wins + [0] * (n - wins)
            rng.shuffle(seq)
            record = "\n".join(f"第{k + 1}次：{rng.choice(WIN if s else LOSE)}" for k, s in enumerate(seq))
            history = f"{intro.format(name=name)}的紀錄：\n{record}"
        else:
            history = f"{intro.format(name=name)}：過去{n}次裡，{wins}次{rng.choice(WIN)}，{n - wins}次{rng.choice(LOSE)}。"
        text = f"{history}\n\n{ask.format(name=name)}{word}。"
        trials.append({"id": f"{split}-{i}", "split": split, "frame": frame, "format": fmt, "name": name, "n": n, "wins": wins, "v": v, "r": r, "word": word, "delta": r - v, "text": text})
    return trials


class NeuronTap:
    """Wraps a layer's down_proj to keep its input (the MLP's hidden units) for one position."""

    def __init__(self, inner):
        self.inner, self.position, self.kept = inner, None, None

    def __call__(self, x):
        if self.position is not None:
            self.kept = x[0, self.position, :]
        return self.inner(x)


def extract(trials, acts_dir, model_id):
    import mlx.core as mx
    from mlx_lm import load
    from steer import Steering

    model, tok = load(model_id)
    steering = Steering()
    steering.attach(model)
    layers = steering.layers
    taps = []
    for layer in layers:
        tap = NeuronTap(layer.mlp.down_proj)
        layer.mlp.down_proj = tap
        taps.append(tap)
    first = lambda w: tok.encode(f"結果：{w}")[2]
    win_ids, lose_ids = [first(w) for w in WIN], [first(w) for w in LOSE]
    colon_id = tok.encode("結果：")[1]
    n, L = len(trials), len(layers)
    resid_pre = resid_post = neurons = None
    vmod = np.zeros(n, np.float32)
    for i, t in enumerate(trials):
        prompt = tok.apply_chat_template([{"role": "system", "content": SYSTEM}, {"role": "user", "content": t["text"]}], add_generation_prompt=True, tokenize=True, enable_thinking=False)
        ids = list(prompt)
        pre = max(k for k in range(len(ids) - 1) if ids[k] == colon_id)
        post = next(k for k in range(pre + 1, len(ids)) if tok.decode([ids[k]]) == "。")
        for tap in taps:
            tap.position = post
        steering.capture = {}
        logits = model(mx.array(ids)[None])
        probs = mx.softmax(logits[0, pre].astype(mx.float32))
        mx.eval(probs, *[tap.kept for tap in taps], *[a[0] for a in steering.capture.values()])
        p = np.array(probs)
        vmod[i] = p[win_ids].sum() / max(p[win_ids].sum() + p[lose_ids].sum(), 1e-12)
        if resid_pre is None:
            hidden = steering.capture[0][0].shape[-1]
            resid_pre, resid_post = np.zeros((n, L, hidden), np.float16), np.zeros((n, L, hidden), np.float16)
        for l in sorted(steering.capture):
            h = np.array(steering.capture[l][0][0].astype(mx.float32))
            resid_pre[i, l], resid_post[i, l] = h[pre], h[post]
        if neurons is None:
            neurons = np.zeros((n, L, taps[0].kept.shape[-1]), np.float16)
        neurons[i] = np.stack([np.array(tap.kept.astype(mx.float32)) for tap in taps])
        steering.capture = None
        if i % 100 == 0:
            print(f"  {i}/{n}  V {t['v']:.2f} r {t['r']} V^mod {vmod[i]:.2f}", file=sys.stderr)
    os.makedirs(acts_dir, exist_ok=True)
    np.save(os.path.join(acts_dir, "resid_pre.npy"), resid_pre)
    np.save(os.path.join(acts_dir, "resid_post.npy"), resid_post)
    np.save(os.path.join(acts_dir, "neurons_post.npy"), neurons)
    np.save(os.path.join(acts_dir, "vmod.npy"), vmod)


# ── analysis ──────────────────────────────────────────────────────────────


def ridge_r2(Xtr, ytr, Xte, yte, lambdas=(1e-1, 1, 10, 100, 1000)):
    """Best-λ ridge on standardised features; returns (R² on the held-out set, λ, a function for permuted ys).

    λ is picked by R² on the same held-out set the R² is reported on (no inner split), so the reported R² is
    slightly optimistic; the permutation null uses the same λ, chosen on the real labels."""
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-6
    A, B = (Xtr - mu) / sd, (Xte - mu) / sd
    U, s, Vt = np.linalg.svd(A, full_matrices=False)
    ym = ytr.mean()

    def fit(y, lam):
        w = Vt.T @ ((s / (s**2 + lam)) * (U.T @ (y - y.mean())))
        return w, y.mean()

    def r2(pred, y):
        return 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()

    best = max(lambdas, key=lambda lam: r2(B @ fit(ytr, lam)[0] + ym, yte))
    w, b = fit(ytr, best)
    return r2(B @ w + b, yte), best, (lambda y: r2(B @ fit(y, best)[0] + y.mean(), yte)), w / sd


def design(trials, v_key="v"):
    """[1, r, V, covariates]: frame, format, synonym group, n (centred)."""
    frames = sorted({t["frame"] for t in trials})
    words = sorted(WIN + LOSE)
    cols = [np.ones(len(trials)), np.array([t["r"] for t in trials], float), np.array([t[v_key] for t in trials], float)]
    cols += [np.array([t["frame"] == f for t in trials], float) for f in frames[1:]]
    cols += [np.array([t["format"] == "list" for t in trials], float)]
    # Synonym within outcome: two dummies per outcome class (the class itself is r).
    for group in (WIN, LOSE):
        cols += [np.array([t["word"] == w for t in trials], float) for w in group[1:]]
    ns = np.array([t["n"] for t in trials], float)
    cols.append(ns - ns.mean())
    return np.stack(cols, 1)


def tstats(X, A):
    """OLS t-statistics of every column of X for every column of A (neurons). Returns (betas, ts): [p, M]."""
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ A
    resid = A - X @ beta
    dof = X.shape[0] - X.shape[1]
    s2 = (resid**2).sum(0) / dof
    se = np.sqrt(np.outer(np.diag(XtX_inv), s2)) + 1e-12
    return beta, beta / se


def pe_neurons(X, A, t_crit, ratio=(1 / 3, 3)):
    beta, t = tstats(X, A)
    br, bv, tr, tv = beta[1], beta[2], t[1], t[2]
    rat = np.abs(bv) / np.maximum(np.abs(br), 1e-12)
    ok_ratio = (rat >= ratio[0]) & (rat <= ratio[1])
    pos = (tr > t_crit) & (tv < -t_crit) & ok_ratio
    neg = (tr < -t_crit) & (tv > t_crit) & ok_ratio
    r_only = (np.abs(tr) > t_crit) & (np.abs(tv) < 2)
    v_only = (np.abs(tv) > t_crit) & (np.abs(tr) < 2)
    return pos, neg, r_only, v_only, beta, t


def analyze(trials, acts_dir, out, perms=1000):
    from scipy import stats

    resid_pre = np.load(os.path.join(acts_dir, "resid_pre.npy"), mmap_mode="r")
    resid_post = np.load(os.path.join(acts_dir, "resid_post.npy"), mmap_mode="r")
    neurons = np.load(os.path.join(acts_dir, "neurons_post.npy"), mmap_mode="r")
    vmod = np.load(os.path.join(acts_dir, "vmod.npy"))
    for t, vm in zip(trials, vmod):
        t["vmod"] = float(vm)
    idx = {s: np.array([i for i, t in enumerate(trials) if t["split"] == s]) for s in SPLITS}
    tr = lambda s: [trials[i] for i in idx[s]]
    L = resid_pre.shape[1]
    rng = np.random.default_rng(0)
    report = {"n": {s: int(len(v)) for s, v in idx.items()}}
    lines = ["# 候選預測誤差訊號：結果", "", f"Qwen3.5-4B；辨識 {len(idx['ident'])}、驗證 {len(idx['valid'])}、測試 {len(idx['test'])}。預先登記見 `prereg-prediction-error.md`。", ""]

    # V^mod against V^exp
    ve, vm = np.array([t["v"] for t in trials]), vmod
    rho = stats.spearmanr(ve, vm).statistic
    report["vmod_vs_vexp_spearman"] = float(rho)
    lines += [f"V^mod 與 V^exp 的 Spearman 相關：{rho:+.2f}（全部試題）。", ""]

    # ── H1 ──
    lines += ["## H1：結果前，從殘差流解碼 V^exp（ridge，辨識 → 驗證）", "", "| 層 | R²（驗證） | 置換 99 百分位 | λ |", "|---|---|---|---|"]
    yv_tr, yv_va = ve[idx["ident"]], ve[idx["valid"]]
    h1 = []
    for l in range(L):
        r2, lam, perm_fn, _ = ridge_r2(np.asarray(resid_pre[idx["ident"], l], np.float32), yv_tr, np.asarray(resid_pre[idx["valid"], l], np.float32), yv_va)
        # The full `perms` (1000) only on every fourth layer and the last; 200 elsewhere, to save time. The
        # preregistration says 1000 on every layer, so the 99th-percentile null on the other layers is coarser.
        null = [perm_fn(rng.permutation(yv_tr)) for _ in range(perms if l % 4 == 0 or l == L - 1 else 200)]
        q99 = float(np.quantile(null, 0.99))
        h1.append({"layer": l, "r2": float(r2), "null_q99": q99, "lambda": lam})
        lines.append(f"| {l} | {r2:.3f} | {q99:.3f} | {lam:g} |")
    best = max(h1, key=lambda h: h["r2"])
    h1_pass = best["r2"] >= 0.3 and best["r2"] > best["null_q99"]
    report["H1"] = {"layers": h1, "best": best, "pass": h1_pass}
    lines += ["", f"**H1 {'成立' if h1_pass else '不成立'}**：最佳層 {best['layer']}，R² {best['r2']:.3f}（門檻 0.3，置換 99 百分位 {best['null_q99']:.3f}）。", ""]

    # ── residual δ probe (a tool) ──
    yd = np.array([t["delta"] for t in trials])
    lines += ["## 殘差流的 δ 探針（工具，不是證據）", "", "| 層 | R²(δ) | R²(r) | R²(V) |", "|---|---|---|---|"]
    probe = []
    yr = np.array([t["r"] for t in trials], float)
    for l in range(L):
        Xa, Xb = np.asarray(resid_post[idx["ident"], l], np.float32), np.asarray(resid_post[idx["valid"], l], np.float32)
        rd, _, _, wd = ridge_r2(Xa, yd[idx["ident"]], Xb, yd[idx["valid"]])
        rr = ridge_r2(Xa, yr[idx["ident"]], Xb, yr[idx["valid"]])[0]
        rv = ridge_r2(Xa, ve[idx["ident"]], Xb, ve[idx["valid"]])[0]
        probe.append({"layer": l, "r2_delta": float(rd), "r2_r": float(rr), "r2_v": float(rv)})
        if l % 2 == 0 or l == L - 1:
            lines.append(f"| {l} | {rd:.3f} | {rr:.3f} | {rv:.3f} |")
        np.save(os.path.join(acts_dir, f"delta_probe_L{l}.npy"), wd.astype(np.float32))
    report["delta_probe"] = probe

    # ── H2 ──
    M = neurons.shape[1] * neurons.shape[2]
    dof = len(idx["ident"]) - design(tr("ident")).shape[1]
    t_crit = float(stats.t.ppf(1 - 0.05 / M / 2, dof))
    X = design(tr("ident"))
    strata = [(t["r"], t["frame"]) for t in tr("ident")]
    groups = {}
    for k, s in enumerate(strata):
        groups.setdefault(s, []).append(k)

    def count(Xm, layer_slices):
        pos = neg = ro = vo = 0
        for A in layer_slices:
            p, n_, r_, v_ = pe_neurons(Xm, A, t_crit)[:4]
            pos, neg, ro, vo = pos + p.sum(), neg + n_.sum(), ro + r_.sum(), vo + v_.sum()
        return int(pos), int(neg), int(ro), int(vo)

    A_ident = [np.asarray(neurons[idx["ident"], l], np.float32) for l in range(L)]
    found = {"pos": [], "neg": []}
    per_layer = []
    for l, A in enumerate(A_ident):
        p, n_, r_, v_, beta, t = pe_neurons(X, A, t_crit)
        per_layer.append({"layer": l, "pos": int(p.sum()), "neg": int(n_.sum()), "r_only": int(r_.sum()), "v_only": int(v_.sum())})
        found["pos"] += [(l, int(j), float(beta[1, j]), float(beta[2, j])) for j in np.where(p)[0]]
        found["neg"] += [(l, int(j), float(beta[1, j]), float(beta[2, j])) for j in np.where(n_)[0]]
    observed = (len(found["pos"]), len(found["neg"]))
    null = []
    for _ in range(perms):
        Xp = X.copy()
        v = Xp[:, 2].copy()
        for ks in groups.values():
            v[ks] = rng.permutation(v[ks])
        Xp[:, 2] = v
        null.append(count(Xp, A_ident)[:2])
    null = np.array(null)
    q99 = np.quantile(null, 0.99, axis=0)

    # Replication on the test set: the identified neurons, same signs, β_V at p < 0.01 uncorrected.
    Xt = design(tr("test"))
    t01 = float(stats.t.ppf(1 - 0.01 / 2, len(idx["test"]) - Xt.shape[1]))
    rep = {}
    for kind, sign in (("pos", 1), ("neg", -1)):
        kept = 0
        for l, j, _, _ in found[kind]:
            A = np.asarray(neurons[idx["test"], l, j], np.float32)[:, None]
            beta, t = tstats(Xt, A)
            kept += int(np.sign(beta[1, 0]) == sign and np.sign(beta[2, 0]) == -sign and abs(t[2, 0]) > t01)
        rep[kind] = (kept, len(found[kind]))
    h2_pass = {kind: observed[k] > q99[k] and rep[kind][1] > 0 and rep[kind][0] >= 0.5 * rep[kind][1] for k, kind in enumerate(("pos", "neg"))}
    report["H2"] = {"t_crit": t_crit, "neurons": M, "observed": observed, "null_q99": q99.tolist(), "null_mean": null.mean(0).tolist(), "replication": rep, "pass": h2_pass, "per_layer": per_layer, "found": found}
    lines += ["", "## H2：結果之後的「。」，預測誤差型神經元", "", f"神經元總數 {M}（{L} 層 × {neurons.shape[2]}）；Bonferroni 門檻 |t| > {t_crit:.2f}；零分佈為在 r × 框架層內打亂 V（{perms} 次）。", "",
              "| 類型 | 辨識集數量 | 零分佈平均 | 零分佈 99 百分位 | 測試集重現 | 成立 |", "|---|---|---|---|---|---|"]
    for k, kind in enumerate(("pos", "neg")):
        lines.append(f"| {'正向（r↑ V↓）' if kind == 'pos' else '負向（r↓ V↑）'} | {observed[k]} | {null.mean(0)[k]:.1f} | {q99[k]:.0f} | {rep[kind][0]}/{rep[kind][1]} | {'是' if h2_pass[kind] else '否'} |")
    lines += ["", "選擇性對照（辨識集）：", "", "| 層 | 正向 | 負向 | 只對 r | 只對 V |", "|---|---|---|---|---|"]
    lines += [f"| {p['layer']} | {p['pos']} | {p['neg']} | {p['r_only']} | {p['v_only']} |" for p in per_layer if p["pos"] or p["neg"] or p["layer"] % 4 == 0]

    # ── H3 (secondary): V^mod instead of V^exp, counts only ──
    Xm = design(tr("ident"), v_key="vmod")
    c3 = count(Xm, A_ident)
    report["H3"] = {"pos": c3[0], "neg": c3[1], "r_only": c3[2], "v_only": c3[3]}
    lines += ["", f"## H3（次要）：以 V^mod 取代 V^exp", "", f"正向 {c3[0]}、負向 {c3[1]}、只對 r {c3[2]}、只對 V {c3[3]}（辨識集，同門檻）。"]
    json.dump(report, open(os.path.join(out, "results.json"), "w"), ensure_ascii=False, indent=1, default=float)
    open(os.path.join(out, "results.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["make", "extract", "analyze"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--acts", default=None, help="where the activations go (large; default <out>/acts)")
    ap.add_argument("--model", default="mlx-community/Qwen3.5-4B-MLX-4bit")
    ap.add_argument("--perms", type=int, default=1000)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    acts = a.acts or os.path.join(a.out, "acts")
    path = os.path.join(a.out, "trials.jsonl")
    if a.stage == "make":
        trials = []
        for k, (split, (n, frames, names)) in enumerate(SPLITS.items()):
            trials += make_trials(split, n, frames, names, seed=100 + k)
        with open(path, "w", encoding="utf-8") as f:
            for t in trials:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        print(f"{len(trials)} trials → {path}", file=sys.stderr)
        return
    trials = [json.loads(l) for l in open(path, encoding="utf-8")]
    if a.stage == "extract":
        extract(trials, acts, a.model)
    else:
        analyze(trials, acts, a.out, a.perms)


if __name__ == "__main__":
    main()
