#!/usr/bin/env python3
"""The benchmark table (bench.sh): per run its wall time, tokens generated per second, how the time split between
reading prompts and decoding, and how much of the prompts came from the prompt store; against the first run, how
many rows (same task, condition, step and seed) produced the same reply and how close their probe states are.

  python bench_report.py <bench dir> <model> A B C D
"""
import json, os, sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "experiments"))
from pressure import load_states  # noqa: E402


def rows_of(d):
    path = os.path.join(d, "gens.jsonl")
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            out[(r["task"], r["cond"], r["k"])] = r
    return out


def main():
    root, model, labels = sys.argv[1], sys.argv[2], sys.argv[3:]
    print(f"# 引擎效能測試：{model}\n")
    print("| 組 | 結束 | 秒 | 生成 token | tok/s | 讀提示 s | 解碼 s | 提示從存放區取 | 列數 | 與 A 同回覆 | 狀態 cos（最小／中位） |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    base_rows, base_states = rows_of(os.path.join(root, labels[0])), load_states(os.path.join(root, labels[0]))
    for label in labels:
        d = os.path.join(root, label)
        try:
            code, secs = open(d + ".exit").read().split()
            secs = float(secs)
        except (OSError, ValueError):
            code, secs = "—", float("nan")
        try:
            m = json.load(open(d + ".metrics.json"))
        except (OSError, json.JSONDecodeError):
            m = {}
        rows, states = rows_of(d), load_states(d) if os.path.isdir(d) else {}
        both = [k for k in rows if k in base_rows]
        same = sum((rows[k].get("reasoning"), rows[k].get("content"), rows[k].get("code")) == (base_rows[k].get("reasoning"), base_rows[k].get("content"), base_rows[k].get("code")) for k in both)
        cos = []
        for key in states.keys() & base_states.keys():
            a, b = states[key].astype(np.float32), base_states[key].astype(np.float32)
            num = (a * b).sum(-1)
            den = np.linalg.norm(a, axis=-1) * np.linalg.norm(b, axis=-1) + 1e-12
            cos.append(float((num / den).min()))
        prompt_total = max(1, m.get("prefilled", 0) + m.get("reused", 0))
        print(f"| {label} | {code} | {secs:.0f} | {m.get('generated', 0)} | {m.get('generated', 0) / secs if secs == secs and secs > 0 else 0:.0f} | {m.get('prefill_s', 0):.0f} | {m.get('decode_s', 0):.0f} | "
              f"{m.get('reused', 0) / prompt_total:.0%} | {len(rows)} | {same}/{len(both)} | "
              + (f"{min(cos):.5f}／{float(np.median(cos)):.5f}（{len(cos)}）" if cos else "—") + " |")
    print("\n逐列的回覆在 bf16 下會因批次組成不同而分岔（同一列在不同批次裡的數值不完全相同），所以「同回覆」只看早期的步驟有沒有大量一致；狀態 cos 是同一份提示讀出的探針狀態，應接近 1。")


if __name__ == "__main__":
    main()
