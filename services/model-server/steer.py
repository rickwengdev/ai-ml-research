"""Activation steering: the model's behavior leanings added straight to the model's residual stream.

The math, per decoder layer l in the steered band and per leaning d, at every token the model produces:

    p      = v_{d,l} · h_{l+1} − μ_{d,l}                          how far the token already sits along the leaning
    t      = α_d · min(r_{d,l} / FULL, K · σ_{d,l})                 where the model's state says it should sit
    h_{l+1} <- h_{l+1} + Σ_d max(0, t − p) · v_{d,l}    (for a negative t: min(0, t − p)); only the gap, toward t

- v_{d,l}  the direction of leaning d at layer l: a unit vector found by contrast (extract.py);
- μ_{d,l}  where neutral activity sits along it at that layer;
- r_{d,l}  how far the pole sits from neutral there (the positive pole for t > 0, the negative one for t < 0): the
           distance a system instruction like "妳現在很戒備" moves the model. α = FULL never goes past it;
- σ_{d,l}  the neutral spread along the direction at that layer, and K how many of them one unit of α may move. An
           instruction moves everything that belongs with the trait at once; one direction alone, pushed as far, comes
           apart (deep layers' poles sit dozens of σ out), so the pole is a ceiling and K·σ the working distance;
- α_d      the model's leaning (−1..1) × the server's strength × a per-leaning damping, capped at MAX_ALPHA; when the leanings
           together sum past TOTAL_ALPHA, all are scaled down by the same factor.

A target, not a sum. The residual stream carries every layer's addition forward, so adding a fixed shift at each of
16 layers piled up to 16σ and more by the band's end, far past where any instruction ever puts the model, and the
output came apart. Steering to a target fills only the gap: the shift is bounded however many layers are steered.
Whatever the context already put along v beyond the target stays (it is never pulled back), so the model's state is a floor
under what the conversation does, not an override.

Vector files from before μ and r were saved fall back to the old addition, h += α · s_d · v_{d,l}.

Three guards keep it off what should stay sober:
- generate-only (default): the shift is applied while the model produces tokens, not while the prompt (system text, tool
  definitions, tool results) is being read;
- tool-call muting (default): inside a <tool_call> block the shift is zero, so a mood never reaches a tool's arguments;
- thinking muting (default): inside <think> the shift is zero, so the model's reasoning stays clear and the state colors how
  the model says it.
Muting covers every intervention the hook applies, not only the directional shift: the physio gains and the
endocrine receptors' gains are off on muted steps too (the hormones themselves keep being secreted, engine.py).

The decoder layer class is patched once; what to add is set per request and cleared after. Captured activations
(for extraction) go through the same hook. Every request leaves an Applied record saying exactly what was done.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import mlx.core as mx
import numpy as np

# Seven leanings from the chemistry (the runtime); familiarity from how long and how much
# they have talked (the runtime); love from the bond and the chemistry
# (the runtime). Felt in the activations, never told.
DIMS = ["energy", "warmth", "guard", "focus", "play", "patience", "initiative", "familiarity", "love"]
LABEL = {"energy": "能量", "warmth": "溫度", "guard": "戒備", "focus": "專注", "play": "玩心", "patience": "耐心", "initiative": "主動", "familiarity": "熟悉", "love": "愛"}
# Names a request may still use for a leaning that was renamed.
ALIASES = {"closeness": "familiarity"}

# The alpha that reaches a pole: the server's default strength, so a full leaning sits where an instruction would put it.
FULL = 2.5
# No leaning goes past this after strength and damping (sweep.py).
MAX_ALPHA = 3.5
# How many neutral standard deviations, at each layer, one unit of alpha moves the model at most (sweep.py). At 1 most
# leanings barely show; at 2 each reads clearly alone, but sampled mixes turn crude and slangy; at 3 a short temper
# already swears. 1.5: every leaning visible at ±1, every mix the model's chemistry makes coherent at temperature 0.7.
SIGMA_PER_ALPHA = 1.5
# Several leanings at once share this much alpha (the sum of |α|); past it they are scaled down together, keeping their
# proportions. Each alone holds at full strength, but energy, play, initiative, warmth and familiarity all at +1 read to
# the model as mania (slang, simplified characters, then loops) however the joint shift is capped; the mixes the model's
# chemistry actually produces sum to about 4–5 (sweep.py).
TOTAL_ALPHA = 5.0
# How the shift is applied (experiments compare them; steer_thinking etc. are the same for all):
#   target  one-sided: each layer in the band fills only the gap to the target (the default; Assistant Axis's
#           activation capping with a per-request threshold);
#   add     each layer in the band adds α · s_d · v_{d,l} (activation addition, as CAA / ActAdd do per layer);
#   ace     one layer (the band's middle) has its component along v set to μ + target, two-sided (affine concept
#           editing: projection replaced by the reference point, then the offset added).
#   mul     each layer in the band multiplies the component its own update writes along v by a gain 2^(α/MAX_ALPHA)
#           (a full leaning doubles it, −full halves it): a volume knob on what the layer computes, which cannot
#           create a feature the context did not put there. The gain is on the update, not the residual, so it does
#           not compound across the band.
METHODS = ("target", "add", "ace", "mul")

# Hill gating (a dose-response curve): a leaning below the threshold barely acts, and one far past it saturates, so
# a large state never drives the shift past the cap. sign(x)·|x|^n / (K^n + |x|^n), in units of the cap.
# Note the curve crosses the identity: with n = 2, K = 1.5 and cap 3.5, gate(α) > α for 0.85 < |α| < 2.65. At the
# default strength a leaning of ±1 (α 2.5) comes out at 2.57, so in the usual range gating raises the dose a little
# rather than softening it; it only holds α down past ~2.65.
HILL_N = 2.0
HILL_K = 1.5


def gate(alpha, cap=None):
    """A gated alpha: Hill curve with half-maximum at HILL_K, saturating at `cap` (MAX_ALPHA by default)."""
    cap = MAX_ALPHA if cap is None else cap
    a = abs(alpha)
    return (1 if alpha >= 0 else -1) * cap * a**HILL_N / (HILL_K**HILL_N + a**HILL_N)


# ── direct physiology ──────────────────────────────────────────────────────
# Hormone levels acting on the model the way they act on a brain, with no translation into behaviour directions:
# a gain on what the circuits already compute (adaptive gain, Servan-Schreiber, Printz & Cohen 1990; Aston-Jones &
# Cohen 2005), not a vector added to it. Inputs are each chemical's deviation from the model's baseline (−1..1,
# the runtime stateOf) and a stress term the generation feeds back from its own
# uncertainty (engine.py: the entropy loop). Outputs are a few knobs:
#   band_gain    noradrenaline (+adrenaline, −endorphin): the band's layer updates scaled, signal over noise;
#   late_gain    cortisol and acute stress: the deep layers' updates scaled down (stress impairs the "prefrontal"
#                end of the network, Arnsten 2009);
#   social_gain  oxytocin: what each band layer's own update writes on the social subspace (warmth, love,
#                familiarity) scaled, unsigned: whatever the layer adds there, more of it (it is the update that is
#                scaled, not the residual's distance from neutral);
#   temperature  dopamine widens sampling (exploration), adrenaline and noradrenaline narrow it (precision).
# Every input goes through the same Hill curve with K = hill_k (0.5), so g(1) = 0.8: noradrenaline +1 alone gives
# band_gain 1 + 0.5·0.8 = 1.40, and −1 gives 0.60. A gain with no direction, the same at every unit of the band.
PHYSIO = {"band": 0.5, "late": 0.4, "social": 0.6, "explore": 0.4, "precision": 0.5, "hill_k": 0.5}
SOCIAL = ("warmth", "love", "familiarity")


def physio_of(deviation, stress=0.0, params=None):
    """The gains and temperature multiplier for a set of chemical deviations and a stress term."""
    P = {**PHYSIO, **(params or {})}
    d = {k: float(deviation.get(k, 0.0) or 0.0) for k in ("NOREPINEPHRINE", "ADRENALINE", "ENDORPHIN", "CORTISOL", "OXYTOCIN", "DOPAMINE")}
    k = P["hill_k"]
    g = lambda x: (1 if x >= 0 else -1) * abs(x) ** HILL_N / (k**HILL_N + abs(x) ** HILL_N)  # −1..1
    arousal = g(d["NOREPINEPHRINE"] + 0.5 * d["ADRENALINE"] - 0.5 * d["ENDORPHIN"])
    strain = g(max(0.0, d["CORTISOL"]) + max(0.0, stress))
    return {
        "band_gain": 1.0 + P["band"] * arousal,
        "late_gain": 1.0 - P["late"] * strain,
        "social_gain": 1.0 + P["social"] * g(d["OXYTOCIN"]),
        "temperature": (1.0 + P["explore"] * max(0.0, g(d["DOPAMINE"]))) / (1.0 + P["precision"] * max(0.0, g(d["ADRENALINE"] + d["NOREPINEPHRINE"]))),
        "arousal": arousal,
        "strain": strain,
    }


# Where the base model's idea of the trait outruns hers: a little impatience already turns to insults in
# Qwen3.5-4B, so those leanings are applied more gently. The model's constitution sets the words; steering only the state.
# Love at 0.8: a full leaning (α 2) reads as missing him, a little clingy, never explicit; past α 3 it starts to slip
# into simplified characters (sweep.py).
DAMPING = {"patience": 0.6, "guard": 0.8, "familiarity": 0.8, "love": 0.8}
# The band of layers steered, as fractions of the depth: early layers still handle tokens, late ones pick the next
# word; the middle carries meaning and manner.
LAYER_BAND = (0.3, 0.8)


def decoder_layers(model):
    """The list of decoder layers, whichever wrapper the architecture uses."""
    for path in ("model.layers", "language_model.model.layers", "layers"):
        node = model
        try:
            for part in path.split("."):
                node = getattr(node, part)
        except AttributeError:
            continue
        if isinstance(node, list) and node:
            return node
    raise RuntimeError("could not find the decoder layers")


@dataclass
class Vectors:
    """The directions and scales for one model, as extract.py writes them (vectors/<model>.npz)."""

    directions: dict  # dim -> np.ndarray [layers, hidden], unit norm per layer
    scales: dict  # dim -> float
    layers: list = field(default_factory=list)
    hidden: int = 0
    means: dict = field(default_factory=dict)  # dim -> np.ndarray [layers]: neutral activity's mean along the direction
    reach: dict = field(default_factory=dict)  # dim -> np.ndarray [2, layers]: distance to the positive, negative pole
    spreads: dict = field(default_factory=dict)  # dim -> np.ndarray [layers]: neutral standard deviation along it
    extra: dict = field(default_factory=dict)  # anything else extract.py keeps (raw directions, nuisance axes), by name

    @classmethod
    def load(cls, path):
        data = np.load(path)
        meta = json.loads(str(data["meta"]))
        dims = meta["dims"]
        means = {dim: data[f"{dim}.mean"] for dim in dims if f"{dim}.mean" in data.files}
        reach = {dim: data[f"{dim}.reach"] for dim in dims if f"{dim}.reach" in data.files}
        spreads = {dim: data[f"{dim}.spread"] for dim in dims if f"{dim}.spread" in data.files}
        extra = {name: data[name] for name in data.files if name.startswith(("raw.", "nuisance."))}
        return cls({dim: data[dim] for dim in dims}, meta["scales"], meta["layers"], meta["hidden"], means, reach, spreads, extra)

    def save(self, path):
        meta = {"dims": list(self.directions), "scales": self.scales, "layers": self.layers, "hidden": self.hidden}
        extra = {f"{dim}.mean": v for dim, v in self.means.items()} | {f"{dim}.reach": v for dim, v in self.reach.items()} | {f"{dim}.spread": v for dim, v in self.spreads.items()}
        np.savez(path, meta=json.dumps(meta), **self.directions, **extra, **self.extra)

    @property
    def targeted(self):
        """True when every direction has its neutral point and poles, so steering can aim rather than add."""
        return all(dim in self.means and dim in self.reach and dim in self.spreads for dim in self.directions)

    def target(self, dim, layer, alpha, sigma_per_alpha=SIGMA_PER_ALPHA):
        """Where alpha aims along dim at layer, from neutral: never past the pole, at most K neutral σ per unit."""
        side = 0 if alpha > 0 else 1
        distance = min(float(self.reach[dim][side][layer]) / FULL, sigma_per_alpha * float(self.spreads[dim][layer]))
        return alpha * distance

    def mean(self, dim, layer):
        return float(self.means[dim][layer]) if dim in self.means else 0.0


@dataclass
class Applied:
    """What one request's steering came to, for the log and the response: readable by a person."""

    requested: dict  # dim -> the model's leaning as sent
    alphas: dict  # dim -> effective alpha after strength, damping and the cap
    capped: list  # dims that hit MAX_ALPHA
    layers: tuple  # (first, last+1) layer indices steered
    mode: str  # "generate" or "always"
    mute_tool_calls: bool
    targeted: bool = True  # steered to a target (bounded) rather than added at every layer
    scaled: float = 1.0  # the factor all alphas were scaled by to stay within TOTAL_ALPHA
    method: str = "target"
    gated: bool = False
    physio: dict | None = None  # the gains a physio request came to (the last ones, when the entropy loop moved them)
    endocrine: dict | None = None  # the nameless endocrine run's description and its hormone trace
    steered_tokens: int = 0  # decode steps the shift was applied to
    muted_tokens: int = 0  # decode steps inside a tool call or thinking, left unsteered

    def summary(self):
        # Keyed on the leanings: a physio- or endocrine-only request logs as "no steering" (its gains are still in
        # as_dict and the response).
        if not self.alphas:
            return "no steering"
        parts = [f"{LABEL.get(d, d)} {a:+.2f}" for d, a in sorted(self.alphas.items(), key=lambda kv: -abs(kv[1]))]
        capped = f", capped: {','.join(self.capped)}" if self.capped else ""
        how = self.method + (", gated" if self.gated else "") + (f", scaled ×{self.scaled:.2f}" if self.scaled < 1 else "")
        if self.physio:
            how += f"; physio band ×{self.physio['band_gain']:.2f} late ×{self.physio['late_gain']:.2f} social ×{self.physio['social_gain']:.2f} temp ×{self.physio['temperature']:.2f}"
        return f"{' '.join(parts)} on layers {self.layers[0]}–{self.layers[1] - 1} ({self.mode}, {how}{capped}); steered {self.steered_tokens} tokens, muted {self.muted_tokens}"

    def as_dict(self):
        return {
            "requested": self.requested,
            "applied_alpha": {d: round(a, 3) for d, a in self.alphas.items()},
            "capped": self.capped,
            "layers": [self.layers[0], self.layers[1] - 1],
            "mode": self.mode,
            "mute_tool_calls": self.mute_tool_calls,
            "targeted": self.targeted,
            "scaled": round(self.scaled, 3),
            "method": self.method,
            "gated": self.gated,
            "physio": self.physio,
            "endocrine": self.endocrine,
            "full": FULL,
            "steered_tokens": self.steered_tokens,
            "muted_tokens": self.muted_tokens,
        }


