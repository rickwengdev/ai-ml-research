#!/usr/bin/env python3
"""Google Cloud adapter, the backup to GPUtw: a GPU VM with the same layout (/vault/work for code, data and logs on
a persistent disk; /workspace on the boot disk for the venv and model weights), so bootstrap.sh, the experiment
commands and monitor.py run unchanged. Everything goes through `gcloud`; nothing here holds a credential.

The project is never taken from gcloud's default: pass --project or set RESEARCH_GCP_PROJECT, so a research VM cannot
land in an unrelated project by accident. Every create prints its estimated cost and needs --yes.

  prices                                  approximate hourly prices of the GPU profiles (us-central1, 2026-11)
  images                                  Deep Learning VM image families with CUDA 12.8 or newer
  zones --gpu P                           zones that offer that GPU profile
  quota [--region R]                      GPU quota of the project (global, and per region)
  vault-create --zone Z [--size 50]       the persistent disk mounted at /vault (once per zone; outlives VMs)
  create NAME --gpu P --zone Z --hours H [--spot] [--yes] [--dry-run]
  list | status NAME | stop NAME | start NAME | delete NAME   (delete keeps the vault disk)
  ssh NAME [-- cmd ...] | sync NAME | push NAME LOCAL REMOTE | fetch NAME REMOTE LOCAL
  backup NAME [--every 300] | run NAME [--job name] -- CMD ... | tunnel NAME [--port 8090]

GPU profiles: rtx6000 (g4-standard-48, RTX PRO 6000 96 GB: 27B bf16 at batch 24), a100-80 (a2-ultragpu-1g: 27B
bf16 at a smaller batch), a100-40 (a2-highgpu-1g), l4 (g2-standard-8, 24 GB: 9B only).

usage: gcp.py <command> [...] --project P   (or RESEARCH_GCP_PROJECT=P)
"""
import argparse, json, os, shlex, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
REMOTE_ROOT = "/vault/work"
STATE = os.path.expanduser("~/.config/gputw/gcp-instances.json")  # name -> {project, zone}, so later commands need only NAME
IMAGE_PROJECT = "deeplearning-platform-release"
# PyTorch 2.9, CUDA 12.9, NVIDIA driver 580: Blackwell (RTX PRO 6000) and Ampere alike. Listed by `gcp.py images`.
DEFAULT_IMAGE_FAMILY = "pytorch-2-9-cu129-ubuntu-2204-nvidia-580"
VAULT_DISK = "research-vault"
LABELS = "purpose=ai-ml-research"

# Accelerator-optimized machine types carry their GPU; no --accelerator flag. Prices in USD per hour, approximate
# (us-central1, 2026-11: Google's pricing page for g4 on demand, third-party trackers for the rest and for Spot;
# Spot moves with demand and region). They are for the cost estimate printed before a create, not for billing.
PROFILES = {
    "rtx6000": {"machine": "g4-standard-48", "gpu": "RTX PRO 6000 96 GB", "on_demand": 4.50, "spot": 2.25, "boot_gb": 200},
    "a100-80": {"machine": "a2-ultragpu-1g", "gpu": "A100 80 GB", "on_demand": 5.07, "spot": 3.04, "boot_gb": 200},
    "a100-40": {"machine": "a2-highgpu-1g", "gpu": "A100 40 GB", "on_demand": 3.67, "spot": 2.20, "boot_gb": 200},
    "l4": {"machine": "g2-standard-8", "gpu": "L4 24 GB", "on_demand": 0.85, "spot": 0.45, "boot_gb": 150},
}
DISK_PER_GB_MONTH = {"pd-balanced": 0.10, "pd-ssd": 0.17, "pd-standard": 0.04}  # charged while the disk exists, VM running or not

