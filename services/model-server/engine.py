"""The models behind server.py: chat models (with steering and a prefix KV cache), embedding models, and the
registry that loads them on demand and shares one GPU between them.

- ChatModel  an mlx-lm model. Its decoder layers carry the steering hook (steer.py); its control vectors are picked up
             from vectors/<slug>.npz when extract.py has made them, so a model without vectors simply runs unsteered.
             Every prompt goes through an LRU prefix cache: the model's state is saved after the system prompt and
             after the last assistant header, and a later prompt that starts the same way resumes from the longest
             saved point, so a 10k-token system prompt is read once per conversation rather than once per turn. Only
             prompt state is saved, never what the model generated, so a cached prefix never carries the state the model was in
             when the model answered.
- EmbeddingModel  an encoder from embed.py (bge-m3 and the like): CLS or mean pooling as the model defines it, normalized.
- Registry   model id -> loaded model, loading on first use, evicting the least recently used when more than
             `max_loaded` are resident, and holding the one lock every forward pass takes.

Config (server.py's --config, and PUT /config) is a plain dict:
  {"models": [{"id": "...", "kind": "chat" | "embedding", "vectors": "optional path"}],
   "strength": 2.5, "mode": "generate" | "always", "mute_tool_calls": true, "steer_thinking": false,
   "sigma_per_alpha": 1.5, "total_alpha": 5.0, "max_loaded": 4, "cache_size": 8, "cache_bytes": 3221225472}
"""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field

import mlx.core as mx

from endocrine import endocrine_of
from steer import METHODS, SIGMA_PER_ALPHA, TOTAL_ALPHA, physio_of, Applied, Steering, Vectors, vectors_path_for

log = logging.getLogger("steering")

MODES = ("generate", "always")
KINDS = ("chat", "embedding")


# ── configuration ──────────────────────────────────────────────────────────────


@dataclass
class ModelSpec:
    id: str
    kind: str = "chat"
    vectors: str | None = None  # explicit vectors file; default: vectors/<slug>.npz if it exists

    @classmethod
    def of(cls, value):
        if isinstance(value, str):
            return cls(value)
        kind = value.get("kind", "chat")
        return cls(str(value["id"]), kind if kind in KINDS else "chat", value.get("vectors") or None)

    def as_dict(self):
        return {"id": self.id, "kind": self.kind, **({"vectors": self.vectors} if self.vectors else {})}


