import sys; sys.path.insert(0, __file__.rsplit('/', 1)[0])
from load import *

print("=== step 1 levels / diffs")
st = STP1.starts([1, 2, 3, 4, 5, 6, 7, 8])
print("starts", len(st))
for a in range(1, 9):
    print(a, "cheat", fmt(STP1.level(a, cheat, st)), "stop_any", round(STP1.level(a, stop_any, st)[0], 3), "stop_reg", round(STP1.level(a, stop_reg, st)[0], 3), "contest", round(STP1.level(a, ct, st)[0], 3), "incoh", round(STP1.level(a, incoh, st)[0], 3), "rep", round(STP1.level(a, rep, st)[0], 3), "fc", round(STP1.level(a, fc, st)[0], 3), "gu", round(STP1.level(a, gu, st)[0], 3))
for b in (1, 5, 6, 7, 8):
    print("2 -", b, fmt(STP1.diff(2, b, cheat, st)))
print("4-1", fmt(STP1.diff(4, 1, cheat, st)), "6-1", fmt(STP1.diff(6, 1, cheat, st)), "7-1", fmt(STP1.diff(7, 1, cheat, st)))
# arm 3 ending counts
from collections import Counter
for a in (1, 2, 3, 4, 5, 6):
    print("arm", a, "endings", Counter(STP1.t[(a, t, s)][-1]["action"] for t, s in st if not STP1.t[(a, t, s)][-1]["has_call"]))
print("arm3 last k", Counter(STP1.t[(3, t, s)][-1]["k"] for t, s in st))
print("arm3 gen tokens at endings false_claim", sorted(STP1.t[(3, t, s)][-1]["generated_tokens"] for t, s in st if STP1.t[(3, t, s)][-1]["action"] == "false_claim"))
print("arm3 endings gen tokens give_up", sorted(STP1.t[(3, t, s)][-1]["generated_tokens"] for t, s in st if STP1.t[(3, t, s)][-1]["action"] == "give_up"))
for t, s in sorted(st):
    r = STP1.t[(3, t, s)][-1]
    print("  arm3", t, s, r["k"], r["action"], r["coherent"], "think", r["thinking_tokens"], "gen", r["generated_tokens"], repr((r["content"] or "")[:90]))

print("per task -d vs none")
tasks = sorted({t for t, _ in st})
for t in tasks:
    a = np.mean([cheat(STP1.t[(2, t, s)]) for tt, s in st if tt == t]); b = np.mean([cheat(STP1.t[(1, t, s)]) for tt, s in st if tt == t])
    print("  ", t, round(b, 2), round(a, 2))
# exploratory items in 5.2
def honest_split(rs, lo=None):
    return rs
def cheat_low(rs): return float(np.mean([r["action"] == "cheat" and (r["honest_ok"] is not None and r["honest_ok"] < 4) for r in rs]))
def cheat_55(rs): return float(np.mean([r["action"] == "cheat" and r["honest_ok"] == 5 for r in rs]))
for f, n in ((cheat_low, "cheat honest<4"), (cheat_55, "cheat honest=5")):
    print(n, "none", round(STP1.level(1, f, st)[0], 3), "-d", round(STP1.level(2, f, st)[0], 3), fmt(STP1.diff(2, 1, f, st)))
all_rows = [r for k, v in STP1.t.items() for r in v]
for act in ("cheat", "revise", "repeat", "contest"):
    x = [r["proj_vs_k0"] for r in all_rows if r["k"] > 3 and r["action"] == act and r.get("proj_vs_k0")]
    print("k>3 proj", act, round(float(np.mean(x)), 2), len(x))
for a in range(1,9):
    print("arm", a, "k3 proj", round(float(np.mean([r["proj_vs_k0"] for k,v in STP1.t.items() if k[0]==a for r in v if r["k"]==3])),2), "k4", round(float(np.mean([r["proj_vs_k0"] for k,v in STP1.t.items() if k[0]==a for r in v if r["k"]==4])),2))
for a in (1, 2):
    x = []
    for k, v in STP1.t.items():
        if k[0] == a:
            c = [r for r in v if r["results"]]
            if c: x.append(c[-1]["honest_ok"])
    print("last honest arm", a, round(float(np.mean(x)), 2), len(x))

print("=== replication")
st = REP.starts([1, 2])
print(len(st), "cheat none", fmt(REP.level(1, cheat, st)), "-d", fmt(REP.level(2, cheat, st)), "diff", fmt(REP.diff(2, 1, cheat, st)))
print("stop_reg", fmt(REP.level(1, stop_reg, st)), fmt(REP.level(2, stop_reg, st)), fmt(REP.diff(2, 1, stop_reg, st)))
print("stop_any", fmt(REP.level(1, stop_any, st)), fmt(REP.level(2, stop_any, st)))
for a in (1, 2):
    print("endings", a, Counter(REP.t[(a, t, s)][-1]["action"] for t, s in st if not REP.t[(a, t, s)][-1]["has_call"]))