STARTUP = r"""#!/bin/bash
# ai-ml-research, every boot (as root): the persistent vault disk at /vault, /workspace on the boot disk.
set -e
DEV=/dev/disk/by-id/google-vault
if [ -e "$DEV" ]; then
  blkid "$DEV" >/dev/null 2>&1 || mkfs.ext4 -m 0 -E lazy_itable_init=0,lazy_journal_init=0,discard "$DEV"
  mkdir -p /vault
  mountpoint -q /vault || mount -o discard,defaults "$DEV" /vault
fi
mkdir -p /vault/work /workspace
chmod 1777 /vault /vault/work /workspace
"""


# ── plumbing ────────────────────────────────────────────────────────────────


def project_of(args):
    project = getattr(args, "project", None) or os.environ.get("RESEARCH_GCP_PROJECT")
    if not project:
        sys.exit("no project: pass --project or set RESEARCH_GCP_PROJECT (gcloud's default project is never used)")
    return project


def gcloud(*argv, project=None, capture=False, check=True, dry=False):
    cmd = ["gcloud", *argv] + ([f"--project={project}"] if project else [])
    if dry:
        print(" ".join(shlex.quote(c) for c in cmd))
        return ""
    if capture:
        out = subprocess.run(cmd, capture_output=True, text=True)
        if check and out.returncode != 0:
            sys.exit(f"gcloud failed: {' '.join(argv[:4])} …\n{out.stderr.strip()[-1500:]}")
        return out.stdout
    subprocess.run(cmd, check=check)
    return ""


def load_state():
    try:
        return json.load(open(STATE))
    except (OSError, json.JSONDecodeError):
        return {}


def remember(name, project, zone):
    state = load_state()
    state[name] = {"project": project, "zone": zone}
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(state, f, indent=1)


def where(args):
    """(project, zone) of an instance: flags first, then what create remembered."""
    known = load_state().get(args.name, {})
    project = getattr(args, "project", None) or os.environ.get("RESEARCH_GCP_PROJECT") or known.get("project")
    zone = getattr(args, "zone", None) or known.get("zone")
    if not project or not zone:
        sys.exit(f"don't know where {args.name} is: pass --project and --zone")
    return project, zone


def host(args):
    """The ssh alias `gcloud compute config-ssh` writes: NAME.ZONE.PROJECT (refreshed on demand)."""
    project, zone = where(args)
    alias = f"{args.name}.{zone}.{project}"
    config = os.path.expanduser("~/.ssh/config")
    if not os.path.exists(config) or f"Host {alias}" not in open(config).read():
        gcloud("compute", "config-ssh", "--quiet", project=project)
    return alias


def ssh_base(args):
    return ["ssh", "-o", "StrictHostKeyChecking=accept-new", host(args)]


def rsync(src, dst, excludes=()):
    cmd = ["rsync", "-az", "-e", "ssh -o StrictHostKeyChecking=accept-new"] + [f"--exclude={e}" for e in excludes] + [src, dst]
    print(" ".join(shlex.quote(c) for c in cmd), file=sys.stderr)
    subprocess.run(cmd, check=True)


# ── catalog and setup ───────────────────────────────────────────────────────


def cmd_prices(args):
    print(f"{'profile':9s} {'machine':16s} {'GPU':20s} {'on demand':>10s} {'spot':>7s}   hours for $80 (spot / on demand)")
    for key, p in PROFILES.items():
        print(f"{key:9s} {p['machine']:16s} {p['gpu']:20s} {p['on_demand']:>9.2f}  {p['spot']:>6.2f}   {80 / p['spot']:5.0f} / {80 / p['on_demand']:3.0f}")
    print("\napproximate; Spot varies by region and over time. Disks bill while they exist, even with the VM stopped.")


def cmd_images(args):
    out = gcloud("compute", "images", "list", f"--project={IMAGE_PROJECT}", "--no-standard-images", "--filter=family~cu12", "--format=value(family)", capture=True)
    for family in sorted({f for f in out.split() if any(t in f for t in ("cu128", "cu129", "cu13"))}):
        print(family + ("   (default)" if family == DEFAULT_IMAGE_FAMILY else ""))


