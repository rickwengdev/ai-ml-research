#!/usr/bin/env python3
"""GPUtw (gputw.ai) adapter: rent a GPU container, put the repo and data on /vault, run an experiment, fetch results.

The API key is read from $GPUTW_API_KEY or ~/.config/gputw/key (chmod 600) and never printed. Endpoints follow
docs.gputw.ai (REST API quickstart, Vault); the ones the docs do not describe (get/delete instance) are tried on
their obvious paths and the raw response is shown, so a refusal is visible rather than hidden.

  catalog                         GPUs on offer with live hourly price and availability (no key needed)
  nodes <catalogId>               machines available for one catalog entry
  deploy --gpu "RTX 5090" [...]   create an instance from a pinned PyTorch CUDA image with SSH, auto-stop set
  list | get <id> | stop <id> | delete <id> | auto-stop <id> --hours N
  balance                         the account's credit balance (NTD) and nothing else from the profile
  ssh <id> [-- cmd ...]           open a shell, or run one command, on the instance
  sync <id>                       rsync this repo's research/ + services/model-server/ (no venvs, no data) to /vault/work
  push <id> <local> <remote>      rsync one path up (data directories, direction files)
  fetch <id> <remote> <local>     rsync results back
  backup <id> [--every 300]       pull every run's data and the logs from /vault to this machine (once, or on a loop)
  run <id> -- <command>           start a long command under nohup on the instance, log in /vault/work/logs/
  jobs <id> | kill <id> <name>    list the jobs `run` started / stop one by its pid file
  vault-upload <local> [--path p] upload one file to Vault through the transfer host (no instance needed)
  vault-fetch <hf-id> [--dest p]  have GPUtw download a Hugging Face model into /vault/work/models/<name>, file by
                                  file, pinned to the repo's current commit (no instance needed; the console's
                                  「從網址下載」 endpoint, /api/vault/downloads, which the docs do not describe).
                                  Three run at once per account, so this waits for slots; rerun it to fill gaps
  vault-downloads [--watch]       those server-side downloads and their progress

usage: gputw.py <command> [...]; GPUTW_API_KEY=... or ~/.config/gputw/key
"""
import argparse, json, os, shlex, subprocess, sys, time

try:
    import requests
except ImportError:  # the model-server venv has no requests; urllib is enough for these calls
    requests = None
import urllib.parse, urllib.request, urllib.error

BASE = "https://gputw.ai"
UPLOAD = "https://upload.gputw.ai"
SSH_HOST, SSH_PORT = "ssh.gputw.ai", 2222
REMOTE_ROOT = "/vault/work"
# A pinned image for Blackwell (sm_120: RTX 5090, RTX Pro 6000) and Ampere alike; CUDA 12.8 is the first that
# supports Blackwell. Verify the tag exists on Docker Hub before the first deploy.
DEFAULT_IMAGE = "pytorch/pytorch:2.7.1-cuda12.8-cudnn9-devel"
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def api_key():
    key = os.environ.get("GPUTW_API_KEY")
    if not key:
        path = os.path.expanduser("~/.config/gputw/key")
        if os.path.exists(path):
            key = open(path).read().strip()
    if not key:
        sys.exit("no API key: set GPUTW_API_KEY or write it to ~/.config/gputw/key (chmod 600)")
    return key


def call(method, path, body=None, auth=True, base=BASE, raw=False):
    url = base + path
    # Cloudflare in front of gputw.ai refuses urllib's default user agent (error 1010), so the client names itself.
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (compatible; ai-ml-research-gputw/0.1)"}
    if auth:
        headers["Authorization"] = f"Bearer {api_key()}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode()
            status = resp.status
    except urllib.error.HTTPError as e:
        text, status = e.read().decode(errors="replace"), e.code
    if raw:
        return status, text
    try:
        parsed = json.loads(text) if text else None
    except json.JSONDecodeError:
        parsed = text
    if status >= 400:
        sys.exit(f"{method} {path} -> {status}: {parsed if isinstance(parsed, str) else json.dumps(parsed, ensure_ascii=False)[:800]}")
    return parsed


