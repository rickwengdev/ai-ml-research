/**
 * Answers a batch of single-turn requests with Claude.
 *
 * With API keys (the default when ~/.persona/anthropic-keys exists, one key per line, or ANTHROPIC_API_KEYS is set,
 * comma-separated): the Messages API through @anthropic-ai/sdk, the keys taken in turn by the workers, and a request
 * the API rate-limits or overloads retried on the next key after a pause.
 * Without keys, or with --via signin: the Claude Agent SDK on the sign-in the persona's Claude Code hand-off uses
 * (<data>/claude), with no tools, no settings files and no saved session.
 *
 * Reads {"id", "system", "user"} lines and appends {"id", "text"} (or {"id", "error"}) lines; ids already answered in
 * the output are skipped, so a stopped batch resumes.
 *
 * Every API call's tokens and estimated cost go to <data>/anthropic-usage.jsonl. A budget in
 * <data>/anthropic-budget.json ({"usd": 105, "expires": "2026-11-22"}) is a hard cap: once the ledger reaches it, the
 * batch stops asking and records the remaining requests as errors (a re-run picks them up if the budget grows).
 * --effort low|medium|high sets the thinking effort (Opus 5.5's default is medium; judging needs little).
 *
 * usage: npx tsx training/claude_batch.mts <requests.jsonl> <answers.jsonl> [--model opus] [--concurrency 3] [--via api|signin] [--effort low] [--tag name]
 */
import { existsSync, mkdirSync, readFileSync, appendFileSync } from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

type Request = { id: string; system: string; user: string };

const [input, output, ...rest] = process.argv.slice(2);
if (!input || !output) throw new Error("usage: claude_batch.mts <requests.jsonl> <answers.jsonl> [--model opus] [--concurrency 3] [--via api|signin]");
const flag = (name: string, fallback: string) => {
  const at = rest.indexOf(`--${name}`);
  return at >= 0 && rest[at + 1] ? rest[at + 1]! : fallback;
};
const model = flag("model", "opus");
const concurrency = Number(flag("concurrency", "3"));
const dataDir = process.env.ENGINE_DATA_DIR ?? path.join(os.homedir(), ".persona");

const lines = (file: string) => (existsSync(file) ? readFileSync(file, "utf8").split("\n").filter((line) => line.trim()) : []);
const done = new Set(
  lines(output)
    .map((line) => JSON.parse(line) as { id: string; text?: string })
    .filter((row) => row.text !== undefined)
    .map((row) => row.id),
);
const requests = lines(input).map((line) => JSON.parse(line) as Request).filter((request) => !done.has(request.id));

// The packages are the runtime's (hoisted to the root node_modules by the workspace); this file sits outside it.
const require = createRequire(path.join(import.meta.dirname, "..", "apps", "runtime", "package.json"));

const keysFile = path.join(dataDir, "anthropic-keys");
const keys = (process.env.ANTHROPIC_API_KEYS?.split(",") ?? (existsSync(keysFile) ? readFileSync(keysFile, "utf8").split("\n") : [])).map((key) => key.trim()).filter(Boolean);
const via = flag("via", keys.length ? "api" : "signin");

/** The model names a caller gives ("opus", "sonnet") as API model ids; a full id passes through. */
const MODEL_IDS: Record<string, string> = { opus: "claude-opus-5-5", sonnet: "claude-sonnet-5-5", haiku: "claude-haiku-5-5", fable: "claude-fable-5-1" };
const modelId = MODEL_IDS[model] ?? model;
const effort = flag("effort", "low") as "low" | "medium" | "high";
const tag = flag("tag", path.basename(output).replace(/\.jsonl$/, ""));

/** $ per million tokens (input, output, cache read), from the Claude API reference; the Batch API halves them. */
const PRICES: Record<string, [number, number, number]> = {
  "claude-opus-5-5": [4, 20, 0.2],
  "claude-sonnet-5-5": [2, 10, 0.2],
  "claude-haiku-5-5": [0.1, 0.5, 0.01],
  "claude-fable-5-1": [10, 50, 0.25],
};
const ledgerFile = path.join(dataDir, "anthropic-usage.jsonl");
const budgetFile = path.join(dataDir, "anthropic-budget.json");
const budget = existsSync(budgetFile) ? (JSON.parse(readFileSync(budgetFile, "utf8")) as { usd: number; expires?: string }) : null;
let spent = lines(ledgerFile).reduce((sum, line) => sum + ((JSON.parse(line) as { usd?: number }).usd ?? 0), 0);

let answer: (request: Request, worker: number) => Promise<string>;

