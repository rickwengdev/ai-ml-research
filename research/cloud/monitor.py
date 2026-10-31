#!/usr/bin/env python3
"""A live panel for a run on a rented GPU: tokens per second, GPU use, power, memory and the run's progress, refreshed
every second. Runs on the GPU box, listens on 127.0.0.1 only; reach it through an SSH tunnel (research/cloud/README.md).

  python monitor.py --out /vault/work/research/data/<run> --log /vault/work/logs/<run>.log [--port 8090]

Sources: $ENGINE_METRICS (written by services/model-server/torch_engine.py, default /workspace/metrics.json),
`nvidia-smi`, the run's gens.jsonl (rows done) and the tail of its log. Standard library only.
"""
import argparse, json, os, subprocess, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARGS = None
_gpu_cache = {"t": 0.0, "data": None}


def gpu():
    if time.time() - _gpu_cache["t"] < 0.5 and _gpu_cache["data"] is not None:
        return _gpu_cache["data"]
    fields = "utilization.gpu,memory.used,memory.total,power.draw,power.limit,temperature.gpu,name"
    try:
        line = subprocess.run(["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout.strip().splitlines()[0]
        util, used, total, power, limit, temp, name = [x.strip() for x in line.split(",")]
        data = {"util": float(util), "mem_used": float(used), "mem_total": float(total), "power": float(power), "power_limit": float(limit), "temp": float(temp), "name": name}
    except Exception as e:  # noqa: BLE001
        data = {"error": str(e)}
    _gpu_cache.update(t=time.time(), data=data)
    return data


def meter():
    try:
        with open(ARGS.metrics) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def progress():
    rows, conds, last = 0, {}, None
    path = os.path.join(ARGS.out, "gens.jsonl") if ARGS.out else None
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rows += 1
                key = r.get("cond") or r.get("arm_name") or "?"
                conds[key] = conds.get(key, 0) + 1
                last = r
        last = {k: last.get(k) for k in ("task", "cond", "arm_name", "k", "action", "batch", "seconds")} if last else None
    tail = []
    if ARGS.log and os.path.exists(ARGS.log):
        with open(ARGS.log, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 8192))
            lines = f.read().decode(errors="replace").splitlines()
        tail = [l for l in lines if l.strip() and "warning" not in l.lower() and "falling back" not in l.lower() and "Loading weights" not in l][-12:]
    return {"rows": rows, "by_cond": conds, "last": last, "tail": tail, "expected": ARGS.expected}


PAGE = r"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GPU 監控</title>
<style>
:root{--bg:#fbfbfa;--surface:#fff;--ink:#1d1d1b;--ink2:#5f5e5a;--ink3:#8a8984;--grid:#ecebe7;--axis:#cfcdc6;--accent:#2f6fb3;--accent2:#c27a1e;--ok:#3a8f5c;--warn:#b5841a;--bad:#b84a42}
@media (prefers-color-scheme:dark){:root{--bg:#181816;--surface:#22221f;--ink:#ecebe6;--ink2:#b3b1aa;--ink3:#86847d;--grid:#2e2e2a;--axis:#45443f;--accent:#6aa3e0;--accent2:#e0a456;--ok:#6cc08f;--warn:#e2b54f;--bad:#e07b72}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"PingFang TC","Noto Sans TC",sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 40px}
h1{font-size:18px;margin:0 0 2px}.sub{color:var(--ink3);font-size:12px;margin-bottom:16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}
.tile{background:var(--surface);border:1px solid var(--grid);border-radius:10px;padding:10px 12px}
.tile .k{color:var(--ink3);font-size:12px}.tile .v{font-size:24px;font-weight:600;font-variant-numeric:tabular-nums;margin-top:2px}.tile .u{font-size:12px;color:var(--ink2);font-weight:400;margin-left:3px}
.tile .s{font-size:12px;color:var(--ink2);margin-top:2px;font-variant-numeric:tabular-nums}
.card{background:var(--surface);border:1px solid var(--grid);border-radius:10px;padding:12px 14px;margin-bottom:12px}
.card h2{font-size:13px;margin:0 0 6px;font-weight:600}.card h2 span{color:var(--ink3);font-weight:400}
svg{display:block;width:100%;height:auto}svg text{fill:var(--ink3);font-size:11px}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media (max-width:760px){.row2{grid-template-columns:1fr}}
pre{margin:0;font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--ink2);white-space:pre-wrap;word-break:break-all;max-height:220px;overflow:auto}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:1px}
.tip{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--axis);border-radius:6px;padding:4px 8px;font-size:12px;color:var(--ink);display:none;font-variant-numeric:tabular-nums}
</style></head><body><main>
<h1>GPU 監控</h1><div class="sub" id="sub">連線中…</div>
<div class="tiles">
 <div class="tile"><div class="k">生成速度（5 秒平均）</div><div class="v" id="tps">–<span class="u">tok/s</span></div><div class="s" id="tps2"></div></div>
 <div class="tile"><div class="k">GPU 使用率</div><div class="v" id="util">–<span class="u">%</span></div><div class="s" id="temp"></div></div>
 <div class="tile"><div class="k">功耗</div><div class="v" id="pow">–<span class="u">W</span></div><div class="s" id="powl"></div></div>
 <div class="tile"><div class="k">顯存</div><div class="v" id="mem">–<span class="u">GB</span></div><div class="s" id="meml"></div></div>
 <div class="tile"><div class="k">批次</div><div class="v" id="batch">–</div><div class="s" id="phase"></div></div>
 <div class="tile"><div class="k">完成步數</div><div class="v" id="rows">–</div><div class="s" id="eta"></div></div>
</div>
<div class="card"><h2>生成速度 <span>tok/s，每秒一點，最近 10 分鐘</span></h2><svg id="c1" viewBox="0 0 1000 200" style="height:200px"></svg></div>
<div class="row2">
 <div class="card"><h2>GPU 使用率 <span>%</span></h2><svg id="c2" viewBox="0 0 1000 160" style="height:160px"></svg></div>
 <div class="card"><h2>功耗 <span>W，虛線為上限</span></h2><svg id="c3" viewBox="0 0 1000 160" style="height:160px"></svg></div>
</div>
<div class="card"><h2>執行紀錄 <span>最後幾行</span></h2><pre id="log"></pre></div>
</main><div class="tip" id="tip"></div>
<script>
const N=600, hist=[]; let prev=null;
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
function fmt(x,d=0){return x==null||isNaN(x)?'–':x.toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:d})}
function chart(id,key,color,h,maxFixed,limitKey){
  const svg=document.getElementById(id),W=Math.max(300,Math.round(svg.clientWidth||1000)),H=h,L=44,R=8,T=8,B=20;
  svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  const pts=hist.filter(p=>p[key]!=null);
  let max=maxFixed||Math.max(1,...pts.map(p=>p[key]),...(limitKey?pts.map(p=>p[limitKey]||0):[]));
  if(!maxFixed){const m=Math.pow(10,Math.floor(Math.log10(max)));max=Math.ceil(max/m)*m;}
  const t1=Date.now()/1000,t0=t1-N;
  const x=t=>L+(t-t0)/(t1-t0)*(W-L-R),y=v=>T+(1-v/max)*(H-T-B);
  let g='';for(let i=0;i<=4;i++){const v=max*i/4,yy=y(v);g+=`<line x1="${L}" x2="${W-R}" y1="${yy}" y2="${yy}" stroke="${css('--grid')}"/>`+`<text x="${L-6}" y="${yy+4}" text-anchor="end">${fmt(v)}</text>`;}
  for(let m=0;m<=10;m+=2){const xx=x(t1-m*60);g+=`<text x="${xx}" y="${H-4}" text-anchor="middle">${m?'−'+m+' 分':'現在'}</text>`;}
  let path='';pts.forEach((p,i)=>{path+=(i&&p.t-pts[i-1].t<5?'L':'M')+x(p.t).toFixed(1)+','+y(p[key]).toFixed(1)});
  let lim='';if(limitKey&&pts.length){const lv=pts[pts.length-1][limitKey];if(lv)lim=`<line x1="${L}" x2="${W-R}" y1="${y(lv)}" y2="${y(lv)}" stroke="${css('--ink3')}" stroke-dasharray="4 4"/>`;}
  svg.innerHTML=g+lim+`<path d="${path}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>`+`<line id="${id}x" y1="${T}" y2="${H-B}" stroke="${css('--axis')}" visibility="hidden"/>`;
  svg.onmousemove=e=>{const r=svg.getBoundingClientRect(),sx=(e.clientX-r.left)/r.width*W,t=t0+(sx-L)/(W-L-R)*(t1-t0);let best=null,bd=1e9;for(const p of pts){const d=Math.abs(p.t-t);if(d<bd){bd=d;best=p}}
    const tip=document.getElementById('tip'),ln=document.getElementById(id+'x');if(!best||bd>3){tip.style.display='none';ln.setAttribute('visibility','hidden');return}
    ln.setAttribute('x1',x(best.t));ln.setAttribute('x2',x(best.t));ln.setAttribute('visibility','visible');
    tip.textContent=`${new Date(best.t*1000).toLocaleTimeString()} · ${fmt(best[key],key==='tps'?1:0)}${key==='tps'?' tok/s':key==='util'?' %':' W'}`;tip.style.display='block';tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY-28)+'px'};
  svg.onmouseleave=()=>{document.getElementById('tip').style.display='none';const ln=document.getElementById(id+'x');if(ln)ln.setAttribute('visibility','hidden')};
}
async function tick(){
  try{
    const d=await (await fetch('metrics',{cache:'no-store'})).json(),now=Date.now()/1000,m=d.meter,g=d.gpu||{},pr=d.progress;
    let inst=null;
    if(m&&prev&&m.t>prev.t){inst=(m.generated-prev.generated)/(m.t-prev.t);if(inst<0)inst=null}
    if(m&&(!prev||m.t>prev.t))prev=m;
    hist.push({t:now,inst,util:g.util,power:g.power,limit:g.power_limit});while(hist.length&&hist[0].t<now-N)hist.shift();
    const win=hist.filter(p=>p.inst!=null&&p.t>now-5);const tps=win.length?win.reduce((a,p)=>a+p.inst,0)/win.length:(m&&m.phase!=='generate'?0:null);
    hist[hist.length-1].tps=tps;
    const all=hist.filter(p=>p.tps!=null);const avg=all.length?all.reduce((a,p)=>a+p.tps,0)/all.length:null;
    document.getElementById('tps').innerHTML=fmt(tps,1)+'<span class="u">tok/s</span>';
    document.getElementById('tps2').textContent=avg!=null?`10 分鐘平均 ${fmt(avg,1)}`:'';
    document.getElementById('util').innerHTML=fmt(g.util)+'<span class="u">%</span>';document.getElementById('temp').textContent=g.temp!=null?`${fmt(g.temp)} °C · ${g.name||''}`:(g.error||'');
    document.getElementById('pow').innerHTML=fmt(g.power)+'<span class="u">W</span>';document.getElementById('powl').textContent=g.power_limit?`上限 ${fmt(g.power_limit)} W`:'';
    document.getElementById('mem').innerHTML=fmt((g.mem_used||0)/1024,1)+'<span class="u">GB</span>';document.getElementById('meml').textContent=g.mem_total?`共 ${fmt(g.mem_total/1024,0)} GB`:'';
    document.getElementById('batch').textContent=m?`${m.active} / ${m.batch}`:'–';
    const PH={generate:'生成中',prefill:'讀取提示詞',state:'讀取狀態',tools:'執行測試',idle:'閒置'};
    document.getElementById('phase').textContent=m?`${PH[m.phase]||m.phase} · 累計 ${fmt(m.generated)} token`:'尚無引擎資料';
    document.getElementById('rows').textContent=pr.expected?`${pr.rows} / ${pr.expected}`:pr.rows;
    let eta='';if(m&&pr.rows>0&&pr.expected){const el=now-m.since,rate=pr.rows/el,left=(pr.expected-pr.rows)/rate;eta=`已跑 ${Math.round(el/60)} 分 · 約剩 ${left>0?Math.round(left/60):0} 分`}
    document.getElementById('eta').textContent=eta||Object.entries(pr.by_cond||{}).map(([k,v])=>`${k} ${v}`).join(' · ');
    document.getElementById('sub').textContent=`${d.run||''} · 每秒更新 · ${new Date().toLocaleTimeString()}`;
    document.getElementById('log').textContent=(pr.tail||[]).join('\n');
    chart('c1','tps',css('--accent'),200);chart('c2','util',css('--accent'),160,100);chart('c3','power',css('--accent'),160,null,'limit');
  }catch(e){document.getElementById('sub').textContent='連線中斷，重試中…'}
}
tick();setInterval(tick,1000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/metrics"):
            self._send(json.dumps({"t": time.time(), "run": os.path.basename(ARGS.out.rstrip("/")) if ARGS.out else "", "meter": meter(), "gpu": gpu(), "progress": progress()}), "application/json")
        else:
            self._send(PAGE, "text/html; charset=utf-8")


def main():
    global ARGS
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="", help="the run's data directory (gens.jsonl)")
    ap.add_argument("--log", default="", help="the run's log file")
    ap.add_argument("--metrics", default=os.environ.get("ENGINE_METRICS", "/workspace/metrics.json"))
    ap.add_argument("--expected", type=int, default=0, help="rows the run is expected to write, for the ETA")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ARGS = ap.parse_args()
    ThreadingHTTPServer((ARGS.host, ARGS.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