def show(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def entries(obj):
    """The list inside whatever envelope the API uses."""
    if isinstance(obj, list):
        return obj
    for key in ("data", "items", "gpus", "nodes", "instances", "results"):
        if isinstance(obj, dict) and isinstance(obj.get(key), list):
            return obj[key]
    return [obj] if isinstance(obj, dict) else []


# ── commands ────────────────────────────────────────────────────────────────


def cmd_catalog(args):
    cat = call("GET", "/api/gpus/active", auth=False)
    rows = entries(cat)
    if args.json:
        show(cat)
        return
    print(f"{'id':40s} {'model':32s} {'vram':>6s} {'price/h':>8s}  availability")
    for g in rows:
        name = g.get("name") or g.get("model") or g.get("displayName") or "?"
        vram = g.get("vram") or g.get("vramGb") or g.get("memoryGb") or ""
        price = g.get("liveRentablePrice") or g.get("price") or g.get("hourlyRate")
        avail = g.get("availability") or g.get("demand") or g.get("status") or ""
        print(f"{str(g.get('id') or g.get('catalogId') or ''):40s} {str(name):32s} {str(vram):>6s} {('%.3f' % price) if isinstance(price, (int, float)) else '—':>8s}  {avail}")


def find_catalog(name):
    for g in entries(call("GET", "/api/gpus/active", auth=False)):
        label = " ".join(str(g.get(k, "")) for k in ("name", "model", "displayName"))
        if name.lower() in label.lower():
            return g
    sys.exit(f"no catalog entry matching {name!r}; see `gputw.py catalog`")


def cmd_nodes(args):
    show(call("GET", f"/api/nodes/available?catalogId={args.catalog_id}"))


def cmd_deploy(args):
    cat = find_catalog(args.gpu)
    cid = cat.get("id") or cat.get("catalogId")
    listed = entries(call("GET", f"/api/nodes/available?catalogId={cid}"))
    # The endpoint lists every machine of that model, busy ones included: only those with a free GPU can be deployed
    # (the catalog's own "AVAILABLE" lags behind), so pick the cheapest machine that actually has one.
    nodes = [n for n in listed if (n.get("availableGpus") if n.get("availableGpus") is not None else 1) > 0]
    if not nodes:
        sys.exit(f"no free {args.gpu} right now ({len(listed)} machine(s), all busy); retry later or pick another GPU")
    nodes = sorted(nodes, key=lambda n: n.get("hourlyRate") or n.get("price") or 1e9)
    node = nodes[0]
    nid = node.get("id") or node.get("nodeId") or node.get("machineId")
    # Model weights go to the instance disk: /vault writes at a few MB/s (measured 6 MB/s direct), /workspace at GB/s.
    # Weights that must persist are fetched into the Vault server-side (gputw.py vault-fetch) instead.
    env = [{"name": k, "value": v} for k, v in ([("HF_HOME", "/workspace/hf"), ("PYTHONUNBUFFERED", "1")] + [tuple(e.split("=", 1)) for e in (args.env or [])])]
    body = {"nodeId": nid, "bandwidthMbps": args.bandwidth, "ports": [],
            "customImage": {"dockerImage": args.image, "sshEnabled": True, "webUiEnabled": False, "env": env, "args": ["sleep", "infinity"]},
            "autoStopHours": args.hours}
    print(f"deploying {cat.get('name') or args.gpu} on node {nid} (rate {node.get('hourlyRate')}) with {args.image}, auto-stop in {args.hours} h", file=sys.stderr)
    if args.dry_run:
        show(body)
        return
    res = call("POST", "/api/instances/create", body)
    show(res)
    data = (res or {}).get("data") if isinstance((res or {}).get("data"), dict) else (res or {})
    iid = data.get("instanceId") or data.get("id") or (data.get("instance") or {}).get("id")
    if iid:
        print(f"\ninstance {iid}\nssh: ssh -p {SSH_PORT} pod-{iid}@{SSH_HOST}\nnext: gputw.py sync {iid}; gputw.py ssh {iid} -- bash {REMOTE_ROOT}/research/cloud/bootstrap.sh", file=sys.stderr)


def cmd_balance(args):
    status, text = call("GET", "/api/auth/me", raw=True)
    data = (json.loads(text) or {}).get("data") or {}
    print(f"balance {data.get('creditBalance')} NTD (low-balance alert at {data.get('lowBalanceThresholdNtd')})" if status == 200 else f"{status} {text[:200]}")


def cmd_list(args):
    show(call("GET", "/api/instances"))


def cmd_get(args):
    status, text = call("GET", f"/api/instances/{args.id}", raw=True)
    print(status, text[:2000])


def cmd_stop(args):
    show(call("POST", "/api/instances/stop", {"instanceId": args.id}))


def cmd_delete(args):
    for method, path, body in (("DELETE", f"/api/instances/{args.id}", None), ("POST", "/api/instances/delete", {"instanceId": args.id})):
        status, text = call(method, path, body, raw=True)
        print(method, path, "->", status, text[:400])
        if status < 400:
            return
    print("delete is not documented by GPUtw; stop the instance and delete it from the dashboard", file=sys.stderr)


def cmd_auto_stop(args):
    body = {"autoStopAt": None} if args.cancel else ({"extendHours": args.extend} if args.extend else {"autoStopAt": args.at})
    show(call("PATCH", f"/api/instances/{args.id}/auto-stop", body))


def ssh_target(iid):
    return f"pod-{iid}@{SSH_HOST}"


def ssh_base(iid):
    return ["ssh", "-p", str(SSH_PORT), "-o", "StrictHostKeyChecking=accept-new", ssh_target(iid)]


def cmd_ssh(args):
    cmd = ssh_base(args.id) + ([" ".join(shlex.quote(c) for c in args.cmd)] if args.cmd else [])
    os.execvp("ssh", cmd)


def rsync(src, dst, excludes=()):
    cmd = ["rsync", "-az", "-e", f"ssh -p {SSH_PORT} -o StrictHostKeyChecking=accept-new"] + [f"--exclude={e}" for e in excludes] + [src, dst]
    print(" ".join(shlex.quote(c) for c in cmd), file=sys.stderr)
    subprocess.run(cmd, check=True)


def cmd_sync(args):
    target = ssh_target(args.id)
    subprocess.run(ssh_base(args.id) + [f"mkdir -p {REMOTE_ROOT}/research {REMOTE_ROOT}/services/model-server {REMOTE_ROOT}/logs"], check=True)
    rsync(os.path.join(REPO, "services", "model-server") + "/", f"{target}:{REMOTE_ROOT}/services/model-server/", excludes=(".venv", ".venv-torch", "__pycache__", "vectors/*.npz"))
    rsync(os.path.join(REPO, "research") + "/", f"{target}:{REMOTE_ROOT}/research/", excludes=("data", "subjects", "figures/*.png", "__pycache__", ".venv*"))
    print(f"synced; data goes up separately: gputw.py push {args.id} research/data/2026-10-31-pressure {REMOTE_ROOT}/research/data/", file=sys.stderr)


def cmd_push(args):
    rsync(args.local.rstrip("/") if os.path.isfile(args.local) else args.local.rstrip("/"), f"{ssh_target(args.id)}:{args.remote}")


def cmd_fetch(args):
    os.makedirs(args.local, exist_ok=True)
    rsync(f"{ssh_target(args.id)}:{args.remote.rstrip('/')}/", args.local.rstrip("/") + "/")


def backup_once(iid):
    """Pull what the runs wrote on /vault back to this machine: research/data/* into research/data/, the logs into
    research/cloud/logs/. Never deletes anything here; files still growing are re-sent whole or appended."""
    target = ssh_target(iid)
    local_data = os.path.join(REPO, "research", "data")
    local_logs = os.path.join(REPO, "research", "cloud", "logs")
    os.makedirs(local_logs, exist_ok=True)
    rsync(f"{target}:{REMOTE_ROOT}/research/data/", local_data + "/", excludes=("*.tmp.npy",))
    rsync(f"{target}:{REMOTE_ROOT}/logs/", local_logs + "/", excludes=("*.pid",))


def cmd_backup(args):
    """Once, or every --every seconds until stopped (keep it running while a job runs: if the account runs out of
    credit the machine stops and /workspace is gone; /vault outlives it, but only 30 days at a zero balance)."""
    while True:
        started = time.strftime("%H:%M:%S")
        try:
            backup_once(args.id)
            print(f"[backup] {started} ok", file=sys.stderr, flush=True)
        except subprocess.CalledProcessError as e:
            print(f"[backup] {started} failed: {e}", file=sys.stderr, flush=True)
        if not args.every:
            return
        time.sleep(args.every)


def cmd_run(args):
    name = args.name or time.strftime("job-%Y%m%d-%H%M%S")
    log = f"{REMOTE_ROOT}/logs/{name}.log"
    # setsid + /dev/null stdin so the ssh session returns at once instead of waiting on the job's inherited pipes.
    remote = f"cd {REMOTE_ROOT} && setsid nohup bash -lc {shlex.quote(' '.join(args.cmd))} > {log} 2>&1 < /dev/null & echo $! > {REMOTE_ROOT}/logs/{name}.pid; echo started $(cat {REMOTE_ROOT}/logs/{name}.pid) log {log}"
    # The gateway keeps the ssh session open while the detached job lives, so the call is cut off after a few
    # seconds; the job survives (setsid), and its log and pid file say so.
    try:
        subprocess.run(ssh_base(args.id) + [remote], check=True, timeout=15)
    except subprocess.TimeoutExpired:
        print(f"started (session cut); log {log}", file=sys.stderr)


def cmd_jobs(args):
    """The jobs `run` started (pid files in /vault/work/logs), whether each is alive, and its log's last line."""
    script = (f"cd {REMOTE_ROOT}/logs 2>/dev/null || exit 0; for f in *.pid; do [ -e \"$f\" ] || continue; n=${{f%.pid}}; p=$(cat \"$f\"); "
              "if kill -0 \"$p\" 2>/dev/null; then s=running; else s=ended; fi; "
              "printf '%-24s %-8s pid %-7s %s\\n' \"$n\" \"$s\" \"$p\" \"$(tail -n 1 \"$n.log\" 2>/dev/null | cut -c1-90)\"; done")
    subprocess.run(ssh_base(args.id) + [script], check=False)


def cmd_kill(args):
    """Stop a job `run` started, by the pid in its pid file (with its process group), never by matching a command
    line: on these boxes the shell running the remote command contains the pattern too and kills itself."""
    script = (f"p=$(cat {REMOTE_ROOT}/logs/{args.name}.pid 2>/dev/null) || {{ echo 'no such job'; exit 1; }}; "
              "kill -TERM -- -\"$p\" 2>/dev/null || kill -TERM \"$p\"; sleep 3; "
              "if kill -0 \"$p\" 2>/dev/null; then echo still running; else echo stopped; fi")
    subprocess.run(ssh_base(args.id) + [script], check=False)


def cmd_vault_upload(args):
    if requests is None:
        sys.exit("vault-upload needs the requests package (pip install requests)")
    with open(args.local, "rb") as f:
        r = requests.post(f"{UPLOAD}/api/vault/upload", params={"path": args.path}, headers={"Authorization": f"Bearer {api_key()}"}, files={"file": (os.path.basename(args.local), f)}, timeout=3600)
    print(r.status_code, r.text[:800])


HF_PATTERNS = (".json", ".safetensors", ".jinja", ".txt", ".model")  # what the job loads; no README, LICENSE, evals


def cmd_vault_fetch(args):
    """Queue one server-side download per file: the console's dialog takes one direct link at a time, and a repo page
    URL fails ("returned a web page, not a file"). Files already in the Vault at the right size are skipped."""
    with urllib.request.urlopen(urllib.request.Request(f"https://huggingface.co/api/models/{args.hf_id}?blobs=true", headers={"User-Agent": "ai-ml-research"}), timeout=60) as r:
        info = json.load(r)
    if info.get("gated"):
        sys.exit(f"{args.hf_id} is gated; this command does not pass a Hugging Face token")
    sha = info["sha"]
    dest = args.dest or f"work/models/{args.hf_id.split('/')[-1]}"
    files = [(s["rfilename"], s.get("size")) for s in info["siblings"] if s["rfilename"].endswith(HF_PATTERNS) and "/" not in s["rfilename"]]
    status, text = call("GET", f"/api/vault/list?path={urllib.parse.quote(dest)}", raw=True)
    have = {f["name"]: f["size"] for f in (json.loads(text)["data"]["files"] if status == 200 else [])}
    queued = 0
    for name, size in files:
        if name in have and (size is None or have[name] == size):
            continue
        if any(r["targetPath"] == f"{dest}/{name}" and r["status"] in ("pending", "downloading") for r in call("GET", "/api/vault/downloads")["data"]):
            continue  # already on its way
        body = {"source": f"https://huggingface.co/{args.hf_id}/resolve/{sha}/{name}", "targetPath": f"{dest}/{name}"}
        while True:  # at most 3 downloads run at once per account (429); wait for a slot
            status, text = call("POST", "/api/vault/downloads", body, raw=True)
            if status != 429:
                break
            time.sleep(30)
        if status >= 400:
            sys.exit(f"{name}: {status} {text[:300]}")
        queued += 1
        print(f"queued {name} ({(size or 0) / 1e9:.2f} GB) → /vault/{dest}/{name}  [{json.loads(text)['data']['id']}]", flush=True)
    total = sum(s or 0 for _, s in files)
    print(f"{args.hf_id}@{sha[:12]}: {len(files)} files, {total / 1e9:.1f} GB; {queued} queued, {len(files) - queued} already in /vault/{dest}")


def cmd_vault_downloads(args):
    while True:
        rows = call("GET", "/api/vault/downloads")["data"]
        rows = [r for r in rows if r["targetPath"].startswith(args.prefix)]
        active = [r for r in rows if r["status"] in ("pending", "downloading")]
        for r in rows:
            pct = f"{100 * r['bytesDownloaded'] / r['totalBytes']:5.1f}%" if r.get("totalBytes") else "  —  "
            print(f"{r['status']:<11} {pct} {r['targetPath']}" + (f"  ({r['error']})" if r.get("error") else ""))
        done = sum(r["bytesDownloaded"] or 0 for r in rows)
        print(f"-- {len(active)} active, {done / 1e9:.1f} GB downloaded")
        if not args.watch or not active:
            return
        time.sleep(args.watch)
        print()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("catalog"); p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_catalog)
    p = sub.add_parser("nodes"); p.add_argument("catalog_id"); p.set_defaults(fn=cmd_nodes)
    sub.add_parser("balance").set_defaults(fn=cmd_balance)
    p = sub.add_parser("deploy"); p.add_argument("--gpu", required=True, help='substring of the catalog name, e.g. "RTX 5090" or "PRO 6000"')
    p.add_argument("--image", default=DEFAULT_IMAGE); p.add_argument("--hours", type=float, default=12, help="auto-stop after this many hours")
    p.add_argument("--bandwidth", type=int, default=100); p.add_argument("--env", action="append", help="KEY=VALUE for the container"); p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_deploy)
    p = sub.add_parser("list"); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("get"); p.add_argument("id"); p.set_defaults(fn=cmd_get)
    p = sub.add_parser("stop"); p.add_argument("id"); p.set_defaults(fn=cmd_stop)
    p = sub.add_parser("delete"); p.add_argument("id"); p.set_defaults(fn=cmd_delete)
    p = sub.add_parser("auto-stop"); p.add_argument("id"); p.add_argument("--at"); p.add_argument("--extend", type=float); p.add_argument("--cancel", action="store_true"); p.set_defaults(fn=cmd_auto_stop)
    p = sub.add_parser("ssh"); p.add_argument("id"); p.add_argument("cmd", nargs="*"); p.set_defaults(fn=cmd_ssh)
    p = sub.add_parser("sync"); p.add_argument("id"); p.set_defaults(fn=cmd_sync)
    p = sub.add_parser("push"); p.add_argument("id"); p.add_argument("local"); p.add_argument("remote"); p.set_defaults(fn=cmd_push)
    p = sub.add_parser("fetch"); p.add_argument("id"); p.add_argument("remote"); p.add_argument("local"); p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("backup", help="pull /vault research data and logs to this machine"); p.add_argument("id"); p.add_argument("--every", type=int, default=0, help="repeat every N seconds"); p.set_defaults(fn=cmd_backup)
    p = sub.add_parser("run"); p.add_argument("id"); p.add_argument("--name"); p.add_argument("cmd", nargs="+"); p.set_defaults(fn=cmd_run)
    p = sub.add_parser("jobs", help="list the jobs `run` started on the instance"); p.add_argument("id"); p.set_defaults(fn=cmd_jobs)
    p = sub.add_parser("kill", help="stop a job `run` started, by its pid file"); p.add_argument("id"); p.add_argument("name"); p.set_defaults(fn=cmd_kill)
    p = sub.add_parser("vault-upload"); p.add_argument("local"); p.add_argument("--path", default="work"); p.set_defaults(fn=cmd_vault_upload)
    p = sub.add_parser("vault-fetch", help="GPUtw downloads a Hugging Face model into the Vault"); p.add_argument("hf_id"); p.add_argument("--dest", help="Vault path (default work/models/<name>)"); p.set_defaults(fn=cmd_vault_fetch)
    p = sub.add_parser("vault-downloads"); p.add_argument("--prefix", default="work/"); p.add_argument("--watch", type=int, default=0, help="refresh every N seconds until none is active"); p.set_defaults(fn=cmd_vault_downloads)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