def cmd_zones(args):
    project = project_of(args)
    machine = PROFILES[args.gpu]["machine"]
    out = gcloud("compute", "machine-types", "list", f"--filter=name={machine}", "--format=value(zone)", project=project, capture=True)
    zones = sorted(set(out.split()))
    print(f"{machine} ({PROFILES[args.gpu]['gpu']}) in {len(zones)} zones:\n" + "\n".join(zones))


def cmd_quota(args):
    project = project_of(args)
    info = json.loads(gcloud("compute", "project-info", "describe", "--format=json", project=project, capture=True))
    for q in info.get("quotas", []):
        if "GPU" in q["metric"]:
            print(f"global  {q['metric']:40s} {q['usage']:>4.0f} / {q['limit']:.0f}")
    if args.region:
        region = json.loads(gcloud("compute", "regions", "describe", args.region, "--format=json", project=project, capture=True))
        for q in region.get("quotas", []):
            if "GPU" in q["metric"] or "RTX" in q["metric"] or "A100" in q["metric"] or "L4" in q["metric"]:
                print(f"{args.region:7s} {q['metric']:40s} {q['usage']:>4.0f} / {q['limit']:.0f}")
    print("\nA 0 limit on GPUS_ALL_REGIONS means the project cannot start any GPU VM yet: upgrade a free-trial billing account,"
          " then request an increase under IAM & Admin > Quotas.")


def cmd_vault_create(args):
    project = project_of(args)
    monthly = args.size * DISK_PER_GB_MONTH[args.type]
    print(f"persistent disk {VAULT_DISK} in {args.zone}: {args.size} GB {args.type}, about ${monthly:.0f} a month while it exists", file=sys.stderr)
    gcloud("compute", "disks", "create", VAULT_DISK, f"--zone={args.zone}", f"--size={args.size}GB", f"--type={args.type}", f"--labels={LABELS}",
           project=project, dry=args.dry_run)


# ── instances ───────────────────────────────────────────────────────────────


def cmd_create(args):
    project = project_of(args)
    p = PROFILES[args.gpu]
    rate = p["spot"] if args.spot else p["on_demand"]
    boot = args.boot_gb or p["boot_gb"]
    disk_hourly = boot * DISK_PER_GB_MONTH["pd-balanced"] / 730
    estimate = args.hours * (rate + disk_hourly)
    print(f"{args.name}: {p['machine']} ({p['gpu']}), {'Spot' if args.spot else 'on demand'} ~${rate:.2f}/h + boot disk {boot} GB ~${disk_hourly:.3f}/h;"
          f" stops itself after {args.hours:g} h -> at most ~${estimate:.0f} (the vault disk is billed separately)", file=sys.stderr)
    if not args.dry_run:
        # Fail before creating anything when the image family has gone away (Deep Learning VM families are retired).
        gcloud("compute", "images", "describe-from-family", args.image_family, f"--project={IMAGE_PROJECT}", "--format=value(name)", capture=True)
        if not args.yes:
            sys.exit("not created: add --yes to confirm the cost above (or --dry-run to see the command)")
    startup = os.path.join(HERE, ".gcp-startup.sh")
    with open(startup, "w") as f:
        f.write(STARTUP)
    argv = ["compute", "instances", "create", args.name, f"--zone={args.zone}", f"--machine-type={p['machine']}",
            f"--image-project={IMAGE_PROJECT}", f"--image-family={args.image_family}", f"--boot-disk-size={boot}GB", "--boot-disk-type=pd-balanced",
            "--maintenance-policy=TERMINATE", f"--max-run-duration={int(args.hours * 3600)}s", "--instance-termination-action=STOP",
            "--metadata=install-nvidia-driver=True", f"--metadata-from-file=startup-script={startup}", f"--labels={LABELS}", "--scopes=default"]
    if args.spot:
        argv.append("--provisioning-model=SPOT")
    if not args.no_vault:
        argv.append(f"--disk=name={VAULT_DISK},device-name=vault,mode=rw,auto-delete=no")
    try:
        gcloud(*argv, project=project, dry=args.dry_run)
    finally:
        os.remove(startup)
    if args.dry_run:
        return
    remember(args.name, project, args.zone)
    gcloud("compute", "config-ssh", "--quiet", project=project)
    print(f"\ncreated {args.name}. The driver installs on first boot (a few minutes). Next:\n"
          f"  gcp.py ssh {args.name} -- nvidia-smi\n  gcp.py sync {args.name}\n"
          f"  gcp.py run {args.name} --job bootstrap -- bash {REMOTE_ROOT}/research/cloud/bootstrap.sh Qwen/Qwen3.5-27B", file=sys.stderr)


