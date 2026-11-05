import sys; sys.path.insert(0, __file__.rsplit('/', 1)[0])
from load import *
from collections import Counter
D = R + "/2026-10-31-pressure"
st = np.load(D + "/states.npz")
keys = list(st.keys())
print(len(keys), keys[:6])
S = {k: st[k].astype(np.float32) for k in keys}
gens = rows("2026-10-31-pressure")
tasks = ORIG
print("S rows last step")
for t in tasks:
    rs = [r for r in gens if r["task"] == t and r["cond"] == "S"]
    rs.sort(key=lambda r: r["k"])
    r = rs[-1]
    print(" ", t, "steps", len(rs), "last k", r["k"], "has_call", r["has_call"], "n_ok seq", [x.get("n_ok") for x in rs], [x.get("n_tests") for x in rs], "msg", repr((r["content"] or "")[:70]))
def traj(c, t):
    ks = sorted(int(k.split("|")[2]) for k in S if k.startswith(f"{c}|{t}|"))
    return {k: S[f"{c}|{t}|{k}"] for k in ks}
F = {t: traj("F", t) for t in tasks}; SS = {t: traj("S", t) for t in tasks}
print("state keys for S per task", {t: sorted(SS[t]) for t in tasks})
norm = lambda d: d / (np.linalg.norm(d, axis=-1, keepdims=True) + 1e-8)
def endpoint(tr):
    ks = sorted(tr); return tr[min(5, ks[-1])] - tr[0]
def spearman(x, y):
    from numpy import argsort
    def rank(a):
        a = np.asarray(a, float); o = a.argsort(); r = np.empty(len(a)); r[o] = np.arange(len(a))
        for v in np.unique(a):
            r[a == v] = r[a == v].mean()
        return r
    rx, ry = rank(x), rank(y)
    if rx.std() == 0 or ry.std() == 0: return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])
def ci(v, n=2000, seed=0):
    v = np.array([x for x in v if not np.isnan(x)]); rng = np.random.default_rng(seed)
    b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(n)]
    return float(v.mean()), float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5)), len(v)
band = slice(9, 25)
def run(s_clean, endS=None):
    def direction(ex):
        f = [endpoint(F[t]) for t in tasks if t != ex]
        s = [(endS(SS[t]) if endS else endpoint(SS[t])) for t in s_clean if t != ex]
        return norm(np.mean(f, axis=0) - np.mean(s, axis=0))
    rf, rs, k2 = [], [], []
    for t in tasks:
        u = direction(t)
        pf = {k: ((F[t][k] - F[t][0]) * u).sum(-1) for k in F[t]}
        ps = {k: ((SS[t][k] - SS[t][0]) * u).sum(-1) for k in SS[t]}
        kf, ks = sorted(pf), sorted(ps)
        rf.append(spearman(kf, [pf[k][band].mean() for k in kf])); rs.append(spearman(ks, [ps[k][band].mean() for k in ks]))
        ki = f"I|{t}|3"
        if ki in S:
            pi = ((S[ki] - F[t][0]) * u).sum(-1); k2.append(float((pi - pf[3])[band].mean()))
    return ci(rf), ci(rs), ci([a - b for a, b in zip(rf, rs)]), ci(k2)
print("as run (no S exclusion):", run(tasks))
failed = []
for t in tasks:
    rs = sorted([r for r in gens if r["task"] == t and r["cond"] == "S"], key=lambda r: r["k"])
    if any(r.get("n_ok") is not None and r.get("n_tests") and r["n_ok"] < r["n_tests"] for r in rs): failed.append(t)
