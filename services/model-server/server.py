#!/usr/bin/env python3
"""The local model server: OpenAI-compatible, over mlx, with activation steering.

One process serves every local model — the chat model, the small one for quick
judgments, the embedding model for memory — loading each when first asked for (engine.py). A chat request may carry
`steering`: {"energy": -0.4, "guard": 0.6, ...}, the model's behavior vector (the runtime); for a
model with control vectors it becomes a shift of the residual stream for that request (steer.py), and nothing about
it enters the prompt. Tools come through the model's own chat template and <tool_call> blocks, thinking through
<think> blocks, so the persona's OpenAI adapter needs nothing new.

Endpoints
  POST /v1/chat/completions   streaming (SSE) or not; every non-streamed response carries `persona.steering`
  POST /v1/embeddings
  GET  /v1/models             the configured models, with whether each is loaded and steerable
  GET  /health                ok, busy, memory, config, models
  GET  /config  PUT /config   read or change the configuration live (strength, mode, muting, model list)
  POST /divergence            KL between the plain and the intervened next-token distributions along a given reply
  POST /attribute             what pushed one token of the model's reply: input tokens, leanings per layer, steering (attribute.py)
  GET  /trace?after=N         the forward passes as they happen: per token, every layer's residual norm and its
                              projection onto the leaning directions (engine.py Trace), for the page that draws them
  POST /models/load  /models/unload   {"model": id}

The log prints one line per request saying what was applied: the leanings as sent, the effective alphas after
strength, damping and cap, which layers, and how many tokens were steered or muted. Nothing is hidden.

usage: server.py [--config steering.json] [--port 1235] [--preload]
       server.py --model mlx-community/Qwen3.5-4B-MLX-4bit [--strength 2.5] [--mode generate|always]
"""
import argparse
import json
import logging
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from engine import Config, ModelSpec, Registry

log = logging.getLogger("steering")

# ── what the model writes, and how it is read back ──────────────────────────

TOOL_CALL = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)
# Qwen3.5 writes calls as XML-ish blocks: <function=name><parameter=key>value</parameter>...</function>. JSON works too.
FUNCTION = re.compile(r"<function=([^>\n]+)>(.*?)</function>", re.S)
PARAMETER = re.compile(r"<parameter=([^>\n]+)>\n?(.*?)\n?</parameter>", re.S)
THINK = re.compile(r"<think>(.*?)</think>", re.S)


def parse_value(text):
    """A parameter value: JSON when it looks like JSON (objects, lists, numbers, booleans), else the text itself."""
    text = text.strip()
    if text and (text[0] in "{[-0123456789" or text in ("true", "false", "null")):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return text


def parse_call(raw):
    """One <tool_call> body as (name, arguments), or None when it is neither form."""
    raw = raw.strip()
    fn = FUNCTION.search(raw)
    if fn:
        return fn.group(1).strip(), {key: parse_value(value) for key, value in PARAMETER.findall(fn.group(2))}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and parsed.get("name"):
        return str(parsed["name"]), parsed["arguments"] if isinstance(parsed.get("arguments"), dict) else {}
    return None