def cmd_list(args):
    gcloud("compute", "instances", "list", f"--filter=labels.purpose=ai-ml-research", "--format=table(name,zone.basename(),machineType.basename(),status,scheduling.provisioningModel)",
           project=project_of(args))


def cmd_status(args):
    project, zone = where(args)
    gcloud("compute", "instances", "describe", args.name, f"--zone={zone}", "--format=yaml(status,machineType.basename(),scheduling,lastStartTimestamp)", project=project)


def cmd_stop(args):
    project, zone = where(args)
    gcloud("compute", "instances", "stop", args.name, f"--zone={zone}", project=project)
    print("stopped: compute is no longer billed; the boot and vault disks still are until deleted", file=sys.stderr)


def cmd_start(args):
    project, zone = where(args)
    gcloud("compute", "instances", "start", args.name, f"--zone={zone}", project=project)


def cmd_delete(args):
    project, zone = where(args)
    gcloud("compute", "instances", "delete", args.name, f"--zone={zone}", "--quiet", project=project)
    state = load_state()
    state.pop(args.name, None)
    with open(STATE, "w") as f:
        json.dump(state, f, indent=1)
    print(f"deleted {args.name} and its boot disk; the vault disk {VAULT_DISK} is kept (delete it with gcloud when done)", file=sys.stderr)


# ── the same workflow as gputw.py ───────────────────────────────────────────


def cmd_ssh(args):
    cmd = ssh_base(args) + ([" ".join(shlex.quote(c) for c in args.cmd)] if args.cmd else [])
    os.execvp("ssh", cmd)


def cmd_sync(args):
    target = host(args)
    subprocess.run(ssh_base(args) + [f"mkdir -p {REMOTE_ROOT}/research {REMOTE_ROOT}/services/model-server {REMOTE_ROOT}/logs"], check=True)
    rsync(os.path.join(REPO, "services", "model-server") + "/", f"{target}:{REMOTE_ROOT}/services/model-server/", excludes=(".venv", ".venv-torch", "__pycache__", "vectors/*.npz"))
    rsync(os.path.join(REPO, "research") + "/", f"{target}:{REMOTE_ROOT}/research/", excludes=("data", "subjects", "figures/*.png", "__pycache__", ".venv*", ".gcp-startup.sh"))


def cmd_push(args):
    rsync(args.local.rstrip("/"), f"{host(args)}:{args.remote}")


def cmd_fetch(args):
    os.makedirs(args.local, exist_ok=True)
    rsync(f"{host(args)}:{args.remote.rstrip('/')}/", args.local.rstrip("/") + "/")


def cmd_backup(args):
    """Pull research/data/* and the logs from /vault to this machine, once or every --every seconds. Never deletes here."""
    target = host(args)
    local_logs = os.path.join(REPO, "research", "cloud", "logs")
    os.makedirs(local_logs, exist_ok=True)
    while True:
        started = time.strftime("%H:%M:%S")
        try:
            rsync(f"{target}:{REMOTE_ROOT}/research/data/", os.path.join(REPO, "research", "data") + "/", excludes=("*.tmp.npy",))
            rsync(f"{target}:{REMOTE_ROOT}/logs/", local_logs + "/", excludes=("*.pid",))
            print(f"[backup] {started} ok", file=sys.stderr, flush=True)
        except subprocess.CalledProcessError as e:
            print(f"[backup] {started} failed: {e}", file=sys.stderr, flush=True)
        if not args.every:
            return
        time.sleep(args.every)


