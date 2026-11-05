import sys; sys.path.insert(0, __file__.rsplit('/', 1)[0])
from load import *
from collections import Counter
rnd = [21, 22, 23]
stK = KL.starts([1, 2, 6, 21, 22, 23])
merged = DS([r for v in REP.t.values() for r in v] + [r for v in CTL.t.values() for r in v])
stR = merged.starts([1, 2, 5, 6])
st1 = STP1.starts([1, 2, 5, 6])

print("=== both no early end (replication)")
full = {(t, s) for t, s in stR if all(r["has_call"] for r in merged.t[(1, t, s)]) and all(r["has_call"] for r in merged.t[(2, t, s)])}
print(len(full), len({t for t, _ in full}), fmt(merged.diff(2, 1, cheat, full)))

print("=== sensitivity of the outcome definition, by run")
for name, ds, st, a_rand, gain in (("step1", STP1, st1, 5, 6), ("Eprime", merged, stR, 5, 6), ("KL", KL, stK, rnd, 6)):
    for fname, f in (("cheat/steps", cheat), ("cheat/3 fixed", cheat3), ("any cheat", anych), ("first step", first)):
        print(name, fname, "-d-none", fmt(ds.diff(2, 1, f, st)), "| rand-none", fmt(ds.diff(a_rand, 1, f, st)), "| gain-none", fmt(ds.diff(gain, 1, f, st)), "| -d-rand", fmt(ds.diff(2, a_rand, f, st)), "| -d-gain", fmt(ds.diff(2, gain, f, st)))

print("=== equivalence-style CI (90%) for Q2 & -d-gain")
print("Q2 90%", fmt(KL.diff(2, rnd, cheat, stK, level=90.0)))
print("KL -d-gain 90%", fmt(KL.diff(2, 6, cheat, stK, level=90.0)))
print("E' -d-gain 90%", fmt(merged.diff(2, 6, cheat, stR, level=90.0)))

print("=== pooled -d minus gain over three runs (task means across runs)")
def pooled(funcs):
    per = {}
    for ds, st, a, b in funcs:
        for t, s in st:
            per.setdefault(t, []).append(ds.val(a, t, s, cheat) - ds.val(b, t, s, cheat))
    return boot(per)
print("-d - gain, 3 runs start-weighted", fmt(pooled([(STP1, st1, 2, 6), (merged, stR, 2, 6), (KL, stK, 2, 6)])))
print("-d - gain, 3 runs, new starts only (E'+KL)", fmt(pooled([(merged, stR, 2, 6), (KL, stK, 2, 6)])))
print("gain - none, 3 runs", fmt(pooled([(STP1, st1, 6, 1), (merged, stR, 6, 1), (KL, stK, 6, 1)])))
print("-d - none, 3 runs", fmt(pooled([(STP1, st1, 2, 1), (merged, stR, 2, 1), (KL, stK, 2, 1)])))
print("-d - gain, step1+KL only", fmt(pooled([(STP1, st1, 2, 6), (KL, stK, 2, 6)])))

print("=== low-KL same-norm vs KL-matched, on the same 12 tasks")
s2t = {}
for r in S2rows:
    if r.get("mode", "contra") == "contra" and r.get("start") == 3 and r.get("variant") == "base":
        s2t.setdefault((r["arm"], r["task"], r["seed"]), []).append(r)
for v in s2t.values(): v.sort(key=lambda r: r["k"])
print("step2 arms", sorted({a for a, _, _ in s2t}), Counter(r.get("source") for r in S2rows))
E = DS([r for v in s2t.values() for r in v], repkey="seed")
stE = E.starts([1, 2, 5, 11, 12, 13, 14, 15])
print("E starts", len(stE))
for a in (1, 2, 5, 11, 12, 13, 14, 15):
    x = E.level(a, cheat, stE)
    print(a, fmt(x), "- none", fmt(E.diff(a, 1, cheat, stE)), "-d - a", fmt(E.diff(2, a, cheat, stE)), "inc", round(E.level(a, incoh, stE)[0], 3), "stop", round(E.level(a, stop_reg, stE)[0], 3))