def split_reply(text, thinking_open=False):
    """A finished generation into (content, reasoning, tool_calls). `thinking_open`: the prompt ended inside <think>."""
    # The template opens <think> inside the prompt, so a generation often starts mid-thought and only closes it; when
    # the budget runs out first there is no tag at all, and all of it is still reasoning.
    if thinking_open and "</think>" not in text:
        return "", text.strip(), []
    if "</think>" in text and "<think>" not in text.split("</think>", 1)[0]:
        text = "<think>" + text
    reasoning = "\n".join(t.strip() for t in THINK.findall(text)).strip()
    text = THINK.sub("", text)
    # An unclosed <think> means the budget ran out while thinking: that is reasoning, not an answer.
    if "<think>" in text:
        head, tail = text.split("<think>", 1)
        reasoning, text = (reasoning + "\n" + tail).strip(), head
    calls = []
    for raw in TOOL_CALL.findall(text):
        parsed = parse_call(raw)
        if parsed:
            name, args = parsed
            calls.append({"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
    return TOOL_CALL.sub("", text).strip(), reasoning, calls


FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n?```\s*$", re.S)


def unfenced(text):
    """JSON mode: a small model likes to wrap the object in a ```json fence; the client wants the object."""
    match = FENCE.match(text.strip())
    return match.group(1).strip() if match else text


class ContentStream:
    """Turns raw output into content deltas as it arrives: thinking and tool-call blocks are held back, and a piece
    is released only once it cannot be the start of a tag (so "<thi" waits for the rest)."""

    TAGS = ("<think>", "</think>", "<tool_call>", "</tool_call>")

    def __init__(self, thinking_open=False):
        self.buffer = ""
        self.hidden = 0  # open <think> or <tool_call> blocks
        # Qwen's template may open <think> inside the prompt: then the output is reasoning until its </think>.
        self.maybe_thinking = thinking_open

    def push(self, text):
        self.buffer += text
        out = ""
        while self.buffer:
            if self.buffer.startswith("<"):
                tag = next((t for t in self.TAGS if self.buffer.startswith(t)), None)
                if tag is None:
                    if any(t.startswith(self.buffer[: len(t)]) for t in self.TAGS if len(self.buffer) < len(t)):
                        break  # a tag may still be forming
                    out += self.emit(self.buffer[0])
                    self.buffer = self.buffer[1:]
                    continue
                self.buffer = self.buffer[len(tag) :]
                if tag == "</think>":
                    self.hidden, self.maybe_thinking = max(0, self.hidden - 1), False
                elif tag == "</tool_call>":
                    self.hidden = max(0, self.hidden - 1)
                elif tag == "<think>":
                    self.hidden, self.maybe_thinking = self.hidden + 1, False
                else:
                    self.hidden += 1
                continue
            cut = self.buffer.find("<")
            piece, self.buffer = (self.buffer, "") if cut < 0 else (self.buffer[:cut], self.buffer[cut:])
            out += self.emit(piece)
        return out

    def emit(self, piece):
        if self.hidden or self.maybe_thinking:
            return ""
        return piece


# ── responses ────────────────────────────────────────────────────────────────


def chat_response(model, gen, calls, content, reasoning):
    message = {"role": "assistant", "content": content}
    if reasoning:
        message["reasoning_content"] = reasoning
    if calls:
        message["tool_calls"] = calls
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model.id,
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else ("length" if gen.finish == "length" else "stop")}],
        "usage": {
            "prompt_tokens": gen.prompt_tokens,
            "completion_tokens": gen.generated_tokens,
            "total_tokens": gen.prompt_tokens + gen.generated_tokens,
            "prompt_tokens_details": {"cached_tokens": gen.cached_tokens},
        },
        # What steering did, in plain terms; clients that do not know the field ignore it.
        "persona": {"steering": gen.applied.as_dict() if gen.applied else None},
    }


def log_request(model, gen, calls):
    log.info(
        "%s: %d prompt (%d cached) + %d generated tokens in %.1fs%s | %s | %d tool call(s)",
        model.id.split("/")[-1],
        gen.prompt_tokens,
        gen.cached_tokens,
        gen.generated_tokens,
        gen.seconds,
        ", thought closed at its budget" if gen.thought_closed else "",
        gen.applied.summary() if gen.applied else "no steering",
        len(calls),
    )


# ── HTTP ────────────────────────────────────────────────────────────────────


def make_handler(registry: Registry):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # the engine logs what matters
            pass

        def send_json(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def send_error_json(self, status, message):
            self.send_json(status, {"error": {"message": message, "type": "invalid_request_error" if status < 500 else "server_error"}})

        def body(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            return json.loads(raw or b"{}")

        def route(self):
            return self.path.split("?", 1)[0].rstrip("/")

        def do_GET(self):
            route = self.route()
            if route in ("/v1/models", "/models"):
                data = [{"id": m["id"], "object": "model", "owned_by": "persona", "persona": m} for m in registry.status()["models"]]
                return self.send_json(200, {"object": "list", "data": data})
            if route == "/health":
                return self.send_json(200, registry.status())
            if route == "/config":
                return self.send_json(200, registry.config.as_dict())
            if route == "/trace":
                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                after = next((int(v) for k, v in (pair.split("=", 1) for pair in query.split("&") if "=" in pair) if k == "after" and v.isdigit()), 0)
                return self.send_json(200, registry.trace.since(after))
            self.send_error_json(404, "not found")

        def do_PUT(self):
            if self.route() != "/config":
                return self.send_error_json(404, "not found")
            try:
                registry.apply(Config.of(self.body(), registry.config))
            except (ValueError, KeyError, json.JSONDecodeError) as err:
                return self.send_error_json(400, f"bad config: {err}")
            self.send_json(200, registry.status())

        def do_POST(self):
            route = self.route()
            try:
                body = self.body()
            except json.JSONDecodeError as err:
                return self.send_error_json(400, f"bad json: {err}")
            try:
                if route in ("/v1/chat/completions", "/chat/completions"):
                    return self.stream_chat(body) if body.get("stream") else self.chat(body)
                if route in ("/v1/embeddings", "/embeddings"):
                    return self.embeddings(body)
                if route == "/attribute":
                    return self.send_json(200, registry.attribute(body))
                if route == "/divergence":
                    return self.send_json(200, registry.divergence(body))
                if route == "/models/load":
                    registry.get(str(body.get("model", "")))
                    return self.send_json(200, registry.status())
                if route == "/models/unload":
                    with registry.lock:
                        registry.unload(str(body.get("model", "")))
                    return self.send_json(200, registry.status())
                if route == "/config":
                    registry.apply(Config.of(body, registry.config))
                    return self.send_json(200, registry.status())
            except ValueError as err:
                return self.send_error_json(400, str(err))
            except Exception as err:  # noqa: BLE001 — report, keep serving
                log.exception("%s failed", route)
                return self.send_error_json(500, str(err))
            self.send_error_json(404, "not found")

        def chat(self, body):
            model, gen = registry.complete(body)
            content, reasoning, calls = split_reply(gen.text, gen.thinking_open)
            if (body.get("response_format") or {}).get("type") == "json_object":
                content = unfenced(content)
            log_request(model, gen, calls)
            self.send_json(200, chat_response(model, gen, calls, content, reasoning))

        def stream_chat(self, body):
            """Server-sent events, as OpenAI streams them: content deltas as they come, tool calls in a final chunk."""
            chat_id, created = f"chatcmpl-{uuid.uuid4().hex[:16]}", int(time.time())
            model_id = body.get("model") or ""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            def chunk(delta, finish=None, extra=None):
                payload = {"id": chat_id, "object": "chat.completion.chunk", "created": created, "model": model_id, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                if extra:
                    payload.update(extra)
                self.wfile.write(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()

            chunk({"role": "assistant", "content": ""})
            streams = []

            def emit(text, gen):
                if not streams:
                    streams.append(ContentStream(gen.thinking_open))
                piece = streams[0].push(text)
                if piece:
                    chunk({"content": piece})

            model, gen = registry.complete(body, emit)
            content, reasoning, calls = split_reply(gen.text, gen.thinking_open)
            log_request(model, gen, calls)
            if calls:
                chunk({"tool_calls": [{"index": i, **call} for i, call in enumerate(calls)]})
            finish = "tool_calls" if calls else ("length" if gen.finish == "length" else "stop")
            usage = {"prompt_tokens": gen.prompt_tokens, "completion_tokens": gen.generated_tokens, "total_tokens": gen.prompt_tokens + gen.generated_tokens}
            chunk({}, finish, {"usage": usage, "persona": {"steering": gen.applied.as_dict() if gen.applied else None}})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

        def embeddings(self, body):
            started = time.time()
            model, vectors = registry.embed(body)
            tokens = sum(len(t) for t in ([body["input"]] if isinstance(body.get("input"), str) else body.get("input", [])))
            log.info("%s: embedded %d text(s) in %.2fs", model.id.split("/")[-1], len(vectors), time.time() - started)
            self.send_json(
                200,
                {
                    "object": "list",
                    "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)],
                    "model": model.id,
                    "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
                },
            )

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="JSON file: models, strength, mode, mute_tool_calls (see engine.py)")
    ap.add_argument("--model", action="append", default=[], help="a chat model to serve (repeatable); with --config, added to it")
    ap.add_argument("--embedding-model", action="append", default=[], help="an embedding model to serve (repeatable)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1235)
    ap.add_argument("--strength", type=float, help="multiplier on the model's leanings (-1..1); 2.5 puts a full leaning at a clear, still coherent effect")
    ap.add_argument("--mode", choices=["generate", "always"], help="steer only while generating (default), or the prompt too")
    ap.add_argument("--no-mute-tool-calls", action="store_true", help="keep steering inside <tool_call> blocks (default: muted there)")
    ap.add_argument("--preload", action="store_true", help="load every configured model at start instead of on first use")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "huggingface_hub", "urllib3", "filelock"):  # hub lookups are not what this log is for
        logging.getLogger(noisy).setLevel(logging.WARNING)

    config = Config.read(a.config) if a.config else Config()
    config.models += [ModelSpec(m) for m in a.model if config.spec(m) is None]
    config.models += [ModelSpec(m, "embedding") for m in a.embedding_model if config.spec(m) is None]
    if not config.models:
        config.models = [ModelSpec("mlx-community/Qwen3.5-4B-MLX-4bit")]
    if a.strength is not None:
        config.strength = a.strength
    if a.mode:
        config.mode = a.mode
    if a.no_mute_tool_calls:
        config.mute_tool_calls = False

    registry = Registry(config)
    registry.apply(config)
    server = ThreadingHTTPServer((a.host, a.port), make_handler(registry))
    server.daemon_threads = True
    log.info("listening on http://%s:%d/v1", a.host, a.port)
    if a.preload:
        registry.preload()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
