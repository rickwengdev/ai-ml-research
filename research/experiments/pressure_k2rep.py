#!/usr/bin/env python3
"""The K2 replication on 27B with new seeds (research/prereg/prereg-pressure-27b-k2-replication.md).

The directions are the original step-0 run's, fixed: for task t, the leave-t-out direction fitted on the original F
and clean S trajectories, exactly as pressure.analyze fits it. Each replication folder (pressure.py run --k2-only
--seed-tag repN) gives, per task, k2 = band mean of (state(I, k=3) − state(F, k=3)) · u_t.

  python pressure_k2rep.py --orig research/data/2026-11-01-pressure-27b \
      --reps research/data/<date>-pressure-27b-k2rep1,... --out research/data/<date>-pressure-27b-k2rep

Writes <out>/results.json and results.md: the replication's K2 (the primary result), the original and the
replications pooled, each seed alone, and the action after the inserted success.
"""
import argparse, json, os, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pressure import INSERT_AT, TASKS, ci, load_states, model_label  # noqa: E402

NINE_B = -2.75  # 9B step 0 (MLX 4-bit, 2026-10-31): K2 −2.75 [−3.66, −1.88], 12 tasks


def directions(orig):
    """{task: leave-task-out unit direction (L, hidden)} and the band, as pressure.analyze computes them."""
    rows = [json.loads(l) for l in open(os.path.join(orig, "gens.jsonl"), encoding="utf-8")]
    states = {k: v.astype(np.float32) for k, v in load_states(orig).items()}
    L = next(iter(states.values())).shape[0]
    band = slice(int(L * 0.3), int(L * 0.8))
    tasks = sorted({r["task"] for r in rows}, key=lambda t: [x["fn"] for x in TASKS].index(t))

    def traj(cond, task):
        ks = sorted(int(k.split("|")[2]) for k in states if k.startswith(f"{cond}|{task}|"))
        return {k: states[f"{cond}|{task}|{k}"] for k in ks}

    F = {t: traj("F", t) for t in tasks}
    S = {t: traj("S", t) for t in tasks}
    s_clean = {t for t in tasks if not any(r.get("s_failed") for r in rows if r["task"] == t and r["cond"] == "S")}
    norm = lambda d: d / (np.linalg.norm(d, axis=-1, keepdims=True) + 1e-8)

    def endpoint(tr):
        ks = sorted(tr)
        return tr[min(5, ks[-1])] - tr[0]

    def direction(exclude):
        f = [endpoint(F[t]) for t in tasks if t != exclude and len(F[t]) >= 2]
        s = [endpoint(S[t]) for t in s_clean if t != exclude and len(S[t]) >= 2]
        return norm(np.mean(f, axis=0) - np.mean(s, axis=0))

    return {t: direction(t) for t in tasks}, band, states


def k2_of(states, units, band):
    """{task: k2} for the tasks whose F reached the k = 3 prompt and have an I branch."""
    out = {}
    for t, u in units.items():
        f, i = states.get(f"F|{t}|{INSERT_AT}"), states.get(f"I|{t}|{INSERT_AT}")
        if f is not None and i is not None:
            out[t] = float((((i.astype(np.float32) - f.astype(np.float32)) * u).sum(-1))[band].mean())
    return out


def per_task_mean(runs):
    """Average each task over the runs that have it; the list the bootstrap resamples by task."""
    tasks = sorted({t for r in runs for t in r})
    return [float(np.mean([r[t] for r in runs if t in r])) for t in tasks]


def fmt(c):
    return f"{c[0]:+.2f} [{c[1]:+.2f}, {c[2]:+.2f}]"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--orig", required=True)
    ap.add_argument("--reps", required=True, help="comma-separated replication folders")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    reps = [d for d in args.reps.split(",") if d]
    units, band, orig_states = directions(args.orig)
    original = k2_of(orig_states, units, band)
    seeds = {os.path.basename(d.rstrip("/")): k2_of({k: v for k, v in load_states(d).items()}, units, band) for d in reps}
    rep_ci = ci(per_task_mean(list(seeds.values())))
    pooled_ci = ci(per_task_mean([original] + list(seeds.values())))
    holds = rep_ci[0] < 0 and rep_ci[2] < 0
    actions = {}
    for d in reps:
        path = os.path.join(d, "gens.jsonl")
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                r = json.loads(line)
                if r["cond"] == "I":
                    actions[r["action"]] = actions.get(r["action"], 0) + 1
    res = {"replication": {"k2": rep_ci, "n_tasks": len(per_task_mean(list(seeds.values()))), "pairs": sum(len(s) for s in seeds.values()), "holds": bool(holds)},
           "pooled": {"k2": pooled_ci, "n_tasks": len(per_task_mean([original] + list(seeds.values())))},
           "original": {"k2": ci(list(original.values())), "n_tasks": len(original)},
           "per_seed": {name: {"k2": ci(list(s.values())), "n_tasks": len(s), "tasks": s} for name, s in seeds.items()},
           "I_next_action": actions, "band": [band.start, band.stop]}
    os.makedirs(args.out, exist_ok=True)
    json.dump(res, open(os.path.join(args.out, "results.json"), "w"), indent=1, ensure_ascii=False)
    md = [f"# 27B 的 K2 重做（{model_label(reps[0]) if reps else '—'}）", "",
          "登記：`prereg-pressure-27b-k2-replication.md`。方向固定用原次步驟 0 的留一題交叉擬合；k2 = band 平均[(狀態(I, k=3) − 狀態(F, k=3)) · u]。以題重抽 2,000 次。原判定（K2 不成立、27B 為探索性）不因這裡的結果改變。", "",
          "| | K2 | 題數 |", "|---|---|---|",
          f"| **重做（主要）**，{len(seeds)} 個種子、每題先平均 | **{fmt(rep_ci)}** → {'成立' if holds else '不成立'} | {res['replication']['n_tasks']}（{res['replication']['pairs']} 對） |",
          f"| 原次（1 個種子） | {fmt(res['original']['k2'])} | {len(original)} |",
          f"| 原次 + 重做合併 | {fmt(pooled_ci)} | {res['pooled']['n_tasks']} |"]
    md += [f"| {name} | {fmt(v['k2'])} | {v['n_tasks']} |" for name, v in res["per_seed"].items()]
    md += [f"| 9B（MLX 4-bit，10-31，對照） | {NINE_B:+.2f} [−3.66, −1.88] | 12 |", "",
           "插入成功後的下一個動作（重做的 I 分支）：" + (", ".join(f"{a} {n}" for a, n in sorted(actions.items(), key=lambda x: -x[1])) or "—")]
    open(os.path.join(args.out, "results.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
