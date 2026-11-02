#!/usr/bin/env python3
"""PyTorch backend for the model server's steering and readouts: the same operations engine.py/steer.py do on MLX,
on CUDA (bf16 or fp16 weights), with MPS/CPU for smoke tests. Meant for rented GPUs (research/cloud/) where mlx is
not available; nothing here imports mlx.

What it covers, in the experiments' terms:
  state(messages, tools)                 residual at the last prompt token, every layer -> (L, hidden) float32
  complete(body, strength)               one generation with thinking budget, tool-call/thinking muting, steering
                                         (add method on the band layers, per generated token) and a uniform band gain
  complete_batch(bodies, strength)       the same for several independent prompts at once (left-padded)
  teacher_logprobs(messages, tools, ids) next-token log-probabilities along a fixed reply, with or without steering

The request body follows engine.py: messages, tools, temperature, top_p, seed, max_tokens, thinking_budget, steering
({dim: leaning}), method ("add" only here), physio ({"NOREPINEPHRINE": 1.0}) + physio_params (band gain only).
Vectors come from the same npz files steer.py writes (meta + per-dim [layers, hidden] arrays).
"""
import contextlib, copy, json, os, re, time
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np
import torch

try:  # the shared constants and helpers when the MLX modules import cleanly; copies otherwise (a CUDA box has no mlx)
    from steer import LAYER_BAND, MAX_ALPHA, physio_of
except Exception:  # noqa: BLE001
    LAYER_BAND, MAX_ALPHA = (0.3, 0.8), 3.5
    HILL_N, PHYSIO = 2.0, {"band": 0.5, "late": 0.4, "social": 0.6, "explore": 0.4, "precision": 0.5, "hill_k": 0.5}

    def physio_of(deviation, stress=0.0, params=None):
        P = {**PHYSIO, **(params or {})}
        d = {k: float(deviation.get(k, 0.0) or 0.0) for k in ("NOREPINEPHRINE", "ADRENALINE", "ENDORPHIN", "CORTISOL", "OXYTOCIN", "DOPAMINE")}
        k = P["hill_k"]
        g = lambda x: (1 if x >= 0 else -1) * abs(x) ** HILL_N / (k**HILL_N + abs(x) ** HILL_N)
        arousal = g(d["NOREPINEPHRINE"] + 0.5 * d["ADRENALINE"] - 0.5 * d["ENDORPHIN"])
        strain = g(max(0.0, d["CORTISOL"]) + max(0.0, stress))
        return {"band_gain": 1.0 + P["band"] * arousal, "late_gain": 1.0 - P["late"] * strain, "social_gain": 1.0 + P["social"] * g(d["OXYTOCIN"]),
                "temperature": (1.0 + P["explore"] * max(0.0, g(d["DOPAMINE"]))) / (1.0 + P["precision"] * max(0.0, g(d["ADRENALINE"] + d["NOREPINEPHRINE"]))),
                "arousal": arousal, "strain": strain}


DEFAULT_MAX_TOKENS = 2048
THINK_CLOSE = "\n</think>\n\n"  # Qwen's; each model's own is ChatFormat.force_close


def to_template(messages):
    """OpenAI messages as the chat template wants them (engine.to_template)."""
    out, names = [], {}
    for m in messages:
        item = {"role": m.get("role", "user")}
        content = m.get("content")
        if isinstance(content, list):
            content = "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
        item["content"] = content or ""
        if m.get("tool_calls"):
            calls = []
            for call in m["tool_calls"]:
                fn = call.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                calls.append({"id": call.get("id", ""), "type": "function", "function": {"name": fn.get("name", ""), "arguments": args}})
                names[call.get("id", "")] = fn.get("name", "")
            item["tool_calls"] = calls
        if m.get("role") == "tool":
            # Gemma's template names the tool in its response block (`response:run_tests{...}`) and finds the name
            # through the call id; Qwen's ignores both. Keep the id and carry the name.
            item["tool_call_id"] = m.get("tool_call_id", "")
            if m.get("name") or names.get(item["tool_call_id"]):
                item["name"] = m.get("name") or names[item["tool_call_id"]]
        out.append(item)
    return out


def inside_tool_call(text, fmt=None):
    fmt = fmt or QWEN
    return text.count(fmt.call_open) > text.count(fmt.call_close)


def inside_thinking(text, thinking_open=False, fmt=None):
    fmt = fmt or QWEN
    if thinking_open and fmt.think_close not in text:
        return True
    return text.count(fmt.think_open) > text.count(fmt.think_close)


@dataclass
class Applied:
    alphas: dict
    layers: tuple
    method: str = "add"
    steered_tokens: int = 0
    muted_tokens: int = 0
    physio: dict | None = None

    def summary(self):
        parts = [f"{d} {a:+.2f}" for d, a in self.alphas.items()] or (["uniform gain"] if self.physio else ["no steering"])
        return f"{' '.join(parts)} on layers {self.layers[0]}–{self.layers[1] - 1} (generate, {self.method}); steered {self.steered_tokens} tokens, muted {self.muted_tokens}"


@dataclass
class Generation:
    text: str = ""
    prompt_tokens: int = 0
    generated_tokens: int = 0
    finish: str = "stop"
    seconds: float = 0.0
    applied: Applied | None = None
    thinking_open: bool = False
    thought_closed: bool = False
    tokens: list = field(default_factory=list)


class Vectors:
    """The npz steer.py writes: directions {dim: [layers, hidden]} and scales {dim: float}."""

    def __init__(self, directions, scales, layers=None, hidden=0):
        self.directions, self.scales, self.layers, self.hidden = directions, scales, layers or [], hidden

    @classmethod
    def load(cls, path):
        data = np.load(path)
        meta = json.loads(str(data["meta"]))
        return cls({dim: data[dim] for dim in meta["dims"]}, meta["scales"], meta["layers"], meta["hidden"])


def decoder_layers(model):
    for path in ("model.layers", "model.language_model.layers", "language_model.layers", "language_model.model.layers", "layers"):
        node = model
        try:
            for part in path.split("."):
                node = getattr(node, part)
        except AttributeError:
            continue
        if isinstance(node, torch.nn.ModuleList) and len(node):
            return list(node)
    raise RuntimeError("could not find the decoder layers")