def cmd_run(args):
    name = args.job or time.strftime("job-%Y%m%d-%H%M%S")
    log = f"{REMOTE_ROOT}/logs/{name}.log"
    remote = f"cd {REMOTE_ROOT} && setsid nohup bash -lc {shlex.quote(' '.join(args.cmd))} > {log} 2>&1 < /dev/null & echo $! > {REMOTE_ROOT}/logs/{name}.pid; echo started $(cat {REMOTE_ROOT}/logs/{name}.pid) log {log}"
    try:
        subprocess.run(ssh_base(args) + [remote], check=True, timeout=30)
    except subprocess.TimeoutExpired:
        print(f"started (session cut); log {log}", file=sys.stderr)


def cmd_tunnel(args):
    """The run monitor (research/cloud/monitor.py, 127.0.0.1 on the VM) on this machine's port, in the background."""
    subprocess.run(["ssh", "-f", "-N", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=30", "-L", f"{args.port}:127.0.0.1:{args.port}", host(args)], check=True)
    print(f"monitor at http://localhost:{args.port}; the research UI's GPU page reads it there too", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, *, project=True, instance=False, zone=False):
        p = sub.add_parser(name)
        if project:
            p.add_argument("--project")
        if instance:
            p.add_argument("name")
        if zone:
            p.add_argument("--zone", required=zone == "required")
        p.set_defaults(fn=fn)
        return p

    add("prices", cmd_prices, project=False)
    add("images", cmd_images, project=False)
    add("zones", cmd_zones).add_argument("--gpu", choices=PROFILES, required=True)
    add("quota", cmd_quota).add_argument("--region")
    p = add("vault-create", cmd_vault_create, zone="required")
    p.add_argument("--size", type=int, default=50, help="GB; code, results and logs only: weights live on the boot disk")
    p.add_argument("--type", choices=DISK_PER_GB_MONTH, default="pd-balanced")
    p.add_argument("--dry-run", action="store_true")
    p = add("create", cmd_create, instance=True, zone="required")
    p.add_argument("--gpu", choices=PROFILES, required=True)
    p.add_argument("--hours", type=float, required=True, help="the VM stops itself after this many hours")
    p.add_argument("--spot", action="store_true", help="Spot: about half the price; Google may stop it at any time (the runs resume)")
    p.add_argument("--image-family", default=DEFAULT_IMAGE_FAMILY)
    p.add_argument("--boot-gb", type=int)
    p.add_argument("--no-vault", action="store_true", help="no persistent disk: /vault is on the boot disk and goes with the VM")
    p.add_argument("--yes", action="store_true", help="confirm the estimated cost")
    p.add_argument("--dry-run", action="store_true")
    add("list", cmd_list)
    for name, fn in (("status", cmd_status), ("stop", cmd_stop), ("start", cmd_start), ("delete", cmd_delete), ("sync", cmd_sync)):
        add(name, fn, instance=True, zone=True)
    add("ssh", cmd_ssh, instance=True, zone=True).add_argument("cmd", nargs="*")
    p = add("push", cmd_push, instance=True, zone=True)
    p.add_argument("local")
    p.add_argument("remote")
    p = add("fetch", cmd_fetch, instance=True, zone=True)
    p.add_argument("remote")
    p.add_argument("local")
    add("backup", cmd_backup, instance=True, zone=True).add_argument("--every", type=int, default=0)
    p = add("run", cmd_run, instance=True, zone=True)
    p.add_argument("--job", help="the job's name: its log is /vault/work/logs/<job>.log")
    p.add_argument("cmd", nargs="+")
    add("tunnel", cmd_tunnel, instance=True, zone=True).add_argument("--port", type=int, default=8090)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