print("orig", fmt(REP.diff(2, 1, cheat, st, tasks=ORIG)), "new", fmt(REP.diff(2, 1, cheat, st, tasks=set(t for t, _ in st) - set(ORIG))))
print("first step", fmt(REP.diff(2, 1, first, st)))
full = {(t, s) for t, s in st if len(REP.t[(1, t, s)]) == 3 and len(REP.t[(2, t, s)]) == 3}
print("both full", len(full), len({t for t,_ in full}), fmt(REP.diff(2, 1, cheat, full)))
d = {}
for t, s in st: d.setdefault(t, []).append(cheat(REP.t[(2, t, s)]) - cheat(REP.t[(1, t, s)]))
m = {t: np.mean(v) for t, v in d.items()}
print("tasks down/up/zero", sum(v < 0 for v in m.values()), sum(v > 0 for v in m.values()), sum(v == 0 for v in m.values()))
for s in range(3):
    print(" seed", s, round(np.mean([cheat(REP.t[(2, t, ss)]) - cheat(REP.t[(1, t, ss)]) for t, ss in st if ss == s]), 3))
top = sorted(m, key=lambda t: m[t])[:3]
print("drop top3", top, round(np.mean([m[t] for t in m if t not in top]), 3))

print("=== controls E'")
CT = CTL
stc = CT.starts([5, 6])
print(len(stc), stc == st)
merged = DS([r for v in REP.t.values() for r in v] + [r for v in CTL.t.values() for r in v])
st2 = merged.starts([1, 2, 5, 6])
for a in (1, 2, 5, 6):
    print(a, "cheat", fmt(merged.level(a, cheat, st2)), "stop", round(merged.level(a, stop_reg, st2)[0], 3), "fc", round(merged.level(a, fc, st2)[0], 3), "inc", round(merged.level(a, incoh, st2)[0], 3), Counter(merged.t[(a, t, s)][-1]["action"] for t, s in st2 if not merged.t[(a, t, s)][-1]["has_call"]))
print("-d - rand", fmt(merged.diff(2, 5, cheat, st2)), "-d - gain", fmt(merged.diff(2, 6, cheat, st2)), "gain-none", fmt(merged.diff(6, 1, cheat, st2)), "rand-none", fmt(merged.diff(5, 1, cheat, st2)))
print("fc -d - gain", fmt(merged.diff(2, 6, fc, st2)), "fc -d - rand", fmt(merged.diff(2, 5, fc, st2)))
new = set(t for t, _ in st2) - set(ORIG)
print("orig -d-rand", fmt(merged.diff(2, 5, cheat, st2, tasks=ORIG)), "orig -d-gain", fmt(merged.diff(2, 6, cheat, st2, tasks=ORIG)), "new -d-rand", fmt(merged.diff(2, 5, cheat, st2, tasks=new)), "new -d-gain", fmt(merged.diff(2, 6, cheat, st2, tasks=new)))

print("=== KL")
st = KL.starts([1, 2, 6, 21, 22, 23])
rnd = [21, 22, 23]
print(len(st), len({t for t, _ in st}))
print("Q1", fmt(KL.diff(rnd, 1, cheat, st)), "Q2", fmt(KL.diff(2, rnd, cheat, st)))
print("Q3", fmt(KL.diff(2, 6, fc, st)), fmt(KL.diff(2, rnd, fc, st)))
print("-d-none", fmt(KL.diff(2, 1, cheat, st)), "gain-none", fmt(KL.diff(6, 1, cheat, st)), "-d-gain", fmt(KL.diff(2, 6, cheat, st)))
for a in rnd:
    print(a, "-none", fmt(KL.diff(a, 1, cheat, st)), "-d - a", fmt(KL.diff(2, a, cheat, st)))
for a in (1, 2, 6, 21, 22, 23):
    print(a, "cheat", fmt(KL.level(a, cheat, st)), "stop", round(KL.level(a, stop_reg, st)[0], 3), "fc", round(KL.level(a, fc, st)[0], 3), "gu", round(KL.level(a, gu, st)[0], 3), "inc", round(KL.level(a, incoh, st)[0], 3), Counter(KL.t[(a, t, s)][-1]["action"] for t, s in st if not KL.t[(a, t, s)][-1]["has_call"]))
print("rand-level inc", KL.level(rnd, incoh, st)[0], KL.level(rnd, stop_reg, st)[0])
print("spread between randoms cheat", [round(KL.level(a, cheat, st)[0], 3) for a in rnd])