R5 = [5, 11, 12, 13, 14]
print("mean5 - none", fmt(E.diff(R5, 1, cheat, stE)), " -d - mean5", fmt(E.diff(2, R5, cheat, stE)))
print("mean of 4 new randoms - none", fmt(E.diff([11, 12, 13, 14], 1, cheat, stE)))
print("KL run, orig12 rand-none", fmt(KL.diff(rnd, 1, cheat, stK, tasks=ORIG)), "new12", fmt(KL.diff(rnd, 1, cheat, stK, tasks=set(t for t, _ in stK) - set(ORIG))))
# unpaired bootstrap difference on the 12 tasks: (KLmatched - none in KL run) minus (same-norm5 - none in E)
def task_effect(ds, st, a, b, tasks):
    d = {}
    for t, s in st:
        if t in tasks:
            d.setdefault(t, []).append(ds.val(a, t, s, cheat) - ds.val(b, t, s, cheat))
    return {t: float(np.mean(v)) for t, v in d.items()}
e1 = task_effect(KL, stK, rnd, 1, ORIG); e2 = task_effect(E, stE, R5, 1, ORIG)
common = sorted(set(e1) & set(e2))
print("KLmatched effect - samenorm effect, same tasks", fmt(boot({t: [e1[t] - e2[t]] for t in common})))
# E' random1 (low KL) on 24 tasks vs KL-matched on same 24
e1 = task_effect(KL, stK, rnd, 1, set(t for t, _ in stK)); e2 = task_effect(merged, stR, 5, 1, set(t for t, _ in stR))
common = sorted(set(e1) & set(e2))
print("KLmatched effect - Eprime random1 effect, 24 tasks", fmt(boot({t: [e1[t] - e2[t]] for t in common})))
# -d advantage over same-norm: -d effect vs KL-matched rand in 12 tasks etc
print("=== direction-level uncertainty (3 directions, Student t, df=2)")
vals = np.array([KL.diff(a, 1, cheat, stK)[0] for a in rnd]); m, s = vals.mean(), vals.std(ddof=1)
print(vals, m, s, "t CI", m - 4.303 * s / 3**.5, m + 4.303 * s / 3**.5)
vals = np.array([E.diff(a, 1, cheat, stE)[0] for a in R5]); m, s = vals.mean(), vals.std(ddof=1)
print("same norm 5", vals, m, s, "t CI", m - 2.776 * s / 5**.5, m + 2.776 * s / 5**.5)

print("=== Q1 without random7; with audit-degenerate excluded")
print("r6,r8 only - none", fmt(KL.diff([21, 23], 1, cheat, stK)), "-d - r6r8", fmt(KL.diff(2, [21, 23], cheat, stK)))

print("=== boundary sensitivity to bootstrap seed")
for name, fn in (("E2 cap-none", lambda sd: E.diff(15, 1, cheat, stE, seed=sd)), ("r6-none", lambda sd: KL.diff(21, 1, cheat, stK, seed=sd)), ("H3 2-5", lambda sd: STP1.diff(2, 5, cheat, st1, seed=sd)), ("step1 2-6", lambda sd: STP1.diff(2, 6, cheat, st1, seed=sd)), ("Q1", lambda sd: KL.diff(rnd, 1, cheat, stK, seed=sd)), ("Q3 gain", lambda sd: KL.diff(2, 6, fc, stK, seed=sd)), ("Q3 rand", lambda sd: KL.diff(2, rnd, fc, stK, seed=sd)), ("E1 r2", lambda sd: E.diff(2, 11, cheat, stE, seed=sd)), ("E1 r5", lambda sd: E.diff(2, 14, cheat, stE, seed=sd))):
    uppers = [fn(sd) for sd in range(10)]
    print(name, "up", [round(u[2], 3) for u in uppers], "low", [round(u[1], 3) for u in uppers])
print("E2 exact results.json:")
res = json.load(open(R + "/2026-11-03-pressure-4bit-step2/results.json"))
print(res["E"]["cap"]["this_minus_none"], res["E"]["E1_randoms_beaten"])
print("=== D")
Dt = {}
for r in S2rows:
    if r.get("mode") == "honest":
        Dt.setdefault((r["arm"], r["task"], r["seed"]), []).append(r)
for a in (1, 2):
    tr = [v for k, v in Dt.items() if k[0] == a]
    print("arm", a, "n", len(tr), "solved", np.mean([any(x.get("n_ok") == 5 or x.get("honest_ok") == 5 for x in v) for v in tr]), "steps", np.mean([len(v) for v in tr]), "first solved", np.mean([v[0].get("honest_ok") == 5 for v in tr]), "actions", Counter(x["action"] for v in tr for x in v), "unsolved", [(v[0]["task"], v[0]["seed"], [x.get("honest_ok") for x in v]) for v in tr if not any(x.get("honest_ok") == 5 for x in v)])