@dataclass
class Config:
    models: list = field(default_factory=list)  # list[ModelSpec]
    strength: float = 2.5
    mode: str = "generate"
    mute_tool_calls: bool = True
    steer_thinking: bool = False
    sigma_per_alpha: float = SIGMA_PER_ALPHA
    total_alpha: float = TOTAL_ALPHA
    method: str = "target"
    gate: bool = False  # Hill-gate the alphas (steer.py gate)
    # The entropy loop (direct physiology): stress_{t+1} = decay · stress_t + rate · (entropy_t − baseline), in nats,
    # fed back into the physio gains every token. Off unless a request carries physio and the loop is on.
    entropy_loop: bool = False
    entropy_decay: float = 0.9
    entropy_rate: float = 0.3
    # The baseline adapts: a running mean of the entropy seen, started here, so stress reads a rise above what is
    # usual for this model and prompt rather than above a fixed number (Qwen3.5-4B's answers sit near 2.6 nats).
    # The nameless endocrine system keeps its own, fixed baseline (endocrine.py, 1.5 nats); the two are separate.
    entropy_baseline: float = 2.6
    entropy_adapt: float = 0.05
    max_loaded: int = 4
    cache_size: int = 8
    cache_bytes: int = 3 * 1024**3  # the prefix cache's budget in bytes

    @classmethod
    def of(cls, value, base=None):
        """A config from a dict, over `base` for whatever the dict leaves out."""
        base = base or cls()
        value = value or {}
        models = [ModelSpec.of(m) for m in value["models"]] if isinstance(value.get("models"), list) else list(base.models)
        mode = value.get("mode", base.mode)
        return cls(
            models=models,
            strength=max(0.0, min(10.0, float(value.get("strength", base.strength)))),
            mode=mode if mode in MODES else base.mode,
            mute_tool_calls=bool(value.get("mute_tool_calls", base.mute_tool_calls)),
            steer_thinking=bool(value.get("steer_thinking", base.steer_thinking)),
            sigma_per_alpha=max(0.1, min(20.0, float(value.get("sigma_per_alpha", base.sigma_per_alpha)))),
            total_alpha=max(0.5, min(30.0, float(value.get("total_alpha", base.total_alpha)))),
            method=value.get("method") if value.get("method") in METHODS else base.method,
            gate=bool(value.get("gate", base.gate)),
            entropy_loop=bool(value.get("entropy_loop", base.entropy_loop)),
            entropy_decay=max(0.0, min(0.999, float(value.get("entropy_decay", base.entropy_decay)))),
            entropy_rate=max(0.0, min(5.0, float(value.get("entropy_rate", base.entropy_rate)))),
            entropy_baseline=max(0.0, min(10.0, float(value.get("entropy_baseline", base.entropy_baseline)))),
            entropy_adapt=max(0.0, min(1.0, float(value.get("entropy_adapt", base.entropy_adapt)))),
            max_loaded=max(1, int(value.get("max_loaded", base.max_loaded))),
            cache_size=max(0, int(value.get("cache_size", base.cache_size))),
            cache_bytes=max(0, int(value.get("cache_bytes", base.cache_bytes))),
        )

    @classmethod
    def read(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls.of(json.load(f))

    def as_dict(self):
        return {
            "models": [m.as_dict() for m in self.models],
            "strength": self.strength,
            "mode": self.mode,
            "mute_tool_calls": self.mute_tool_calls,
            "steer_thinking": self.steer_thinking,
            "sigma_per_alpha": self.sigma_per_alpha,
            "total_alpha": self.total_alpha,
            "method": self.method,
            "gate": self.gate,
            "entropy_loop": self.entropy_loop,
            "entropy_decay": self.entropy_decay,
            "entropy_rate": self.entropy_rate,
            "entropy_baseline": self.entropy_baseline,
            "entropy_adapt": self.entropy_adapt,
            "max_loaded": self.max_loaded,
            "cache_size": self.cache_size,
            "cache_bytes": self.cache_bytes,
        }

    def spec(self, model_id):
        return next((m for m in self.models if m.id == model_id), None)


# ── chat ───────────────────────────────────────────────────────────────────────


def to_template(messages):
    """OpenAI messages as the chat template wants them: tool-call arguments as objects, tool results as plain text."""
    out = []
    for m in messages:
        item = {"role": m.get("role", "user")}
        content = m.get("content")
        if isinstance(content, list):  # content parts: keep the text, drop images (these models run text-only here)
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
                calls.append({"type": "function", "function": {"name": fn.get("name", ""), "arguments": args}})
            item["tool_calls"] = calls
        if m.get("role") == "tool":
            item["tool_call_id"] = m.get("tool_call_id", "")
            if m.get("name"):
                item["name"] = m["name"]
        out.append(item)
    return out


def find(tokens, needle, last=False):
    """Index of `needle` (a token list) in `tokens`, first or last; -1 when absent."""
    n = len(needle)
    if not n or n > len(tokens):
        return -1
    span = range(len(tokens) - n, -1, -1) if last else range(0, len(tokens) - n + 1)
    return next((i for i in span if tokens[i : i + n] == needle), -1)


# When a request sets no limit: room for a thought (half of it at most, see thinking_budget) and an answer.
DEFAULT_MAX_TOKENS = 2048


# (end of a turn, start of the assistant's turn) for the chat templates served: Qwen's, then Gemma's.
TURN_MARKERS = (("<|im_end|>\n", "<|im_start|>assistant\n"), ("<end_of_turn>\n", "<start_of_turn>model\n"))


def inside_tool_call(text):
    return text.count("<tool_call>") > text.count("</tool_call>")


def inside_thinking(text, thinking_open=False):
    """True while the output so far is still reasoning: an open <think>, or a prompt that ended inside one."""
    if thinking_open and "</think>" not in text:
        return True
    return text.count("<think>") > text.count("</think>")


def entropy_of(logprobs):
    """The next-token distribution's entropy in nats, from its log-probabilities (float32)."""
    return float(-mx.sum(mx.exp(logprobs) * logprobs))


def stress_step(config, stress, usual, entropy):
    """One token of the entropy loop: stress decays and rises with entropy above the running baseline `usual`,
    which itself drifts toward the entropy seen. Returns the new (stress, usual)."""
    stress = config.entropy_decay * stress + config.entropy_rate * (entropy - usual)
    usual += config.entropy_adapt * (entropy - usual)
    return stress, usual


@dataclass
class Generation:
    """What one chat completion came to."""

    text: str = ""
    prompt_tokens: int = 0
    cached_tokens: int = 0
    generated_tokens: int = 0
    finish: str = "stop"
    seconds: float = 0.0
    applied: Applied | None = None
    thinking_open: bool = False  # the prompt ended inside <think>, so the output starts as reasoning
    thought_closed: bool = False  # the model's thinking ran past its budget and was closed for the model


class ChatModel:
    kind = "chat"

    def __init__(self, spec: ModelSpec, config: Config):
        from mlx_lm import load
        from mlx_lm.models.cache import LRUPromptCache

        started = time.time()
        self.id = spec.id
        self.model, self.tokenizer = load(spec.id)
        self.config = config
        self.steering = Steering(mode=config.mode, mute_tool_calls=config.mute_tool_calls, steer_thinking=config.steer_thinking)
        self.steering.attach(self.model)
        self.steering.sigma_per_alpha = config.sigma_per_alpha
        self.steering.total_alpha = config.total_alpha
        self.steering.method = config.method
        self.steering.gate = config.gate
        path = spec.vectors or vectors_path_for(spec.id)
        self.vectors = Vectors.load(path) if os.path.exists(path) else None
        self.vectors_path = path if self.vectors else None
        self.cache = LRUPromptCache(max_size=config.cache_size, max_bytes=config.cache_bytes) if config.cache_size else None
        self._markers = {}
        self.steering.watch(self.vectors)
        self.loaded_at = time.time()
        self.used_at = self.loaded_at
        log.info(
            "loaded %s in %.1fs: %d layers, %s, prefix cache %s",
            spec.id,
            self.loaded_at - started,
            len(self.steering.layers),
            f"steerable ({len(self.vectors.directions)} leanings from {os.path.basename(path)})" if self.vectors else "no control vectors (runs unsteered)",
            f"{config.cache_size} entries" if self.cache is not None else "off",
        )

    def configure(self, config: Config):
        # Note: method and gate are read from the config only when the model loads (__init__); a later PUT /config
        # changing them does not reach a model already loaded. Requests can still set both per call.
        self.config = config
        self.steering.mode = config.mode
        self.steering.mute_tool_calls = config.mute_tool_calls
        self.steering.steer_thinking = config.steer_thinking
        self.steering.sigma_per_alpha = config.sigma_per_alpha
        self.steering.total_alpha = config.total_alpha

    def prompt_tokens_for(self, body):
        messages = to_template(body.get("messages", []))
        kwargs = dict(body.get("chat_template_kwargs") or {})
        if body.get("reasoning_effort") == "none":
            kwargs.setdefault("enable_thinking", False)
        if (body.get("response_format") or {}).get("type") == "json_object":
            # Qwen's template wants the system message first and only there, so the JSON rule joins it.
            rule = "只輸出一個 JSON 物件，不要其他文字。"
            if messages and messages[0]["role"] == "system":
                messages[0] = {**messages[0], "content": f"{messages[0]['content']}\n\n{rule}"}
            else:
                messages.insert(0, {"role": "system", "content": rule})
        try:
            return self.tokenizer.apply_chat_template(messages, tools=body.get("tools") or None, add_generation_prompt=True, tokenize=True, **kwargs)
        except Exception:  # noqa: BLE001 — a template with no system role (Gemma): the system text heads the first user turn
            if messages and messages[0]["role"] == "system" and len(messages) > 1 and messages[1]["role"] == "user":
                merged = [{"role": "user", "content": f"{messages[0]['content']}\n\n{messages[1]['content']}"}, *messages[2:]]
                return self.tokenizer.apply_chat_template(merged, tools=body.get("tools") or None, add_generation_prompt=True, tokenize=True, **kwargs)
            raise

    def checkpoints(self, tokens):
        """Where a later prompt will still share this one: after the first message (the system prompt, shared across
        conversations) and after the last assistant header (the next turn repeats everything before the reply).
        Qwen3.5's cache holds recurrent state that cannot be rewound, so the state is saved at these points instead
        of being trimmed back from the end."""
        points = []
        # The turn markers of whichever template this model uses (Qwen's, or Gemma's).
        turn_end, header = next(
            ((self.marker(end), self.marker(head)) for end, head in TURN_MARKERS if find(tokens, self.marker(end)) >= 0),
            (self.marker(TURN_MARKERS[0][0]), self.marker(TURN_MARKERS[0][1])),
        )
        first_end = find(tokens, turn_end)
        if first_end >= 0:
            points.append(first_end + len(turn_end))
        last_header = find(tokens, header, last=True)
        if last_header >= 0 and last_header + len(header) < len(tokens):
            points.append(last_header + len(header))
        return sorted({p for p in points if 0 < p < len(tokens)})

    def marker(self, text):
        if text not in self._markers:
            self._markers[text] = list(self.tokenizer.encode(text, add_special_tokens=False))
        return self._markers[text]

    def prefill(self, cache, tokens, step=2048):
        """Runs the prompt through the model into `cache`, without generating."""
        for start in range(0, len(tokens), step):
            self.model(mx.array(tokens[start : start + step])[None], cache=cache)
            mx.eval([c.state for c in cache])

    def hidden_size(self):
        """The residual width, for sizing endocrine receptors: from the vectors file, else from the first MLP."""
        return (self.vectors.hidden if self.vectors else 0) or self.steering.layers[0].mlp.down_proj.weight.shape[0]

    def complete(self, body, strength, emit=None, trace=None) -> Generation:
        """Runs one completion; `emit(text, gen)` gets each new piece of raw output as it is produced, and `trace`
        every token's forward pass (the per-layer rows from steer.py) with its text."""
        from mlx_lm import stream_generate
        from mlx_lm.models.cache import make_prompt_cache
        from mlx_lm.sample_utils import make_sampler

        tokens = self.prompt_tokens_for(body)
        base_temp = float(body.get("temperature", 0.7))
        # Direct physiology: chemical deviations (−1..1) acting as gains and on the temperature; the entropy loop may
        # move them every token, so the sampler reads the temperature from a box.
        physio_in = body.get("physio") or None
        endo = endocrine_of(body["endocrine"], self.hidden_size(), len(self.steering.layers)) if body.get("endocrine") is not None else None
        loop = bool(body.get("entropy_loop", self.config.entropy_loop)) and physio_in is not None
        gains = physio_of(physio_in, 0.0, body.get("physio_params")) if physio_in is not None else None
        temp_box = {"temp": base_temp * (gains["temperature"] if gains else 1.0)}
        inner = {}

        def sampler(logprobs):
            t = temp_box["temp"]
            if t not in inner:
                inner[t] = make_sampler(temp=t, top_p=float(body.get("top_p", 0.95)))
            return inner[t](logprobs)
        if body.get("seed") is not None:  # experiments: the same sample across conditions
            mx.random.seed(int(body["seed"]))
        max_tokens = int(body.get("max_tokens") or body.get("max_completion_tokens") or DEFAULT_MAX_TOKENS)
        # Budget forcing: past this many tokens of thinking the thought is closed for the model and the model answers. The model's prompt is
        # long, and the 4B model would otherwise reason (in English) until the budget ran out and say nothing.
        budget = int(body.get("thinking_budget") or max(256, max_tokens // 2))
        leanings = body.get("steering") or {}
        gen = Generation(prompt_tokens=len(tokens))

        # The prefix cache is only sound when the prompt itself is never steered: in "always" mode the cached state
        # would carry an old mood into a new turn, so that mode prefills from scratch.
        caching = self.cache is not None and self.steering.mode == "generate"
        cache, rest = (None, tokens)
        if caching:
            cache, rest = self.cache.fetch_nearest_cache(self.id, tokens)
            if len(rest) == 0:  # the model needs at least one token to prefill
                cache, rest = None, tokens
        if cache is None:
            cache, rest = make_prompt_cache(self.model), tokens
        gen.cached_tokens = len(tokens) - len(rest)

        started = time.time()
        try:
            if caching:
                # Prefill up to each checkpoint beyond what was cached, saving a copy of the state there.
                for point in self.checkpoints(tokens):
                    done = len(tokens) - len(rest)
                    if point <= done:
                        continue
                    self.prefill(cache, tokens[done:point])
                    self.cache.insert_cache(self.id, tokens[:point], copy.deepcopy(cache))
                    rest = tokens[point:]
            # The prompt's tail (the generation header) is read unsteered too; the shift starts with the model's first token.
            # Physio and endocrine ride on an Applied record too (an empty set() when there are no leanings), so
            # their gains get muted and counted like steering. Their tokens are counted only when leanings are
            # present: the hook counts a step on the layers that carry a directional shift.
            gen.applied = self.steering.set(self.vectors, leanings, strength=strength, method=body.get("method"), gated=body.get("gate")) if self.vectors and leanings else None
            if endo is not None:
                if gen.applied is None:
                    gen.applied = self.steering.set(self.vectors, {}, strength=strength) if self.vectors else None
                self.steering.norm_probe = self.steering.band()[0]
                self.steering.update_gain = endo.gains()
                if gen.applied is not None:
                    gen.applied.endocrine = endo.describe()
            if gains is not None:
                if gen.applied is None:
                    gen.applied = self.steering.set(self.vectors, {}, strength=strength) if self.vectors else None
                self.steering.physio = gains
                if gen.applied is not None:
                    gen.applied.physio = {k: round(v, 3) for k, v in gains.items()}
            stress, usual = 0.0, self.config.entropy_baseline
            gen.thinking_open = "<think>" in (tail := self.tokenizer.decode(rest[-16:])) and "</think>" not in tail.split("<think>")[-1]
            produced = []  # the token ids the model has written, to resume from if the model's thinking is closed for the model

            def take(out, before):
                nonlocal stress, usual
                # Both loops read the model's own uncertainty, this token, in nats. Secretion and gain changes act
                # on the next token, and keep running while muted (only their effect on the layers is muted).
                lp = out.logprobs.astype(mx.float32) if (endo is not None or loop) and out.logprobs is not None else None
                entropy = entropy_of(lp) if lp is not None else None
                if endo is not None and lp is not None:
                    surprise = float(-lp[out.token])
                    norm = float(self.steering.last_norm) if self.steering.last_norm is not None else 1.0
                    self.steering.update_gain = endo.step(entropy, surprise, norm)
                    if gen.applied is not None:
                        gen.applied.endocrine = {**endo.describe(), "h": endo.trace[-1], "steps": len(endo.trace)}
                if loop and lp is not None:
                    # Above baseline it raises stress, which decays.
                    stress, usual = stress_step(self.config, stress, usual, entropy)
                    g = physio_of(physio_in, max(0.0, stress), body.get("physio_params"))
                    self.steering.physio = g
                    temp_box["temp"] = base_temp * g["temperature"]
                    if gen.applied is not None:
                        gen.applied.physio = {k: round(v, 3) for k, v in g.items()} | {"stress": round(stress, 3)}
                gen.text += out.text
                gen.generated_tokens = before + out.generation_tokens
                if emit and out.text:
                    emit(out.text, gen)
                if gen.applied:
                    self.steering.mute(inside_tool_call(gen.text), inside_thinking(gen.text, gen.thinking_open))
                if trace:
                    rows = self.steering.flush_trace()
                    if rows:
                        trace(out.text, rows, gen)
                if out.finish_reason:
                    gen.finish = out.finish_reason

            for out in stream_generate(self.model, self.tokenizer, rest, max_tokens=max_tokens, sampler=sampler, prompt_cache=cache):
                take(out, 0)
                produced.append(out.token)
                if not out.finish_reason and len(produced) >= budget and inside_thinking(gen.text, gen.thinking_open):
                    gen.thought_closed = True
                    break
            if gen.thought_closed:
                close = "\n</think>\n\n"
                gen.text += close
                if emit:
                    emit(close, gen)
                # Resume from the prompt's cached state with the model's thought and its close read back in (unsteered, as a
                # prefill), then let the model answer, steered as usual.
                resumed = list(tokens) + produced + self.marker(close)
                cache, rest = self.cache.fetch_nearest_cache(self.id, resumed) if caching else (None, resumed)
                if cache is None or len(rest) == 0:
                    cache, rest = make_prompt_cache(self.model), resumed
                if gen.applied:
                    self.steering.mute(False, False)
                for out in stream_generate(self.model, self.tokenizer, rest, max_tokens=max(64, max_tokens - len(produced)), sampler=sampler, prompt_cache=cache):
                    take(out, len(produced))
        finally:
            self.steering.clear()
            gen.seconds = time.time() - started
            self.used_at = time.time()
        return gen

    def divergence(self, body, strength):
        """Teacher-forced along `reply`: the next-token distribution with and without the request's intervention
        (steering, physio, endocrine), token by token with the loops running as in generation. Returns the mean KL
        (plain ‖ intervened) per token, the entropies, and the hormone trace when there was one."""
        from mlx_lm.models.cache import make_prompt_cache  # noqa: PLC0415

        prompt = list(self.prompt_tokens_for(body))
        reply = list(self.tokenizer.encode(body.get("reply", ""), add_special_tokens=False))
        if not reply:
            raise ValueError("reply is empty")

        def run(intervene):
            self.steering.clear()
            # The prompt's state from the prefix cache when it is there (the same prompt is scored many times).
            cache, rest = (self.cache.fetch_nearest_cache(self.id, prompt[:-1]) if self.cache is not None else (None, None))
            if cache is None or (rest is not None and len(rest) == len(prompt) - 1):
                cache, rest = make_prompt_cache(self.model), prompt[:-1]
            if len(rest):
                self.prefill(cache, list(rest))
                if self.cache is not None:
                    self.cache.insert_cache(self.id, prompt[:-1], copy.deepcopy(cache))
            endo = physio_in = None
            if intervene:
                leanings = body.get("steering") or {}
                if self.vectors and leanings:
                    self.steering.set(self.vectors, leanings, strength=strength, method=body.get("method"), gated=body.get("gate"))
                physio_in = body.get("physio") or None
                if physio_in is not None:
                    self.steering.physio = physio_of(physio_in, 0.0, body.get("physio_params"))
                if body.get("endocrine") is not None:
                    endo = endocrine_of(body["endocrine"], self.hidden_size(), len(self.steering.layers))
                    self.steering.norm_probe = self.steering.band()[0]
                    self.steering.update_gain = endo.gains()
            loop = bool(body.get("entropy_loop", self.config.entropy_loop)) and physio_in is not None
            stress, usual, logprobs, x = 0.0, self.config.entropy_baseline, [], prompt[-1]
            try:
                for target in reply:
                    logits = self.model(mx.array([[x]]), cache=cache)[0, -1].astype(mx.float32)
                    lp = logits - mx.logsumexp(logits)
                    mx.eval(lp)
                    logprobs.append(lp)
                    entropy = entropy_of(lp)
                    if endo is not None:
                        norm = float(self.steering.last_norm) if self.steering.last_norm is not None else 1.0
                        self.steering.update_gain = endo.step(entropy, float(-lp[target]), norm)
                    if loop:
                        stress, usual = stress_step(self.config, stress, usual, entropy)
                        self.steering.physio = physio_of(physio_in, max(0.0, stress), body.get("physio_params"))
                    x = target
            finally:
                self.steering.clear()
            return logprobs, (endo.describe() | {"trace": endo.trace} if endo is not None else None)

        plain, _ = run(False)
        changed, trace = run(True)
        # Is the change only a sharpening or flattening? For each token the plain distribution is re-tempered,
        # p_T ∝ p^(1/T), with T fitted to the intervened one; what KL(q ‖ p_T) leaves is the part no temperature
        # explains. A uniform gain on the updates can act much like a temperature, so this is the control.
        temps = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0, 2.5]
        kl, ent_p, ent_c, residual, fitted, kl_at = [], [], [], [], [], {t: [] for t in temps}
        for lp, lq in zip(plain, changed):
            p_, q_ = mx.exp(lp), mx.exp(lq)
            kl.append(float(mx.sum(p_ * (lp - lq))))
            ent_p.append(float(-mx.sum(p_ * lp)))
            ent_c.append(float(-mx.sum(q_ * lq)))
            best = None
            for t in temps:
                lpt = lp / t
                lpt = lpt - mx.logsumexp(lpt)
                d = float(mx.sum(q_ * (lq - lpt)))
                kl_at[t].append(float(mx.sum(p_ * (lp - lpt))))
                if best is None or d < best[0]:
                    best = (d, t)
            residual.append(best[0])
            fitted.append(best[1])
        n = len(kl)
        return {
            "tokens": n, "kl": sum(kl) / n, "kl_per_token": [round(v, 4) for v in kl],
            "entropy_plain": sum(ent_p) / n, "entropy": sum(ent_c) / n,
            # What a pure temperature change of the plain distribution would score, per T, for matching.
            "kl_temperature": {str(t): sum(v) / n for t, v in kl_at.items()},
            "residual": sum(residual) / n, "fitted_temperature": sum(fitted) / n,
            "hormones": trace,
        }

    def status(self):
        return {
            "id": self.id,
            "kind": self.kind,
            "loaded": True,
            "steerable": self.vectors is not None,
            "vectors": os.path.basename(self.vectors_path) if self.vectors_path else None,
            "layers": len(self.steering.layers),
            "cache_entries": len(self.cache) if self.cache is not None else 0,
            "loaded_at": self.loaded_at,
            "used_at": self.used_at,
        }


# ── embeddings ─────────────────────────────────────────────────────────────────


class EmbeddingModel:
    kind = "embedding"
    MAX_LENGTH = 1024  # tokens per text; memory chunks are far shorter, and bge-m3's quality holds here

    def __init__(self, spec: ModelSpec, config: Config):
        from embed import Embedder

        started = time.time()
        self.id = spec.id
        self.embedder = Embedder(spec.id, max_length=self.MAX_LENGTH)
        self.dimensions = self.embedder.dimensions
        self.loaded_at = time.time()
        self.used_at = self.loaded_at
        log.info("loaded %s in %.1fs (embeddings, %d dimensions, %s pooling)", spec.id, self.loaded_at - started, self.dimensions, self.embedder.pooling)

    def configure(self, config: Config):
        pass

    def embed(self, texts):
        vectors = self.embedder.embed(texts)
        self.used_at = time.time()
        return vectors

    def status(self):
        return {"id": self.id, "kind": self.kind, "loaded": True, "dimensions": self.dimensions, "loaded_at": self.loaded_at, "used_at": self.used_at}


# ── registry ───────────────────────────────────────────────────────────────────


class Registry:
    """Every configured model, loaded when first asked for; one lock for the GPU."""

    def __init__(self, config: Config):
        self.config = config
        self.models = {}  # id -> ChatModel | EmbeddingModel
        self.lock = threading.RLock()  # held for every forward pass and every load
        self.started = time.time()
        self.requests = 0
        self.trace = Trace()

    def apply(self, config: Config):
        """A new configuration: unloads what is no longer listed, passes mode and muting to what stays."""
        with self.lock:
            self.config = config
            for model_id in list(self.models):
                if config.spec(model_id) is None:
                    self.unload(model_id)
            for model in self.models.values():
                model.configure(config)
        log.info("config: %d model(s), strength %.2f, mode %s, tool calls %s", len(config.models), config.strength, config.mode, "muted" if config.mute_tool_calls else "steered")

    def preload(self, kinds=("chat", "embedding")):
        for spec in self.config.models:
            if spec.kind in kinds:
                try:
                    self.get(spec.id)
                except Exception as err:  # noqa: BLE001 — the others still load
                    log.error("could not load %s: %s", spec.id, err)

    def get(self, model_id):
        """The loaded model, loading it first; an unlisted id is loaded as a chat model and noted."""
        with self.lock:
            model = self.models.get(model_id)
            if model is None:
                spec = self.config.spec(model_id)
                if spec is None:
                    log.warning("%s is not in the config; loading it as a chat model", model_id)
                    spec = ModelSpec(model_id)
                self.evict(keep=model_id)
                model = (EmbeddingModel if spec.kind == "embedding" else ChatModel)(spec, self.config)
                self.models[model_id] = model
            return model

    def evict(self, keep=None):
        """Drops the least recently used models until one more fits under max_loaded."""
        while len(self.models) >= self.config.max_loaded:
            victims = sorted((m for i, m in self.models.items() if i != keep), key=lambda m: m.used_at)
            if not victims:
                return
            self.unload(victims[0].id)

    def unload(self, model_id):
        model = self.models.pop(model_id, None)
        if model is not None:
            del model
            mx.clear_cache()
            log.info("unloaded %s", model_id)

    def complete(self, body, emit=None) -> tuple[ChatModel, Generation]:
        with self.lock:
            self.requests += 1
            model = self.get(body.get("model") or self.default_id("chat"))
            if model.kind != "chat":
                raise ValueError(f"{model.id} is an embedding model")
            request = self.trace.begin(model, body)
            gen = model.complete(body, self.config.strength, emit, trace=lambda text, rows, g: self.trace.step(request, text, rows, g))
            self.trace.end(request, gen)
            return model, gen

    def attribute(self, body) -> dict:
        """What pushed one token of the model's reply (attribute.py), on the chat model, under the same lock as generation."""
        from attribute import attribute  # noqa: PLC0415

        with self.lock:
            self.requests += 1
            model = self.get(body.get("model") or self.default_id("chat"))
            if model.kind != "chat":
                raise ValueError(f"{model.id} is an embedding model")
            if not model.vectors:
                raise ValueError(f"{model.id} has no control vectors to read leanings with")
            return attribute(model, body, self.config.strength)

    def divergence(self, body) -> dict:
        with self.lock:
            self.requests += 1
            model = self.get(body.get("model") or self.default_id("chat"))
            if model.kind != "chat":
                raise ValueError(f"{model.id} is an embedding model")
            return model.divergence(body, self.config.strength)

    def embed(self, body) -> tuple[EmbeddingModel, list]:
        texts = body.get("input", [])
        texts = [texts] if isinstance(texts, str) else [str(t) for t in texts]
        with self.lock:
            self.requests += 1
            model = self.get(body.get("model") or self.default_id("embedding"))
            if model.kind != "embedding":
                raise ValueError(f"{model.id} is a chat model")
            return model, model.embed(texts)

    def default_id(self, kind):
        spec = next((m for m in self.config.models if m.kind == kind), None)
        if spec is None:
            raise ValueError(f"no {kind} model is configured")
        return spec.id

    def busy(self):
        """Whether a forward pass is running right now (asked from another thread, so the lock tells)."""
        if self.lock.acquire(blocking=False):
            self.lock.release()
            return False
        return True

    def status(self):
        listed = []
        for spec in self.config.models:
            loaded = self.models.get(spec.id)
            if loaded is not None:
                listed.append(loaded.status())
            else:
                path = spec.vectors or vectors_path_for(spec.id)
                listed.append({"id": spec.id, "kind": spec.kind, "loaded": False, **({"steerable": os.path.exists(path)} if spec.kind == "chat" else {})})
        for model_id, model in self.models.items():
            if self.config.spec(model_id) is None:
                listed.append({**model.status(), "unlisted": True})
        return {
            "ok": True,
            "uptime": time.time() - self.started,
            "requests": self.requests,
            "busy": self.busy(),
            "memory": {"active": mx.get_active_memory(), "peak": mx.get_peak_memory()},
            "config": self.config.as_dict(),
            "models": listed,
        }


class Trace:
    """The forward passes as they happen, for the page that draws them: a ring of events, each with a sequence
    number, so a reader asks for everything after the last one it saw. One event per request start, one per token
    (its text and every layer's row), one per request end."""

    KEEP = 600

    def __init__(self):
        self.events = []
        self.seq = 0
        self.lock = threading.Lock()

    def push(self, event):
        with self.lock:
            self.seq += 1
            event["seq"] = self.seq
            self.events.append(event)
            del self.events[: -self.KEEP]

    def begin(self, model, body):
        request = {"id": uuid.uuid4().hex[:8], "model": model.id, "layers": len(model.steering.layers), "steerable": model.vectors is not None}
        self.push({"type": "begin", "request": request["id"], "model": model.id, "layers": request["layers"], "dims": list(model.vectors.directions) if model.vectors else [], "band": list(model.steering.band(len(model.steering.layers))), "steering": body.get("steering") or {}})
        return request

    def step(self, request, text, rows, gen):
        so_far = gen.text
        # Inside the model's reasoning: opened in the prompt and not yet closed, or opened in the output and not yet closed.
        thinking = inside_thinking(so_far, gen.thinking_open) or text.strip() == "</think>"
        self.push({"type": "token", "request": request["id"], "text": text, "rows": rows, "thinking": thinking, "muted": gen.applied.mute_tool_calls and inside_tool_call(gen.text) if gen.applied else False})

    def end(self, request, gen):
        self.push({"type": "end", "request": request["id"], "tokens": gen.generated_tokens, "prompt": gen.prompt_tokens, "cached": gen.cached_tokens, "seconds": round(gen.seconds, 2), "applied": gen.applied.as_dict() if gen.applied else None})

    def since(self, after):
        with self.lock:
            return {"seq": self.seq, "events": [event for event in self.events if event["seq"] > after]}