class Steering:
    """Forward hooks on every decoder layer: capture of the last position, per-row additive deltas and a uniform
    band gain on decode steps (sequence length 1), with per-row muting."""

    def __init__(self, layers, band):
        self.layers, self.band = layers, band
        self.deltas = {}  # layer index -> tensor [B, hidden]
        self.band_gain = None  # tensor [B] or None
        self.muted = None  # bool tensor [B]; True = this row is muted for the current step
        self.capture = None  # None or dict layer -> tensor [B, hidden] (last position, float32, on CPU)
        self.caps = {}  # layer index -> (unit direction [hidden], ceiling per row [B]): Meek-style capping
        self.applied = None
        self._handles = []
        for i, layer in enumerate(layers):
            self._handles.append(layer.register_forward_hook(self._hook(i), with_kwargs=True))

    def _hook(self, i):
        def fn(module, args, kwargs, output):
            tupled = isinstance(output, tuple)
            out = output[0] if tupled else output
            if self.capture is not None:
                self.capture[i] = out[:, -1, :].detach().float().cpu()
            decoding = out.shape[1] == 1
            in_band = self.band[0] <= i < self.band[1]
            delta = self.deltas.get(i)
            cap = self.caps.get(i)
            if decoding and in_band and (delta is not None or self.band_gain is not None or cap is not None):
                # No .item() here: a host sync inside every layer stalls the GPU; the loop counts steered tokens.
                live = (~self.muted).to(out.dtype) if self.muted is not None else torch.ones(out.shape[0], dtype=out.dtype, device=out.device)
                if self.band_gain is not None:
                    xin = args[0] if args else kwargs["hidden_states"]
                    g = 1.0 + (self.band_gain.to(out.dtype) - 1.0) * live
                    out = xin + (out - xin) * g[:, None, None]
                if delta is not None:
                    out = out + (delta.to(out.dtype) * live[:, None])[:, None, :]
                if cap is not None:  # the part of the projection above the row's ceiling is removed, nothing below it
                    unit, ceiling = cap
                    proj = (out.float() * unit).sum(-1)
                    excess = (proj - ceiling[:, None]).clamp(min=0.0) * live.float()[:, None]
                    out = out - (excess[..., None] * unit).to(out.dtype)
                return (out, *output[1:]) if tupled else out
            return output

        return fn

    def clear(self):
        self.deltas, self.band_gain, self.muted, self.applied, self.caps = {}, None, None, None, {}


class Meter:
    """Throughput counters written at most once a second to $ENGINE_METRICS (a small JSON file, replaced atomically)
    for research/cloud/monitor.py: tokens generated and prefilled so far, prompt tokens served from the prompt store
    instead of being read again, seconds spent reading prompts and decoding, rows in the current batch, steps taken."""

    def __init__(self, path=None):
        self.path = path or os.environ.get("ENGINE_METRICS")
        self.generated = self.prefilled = self.reused = self.steps = 0
        self.prefill_s = self.decode_s = 0.0
        self.batch = self.active = 0
        self.phase = "idle"
        self.started = time.time()
        self.written = 0.0
        if self.path:
            import atexit

            atexit.register(self.write, True)  # the final counts, not those of up to a second before the end

    def write(self, force=False):
        if not self.path or (not force and time.time() - self.written < 1.0):
            return
        self.written = time.time()
        data = {"t": self.written, "since": self.started, "generated": self.generated, "prefilled": self.prefilled, "reused": self.reused, "steps": self.steps,
                "prefill_s": round(self.prefill_s, 1), "decode_s": round(self.decode_s, 1), "batch": self.batch, "active": self.active, "phase": self.phase}
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        except OSError:
            pass


def _tensor_bytes(obj, depth=0):
    if torch.is_tensor(obj):
        return obj.numel() * obj.element_size()
    if depth > 4:
        return 0
    if isinstance(obj, (list, tuple)):
        return sum(_tensor_bytes(v, depth + 1) for v in obj)
    if isinstance(obj, dict):
        return sum(_tensor_bytes(v, depth + 1) for v in obj.values())
    if hasattr(obj, "__dict__") and not isinstance(obj, type):
        return sum(_tensor_bytes(v, depth + 1) for v in vars(obj).values())
    return 0


# ── decode speed: sampling noise, the KV cache, attention ───────────────────

TOPK_CANDIDATES = 1024


def _mul32(x, c):
    """(x · c) mod 2**32 for int64 tensors x < 2**32 and a constant c < 2**32, in two 16-bit halves so that no
    product reaches 2**63."""
    m = 0xFFFFFFFF
    return (x * (c & 0xFFFF) + (((x * (c >> 16)) & 0xFFFF) << 16)) & m


def _mix32(x):
    """Wellons' triple32, a 32-bit integer hash with very low bias, on int64 tensors holding values below 2**32."""
    x = x ^ (x >> 17)
    x = _mul32(x, 0xED5AD4BB)
    x = x ^ (x >> 11)
    x = _mul32(x, 0xAC4C1B51)
    x = x ^ (x >> 15)
    x = _mul32(x, 0x31848BAB)
    return x ^ (x >> 14)


def _gumbel(seed, step, token):
    """Gumbel noise for token ids `token` [B, K] of rows with `seed`, `step` [B, 1]: −log(−log u), u the top 23 bits
    of a hash of the three plus one half, over 2**23: uniform on (0, 1), never 0 or 1, and exact in float32 (MPS has
    no float64; with 24 bits the largest value would round to 1 and its noise to infinity)."""
    # The token id is hashed on its own before it meets the row's (seed, step) hash: with a plain XOR, two steps
    # whose hashes differ by d < vocabulary size would draw the same noise, permuted (token t ↔ t ^ d).
    u = ((_mix32(_mix32(_mix32(seed) ^ step) ^ _mix32(token)) >> 9).float() + 0.5) / 2**23
    return (-torch.log(-torch.log(u))).float()


