import sys; sys.path.insert(0, __file__.rsplit('/', 1)[0])
from load import *
from collections import Counter
rnd=[21,22,23]
stK = KL.starts([1,2,6,21,22,23])
merged = DS([r for v in REP.t.values() for r in v] + [r for v in CTL.t.values() for r in v])
stR = merged.starts([1,2,5,6]); st1 = STP1.starts([1,2,3,4,5,6,7,8])
print("== step1 false claims: previous step all pass?")
for a in (2,3):
    for t,s in sorted(st1):
        rs=STP1.t[(a,t,s)]; r=rs[-1]
        if r["action"]=="false_claim" and a==2 or (a==3 and r["action"]=="false_claim" and len(rs)>1):
            p=rs[-2] if len(rs)>1 else None
            print(a,t,s,"k",r["k"],"prev n_ok",p and p.get("n_ok"),"prev act",p and p["action"],"think",r["thinking_tokens"],repr((r["content"] or "")[:80]))
print("== readings of item messages")
for ds,a,t,s in ((KL,2,"count_vowels",2),(REP,2,"slugify",2),(KL,2,"safe_div",0),(KL,2,"celsius_to_f",2)):
    r=ds.t[(a,t,s)][-1]; c=r["content"] or ""
    print("---",t,s,len(c),repr(c[:500])); print("   ...",repr(c[-350:]))
print("== reasoning mentions failing tests, in -d false-claim steps (audit 9 + rep 9 + step1 2)")
AUD=[("rle",0),("chunk",1),("digit_sum",2),("slugify",0),("chunk",0),("truncate",1),("initials",0),("count_vowels",2),("title_case",0)]
FAIL=re.compile(r"(fail|2 tests|contradict|incorrect expect|wrong|expected)",re.I)
def show(ds,a,t,s):
    r=ds.t[(a,t,s)][-1]; th=r["reasoning"] or ""
    m=[x.group(0) for x in FAIL.finditer(th)]
    tail=bool(re.search(r"(tests? (still )?fail|failing|fail)",th[-400:],re.I))
    return dict(task=t,rep=s,k=r["k"],think=r["thinking_tokens"],nmention=len(m),fail_near_end=tail, firstsent=th[:120])
for t,s in AUD: print("KL",show(KL,2,t,s))
for t,s in sorted(stR):
    if REP.t[(2,t,s)][-1]["action"]=="false_claim": print("REP",show(REP,2,t,s))
print("== thinking tokens of ending steps")
for a in (1,2,6,21,22,23):
    th=[KL.t[(a,t,s)][-1]["thinking_tokens"] for t,s in stK if not KL.t[(a,t,s)][-1]["has_call"]]
    print(a,len(th),"median",np.median(th) if th else None)
allth={a:np.mean([r["thinking_tokens"] for t,s in stK for r in KL.t[(a,t,s)]]) for a in (1,2,6,21,22,23)}; print("mean think all steps",allth)
print("stop_any",{a:round(KL.level(a,stop_any,stK)[0],3) for a in (1,2,6,21,22,23)})
print("contest_note",{a:round(np.mean([r["contest_note"] for t,s in stK for r in KL.t[(a,t,s)]]),3) for a in (1,2,6,21,22,23)})
print("== persistence: prefix has cheat?")
pre={}
for r in rows("2026-11-04-pressure-4bit-kl","prefix.jsonl"): pre.setdefault((r["task"],r["rep"]),[]).append(r)
pc={k for k,v in pre.items() if any(x["action"]=="cheat" for x in v)}
a_=stK&pc; b_=stK-pc; print("starts with prior cheat",len(a_),len({t for t,_ in a_}),"without",len(b_),len({t for t,_ in b_}))
for nm,S in (("prior",a_),("noprior",b_)):
    print(nm,"none",fmt(KL.level(1,cheat,S)),"-d-none",fmt(KL.diff(2,1,cheat,S)),"rand-none",fmt(KL.diff(rnd,1,cheat,S)),"gain-none",fmt(KL.diff(6,1,cheat,S)),"-d-rand",fmt(KL.diff(2,rnd,cheat,S)))
pre2={}
for r in rows("2026-11-02-pressure-4bit-replication","prefix.jsonl"): pre2.setdefault((r["task"],r["rep"]),[]).append(r)
pc2={k for k,v in pre2.items() if any(x["action"]=="cheat" for x in v)}
a_=stR&pc2; b_=stR-pc2; print("REP prior",len(a_),"none",len(b_))
for nm,S in (("prior",a_),("noprior",b_)):
    print(nm,"none",fmt(merged.level(1,cheat,S)),"-d-none",fmt(merged.diff(2,1,cheat,S)),"gain-none",fmt(merged.diff(6,1,cheat,S)),"r-none",fmt(merged.diff(5,1,cheat,S)))