class Steering:
    """The hook's state: deltas per layer while a request is steered, the phase guards, and a capture buffer."""

    def __init__(self, mode="generate", mute_tool_calls=True, steer_thinking=False):
        self.mode = mode  # "generate": decode steps only; "always": the prompt too
        self.mute_tool_calls = mute_tool_calls
        self.steer_thinking = steer_thinking
        self.sigma_per_alpha = SIGMA_PER_ALPHA
        self.total_alpha = TOTAL_ALPHA
        self.method = "target"
        self.gate = False  # Hill gating of the alphas (set per request or in the config)
        self.gains = {}  # layer index -> (dirs [D, hidden], means [D], gains [D]) for the mul method
        # Direct physiology (physio_of): a gain on the band's updates, on the deep layers' updates, on the social
        # subspace, read by the hook on every call so the entropy loop can move them mid-generation.
        self.physio = None
        self.late = None  # (first, last+1) layers counted as deep
        # Endocrine receptors (endocrine.py): per-unit gains on a layer's update, set every token by the engine.
        self.update_gain = {}  # layer index -> mx.array [hidden]
        self.norm_probe = None  # layer index whose residual norm the engine reads each token (a secretion signal)
        self.last_norm = None
        self.social = {}  # layer index -> orthonormal basis [S, hidden] of the social subspace
        # Per layer, either a fixed shift (old vector files) or what to aim for: (dirs [D, H], means [D], targets [D]).
        self.deltas = {}  # layer index -> mx.array [hidden]
        self.caps = {}  # layer index -> (unit direction [hidden], ceiling): activation capping (research)
        self.aims = {}  # layer index -> (mx.array [D, hidden], mx.array [D], mx.array [D])
        # Attribution (attribute.py): zero probes added to layer outputs to take gradients by, what each layer gave,
        # and from which token of a multi-token pass the steering applies.
        self.probes = None  # None, or {"in" | layer index: mx.array [1, tokens, hidden]}
        self.records = None  # None, or a dict filled with layer outputs, the first input and each layer's shift
        self.span = None
        self.two_sided = False
        self.muted = False  # set by the server while the output is inside a <tool_call>
        self.applied = None  # the current request's Applied, for counting
        self.capture = None  # None, or dict layer index -> list of mx.array [batch, tokens, hidden]
        self.layers = []
        # The forward-pass trace: per decode step, each layer's residual norm and its projection onto the leaning
        # directions, from neutral, in units of each leaning's scale s_d (Vectors.scales: one number per leaning,
        # not the per-layer neutral σ). Set by `watch`; read with `flush_trace`.
        self.trace_dirs = None  # layer index -> mx.array [dims, hidden]
        self.trace_means = None  # layer index -> mx.array [dims]
        self.trace_scales = None  # mx.array [dims]
        self.pending = {}  # layer index -> mx.array [1 + dims], lazily computed during the step

    # ── attaching to the model ─────────────────────────────────────────────

    def attach(self, model):
        # Each layer instance points at its own model's state: two models of the same architecture share the
        # patched class but never each other's deltas.
        self.layers = decoder_layers(model)
        for i, layer in enumerate(self.layers):
            layer._steer_index = i
            layer._steer_state = self
        cls = type(self.layers[0])
        if getattr(cls, "_steer_patched", False):
            return
        original = cls.__call__

        def steered(layer, x, *args, **kwargs):
            state = getattr(layer, "_steer_state", None)
            i = getattr(layer, "_steer_index", None)
            # Attribution (attribute.py): a zero probe on the first layer's input, to differentiate by the embeddings.
            if state is not None and i == 0:
                if state.probes is not None and "in" in state.probes:
                    x = x + state.probes["in"].astype(x.dtype)
                if state.records is not None:
                    state.records["in"] = x
            full = original(layer, x, *args, **kwargs)
            if state is None or i is None:
                return full
            # A layer may hand back more than the residual: Gemma 4 returns (h, shared kv, offset); Gemma 3n stacks
            # its AltUp streams on a leading axis, the residual stream first. Only the residual is steered or read.
            tupled = isinstance(full, tuple)
            body = full[0] if tupled else full
            stacked = body.ndim == 4
            out = body[0] if stacked else body
            if state.capture is not None:
                state.capture.setdefault(i, []).append(out)
            delta = state.deltas.get(i)
            aim = state.aims.get(i)
            gain = state.gains.get(i)
            decoding = out.shape[1] == 1
            # Direct physiology and endocrine receptors: the layer's own update (out − x) scaled, per unit for the
            # receptors, uniformly for the band and deep layers, and only its social-subspace part for oxytocin.
            # Applied where the directional shift is (decode steps, not the prompt) and, like it, off while muted.
            physio = state.physio
            if state.update_gain and i in state.update_gain and not state.muted and (decoding or state.mode != "generate"):
                xin = x[0] if x.ndim == 4 else x
                out = xin + (out - xin) * state.update_gain[i].astype(out.dtype)
            if state.norm_probe == i and decoding:
                state.last_norm = mx.linalg.norm(out[0, -1, :].astype(mx.float32))
            if physio is not None and not state.muted and (decoding or state.mode != "generate"):
                band = state.band()
                xin = x[0] if x.ndim == 4 else x
                if band[0] <= i < band[1] and physio["band_gain"] != 1.0:
                    out = xin + (out - xin) * physio["band_gain"]
                if state.late and state.late[0] <= i < state.late[1] and physio["late_gain"] != 1.0:
                    out = xin + (out - xin) * physio["late_gain"]
                basis = state.social.get(i)
                if basis is not None and band[0] <= i < band[1] and physio["social_gain"] != 1.0:
                    # What this layer wrote on the social subspace, scaled: more or less of what the context put there.
                    wrote = (out - xin).astype(mx.float32) @ basis.T  # [batch, tokens, S]
                    out = out + ((physio["social_gain"] - 1.0) * wrote @ basis).astype(out.dtype)
            # A decode step is one token wide; prefill chunks are wider. generate-only leaves the prompt alone. An
            # attribution pass reads the model's reply in one go and steers it from `span` on, where generation would have.
            spanned = state.span is not None
            if (delta is not None or aim is not None or gain is not None) and not state.muted and (decoding or state.mode != "generate" or spanned):
                if state.applied is not None and i == min(state.deltas or state.aims or state.gains):  # count once per step
                    state.applied.steered_tokens += 1
                if gain is not None:
                    dirs, _, gains = gain  # the means are unused: the gain acts on the update, not on a position
                    # What this layer wrote along each leaning, scaled by its gain: more or less of what is present.
                    xin = x[0] if x.ndim == 4 else x
                    wrote = (out - xin).astype(mx.float32) @ dirs.T  # [batch, tokens, D]
                    shift = ((gains - 1.0) * wrote) @ dirs
                elif aim is not None:
                    dirs, means, targets = aim
                    # Where each token sits along each leaning, from neutral; then only the gap toward the target.
                    sits = (out.astype(mx.float32) @ dirs.T) - means  # [batch, tokens, D]
                    gap = targets - sits
                    need = gap if state.two_sided else mx.where(gap * mx.sign(targets) > 0, gap, 0.0)
                    shift = need @ dirs
                else:
                    shift = mx.broadcast_to(delta.astype(mx.float32), out.shape)
                if spanned:
                    shift = shift * (mx.arange(out.shape[1]) >= state.span)[None, :, None]
                if state.records is not None:
                    state.records[f"shift{i}"] = shift
                out = out + shift.astype(out.dtype)
            cap = state.caps.get(i)
            if cap is not None and decoding and not state.muted:
                # Meek-style capping, as in torch_engine: the part of the projection above the ceiling is removed,
                # nothing below it.
                if state.applied is not None and i == min(state.caps) and not state.deltas:
                    state.applied.steered_tokens += 1
                unit, ceiling = cap
                proj = (out.astype(mx.float32) * unit).sum(-1)
                out = out - (mx.maximum(proj - ceiling, 0.0)[..., None] * unit).astype(out.dtype)
            if state.probes is not None and i in state.probes:
                out = out + state.probes[i].astype(out.dtype)
            if state.records is not None:
                state.records[i] = out
            if state.trace_dirs is not None and decoding:
                # Lazy and tiny: evaluated once per token by flush_trace, with the step's own graph.
                h = out[0, -1, :].astype(mx.float32)
                dirs = state.trace_dirs.get(i)
                norm = mx.linalg.norm(h)[None]
                state.pending[i] = norm if dirs is None else mx.concatenate([norm, (dirs @ h - state.trace_means[i]) / state.trace_scales])
            if stacked:
                out = mx.concatenate([out[None], body[1:]])
            return (out, *full[1:]) if tupled else out

        cls.__call__ = steered
        cls._steer_patched = True

    # ── per request ────────────────────────────────────────────────────────

    def band(self, n=None):
        """The (first, last+1) layer indices steered, for a model with `n` layers."""
        n = len(self.layers) if n is None else n
        return (int(n * LAYER_BAND[0]), int(n * LAYER_BAND[1]))

    def set(self, vectors, leanings, strength=1.0, method=None, gated=None):
        """Prepares this request's shift from the model's leanings (dim -> −1..1). Returns the Applied record."""
        band = self.band()
        method = method if method in METHODS else self.method
        gated = self.gate if gated is None else bool(gated)
        self.deltas, self.aims, self.gains, self.muted = {}, {}, {}, False
        alphas, capped = {}, []
        for dim, value in (leanings or {}).items():
            dim = ALIASES.get(dim, dim)
            if dim not in vectors.directions or abs(float(value)) < 1e-6:
                continue
            raw = float(value) * strength * DAMPING.get(dim, 1.0)
            alpha = gate(raw) if gated else max(-MAX_ALPHA, min(MAX_ALPHA, raw))
            if alpha != raw:
                capped.append(dim)
            alphas[dim] = alpha
        total = sum(abs(a) for a in alphas.values())
        scaled = min(1.0, self.total_alpha / total) if total else 1.0
        if scaled < 1.0:
            alphas = {dim: alpha * scaled for dim, alpha in alphas.items()}
        targeted = vectors.targeted and method not in ("add", "mul")
        dims = list(alphas)
        layers = [(band[0] + band[1]) // 2] if method == "ace" else range(*band)
        for i in layers:
            if not dims:
                break
            if method == "mul":
                self.gains[i] = (
                    mx.array(np.stack([vectors.directions[d][i] for d in dims]).astype(np.float32)),
                    mx.array(np.array([vectors.mean(d, i) for d in dims], dtype=np.float32)),
                    mx.array(np.array([2.0 ** (alphas[d] / MAX_ALPHA) for d in dims], dtype=np.float32)),
                )
            elif targeted:
                # Aim each leaning at its share of the way to the pole on its side.
                targets = [vectors.target(d, i, alphas[d], self.sigma_per_alpha) for d in dims]
                self.aims[i] = (
                    mx.array(np.stack([vectors.directions[d][i] for d in dims]).astype(np.float32)),
                    mx.array(np.array([vectors.mean(d, i) for d in dims], dtype=np.float32)),
                    mx.array(np.array(targets, dtype=np.float32)),
                )
            else:
                total = sum(vectors.directions[d][i] * (alphas[d] * vectors.scales[d]) for d in dims)
                self.deltas[i] = mx.array(total.astype(np.float32))
        self.two_sided = method == "ace"
        self.applied = Applied(dict(leanings or {}), alphas, capped, (layers[0], layers[-1] + 1) if dims else band, self.mode, self.mute_tool_calls, targeted, scaled, method, gated)
        return self.applied

    def mute(self, inside_tool_call, thinking=False):
        """Called by the server as text accrues: inside a <tool_call>, or while thinking, the next step is unsteered."""
        self.muted = bool(inside_tool_call and self.mute_tool_calls) or bool(thinking and not self.steer_thinking)
        if self.muted and self.applied is not None:
            self.applied.muted_tokens += 1

    def set_caps(self, vectors, cap):
        """`cap`: {"dim": name, "levels": {layer: ceiling}}, on the band. The ceiling is in units of the projection on
        that layer's unit direction (the vector normalized), as in torch_engine."""
        levels = {int(k): float(v) for k, v in (cap.get("levels") or {}).items()}
        first, last = self.band()
        self.caps = {}
        for i in range(first, last):
            if i in levels:
                v = np.asarray(vectors.directions[cap["dim"]][i], dtype=np.float32)
                self.caps[i] = (mx.array(v / (np.linalg.norm(v) + 1e-12)), levels[i])
        if self.applied is not None:
            self.applied.alphas[f"cap:{cap['dim']}"] = 0.0

    def clear(self):
        self.deltas, self.aims, self.gains, self.muted, self.applied = {}, {}, {}, False, None
        self.caps = {}
        self.physio = None
        self.update_gain, self.norm_probe, self.last_norm = {}, None, None

    # ── the forward-pass trace ─────────────────────────────────────────────

    def watch(self, vectors):
        """Reads every layer's residual from now on, projected onto the leaning directions when there are any."""
        n = len(self.layers)
        self.late = (int(n * LAYER_BAND[1]), n)
        self.social = {}
        if vectors is not None and all(d in vectors.directions for d in SOCIAL):
            for i in range(n):
                basis = np.stack([vectors.directions[d][i] for d in SOCIAL]).astype(np.float32)
                q, _ = np.linalg.qr(basis.T)  # orthonormal columns spanning the three directions
                self.social[i] = mx.array(q.T.astype(np.float32))
        if vectors is not None:
            dims = list(vectors.directions)
            self.trace_dirs = {i: mx.array(np.stack([vectors.directions[d][i] for d in dims]).astype(np.float32)) for i in range(len(self.layers))}
            # Projections are read from neutral, so 0 means "as usual" in the panel (units: s_d, see __init__).
            self.trace_means = {i: mx.array(np.array([vectors.mean(d, i) for d in dims], dtype=np.float32)) for i in range(len(self.layers))}
            self.trace_scales = mx.array(np.array([vectors.scales[d] for d in dims], dtype=np.float32))
        else:
            self.trace_dirs = {}
        self.pending = {}

    def flush_trace(self):
        """The last step's rows, [layers][1 + dims] as floats, or None when nothing was traced."""
        if not self.pending:
            return None
        rows = mx.stack([self.pending[i] for i in sorted(self.pending)])
        mx.eval(rows)
        self.pending = {}
        return [[round(float(v), 3) for v in row] for row in rows.tolist()]


def vectors_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "vectors")


def vectors_slug(model_id):
    """The file stem for a model's vectors: its repo name, lowercased, non-alphanumerics folded to '-'."""
    name = model_id.rstrip("/").split("/")[-1].lower()
    return "-".join(part for part in "".join(c if c.isalnum() or c == "." else "-" for c in name).split("-") if part)


def vectors_path_for(model_id):
    """Where extract.py writes, and the server looks for, this model's vectors (whether or not the file exists)."""
    return os.path.join(vectors_dir(), f"{vectors_slug(model_id)}.npz")


def default_vectors_path():
    return vectors_path_for("mlx-community/Qwen3.5-4B-MLX-4bit")
