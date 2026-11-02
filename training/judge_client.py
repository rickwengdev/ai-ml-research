"""The judge's Claude client (experiments/judge.py) and small JSONL helpers."""
import hashlib, json, os, re, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "training", "data", "cache")  # Claude's request/answer files, reused by re-runs


def json_of(text):
    """The first JSON object in a reply, or None."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


class Claude:
    """Claude through the Claude Agent SDK (training/claude_batch.mts), with the persona's Claude Code sign-in.
    Requests go out as one batch per stage; the batch's answers file is its cache, kept in data/cache whatever
    folder the caller writes its results to."""

    def __init__(self, model="opus", concurrency=3):
        self.model, self.concurrency, self.name = model, concurrency, f"claude_{slug(model)}"

    def ask_many(self, requests, stage, out_dir, temperature=None, max_tokens=None):
        # One request per key (a repeated key would be asked once), each id derived from its own key.
        unique = list({key: (key, system, user) for key, system, user in requests}.values())
        rows = [(f"{stage}:{hashlib.sha1(key.encode()).hexdigest()[:16]}", key, system, user) for key, system, user in unique]
        ids = {rid: key for rid, key, _, _ in rows}
        # Absolute: the batch runs from the repository root.
        os.makedirs(CACHE, exist_ok=True)
        req_path = os.path.join(CACHE, f"{self.name}_{stage}_requests.jsonl")
        ans_path = os.path.join(CACHE, f"{self.name}_{stage}_answers.jsonl")
        write_jsonl(req_path, [{"id": rid, "system": system, "user": user} for rid, _, system, user in rows])
        if requests:
            subprocess.run(
                [os.path.join(REPO, "node_modules", ".bin", "tsx"), os.path.join(REPO, "training", "claude_batch.mts"), req_path, ans_path, "--model", self.model, "--concurrency", str(self.concurrency)],
                check=True, cwd=REPO,
            )
        answers = {}
        for row in read_jsonl(ans_path):
            if row.get("id") in ids and "text" in row:
                answers[ids[row["id"]]] = row["text"]
            elif row.get("id") in ids:
                print(f"  {stage}: {row.get('error', '')[:120]}", file=sys.stderr)
        return answers


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def slug(model):
    return re.sub(r"[^\w.-]+", "_", model)