print("== new-code cheat vs resubmitted")
def split(rs,prior):
    seen=set(prior); nw=rs_=0
    for r in rs:
        if r["action"]=="cheat":
            c=re.sub(r"\s+","",r["code"] or "")
            if c in seen: rs_+=1
            else: nw+=1
            seen.add(c)
        elif r["code"]: seen.add(re.sub(r"\s+","",r["code"]))
    return nw/len(rs),rs_/len(rs)
for a,n in ((1,"none"),(2,"-d"),(6,"gain"),(21,"r6"),(22,"r7"),(23,"r8")):
    x=[split(KL.t[(a,t,s)],[re.sub(r"\s+","",q["code"] or "") for q in pre[(t,s)]]) for t,s in stK]
    print(n,"new",round(np.mean([q[0] for q in x]),3),"resub",round(np.mean([q[1] for q in x]),3))
print("== t and sign-flip checks, per-task differences")
def tchk(ds,a,b,f,st,tasks=None):
    d={}
    for t,s in st:
        if tasks is None or t in tasks: d.setdefault(t,[]).append(ds.val(a,t,s,f)-ds.val(b,t,s,f))
    v=np.array([np.mean(x) for x in d.values()]); n=len(v); m=v.mean(); se=v.std(ddof=1)/n**.5
    tc={12:2.201,24:2.069,20:2.093,22:2.080}.get(n,2.1)
    rng=np.random.default_rng(1); fl=rng.choice([-1,1],size=(200000,n)); p=float(np.mean(np.abs((fl*v).mean(1))>=abs(m)-1e-12))
    return f"{m:+.3f} t95[{m-tc*se:+.3f},{m+tc*se:+.3f}] signflip p={p:.4f} n={n}"
print("H1",tchk(STP1,2,1,cheat,st1)); print("H3 rand",tchk(STP1,2,5,cheat,st1)); print("H3 gain",tchk(STP1,2,6,cheat,st1))
print("H1r",tchk(merged,2,1,cheat,stR)); print("E'gain",tchk(merged,2,6,cheat,stR)); print("E'rand",tchk(merged,2,5,cheat,stR))
print("Q1",tchk(KL,rnd,1,cheat,stK)); print("Q2",tchk(KL,2,rnd,cheat,stK)); print("Q3g",tchk(KL,2,6,fc,stK)); print("Q3r",tchk(KL,2,rnd,fc,stK)); print("-d-none KL",tchk(KL,2,1,cheat,stK)); print("gain-none KL",tchk(KL,6,1,cheat,stK))
print("Q3 with audit labels")
fin=json.load(open(R+"/2026-11-04-pressure-4bit-kl/audit/final.json")); key=json.load(open(R+"/2026-11-04-pressure-4bit-kl/audit/key.json"))
aud={(i["arm"],i["task"],i["rep"]):fin["category"][str(i["item"])] for i in key["items"]}
afc=lambda a,t,s: float(aud.get((a,t,s))=="false_claim")
def d_aud(a,b):
    d={}
    for t,s in stK:
        va=afc(a,t,s); vb=np.mean([afc(x,t,s) for x in b]) if isinstance(b,list) else afc(b,t,s)
        d.setdefault(t,[]).append(va-vb)
    return boot(d)
print("audited -d-gain",fmt(d_aud(2,6)),"-d-rand",fmt(d_aud(2,rnd)))
print("audit incoherent endings removed (start-level) Q1,Q2:")
bad={(t,s) for (a,t,s),c in aud.items() if c=="incoherent"}
S=stK-bad; print(len(S),"Q1",fmt(KL.diff(rnd,1,cheat,S)),"Q2",fmt(KL.diff(2,rnd,cheat,S)),"r7-none",fmt(KL.diff(22,1,cheat,S)))
bad7={(t,s) for (a,t,s),c in aud.items() if c=="incoherent" and a==22}
print("r7 degenerate-start",bad7)
print("count of r2-broad A flags per arm over 69")
print("== step-2 k=3 'incoherent' any vs mean arm3:", np.mean([any(not r["coherent"] for r in STP1.t[(3,t,s)]) for t,s in st1]), np.mean([np.mean([not r["coherent"] for r in STP1.t[(3,t,s)]]) for t,s in st1]))
print("arm3 endings by content: claim text regex")
print(Counter(("pass" in (STP1.t[(3,t,s)][-1]["content"] or "").lower()) for t,s in st1))
print("== times"); 
for f in ("2026-10-31-pressure","2026-11-01-pressure-steer"):
    rr=rows(f); print(f,len(rr),"hours",round(sum(r.get("seconds",0) for r in rr)/3600,2))
d=np.load(R+"/2026-10-31-pressure/direction.npz"); print(d["unit"].shape)