def _grow_update(layer, key_states, value_states, *args, **kwargs):
    """DynamicLayer.update for the running batch's full-attention layers: the keys and values live in a buffer with
    room to spare and a decode step writes its position in place, where DynamicLayer's torch.cat copies the whole
    cache every step. The values are the same. When the batcher replaces a layer's tensors (a row joins or leaves),
    the next update moves them into a new buffer, once."""
    if not layer.is_initialized:
        layer.lazy_initialization(key_states, value_states)
    n = layer.keys.shape[-2] if layer.keys.numel() else 0
    t = key_states.shape[-2]
    buf = getattr(layer, "_kv_buf", None)
    fits = (buf is not None and layer.keys is buf[2] and buf[0].shape[:2] == key_states.shape[:2] and buf[0].shape[-1] == key_states.shape[-1]
            and buf[0].dtype == key_states.dtype and n + t <= buf[0].shape[-2])
    if fits:
        kb, vb = buf[0], buf[1]
    else:
        layer._kv_buf = None
        cap = n + t + max(256, (n + t) // 8)
        kb = key_states.new_empty((*key_states.shape[:2], cap, key_states.shape[-1]))
        vb = value_states.new_empty((*value_states.shape[:2], cap, value_states.shape[-1]))
        if n:
            kb[:, :, :n] = layer.keys
            vb[:, :, :n] = layer.values
    kb[:, :, n : n + t] = key_states
    vb[:, :, n : n + t] = value_states
    layer.keys, layer.values = kb[:, :, : n + t], vb[:, :, : n + t]
    layer._kv_buf = (kb, vb, layer.keys)
    return layer.keys, layer.values


def _grow_in_place(cache):
    """Give a cache's plain full-attention layers _grow_update (sliding and linear-attention layers keep their own)."""
    import types

    from transformers.cache_utils import DynamicLayer

    for layer in getattr(cache, "layers", []):
        if type(layer) is DynamicLayer:
            layer.update = types.MethodType(_grow_update, layer)


_DECODE_ATTENTION = "engine_sdpa"


def _register_decode_attention():
    """An attention implementation that is SDPA except on a decode step (one query position) of a layer with grouped
    key/value heads: there SDPA with an attention mask (the batch's left padding) cannot use grouped heads and HF first
    copies every key and value out once per query head (repeat_kv), several times the cache per step. Here the query
    heads of each key/value head are multiplied against it directly: the same attention, read once. Prompt reads,
    probe states included, go through SDPA unchanged."""
    from transformers import AttentionInterface
    from transformers.integrations.sdpa_attention import sdpa_attention_forward
    from transformers.masking_utils import AttentionMaskInterface, sdpa_mask

    def forward(module, query, key, value, attention_mask, dropout=0.0, scaling=None, is_causal=None, **kwargs):
        rep = getattr(module, "num_key_value_groups", 1)
        if query.shape[2] != 1 or rep == 1 or dropout or kwargs.get("softcap") is not None or kwargs.get("position_bias") is not None or key.shape[-1] != value.shape[-1]:
            return sdpa_attention_forward(module, query, key, value, attention_mask, dropout=dropout, scaling=scaling, is_causal=is_causal, **kwargs)
        b, h, _, d = query.shape
        g = key.shape[1]
        q = query.reshape(b, g, rep, d)
        scores = torch.matmul(q, key.transpose(-1, -2)).float() * (scaling if scaling is not None else d**-0.5)
        if attention_mask is not None:
            m = attention_mask[:, :, -1:, -key.shape[-2] :]
            scores = scores.masked_fill(~m, float("-inf")) if m.dtype == torch.bool else scores + m.float()
        out = torch.matmul(torch.softmax(scores, -1).to(value.dtype), value)
        return out.reshape(b, h, 1, d).transpose(1, 2).contiguous(), None

    AttentionInterface.register(_DECODE_ATTENTION, forward)
    AttentionMaskInterface.register(_DECODE_ATTENTION, sdpa_mask)
    return _DECODE_ATTENTION


class PromptStore:
    """Caches of prompts already read, unsteered, for the next read that starts with the same tokens: a trajectory's
    next step (its prompt is the last one plus the reply and the tool's answer), the generation that follows a probe
    read of the same prompt, and the arms and seeds that start from one history. Prompts are always read unsteered
    (steering acts on generated tokens only), so continuing from a stored cache computes what reading the whole prompt
    computes, up to floating-point order. A linear-attention or sliding-window cache cannot be cut back to a shorter
    prefix, so entries are kept at the points a later prompt can continue from (see TorchChatModel.read_prompt).
    Entries are deep copies (decoding updates some states in place) and the least recently used go first once the
    byte budget is full; a budget of 0 turns the store off."""

    @dataclass
    class Entry:
        key: tuple
        cache: object
        logits: object
        capture: object
        nbytes: int

    def __init__(self, budget):
        self.budget, self.used = int(budget), 0
        self.entries = OrderedDict()
        self.hits = self.misses = 0

    def lookup(self, tokens):
        """The entry with the longest key that `tokens` start with, or None."""
        t, best = tuple(tokens), None
        for key, e in self.entries.items():
            n = len(key)
            if n <= len(t) and (best is None or n > len(best.key)) and key[0] == t[0] and t[:n] == key:
                best = e
        if best is not None:
            self.entries.move_to_end(best.key)
        return best

    def put(self, tokens, cache, logits=None, capture=None):
        if self.budget <= 0:
            return
        key = tuple(tokens)
        if key in self.entries:
            old = self.entries.pop(key)
            self.used -= old.nbytes
            if capture is None:
                logits, capture = old.logits, old.capture
        cache = copy.deepcopy(cache)
        logits = logits.clone() if logits is not None else None
        nb = _tensor_bytes(cache) + (_tensor_bytes(logits) if logits is not None else 0)
        if nb > self.budget:
            return
        while self.entries and self.used + nb > self.budget:
            self.used -= self.entries.popitem(last=False)[1].nbytes
        self.entries[key] = self.Entry(key, cache, logits, capture, nb)
        self.used += nb


def _store_budget(device):
    """Bytes for the prompt store: $ENGINE_PROMPT_STORE_GB, else a quarter of the GPU memory the weights left free
    (CUDA), else 1 GB."""
    env = os.environ.get("ENGINE_PROMPT_STORE_GB")
    if env is not None:
        return float(env) * 2**30
    if str(device).startswith("cuda") and torch.cuda.is_available():
        free, _ = torch.cuda.mem_get_info()
        return 0.25 * free
    return 2**30


class TorchChatModel:
    def __init__(self, model_id, vectors_path=None, dtype="bfloat16", device=None, steer_thinking=True, mute_tool_calls=True, trust_remote_code=False):
        from transformers import AutoModelForCausalLM, AutoTokenizer

        started = time.time()
        self.id = model_id
        # How tokens are drawn (see _sample): "generator" (each row's torch.Generator over the whole vocabulary, the
        # sampler of every run before 2026-11-02) or "hash" (the nucleus found in the top TOPK_CANDIDATES, noise from a
        # per-row counter hash). Both draw from the same distribution; a folder keeps the sampler it was started with
        # (pressure.write_run_info). $ENGINE_FAST_DECODE=0 turns off the decode attention and the growing KV cache.
        self.sampler = os.environ.get("ENGINE_SAMPLER", "generator")
        assert self.sampler in ("generator", "hash"), self.sampler
        self.fast_decode = os.environ.get("ENGINE_FAST_DECODE", "1") != "0"
        attn = {"attn_implementation": _register_decode_attention()} if self.fast_decode else {}
        self.device = device or ("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")
        torch_dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}[dtype]
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=trust_remote_code)
        try:
            self.model = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch_dtype, trust_remote_code=trust_remote_code, **attn)
        except Exception:  # noqa: BLE001 — a vision-language checkpoint: its text model generates the same way
            from transformers import AutoModelForImageTextToText

            self.model = AutoModelForImageTextToText.from_pretrained(model_id, dtype=torch_dtype, trust_remote_code=trust_remote_code, **attn)
        self.model.to(self.device).eval()
        self.layers = decoder_layers(self.model)
        self.L = len(self.layers)
        self.band = (int(self.L * LAYER_BAND[0]), int(self.L * LAYER_BAND[1]))
        self.steering = Steering(self.layers, self.band)
        self.steer_thinking, self.mute_tool_calls = steer_thinking, mute_tool_calls
        self.vectors = Vectors.load(vectors_path) if vectors_path else None
        self.text_config = getattr(self.model.config, "text_config", None) or self.model.config
        self.hidden = self.text_config.hidden_size
        self.format = detect_format(self.tokenizer)
        eos = {self.tokenizer.eos_token_id} if self.tokenizer.eos_token_id is not None else set()
        for tok in self.format.end_tokens:
            tid = self.tokenizer.convert_tokens_to_ids(tok)
            if isinstance(tid, int) and tid >= 0 and tid != self.tokenizer.unk_token_id:
                eos.add(tid)
        gen_eos = getattr(getattr(self.model, "generation_config", None), "eos_token_id", None)
        eos.update([gen_eos] if isinstance(gen_eos, int) else (gen_eos or []))
        self.eos_ids = eos
        self.pad_id = self.tokenizer.pad_token_id if self.tokenizer.pad_token_id is not None else next(iter(eos))
        self._markers = {}
        self._units = {}
        # The four tags the loop tracks. When each is one token (Qwen's and Gemma's templates: added special tokens),
        # thinking and tool-call state is followed by token id, so the text is decoded once at the end, not every step.
        tags = {}
        f = self.format
        for name, text in (("think", f.think_open), ("/think", f.think_close), ("call", f.call_open), ("/call", f.call_close)):
            ids = self.tokenizer.encode(text, add_special_tokens=False)
            tags[name] = ids[0] if len(ids) == 1 else None
        self.tag_ids = tags if all(v is not None for v in tags.values()) else None
        self.meter = Meter()
        self.prompts = PromptStore(_store_budget(self.device))
        self.loaded_at = time.time()
        print(f"[torch_engine] loaded {model_id} on {self.device} ({dtype}) in {self.loaded_at - started:.1f}s: {self.L} layers, hidden {self.hidden}, band {self.band}, format {self.format.name}, prompt store {self.prompts.budget / 2**30:.1f} GB, sampler {self.sampler}, fast decode {'on' if self.fast_decode else 'off'}", flush=True)

    # ── prompts ────────────────────────────────────────────────────────────

    def prompt_tokens_for(self, body, messages=None, generation_prompt=True):
        messages = to_template(messages if messages is not None else body.get("messages", []))
        kwargs = {**dict(self.format.template_kwargs), **(body.get("chat_template_kwargs") or {})}
        if body.get("reasoning_effort") == "none":
            kwargs["enable_thinking"] = False
        ids = self.tokenizer.apply_chat_template(messages, tools=body.get("tools") or None, add_generation_prompt=generation_prompt, tokenize=True, **kwargs)
        if hasattr(ids, "input_ids"):
            ids = ids["input_ids"]
        return list(ids)

    # Turns the conversation could go on with; where their renderings part from the prompt is where the next
    # prompt can part from it too.
    _NEXT_TURNS = (
        {"role": "assistant", "content": "x", "tool_calls": [{"id": "call_a", "type": "function", "function": {"name": "a", "arguments": "{}"}}]},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "call_b", "type": "function", "function": {"name": "b", "arguments": "{\"k\": 1}"}}]},
        {"role": "assistant", "content": "y"},
    )

    def continuation_point(self, body, tokens):
        """How many leading tokens of this prompt every possible next prompt shares: the next turn renders the same up
        to there and differs after. Qwen's prompt ends where the next turn begins, so it is the whole prompt; Gemma's
        ends with a thinking opener that a rendered turn does not have, so it is a few tokens short. A read of this
        prompt stores its cache at that point as well, for the next step to continue from."""
        point = len(tokens)
        for turn in self._NEXT_TURNS:
            try:
                other = self.prompt_tokens_for(body, list(body.get("messages", [])) + [turn], generation_prompt=False)
            except Exception:  # noqa: BLE001 — a template that refuses the shape: no continuation point
                return None
            n = min(len(tokens), len(other))
            common = next((i for i in range(n) if tokens[i] != other[i]), n)
            point = min(point, common)
        return point if point > 0 else None

    def split(self, gen):
        """(content, reasoning, tool calls) of a finished Generation, in this model's format."""
        return self.format.split(gen.text, gen.thinking_open)

    def marker(self, text):
        if text not in self._markers:
            self._markers[text] = list(self.tokenizer.encode(text, add_special_tokens=False))
        return self._markers[text]

    # ── reading a prompt ───────────────────────────────────────────────────

    @contextlib.contextmanager
    def _unsteered(self):
        """Prompts are read unsteered: the hooks steer decode steps (length 1), and a 1-token piece of a prompt read in
        parts must not count as one."""
        st = self.steering
        saved = (st.deltas, st.band_gain, st.muted, st.caps)
        st.deltas, st.band_gain, st.muted, st.caps = {}, None, None, {}
        try:
            yield
        finally:
            st.deltas, st.band_gain, st.muted, st.caps = saved

    @torch.no_grad()
    def read_prompt(self, tokens, point=None):
        """Read a prompt (one row, unsteered) into a fresh cache: (cache, last-position logits [1, V], residual at the
        last prompt token for every layer (L, hidden) float32). Continues from the longest stored prompt it starts
        with; stores the result, and the cache at `point` (TorchChatModel.continuation_point) on the way."""
        from transformers import DynamicCache

        started = time.perf_counter()
        n = len(tokens)
        hit = self.prompts.lookup(tokens) if self.prompts.budget > 0 else None
        if hit is not None and len(hit.key) == n and hit.capture is not None:
            self.prompts.hits += 1
            self.meter.reused += n
            return copy.deepcopy(hit.cache), hit.logits.clone(), hit.capture
        start = reused = len(hit.key) if hit is not None and len(hit.key) < n else 0
        if start:
            self.prompts.hits += 1
            cache = copy.deepcopy(hit.cache)
        else:
            self.prompts.misses += 1
            cache = DynamicCache(config=self.text_config)
        cuts = ([point] if point and start < point < n else []) + [n]
        logits = capture = None
        with self._unsteered():
            for c in cuts:
                last = c == n
                if last:
                    self.steering.capture = {}
                try:
                    logits = self._forward(input_ids=torch.tensor([tokens[start:c]], device=self.device), past_key_values=cache, use_cache=True).logits[:, -1, :]
                    if last:
                        capture = np.stack([self.steering.capture[l][0].numpy() for l in range(self.L)])
                finally:
                    self.steering.capture = None
                self.prompts.put(tokens[:c], cache, logits if last else None, capture if last else None)
                start = c
        self.meter.prefilled += n - reused
        self.meter.reused += reused
        self.meter.prefill_s += time.perf_counter() - started
        return cache, logits, capture

    # ── readouts ───────────────────────────────────────────────────────────

    def _forward(self, **kwargs):
        """One forward pass that keeps only the last position's logits (a full [B, T, vocab] tensor for a long batched
        prompt runs to tens of GB)."""
        try:
            return self.model(logits_to_keep=1, **kwargs)
        except TypeError:
            return self.model(**kwargs)

    @staticmethod
    def _left_pad(prompts, pad_id, device):
        width = max(len(p) for p in prompts)
        ids = torch.full((len(prompts), width), pad_id, dtype=torch.long, device=device)
        mask = torch.zeros((len(prompts), width), dtype=torch.long, device=device)
        for r, p in enumerate(prompts):
            ids[r, width - len(p):] = torch.tensor(p, device=device)
            mask[r, width - len(p):] = 1
        return ids, mask

    @torch.no_grad()
    def state(self, messages, tools=None):
        """The residual at the last prompt token, every layer: (L, hidden) float32, and the prompt length."""
        arrs, ns = self.states([messages], tools)
        return arrs[0], ns[0]

    @torch.no_grad()
    def states(self, messages_list, tools=None, chunk=1):
        """`state` for several prompts. One at a time by default: left padding leaks into Qwen3.5's linear-attention
        layers (2 pad tokens moved a 0.8B state to cos 0.9995, growing with depth), and a prefill is cheap next to the
        generation that follows it."""
        bodies = [{"messages": m, "tools": tools} for m in messages_list]
        prompts = [self.prompt_tokens_for(b) for b in bodies]
        out = []
        if chunk == 1:
            self.meter.phase = "state"
            self.meter.write()
            for b, p in zip(bodies, prompts):
                out.append(self.read_prompt(p, self.continuation_point(b, p))[2])
            return out, [len(p) for p in prompts]
        for start in range(0, len(prompts), chunk):
            part = prompts[start : start + chunk]
            ids, mask = self._left_pad(part, self.pad_id, self.device)
            self.steering.capture = {}
            self.meter.phase = "state"
            self.meter.prefilled += sum(len(p) for p in part)
            self.meter.write()
            try:
                self._forward(input_ids=ids, attention_mask=mask if len(part) > 1 else None, use_cache=False)
                for r in range(len(part)):
                    out.append(np.stack([self.steering.capture[l][r].numpy() for l in range(self.L)]))
            finally:
                self.steering.capture = None
        return out, [len(p) for p in prompts]

    @torch.no_grad()
    def teacher_logprobs(self, messages, tools, reply_ids, extra=None, strength=1.0):
        """Next-token log-probabilities (float32, on CPU) at each position along `reply_ids`, teacher-forced after the
        prompt, with the request's steering (`extra`: steering/physio fields) active on every step as in generation."""
        from transformers import DynamicCache

        prompt = self.prompt_tokens_for({"messages": messages, "tools": tools})
        cache = DynamicCache(config=self.text_config)
        self._forward(input_ids=torch.tensor([prompt[:-1]], device=self.device), past_key_values=cache, use_cache=True)
        self.steering.clear()
        self._arm(extra or {}, strength, batch=1)
        self.steering.muted = torch.zeros(1, dtype=torch.bool, device=self.device)
        out, x = [], prompt[-1]
        try:
            for target in reply_ids:
                logits = self.model(input_ids=torch.tensor([[x]], device=self.device), past_key_values=cache, use_cache=True).logits[0, -1].float()
                out.append(torch.log_softmax(logits, -1).cpu())
                x = int(target)
        finally:
            self.steering.clear()
        return out

    # ── steering setup ─────────────────────────────────────────────────────

    def _arm(self, body, strength, batch, row=None):
        """Per-row deltas and band gain from one request body; `row` fills one row of an already-sized batch."""
        leanings = body.get("steering") or {}
        gains = physio_of(body["physio"], 0.0, body.get("physio_params")) if body.get("physio") else None
        alphas = {}
        if self.vectors and leanings:
            for dim, value in leanings.items():
                if dim not in self.vectors.directions or abs(float(value)) < 1e-6:
                    continue
                raw = float(value) * strength
                alphas[dim] = max(-MAX_ALPHA, min(MAX_ALPHA, raw))
            for i in range(*self.band):
                total = sum(self.vectors.directions[d][i] * (alphas[d] * self.vectors.scales[d]) for d in alphas)
                if alphas:
                    t = torch.tensor(np.asarray(total, dtype=np.float32), device=self.device)
                    if i not in self.steering.deltas:
                        self.steering.deltas[i] = torch.zeros(batch, self.hidden, device=self.device)
                    self.steering.deltas[i][row if row is not None else 0] = t
        if gains is not None:
            if self.steering.band_gain is None:
                self.steering.band_gain = torch.ones(batch, device=self.device)
            self.steering.band_gain[row if row is not None else 0] = float(gains["band_gain"])
        if self.steering.applied is None:
            self.steering.applied = Applied({}, self.band)
        self.steering.applied.alphas.update(alphas)
        if gains is not None:
            self.steering.applied.physio = {k: round(v, 3) for k, v in gains.items()}
        return alphas, gains

    def _row_steering(self, body, strength):
        """One request's steering on its own: per band layer the vector to add (None when it adds nothing), the band
        gain (None when none), and the record of what was asked for."""
        leanings = body.get("steering") or {}
        gains = physio_of(body["physio"], 0.0, body.get("physio_params")) if body.get("physio") else None
        alphas = {}
        if self.vectors and leanings:
            for dim, value in leanings.items():
                if dim in self.vectors.directions and abs(float(value)) >= 1e-6:
                    alphas[dim] = max(-MAX_ALPHA, min(MAX_ALPHA, float(value) * strength))
        delta = None
        if alphas:
            delta = {}
            for i in range(*self.band):
                total = sum(self.vectors.directions[d][i] * (alphas[d] * self.vectors.scales[d]) for d in alphas)
                delta[i] = torch.tensor(np.asarray(total, dtype=np.float32), device=self.device)
        applied = Applied(dict(alphas), self.band)
        if gains is not None:
            applied.physio = {k: round(v, 3) for k, v in gains.items()}
        return delta, (float(gains["band_gain"]) if gains is not None else None), applied

    def _row_cap(self, body):
        """`cap`: {"dim": name, "levels": {layer: ceiling}} → {layer: ceiling} on the band, or None. The ceiling is in
        units of the projection on that layer's unit direction (the vector normalized), as in Meek et al.'s capping."""
        cap = body.get("cap")
        if not cap or not self.vectors or cap.get("dim") not in self.vectors.directions:
            return None
        levels = {int(k): float(v) for k, v in (cap.get("levels") or {}).items()}
        return {i: levels[i] for i in range(*self.band) if i in levels}

    def unit_of(self, dim, i):
        key = (dim, i)
        if key not in self._units:
            v = np.asarray(self.vectors.directions[dim][i], dtype=np.float32)
            self._units[key] = torch.tensor(v / (np.linalg.norm(v) + 1e-12), device=self.device)
        return self._units[key]

    # ── generation ─────────────────────────────────────────────────────────

    def complete(self, body, strength=1.0):
        return self.complete_batch([body], strength)[0]

    def _generator(self, seed):
        """A per-row random stream on the model's device (CPU fallback): a row samples the same tokens whatever else
        shares its batch, so a batched run is reproducible row by row."""
        for device in (self.device, "cpu"):
            try:
                g = torch.Generator(device=device)
                break
            except RuntimeError:
                continue
        g.manual_seed(int(seed) if seed is not None else int(torch.randint(0, 2**31 - 1, (1,)).item()))
        return g

    def _sample(self, logits, rows, temps, top_ps, gens, keys=None):
        """One token for each of `rows` (indices into the batch) from `logits` [B, V], on the device: temperature,
        top-p, then Gumbel-max with each row's own generator. Returns a CPU list of token ids, one sync per step.
        With the "hash" sampler, `keys` gives each row's (seed, step) and the draw is _sample_hash's."""
        if self.sampler == "hash":
            return self._sample_hash(logits, rows, temps, top_ps, keys)
        lg = logits[rows].float()
        greedy = [r for r in rows if temps[r] <= 0]
        t = torch.tensor([temps[r] if temps[r] > 0 else 1.0 for r in rows], device=lg.device)[:, None]
        lp = torch.log_softmax(lg / t, -1)
        p_top = torch.tensor([top_ps[r] for r in rows], device=lg.device)[:, None]
        if bool((p_top < 1.0).any()):
            sp, si = torch.sort(lp, descending=True, dim=-1)
            before = torch.cumsum(sp.exp(), -1) - sp.exp()
            sp = sp.masked_fill(before >= p_top, float("-inf"))
            lp = torch.full_like(lp, float("-inf")).scatter(1, si, sp)
        noise = []
        for r in rows:
            g = gens[r]
            u = torch.rand(lg.shape[-1], generator=g, device=g.device)
            noise.append(u.to(lg.device))
        u = torch.stack(noise).clamp_(1e-20, 1.0)
        pick = torch.argmax(lp - torch.log(-torch.log(u)), -1)
        if greedy:
            idx = [rows.index(r) for r in greedy]
            pick[idx] = torch.argmax(lg[idx], -1)
        return pick.tolist()

    def _sample_hash(self, logits, rows, temps, top_ps, keys):
        """The "hash" sampler: the same distribution as the "generator" one (temperature, top-p, Gumbel-max), at a
        fraction of its cost per step. The nucleus is found among the TOPK_CANDIDATES most likely tokens, which hold it
        whenever their mass reaches top_p (almost always at temperature 0.6); a row whose nucleus does not fit, or with
        top_p = 1, is drawn over the whole vocabulary. The uniform for token v of a row at its step n is a hash of
        (seed, n, v), computed on the device for every row at once, so a row's draws depend on nothing else in the
        batch and are the same whichever path takes them."""
        lg = logits[rows].float()
        dev = lg.device
        t = torch.tensor([temps[r] if temps[r] > 0 else 1.0 for r in rows], device=dev)[:, None]
        p_top = torch.tensor([top_ps[r] for r in rows], device=dev)[:, None]
        seed = torch.tensor([keys[r][0] % 2**32 for r in rows], dtype=torch.int64, device=dev)[:, None]
        step = torch.tensor([keys[r][1] % 2**32 for r in rows], dtype=torch.int64, device=dev)[:, None]
        z = lg / t
        lse = torch.logsumexp(z, -1, keepdim=True)
        k = min(TOPK_CANDIDATES, z.shape[-1])
        vals, idx = torch.topk(z, k, dim=-1)
        lp = vals - lse
        p = lp.exp()
        keep = (torch.cumsum(p, -1) - p) < p_top
        score = lp.masked_fill(~keep, float("-inf")) + _gumbel(seed, step, idx)
        pick = idx.gather(1, score.argmax(-1, keepdim=True))[:, 0]
        full = ((p.sum(-1, keepdim=True) < p_top) | (p_top >= 1.0))[:, 0]
        if bool(full.any()):
            f = full.nonzero()[:, 0]
            lpf = z[f] - lse[f]
            if bool((p_top[f] < 1.0).any()):
                sp, si = torch.sort(lpf, descending=True, dim=-1)
                before = torch.cumsum(sp.exp(), -1) - sp.exp()
                sp = sp.masked_fill(before >= p_top[f], float("-inf"))
                lpf = torch.full_like(lpf, float("-inf")).scatter(1, si, sp)
            vocab = torch.arange(lpf.shape[-1], device=dev)[None, :]
            pick[f] = torch.argmax(lpf + _gumbel(seed[f], step[f], vocab), -1)
        greedy = [i for i, r in enumerate(rows) if temps[r] <= 0]
        if greedy:
            pick[greedy] = torch.argmax(lg[greedy], -1)
        return pick.tolist()

    def batcher(self, max_batch=24, strength=1.0):
        return ContinuousBatcher(self, max_batch, strength)

    @torch.no_grad()
    def complete_batch(self, bodies, strength=1.0):
        """Several independent requests generated together; one Generation per body, in order."""
        batcher = ContinuousBatcher(self, max(1, len(bodies)), strength)
        for i, body in enumerate(bodies):
            batcher.submit(i, body)
        done = {}
        while len(batcher):
            for key, gen in batcher.step():
                done[key] = gen
        return [done[i] for i in range(len(bodies))]


