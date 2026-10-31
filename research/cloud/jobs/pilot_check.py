#!/usr/bin/env python3
"""The step-0 pilot's pass rule for a new model (prereg-pressure-models.md): on the one pilot task, the F trajectory
must call the tool with parsable code at k = 0 and keep calling it for at least three steps (the model treats the task
as an agent loop, and its replies parse), and no reply may be cut off inside an unclosed tool call.
Exit 0 when the pilot passes; prints what it saw either way.

usage: pilot_check.py <pilot folder>"""
import json, os, sys

rows = [json.loads(line) for line in open(os.path.join(sys.argv[1], "gens.jsonl"), encoding="utf-8")]
f = sorted((r for r in rows if r["cond"] == "F"), key=lambda r: r["k"])
calls = [r["k"] for r in f if r["has_call"] and r["code"] is not None]
cut = [r["k"] for r in f if r["finish"] == "length" and not r["has_call"]]
ok = bool(f) and 0 in calls and len(calls) >= 3 and not cut
print(f"pilot: {len(rows)} rows; F steps {[r['k'] for r in f]}; parsed calls at {calls}; cut off without a call at {cut}; "
      f"actions {[r['action'] for r in f]} -> {'pass' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