if (via === "api") {
  if (!keys.length) throw new Error(`no API keys: put one per line in ${keysFile} or set ANTHROPIC_API_KEYS`);
  const { default: Anthropic } = (await import(pathToFileURL(require.resolve("@anthropic-ai/sdk")).href)) as typeof import("@anthropic-ai/sdk");
  const clients = keys.map((apiKey) => new Anthropic({ apiKey, maxRetries: 0 }));
  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
  // Keys whose account has run out of credit; the others carry on without them.
  const spentKeys = new Set<number>();
  answer = async (request, worker) => {
    // Each worker starts on its own key; a rate limit or overload moves it to the next one.
    for (let attempt = 0; attempt < 6; attempt++) {
      const live = clients.map((_, index) => index).filter((index) => !spentKeys.has(index));
      if (!live.length) throw new Error("every key is out of credit");
      const keyIndex = live[(worker + attempt) % live.length]!;
      const client = clients[keyIndex]!;
      try {
        if (budget && spent >= budget.usd) throw new Error(`budget reached: $${spent.toFixed(2)} of $${budget.usd}`);
        const message = await client.messages.create({ model: modelId, max_tokens: 4096, system: request.system, messages: [{ role: "user", content: request.user }], output_config: { effort } } as Parameters<typeof client.messages.create>[0]) as import("@anthropic-ai/sdk").default.Message;
        const [pin, pout, pcache] = PRICES[modelId] ?? [0, 0, 0];
        const u = message.usage;
        const usd = ((u.input_tokens ?? 0) * pin + (u.output_tokens ?? 0) * pout + (u.cache_read_input_tokens ?? 0) * pcache) / 1e6;
        spent += usd;
        appendFileSync(ledgerFile, `${JSON.stringify({ at: new Date().toISOString(), tag, model: modelId, key: keyIndex, input: u.input_tokens, output: u.output_tokens, cache_read: u.cache_read_input_tokens ?? 0, usd: Number(usd.toFixed(5)) })}\n`);
        if (message.stop_reason === "refusal") throw new Error("refusal");
        return message.content.flatMap((block) => (block.type === "text" ? [block.text] : [])).join("");
      } catch (error) {
        const status = (error as { status?: number }).status;
        if (status === 400 && /credit balance is too low/i.test((error as Error).message)) {
          if (!spentKeys.has(keyIndex)) process.stderr.write(`  key ${keyIndex} is out of credit; going on without it\n`);
          spentKeys.add(keyIndex);
          continue;
        }
        if (status === 429 || status === 529 || status === 500 || status === 503) {
          await sleep(2000 * 2 ** attempt);
          continue;
        }
        throw error;
      }
    }
    throw new Error("rate-limited on every key");
  };
} else {
  const { query } = (await import(pathToFileURL(require.resolve("@anthropic-ai/claude-agent-sdk")).href)) as typeof import("@anthropic-ai/claude-agent-sdk");
  // The platform's `claude` binary that ships with the SDK (as the runtime finds it).
  const cli = path.join(path.dirname(require.resolve(`@anthropic-ai/claude-agent-sdk-${process.platform}-${process.arch}/package.json`)), "claude");
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) if (value !== undefined) env[key] = value;
  env.CLAUDE_CONFIG_DIR = process.env.ENGINE_CLAUDE_CONFIG_DIR ?? path.join(dataDir, "claude");
  const cwd = path.join(os.tmpdir(), "persona-claude-batch");
  mkdirSync(cwd, { recursive: true });
  answer = async (request) => {
    let text = "";
    for await (const message of query({
      prompt: request.user,
      options: { cwd, env, model, pathToClaudeCodeExecutable: cli, systemPrompt: request.system, settingSources: [], tools: [], maxTurns: 1, persistSession: false },
    })) {
      if (message.type === "result") {
        if (message.subtype === "success" && !message.is_error) text = message.result;
        else throw new Error(("result" in message && typeof message.result === "string" && message.result) || message.subtype);
      }
    }
    return text;
  };
}

process.stderr.write(`  claude via ${via}${via === "api" ? ` (${keys.length} keys, ${modelId}, effort ${effort}; spent so far $${spent.toFixed(2)}${budget ? ` of $${budget.usd}` : ""})` : ""}: ${requests.length} requests\n`);
let next = 0;
let finished = 0;
async function worker(index: number): Promise<void> {
  while (next < requests.length) {
    const request = requests[next++]!;
    try {
      appendFileSync(output, `${JSON.stringify({ id: request.id, text: await answer(request, index) })}\n`);
    } catch (error) {
      appendFileSync(output, `${JSON.stringify({ id: request.id, error: error instanceof Error ? error.message : String(error) })}\n`);
    }
    finished += 1;
    process.stderr.write(`  claude ${finished}/${requests.length}\n`);
  }
}
await Promise.all(Array.from({ length: Math.min(concurrency, requests.length) }, (_, index) => worker(index)));
if (via === "api") process.stderr.write(`  spent $${spent.toFixed(2)}${budget ? ` of $${budget.usd}` : ""}\n`);