class _Row:
    """One request in a running batch: its prompt, sampling settings and stream, thinking budget, tag state, steering."""

    def __init__(self, cm, key, body, strength):
        self.key, self.body = key, body
        self.prompt = cm.prompt_tokens_for(body)
        self.point = cm.continuation_point(body, self.prompt)
        self.temp = float(body.get("temperature", 0.7))
        self.top_p = float(body.get("top_p", 0.95))
        self.max_tokens = int(body.get("max_tokens") or body.get("max_completion_tokens") or DEFAULT_MAX_TOKENS)
        self.budget = int(body.get("thinking_budget") or max(256, self.max_tokens // 2))
        self.rng = cm._generator(body.get("seed")) if cm.sampler == "generator" else None
        self.seed = int(body["seed"]) if body.get("seed") is not None else int(np.random.default_rng().integers(0, 2**31 - 1))
        self.gen = Generation(prompt_tokens=len(self.prompt))
        self.gen.thinking_open = cm.format.thinking_open_at(cm.tokenizer.decode(self.prompt[-16:]))
        self.think = 1 if self.gen.thinking_open else 0
        self.call = 0
        self.produced, self.forced = [], []
        self.done = False
        self.muted = True
        self.position = len(self.prompt)  # the rotary position of the next token fed back
        self.next_token = None
        self.delta, self.gain, self.gen.applied = cm._row_steering(body, strength)
        self.cap = cm._row_cap(body)
        self.cap_dim = (body.get("cap") or {}).get("dim")
        if self.cap and self.gen.applied is not None:
            self.gen.applied.alphas[f"cap:{self.cap_dim}"] = 0.0
        self.started = time.time()


class ContinuousBatcher:
    """Generation with rows joining and leaving a running batch. `submit` queues a request; each `step` admits queued
    requests while there is room, samples one token for every row, and drops the rows that finished, returning their
    Generations; the rest move one token on. A row that finishes no longer holds the others back, and a trajectory's
    next request can join the batch as soon as its tools have run.

    A request joins by being prefilled alone and its cache stacked onto the batch's: the linear-attention layers' fixed
    states are concatenated; the full-attention keys and values are padded on the left (the attention mask hides the
    padding), widening the batch's when the newcomer is the longest. Rows leave by index; padding no row needs any more
    is trimmed. Each row keeps its own rotary position and its own random stream, so its tokens do not depend on what
    else is in the batch (up to bf16 differences between batch shapes).

    Sliding-window layers (Gemma 4: five in six) keep only the last window − 1 positions but count every position
    seen, and the attention mask is laid out from that count. The batch keeps two invariants: a full-attention layer
    holds exactly `width` positions (the mask's columns), and a sliding layer has seen `width` and holds the last
    min(width, window − 1). Left padding shifts a row's whole timeline by a constant, so its distances, and with them
    the sliding window, are the ones it would have alone."""

    def __init__(self, cm, max_batch=24, strength=1.0):
        self.cm, self.max_batch, self.strength = cm, max_batch, strength
        self.queue = []
        self.rows = []
        self.cache = self.mask = self.logits = None

    def __len__(self):
        return len(self.rows) + len(self.queue)

    def submit(self, key, body):
        self.queue.append((key, body))

    # ── the cache ──────────────────────────────────────────────────────────

    @staticmethod
    def _layers(cache):
        for layer in cache.layers:
            if hasattr(layer, "conv_states"):
                yield "linear", layer
            elif getattr(layer, "keys", None) is not None and layer.keys.numel():
                yield ("sliding" if getattr(layer, "is_sliding", False) and hasattr(layer, "cumulative_length") else "attn"), layer

    def _widen(self, cache, width):
        """Pad every attention layer on the left so the cache describes `width` positions (see the class note)."""
        for kind, layer in self._layers(cache):
            if kind == "linear":
                continue
            target = min(width, layer.sliding_window - 1) if kind == "sliding" else width
            k = target - layer.keys.shape[-2]
            if k > 0:
                layer.keys = torch.nn.functional.pad(layer.keys, (0, 0, k, 0))
                layer.values = torch.nn.functional.pad(layer.values, (0, 0, k, 0))
            if kind == "sliding":
                layer.cumulative_length = width

    def _stack(self, src):
        for (kind, dst), (_, add) in zip(self._layers(self.cache), self._layers(src)):
            if kind in ("attn", "sliding"):
                dst.keys = torch.cat([dst.keys, add.keys], 0)
                dst.values = torch.cat([dst.values, add.values], 0)
            else:
                for i in list(dst.conv_states):
                    if dst.conv_states[i] is not None:
                        dst.conv_states[i] = torch.cat([dst.conv_states[i], add.conv_states[i]], 0)
                for i in list(dst.recurrent_states):
                    if dst.recurrent_states[i] is not None:
                        dst.recurrent_states[i] = torch.cat([dst.recurrent_states[i], add.recurrent_states[i]], 0)

    def _keep(self, keep):
        idx = torch.tensor(keep, dtype=torch.long, device=self.cm.device)
        lead = int((self.mask[idx].cumsum(1) == 0).sum(1).min().item()) if keep else 0
        width = self.mask.shape[1] - lead
        for kind, layer in self._layers(self.cache):
            if kind == "attn":
                layer.keys = layer.keys.index_select(0, idx)[:, :, lead:, :]
                layer.values = layer.values.index_select(0, idx)[:, :, lead:, :]
            elif kind == "sliding":
                held = min(width, layer.sliding_window - 1)
                layer.keys = layer.keys.index_select(0, idx)[:, :, layer.keys.shape[-2] - held :, :]
                layer.values = layer.values.index_select(0, idx)[:, :, layer.values.shape[-2] - held :, :]
                layer.cumulative_length = width
            else:
                for i in list(layer.conv_states):
                    if layer.conv_states[i] is not None:
                        layer.conv_states[i] = layer.conv_states[i].index_select(0, idx)
                for i in list(layer.recurrent_states):
                    if layer.recurrent_states[i] is not None:
                        layer.recurrent_states[i] = layer.recurrent_states[i].index_select(0, idx)
        self.mask = self.mask.index_select(0, idx)[:, lead:]
        self.logits = self.logits.index_select(0, idx)

    def _admit(self, key, body):
        cm = self.cm
        row = _Row(cm, key, body, self.strength)
        cm.meter.phase = "prefill"
        cm.meter.write()
        cache, logits, _ = cm.read_prompt(row.prompt, row.point)  # unsteered, alone; often continued from a stored read
        n = len(row.prompt)
        ones = torch.ones((1, n), dtype=torch.long, device=cm.device)
        if self.cache is None:
            self.cache, self.mask, self.logits = cache, ones, logits
            if cm.fast_decode:
                _grow_in_place(self.cache)
        else:
            width = self.mask.shape[1]
            if n > width:
                self._widen(self.cache, n)
                self.mask = torch.cat([torch.zeros((self.mask.shape[0], n - width), dtype=torch.long, device=cm.device), self.mask], 1)
                width = n
            self._widen(cache, width)
            self._stack(cache)
            self.mask = torch.cat([self.mask, torch.cat([torch.zeros((1, width - n), dtype=torch.long, device=cm.device), ones], 1)], 0)
            self.logits = torch.cat([self.logits, logits], 0)
        self.rows.append(row)

    def _restack_steering(self):
        st, rows, cm = self.cm.steering, self.rows, self.cm
        if any(r.delta for r in rows):
            zero = torch.zeros(cm.hidden, device=cm.device)
            st.deltas = {i: torch.stack([r.delta[i] if r.delta else zero for r in rows]) for i in range(*cm.band)}
        else:
            st.deltas = {}
        st.band_gain = torch.tensor([r.gain if r.gain is not None else 1.0 for r in rows], device=cm.device) if any(r.gain is not None for r in rows) else None
        capped = [r for r in rows if r.cap]
        if capped:
            dim = capped[0].cap_dim
            st.caps = {i: (cm.unit_of(dim, i), torch.tensor([r.cap[i] if r.cap else 1e9 for r in rows], device=cm.device)) for i in capped[0].cap}
        else:
            st.caps = {}

    # ── one token ──────────────────────────────────────────────────────────

    @torch.no_grad()
    def step(self):
        cm = self.cm
        admitted = False
        started = time.perf_counter()
        prefill0 = cm.meter.prefill_s
        while self.queue and len(self.rows) < self.max_batch:
            self._admit(*self.queue.pop(0))
            admitted = True
        if not self.rows:
            return []
        if admitted:
            self._restack_steering()
        rows = self.rows
        sample = [i for i, r in enumerate(rows) if not r.forced]
        picked = dict(zip(sample, cm._sample(self.logits, sample, [r.temp for r in rows], [r.top_p for r in rows], [r.rng for r in rows], [(r.seed, len(r.produced)) for r in rows]))) if sample else {}
        tags = cm.tag_ids
        for i, r in enumerate(rows):
            was_forced = bool(r.forced)
            tok = r.forced.pop(0) if was_forced else picked[i]
            r.next_token = tok
            r.produced.append(tok)
            r.gen.tokens.append(tok)
            r.gen.generated_tokens = len(r.produced)
            if tok in cm.eos_ids and not was_forced:
                r.done, r.gen.finish = True, "stop"
            if tags is not None:
                r.think += (tok == tags["think"]) - (tok == tags["/think"] and r.think > 0)
                r.call += (tok == tags["call"]) - (tok == tags["/call"] and r.call > 0)
                thinking, in_call = r.think > 0, r.call > 0
            else:
                text = cm.tokenizer.decode([t for t in r.produced if t not in cm.eos_ids])
                thinking, in_call = inside_thinking(text, r.gen.thinking_open, cm.format), inside_tool_call(text, cm.format)
            if not r.done and not r.forced and not r.gen.thought_closed and len(r.produced) >= r.budget and thinking:
                r.gen.thought_closed = True
                r.forced = list(cm.marker(cm.format.force_close))
            if not r.done and len(r.produced) >= r.max_tokens and not r.forced:
                r.done, r.gen.finish = True, "length"
            r.muted = bool(r.forced) or (in_call and cm.mute_tool_calls) or (thinking and not cm.steer_thinking)
        cm.meter.generated += len(rows)
        cm.meter.steps += 1
        finished = [r for r in rows if r.done]
        if finished:
            keep = [i for i, r in enumerate(rows) if not r.done]
            width = len(rows)
            if keep:
                self._keep(keep)
                self.rows = [rows[i] for i in keep]
            else:
                self.rows, self.cache, self.mask, self.logits = [], None, None, None
            self._restack_steering()
            for r in finished:
                r.gen.text = cm.tokenizer.decode([t for t in r.produced if t not in cm.eos_ids])
                r.gen.seconds = time.time() - r.started
                r.gen.batch = width
        rows = self.rows
        cm.meter.phase, cm.meter.batch, cm.meter.active = ("generate" if rows else "tools"), self.max_batch, len(rows)
        cm.meter.write()
        if rows:
            for r in rows:
                if r.gen.applied is not None:
                    r.gen.applied.steered_tokens += 0 if r.muted else 1
                    r.gen.applied.muted_tokens += 1 if r.muted else 0
            cm.steering.muted = torch.tensor([r.muted for r in rows], dtype=torch.bool, device=cm.device)
            self.mask = torch.cat([self.mask, torch.ones((len(rows), 1), dtype=torch.long, device=cm.device)], 1)
            ids = torch.tensor([r.next_token for r in rows], device=cm.device)[:, None]
            pos = torch.tensor([r.position for r in rows], dtype=torch.long, device=cm.device)[:, None]
            try:
                self.logits = cm._forward(input_ids=ids, attention_mask=self.mask, position_ids=pos, past_key_values=self.cache, use_cache=True).logits[:, -1, :]
            finally:
                cm.steering.muted = None
            for r in rows:
                r.position += 1
        # Decode time: this step less the prompt reads in it. The next step's sampling waits for this forward pass,
        # so a step's GPU time lands in the following one; the totals are right.
        cm.meter.decode_s += time.perf_counter() - started - (cm.meter.prefill_s - prefill0)
        return [(r.key, r.gen) for r in finished]


# ── reply parsing (server.split_reply, copied so this module needs no mlx) ──

TOOL_CALL = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)
FUNCTION = re.compile(r"<function=([^>\n]+)>(.*?)</function>", re.S)
PARAMETER = re.compile(r"<parameter=([^>\n]+)>\n?(.*?)\n?</parameter>", re.S)
THINK = re.compile(r"<think>(.*?)</think>", re.S)


def parse_value(text):
    text = text.strip()
    if text and (text[0] in "{[-0123456789" or text in ("true", "false", "null")):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return text


def parse_call(raw):
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
    import uuid

    if thinking_open and "</think>" not in text:
        return "", text.strip(), []
    if "</think>" in text and "<think>" not in text.split("</think>", 1)[0]:
        text = "<think>" + text
    reasoning = "\n".join(t.strip() for t in THINK.findall(text)).strip()
    text = THINK.sub("", text)
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


# ── chat formats: the tags each model family writes, and how its replies are read ──

GEMMA_QUOTE = '<|"|>'


def parse_gemma_args(text):
    """Gemma 4's tool-call arguments: `{key:value,...}` with unquoted keys, strings between <|"|> marks (so code needs
    no escaping), numbers, true/false/null, nested objects and lists. Returns (value, end index)."""

    def ws(i):
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
        return i

    def value(i):
        i = ws(i)
        if text.startswith(GEMMA_QUOTE, i):
            j = text.find(GEMMA_QUOTE, i + len(GEMMA_QUOTE))
            j = len(text) if j < 0 else j
            return text[i + len(GEMMA_QUOTE) : j], j + len(GEMMA_QUOTE)
        if i < len(text) and text[i] == "{":
            out, i = {}, ws(i + 1)
            while i < len(text) and text[i] != "}":
                if text.startswith(GEMMA_QUOTE, i):
                    key, i = value(i)
                else:
                    j = text.find(":", i)
                    j = len(text) if j < 0 else j
                    key, i = text[i:j].strip(), j
                i = ws(i)
                if i < len(text) and text[i] == ":":
                    i += 1
                out[key], i = value(i)
                i = ws(i)
                if i < len(text) and text[i] == ",":
                    i = ws(i + 1)
            return out, i + 1
        if i < len(text) and text[i] == "[":
            out, i = [], ws(i + 1)
            while i < len(text) and text[i] != "]":
                item, i = value(i)
                out.append(item)
                i = ws(i)
                if i < len(text) and text[i] == ",":
                    i = ws(i + 1)
            return out, i + 1
        j = i
        while j < len(text) and text[j] not in ",}]":
            j += 1
        raw = text[i:j].strip()
        try:
            return json.loads(raw), j
        except json.JSONDecodeError:
            return raw, j

    return value(0)[0]


@dataclass(frozen=True)
class ChatFormat:
    """One model family's tags: thinking open/close, tool call open/close, what closes a thought the budget cut short,
    the tokens that end a reply, and the chat-template switches its prompts need."""

    name: str
    think_open: str
    think_close: str
    call_open: str
    call_close: str
    force_close: str
    end_tokens: tuple
    template_kwargs: tuple = ()  # (key, value) pairs, defaults the request can override

    def thinking_open_at(self, prompt_tail):
        """Whether the prompt itself opened a thought the reply continues (Qwen: `<think>\\n`; Gemma after a tool
        response: `<|channel>thought\\n`)."""
        return self.think_open in prompt_tail and self.think_close not in prompt_tail.split(self.think_open)[-1]

    def split(self, text, thinking_open=False):
        """(content, reasoning, tool calls in OpenAI form). A call written inside a thought that never closed (seen in
        the 9B pilot) is still the action: the thought is what precedes it."""
        content, reasoning, calls = self._split(text, thinking_open)
        if not calls and self.call_open in reasoning:
            head, tail = reasoning.split(self.call_open, 1)
            _, _, calls = self._split(head + self.think_close + self.call_open + tail, True)
            reasoning = head.strip()
        return content, reasoning, calls

    def _split(self, text, thinking_open):
        if self.name == "qwen":
            return split_reply(text, thinking_open)
        import uuid

        if thinking_open:
            text = self.think_open + "thought\n" + text
        thought = re.compile(re.escape(self.think_open) + r"(?:thought\n)?(.*?)" + re.escape(self.think_close), re.S)
        reasoning = "\n".join(t.strip() for t in thought.findall(text)).strip()
        text = thought.sub("", text)
        if self.think_open in text:  # a thought still open at the end: everything after it is thinking
            head, tail = text.split(self.think_open, 1)
            reasoning, text = (reasoning + "\n" + (tail[len("thought\n"):] if tail.startswith("thought\n") else tail)).strip(), head
        pattern = re.compile(re.escape(self.call_open) + r"call:([\w.-]+)(\{.*?\})" + re.escape(self.call_close), re.S)
        calls = []
        for name, raw in pattern.findall(text):
            args = parse_gemma_args(raw)
            calls.append({"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function", "function": {"name": name, "arguments": json.dumps(args if isinstance(args, dict) else {}, ensure_ascii=False)}})
        content = pattern.sub("", text)
        for tag in self.end_tokens:
            content = content.replace(tag, "")
        return content.strip(), reasoning, calls


QWEN = ChatFormat("qwen", "<think>", "</think>", "<tool_call>", "</tool_call>", THINK_CLOSE, ("<|im_end|>", "<|endoftext|>"))
GEMMA4 = ChatFormat("gemma4", "<|channel>", "<channel|>", "<|tool_call>", "<tool_call|>", "\n<channel|>", ("<turn|>", "<eos>", "<|tool_response>"), (("enable_thinking", True),))


def detect_format(tokenizer):
    """The format whose tags are single tokens in this vocabulary (Qwen when nothing else matches)."""
    vocab = tokenizer.get_vocab()
    return GEMMA4 if all(t in vocab for t in (GEMMA4.think_open, GEMMA4.call_open, GEMMA4.call_close)) else QWEN


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="smoke test: load a model, generate once, read a state")
    ap.add_argument("--model", default="Qwen/Qwen3.5-0.8B")
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--max-tokens", type=int, default=64)
    args = ap.parse_args()
    cm = TorchChatModel(args.model, dtype=args.dtype)
    msgs = [{"role": "user", "content": "Write a Python function that clamps x to [lo, hi]. Reply in one line."}]
    arr, n = cm.state(msgs)
    print("state", arr.shape, "prompt tokens", n, "band mean norm", float(np.linalg.norm(arr[cm.band[0]:cm.band[1]], axis=-1).mean()))
    gen = cm.complete({"messages": msgs, "temperature": 0.6, "seed": 1, "max_tokens": args.max_tokens, "thinking_budget": 32})
    print(f"generated {gen.generated_tokens} tokens in {gen.seconds:.1f}s ({gen.generated_tokens / gen.seconds:.1f} tok/s), finish {gen.finish}, thought_closed {gen.thought_closed}")
    print(repr(gen.text[:300]))
    print(cm.split(gen))