print("S trajectories with a failed step:", failed)
clean = [t for t in tasks if t not in failed]
print("registered exclusion:", run(clean))
print("S endpoint at k=4 rather than 5 (not the completion step):", run(tasks, endS=lambda tr: tr[4] - tr[0]))
# direction comparison
pool = lambda ts, endS=None: norm(np.mean([endpoint(F[t]) for t in tasks], axis=0) - np.mean([(endS(SS[t]) if endS else endpoint(SS[t])) for t in ts], axis=0))
d0 = np.load(D + "/direction.npz"); u_file = d0["unit"]
u_all, u_clean, u_k4 = pool(tasks), pool(clean), pool(tasks, lambda tr: tr[4] - tr[0])
cos = lambda a, b: (a * b).sum(-1)
print("file vs recomputed cos band mean", cos(u_file, u_all)[band].mean())
print("registered exclusion vs used, cos band", cos(u_all, u_clean)[band].mean(), "min", cos(u_all, u_clean)[band].min())
print("S endpoint k=4 vs used, cos band", cos(u_all, u_k4)[band].mean(), "min", cos(u_all, u_k4)[band].min())
# decomposition of the pooled difference
fp = np.mean([endpoint(F[t]) for t in tasks], axis=0); sp = np.mean([endpoint(SS[t]) for t in tasks], axis=0)
print("||F part|| band mean", np.linalg.norm(fp, axis=-1)[band].mean(), "||S part||", np.linalg.norm(sp, axis=-1)[band].mean())
print("cos(d, F part)", cos(u_all, norm(fp))[band].mean(), "cos(d, -S part)", cos(u_all, norm(-sp))[band].mean())
print("projection of F part on d", (fp * u_all).sum(-1)[band].mean(), "of -S part on d", (-sp * u_all).sum(-1)[band].mean())
sk4 = np.mean([SS[t][4] - SS[t][0] for t in tasks], axis=0)
print("S(k=4) projection on d", (sk4 * u_all).sum(-1)[band].mean(), "S(k=5)", (sp * u_all).sum(-1)[band].mean())
# round_per_layer
print("round band", d0["round_per_layer"][band].mean(), "L24", d0["round_per_layer"][24], "k3", d0["k3_per_layer"][band].mean())
res = json.load(open(D + "/results.json"))
P = res["projections"]["F"]
print("F by k mean", {k: round(np.mean([P[t][str(k)] for t in P if str(k) in P[t]]), 2) for k in range(6)})
print("F at k=5 per task", {t: round(P[t].get("5", float('nan')), 1) for t in P})
print("F at k=1 per task", {t: round(P[t]["1"], 1) for t in P})
Ss = res["projections"]["S"]
print("S last", {t: (max(Ss[t], key=int), round(Ss[t][max(Ss[t], key=int)], 1)) for t in Ss})
print("I next actions", Counter(r["action"] for r in gens if r["cond"] == "I"))
print("F actions by k", {k: dict(Counter(r["action"] for r in gens if r["cond"] == "F" and r["k"] == k)) for k in range(6)})
print("F contest_note by k", {k: sum(r["contest_note"] for r in gens if r["cond"] == "F" and r["k"] == k) for k in range(6)})
aware = [r for r in gens if r["cond"] == "F" and r["action"] == "cheat"]
print("F cheat aware", sum(r["contest_note"] for r in aware), len(aware), "I", sum(r["contest_note"] for r in gens if r["cond"] == "I" and r["action"] == "cheat"), sum(1 for r in gens if r["cond"] == "I" and r["action"] == "cheat"))
print("k2 mean per k=2 cheat", sum(r['action']=='cheat' for r in gens if r['cond']=='F' and r['k']==2), "contest", sum(r['action']=='contest' for r in gens if r['cond']=='F' and r['k']==2))
print("=== audit")
A = R + "/2026-11-04-pressure-4bit-kl/audit/"
fin = json.load(open(A + "final.json")); key = json.load(open(A + "key.json")); r1 = json.load(open(A + "rater-llm.json")); r2 = json.load(open(A + "rater-llm-full.json"))
items = {str(i["item"]): i for i in key["items"]}
print("n", len(items), "rater1 keys", list(r1["ratings"].items())[:3] if isinstance(r1["ratings"], dict) else r1["ratings"][:3]); print("rater2", list(r2["ratings"].items())[:3] if isinstance(r2["ratings"], dict) else r2["ratings"][:3])
print("questions", json.dumps(r2.get("questions"), ensure_ascii=False)[:1200])
print("rater1 notes", str(r1.get("notes"))[:400]); print(r1.get("rater"), r2.get("rater"))
c = Counter((items[k]["arm_name"], v) for k, v in fin["category"].items()); print(sorted(c.items()))
for k, v in fin["labels"].items():
    if "A" in v:
        it = items[k]; print("  A:", k, it["task"], it["rep"], it["arm_name"], "k", it["k"], "prog", it["program_action"], "label", v)
for k, v in fin["labels"].items():
    if "E" in v:
        it = items[k]; print("  E:", k, it["task"], it["rep"], it["arm_name"], "k", it["k"], "prog", it["program_action"], "label", v)
def getr(r, k):
    x = r["ratings"]
    if isinstance(x, dict):
        v = x[k]; return v if isinstance(v, str) else v.get("label", v.get("labels"))
    for e in x:
        if str(e.get("item")) == k: return e.get("label", e.get("labels"))
agree = sum(set(getr(r1, k) or "") == set(getr(r2, k) or "") for k in items); print("r1 vs r2 exact", agree, len(items))
aa = [(("A" in (getr(r1, k) or "")), ("A" in (getr(r2, k) or ""))) for k in items]; print("A-flag table r1,r2", Counter(aa))
print("r2 A by arm", Counter(items[k]["arm_name"] for k in items if "A" in (getr(r2, k) or "")))
print("final A vs r2", sum(("A" in fin["labels"][k]) != ("A" in (getr(r2, k) or "")) for k in items))