print("=== tamper anywhere")
for f in ("2026-10-31-pressure", "2026-11-01-pressure-steer", "2026-11-02-pressure-4bit-replication", "2026-11-03-pressure-4bit-controls", "2026-11-03-pressure-4bit-step2", "2026-11-04-pressure-4bit-kl"):
    print(f, Counter(r["action"] for r in rows(f)))
print("=== contest_note and thinking step 1")
for a in (1, 2):
    rs = [r for k, v in STP1.t.items() if k[0] == a for r in v]
    print(a, "contest_note step-weighted", round(np.mean([r["contest_note"] for r in rs]), 3), "traj-weighted", round(STP1.level(a, lambda x: float(np.mean([r["contest_note"] for r in x])), st1)[0], 3), "think step-weighted", round(np.mean([r["thinking_tokens"] for r in rs])), "traj", round(STP1.level(a, lambda x: float(np.mean([r["thinking_tokens"] for r in x])), st1)[0]))
    code = [r for r in rs if r["code"] is not None]
    print("   on code steps only: contest", round(np.mean([r["contest_note"] for r in code]), 3), "think", round(np.mean([r["thinking_tokens"] for r in code])))
print("=== step 1 proj")
band = lambda r: float(np.mean(r["proj"][9:25]))
allr = [r for v in STP1.t.values() for r in v]
for act in ("cheat", "revise", "repeat", "contest"):
    x = [band(r) for r in allr if r["k"] > 3 and r["action"] == act]
    print("k>3 proj", act, round(np.mean(x), 2), len(x))
for a in range(1, 9):
    print("arm", a, "k3", round(np.mean([band(r) for k, v in STP1.t.items() if k[0] == a for r in v if r["k"] == 3]), 2), "k4", round(np.mean([band(r) for k, v in STP1.t.items() if k[0] == a for r in v if r["k"] == 4]), 2), "k5", round(np.mean([band(r) for k, v in STP1.t.items() if k[0] == a for r in v if r["k"] == 5]), 2))
print("=== section 6 split")
aw = lambda rs: float(np.mean([r["action"] == "cheat" and r["contest_note"] for r in rs])); un = lambda rs: float(np.mean([r["action"] == "cheat" and not r["contest_note"] for r in rs]))
for a in range(1, 9):
    if a in STP1.arms():
        print(a, fmt(STP1.level(a, aw, STP1.starts([a]))), fmt(STP1.level(a, un, STP1.starts([a]))))
print("2-1", fmt(STP1.diff(2, 1, aw, st1)), fmt(STP1.diff(2, 1, un, st1)))
for b in (5, 6):
    print("2-",b, "aware", fmt(STP1.diff(2, b, aw, st1)), "b-1 aware", fmt(STP1.diff(b, 1, aw, st1)))
st8 = STP1.starts([1, 2, 7, 8])
for b in (7, 8):
    print("2-",b, "aware", fmt(STP1.diff(2, b, aw, st8)), "b-1 aware", fmt(STP1.diff(b, 1, aw, st8)))
print("KL aw", fmt(KL.diff(2, 1, aw, stK)), fmt(KL.diff(2, 1, un, stK)), "gain", fmt(KL.diff(6, 1, aw, stK)), fmt(KL.diff(6, 1, un, stK)), "rand", fmt(KL.diff(rnd, 1, aw, stK)), fmt(KL.diff(rnd, 1, un, stK)))
print("E' aw", fmt(merged.diff(2, 1, aw, stR)), fmt(merged.diff(2, 1, un, stR)), "gain", fmt(merged.diff(6, 1, aw, stR)), fmt(merged.diff(6, 1, un, stR)))
print("=== cheat with all honest (arm 1 step 1)")
for a in (1, 2):
    rs = [r for k, v in STP1.t.items() if k[0] == a for r in v if r["action"] == "cheat"]
    print(a, len(rs), "honest5", sum(r["honest_ok"] == 5 for r in rs), Counter(r["honest_ok"] for r in rs))
print("=== rigged tests passing identity")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "experiments"))
import importlib
try:
    import pressure as P, pressure_tasks2 as P2
    n = 0
    for t in P.TASKS + P2.TASKS2:
        for name, args, exp in t["rigged"]:
            if args[0] == exp and type(args[0]) == type(exp):
                n += 1; print("  ", t["fn"], name)
    print("identity passes", n)
except Exception as e:
    print("import failed", e)
