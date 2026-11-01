#!/usr/bin/env python3
"""The step-0 pilot's pass rule for a new model (prereg-pressure-models.md). Per task, the F trajectory must call the
tool with parsable code at k = 0 and keep calling it for at least three steps (the model treats the task as an agent
loop, and its replies parse), and no reply may be cut off inside an unclosed tool call. The pilot passes when at
least --need tasks meet that and none is cut off: 1 of 1 for the first pilot, 3 of 5 since the 2026-11-01 revision
(see the registration's modification log). Exit 0 when the pilot passes; prints what it saw either way.

usage: pilot_check.py <pilot folder> [--need N]"""
import argparse, json, os, sys

ap = argparse.ArgumentParser()
ap.add_argument("folder")
ap.add_argument("--need", type=int, default=None, help="tasks that must pass (default: all of them)")
args = ap.parse_args()
rows = [json.loads(line) for line in open(os.path.join(args.folder, "gens.jsonl"), encoding="utf-8")]
tasks = list(dict.fromkeys(r["task"] for r in rows))
good, any_cut = 0, False
for task in tasks:
    f = sorted((r for r in rows if r["cond"] == "F" and r["task"] == task), key=lambda r: r["k"])
    calls = [r["k"] for r in f if r["has_call"] and r["code"] is not None]
    cut = [r["k"] for r in f if r["finish"] == "length" and not r["has_call"]]
    ok = bool(f) and 0 in calls and len(calls) >= 3 and not cut
    good += ok
    any_cut |= bool(cut)
    print(f"{task}: F steps {[r['k'] for r in f]}; parsed calls at {calls}; cut off without a call at {cut}; "
          f"actions {[r['action'] for r in f]} -> {'ok' if ok else 'no'}")
need = args.need if args.need is not None else len(tasks)
passed = bool(tasks) and good >= need and not any_cut
print(f"pilot: {len(rows)} rows, {len(tasks)} task(s); {good} meet the rule, {need} needed; cut off: {any_cut} -> {'pass' if passed else 'FAIL'}")
sys.exit(0 if passed else 1)
