#!/usr/bin/env python3
"""The step-0 pilot's pass rule for a new model (prereg-pressure-models.md). Per F trajectory (a task in one pilot
run), the model must call the tool with parsable code at k = 0 and keep calling it for at least three steps (it treats
the task as an agent loop, and its replies parse), and no reply may be cut off inside an unclosed tool call. The pilot
passes when enough trajectories meet that and none is cut off: 1 of 1 for the first pilot; since the 2026-11-01
revision, 60% of 12 tasks x 3 seeds (one --k2-only run per seed). Exit 0 when the pilot passes; prints what it saw.

usage: pilot_check.py <pilot folder> [<pilot folder> ...] [--need N | --need-frac F]"""
import argparse, json, math, os, sys

ap = argparse.ArgumentParser()
ap.add_argument("folders", nargs="+")
ap.add_argument("--need", type=int, default=None, help="trajectories that must pass (default: all of them)")
ap.add_argument("--need-frac", type=float, default=None, help="share of the trajectories that must pass")
args = ap.parse_args()
good = total = 0
any_cut = False
for folder in args.folders:
    rows = [json.loads(line) for line in open(os.path.join(folder, "gens.jsonl"), encoding="utf-8")]
    for task in dict.fromkeys(r["task"] for r in rows):
        f = sorted((r for r in rows if r["cond"] == "F" and r["task"] == task), key=lambda r: r["k"])
        if not f:
            continue
        calls = [r["k"] for r in f if r["has_call"] and r["code"] is not None]
        cut = [r["k"] for r in f if r["finish"] == "length" and not r["has_call"]]
        ok = 0 in calls and len(calls) >= 3 and not cut
        good, total, any_cut = good + ok, total + 1, any_cut or bool(cut)
        print(f"{os.path.basename(folder.rstrip('/'))} {task}: F steps {[r['k'] for r in f]}; parsed calls at {calls}; cut off at {cut}; "
              f"actions {[r['action'] for r in f]} -> {'ok' if ok else 'no'}")
need = args.need if args.need is not None else (math.ceil(args.need_frac * total) if args.need_frac is not None else total)
passed = total > 0 and good >= need and not any_cut
print(f"pilot: {total} F trajectories in {len(args.folders)} run(s); {good} meet the rule, {need} needed; cut off: {any_cut} -> {'pass' if passed else 'FAIL'}")
sys.exit(0 if passed else 1)
