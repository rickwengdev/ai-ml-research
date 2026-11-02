"""Attribution for one token of the model's reply: what in the input, in the model's leanings and in the model's steering pushed the model
to say it. A cheap stand-in for an attribution graph (Anthropic's circuit-tracer) on a model nobody has trained
transcoders for: the nodes are things already readable (the input tokens, the nine leaning directions at every layer,
the steering shift each layer adds), and the edges are gradient × activation, the same first-order rule.

The pass, for the reply token at index t (predicted from the prompt and the reply before it):
- Only the last `window` tokens before t (24 by default) are differentiated; everything before them is a constant,
  from the prefix cache. Backpropagating through the gated delta layers keeps every token's recurrent state, so the
  window is what bounds the memory.
- The model's steering is applied to the reply positions of the tail as generation applied it there (steer.py `span`).
- A zero probe is added to every layer's output and to the first layer's input. The gradient of the target token's
  log-probability by each probe, at the last position, is g_l; then
    leaning node (l, d):   (g_l · v_{d,l}) × (v_{d,l} · h_l − μ_{d,l})      how much that leaning's deviation pushed
    steering at layer l:   g_l · shift_l                                    how much the shift added there pushed
    layer l:               g_l · (h_l − h_{l−1})                            how much the layer's own update pushed
    input token j:         Σ g_in[j] · x_in[j]                              saliency of each tail token
- Edges: for the strongest leaning nodes, the same rule with that node's projection as the objective instead of the
  token: which other leanings earlier layers wrote and which input tokens fed it. An edge counts only what a layer
  wrote (its update, not the residual it carries along) on the part of the source leaning not shared with the
  target's, so neither the residual stream nor the leanings' overlap passes for a cause.

All first-order (linear) estimates through a nonlinear network: they rank causes, they do not measure them exactly.
The recurrent (gated delta) layers are differentiated as they are, not frozen; see research for the frozen variant.
"""
from __future__ import annotations

import contextlib
import copy
import time

import mlx.core as mx
import numpy as np

from steer import DIMS, LABEL


# Tokens differentiated by default, and at most (each costs about 50 MB through the recurrent layers).
WINDOW = 24
MAX_WINDOW = 64


@contextlib.contextmanager
def differentiable(model):
    """Qwen3.5's gated delta layers run a Metal kernel with no gradient; the pure-ops version has one."""
    module = None
    try:
        import mlx_lm.models.qwen3_5 as module  # noqa: PLC0415
    except ImportError:
        pass
    original = getattr(module, "gated_delta_update", None) if module else None
    if original is None:
        yield
        return

    def ops(*args, **kwargs):
        kwargs["use_kernel"] = False
        return original(*args, **kwargs)

    module.gated_delta_update = ops
    try:
        yield
    finally:
        module.gated_delta_update = original


def attribute(chat, body, strength):
    """`chat` is a loaded ChatModel; `body` carries messages (ending with his), reply (the model's text), index (which reply
    token, default the last), steering (the model's leanings), edges (how many nodes to trace back, default 5)."""
    from mlx_lm.models.cache import make_prompt_cache  # noqa: PLC0415

    started = time.time()
    tokenizer, model, steer, vectors = chat.tokenizer, chat.model, chat.steering, chat.vectors
    prompt = list(chat.prompt_tokens_for({"messages": body["messages"], "reasoning_effort": body.get("reasoning_effort", "none")}))
    reply = list(tokenizer.encode(body.get("reply", ""), add_special_tokens=False))
    if not reply:
        raise ValueError("reply is empty: give the text the model said, or part of it")
    index = int(body.get("index", len(reply) - 1)) % len(reply)
    target = reply[index]
    tokens = prompt + reply[:index]

    # Only the last `window` tokens are differentiated: through the gated delta layers a backward pass keeps the
    # recurrent state of every token (about 2 MB per token per layer), so a few hundred would not fit in memory.
    # Everything before is a constant: the prompt from the model's prefix cache, unsteered as generation reads it, then
    # the part of the model's reply already said, read with the model's steering as it was generated.
    window = max(4, min(MAX_WINDOW, int(body.get("window", WINDOW))))
    split = max(1, len(tokens) - window)
    tail = tokens[split:]
    steer.clear()
    if chat.cache is not None:
        cache, rest = chat.cache.fetch_nearest_cache(chat.id, prompt[: min(split, len(prompt))])
    else:
        cache, rest = None, None
    if cache is None:
        cache, rest = make_prompt_cache(model), prompt[: min(split, len(prompt))]
    if rest:
        chat.prefill(cache, list(rest))
    applied = steer.set(vectors, body.get("steering") or {}, strength=strength) if vectors and body.get("steering") else None
    if split > len(prompt):
        steer.span = 0
        chat.prefill(cache, tokens[len(prompt) : split])
    steer.span = max(0, len(prompt) - split)  # where the model's reply starts in the tail
    n = len(steer.layers)
    try:
        with differentiable(model):
            # 1. A plain pass: what each layer holds, the shifts, the prediction.
            steer.probes, steer.records = None, {}
            logits = model(mx.array(tail)[None], cache=copy.deepcopy(cache))
            records = steer.records
            mx.eval(logits, *records.values())
            hidden = records[0].shape[-1]
            shape = (1, len(tail), hidden)
            probs = mx.softmax(logits[0, -1].astype(mx.float32))
            top = mx.argsort(-probs)[:6].tolist()
            prediction = {
                "target": {"id": target, "text": tokenizer.decode([target]), "p": float(probs[target])},
                "alternatives": [{"id": t, "text": tokenizer.decode([t]), "p": float(probs[t])} for t in top if t != target][:5],
            }
            h = {i: np.array(records[i][0, -1].astype(mx.float32)) for i in range(n)}
            x_in = np.array(records["in"][0].astype(mx.float32)) if "in" in records else None
            shifts = {i: np.array(records[f"shift{i}"][0, -1].astype(mx.float32)) for i in range(n) if f"shift{i}" in records}

            def grads(objective_of):
                """Gradients of objective_of(logits, records) by a zero probe on every layer (and the input)."""
                zeros = {"in": mx.zeros(shape), **{i: mx.zeros(shape) for i in range(n)}}

                def objective(probes):
                    steer.probes, steer.records = probes, {}
                    out = model(mx.array(tail)[None], cache=copy.deepcopy(cache))
                    return objective_of(out, steer.records)

                g = mx.grad(objective)(zeros)
                mx.eval(g)
                return {k: np.array(v[0].astype(mx.float32)) for k, v in g.items()}

            g = grads(lambda out, _: (out[0, -1].astype(mx.float32) - mx.logsumexp(out[0, -1].astype(mx.float32)))[target])

            dims = [d for d in DIMS if vectors and d in vectors.directions]
            leaning_nodes = []
            for l in range(n):
                for d in dims:
                    v = vectors.directions[d][l]
                    dev = float(v @ h[l]) - vectors.mean(d, l)
                    sigma = float(vectors.spreads[d][l]) if d in vectors.spreads else vectors.scales[d]
                    leaning_nodes.append({"layer": l, "dim": d, "label": LABEL.get(d, d), "sigma": round(dev / sigma, 2), "attr": round(float(g[l][-1] @ v) * dev, 4)})
            steering_by_layer = [{"layer": l, "attr": round(float(g[l][-1] @ shifts[l]), 4)} for l in sorted(shifts)]
            layer_updates = [{"layer": l, "attr": round(float(g[l][-1] @ (h[l] - (h[l - 1] if l else x_in[-1]))), 4)} for l in range(n)] if x_in is not None else []
            text = [tokenizer.decode([t]) for t in tail]
            saliency = [round(float(v), 4) for v in (g["in"] * x_in).sum(-1)] if x_in is not None else []

            # 2. Edges into the strongest leaning nodes.
            # The strongest nodes, at most two per leaning: neighbouring layers of one leaning have the same sources.
            strongest, per_dim = [], {}
            for node in sorted(leaning_nodes, key=lambda node: -abs(node["attr"])):
                if len(strongest) >= int(body.get("edges", 5)):
                    break
                if per_dim.get(node["dim"], 0) < 2:
                    strongest.append(node)
                    per_dim[node["dim"]] = per_dim.get(node["dim"], 0) + 1
            edges = []
            for node in strongest:
                l, d = node["layer"], node["dim"]
                v = mx.array(vectors.directions[d][l].astype(np.float32))
                gn = grads(lambda _, records, l=l, v=v: records[l][0, -1].astype(mx.float32) @ v)
                incoming = []
                for l2 in range(l):
                    # The same direction one layer down mostly is the residual stream carrying it; other leanings
                    # feeding this one are what says something.
                    for d2 in (d2 for d2 in dims if d2 != d):
                        # What layer l2 wrote along d2 this time, on the part of d2 not shared with d: leanings
                        # overlap (guard and patience, cosine −0.57), and an edge should not just measure that.
                        v2, vd = vectors.directions[d2][l2], vectors.directions[d][l2]
                        v2 = v2 - (v2 @ vd) * vd
                        v2 = v2 / max(float(np.linalg.norm(v2)), 1e-6)
                        written = h[l2] - (h[l2 - 1] if l2 else x_in[-1])
                        incoming.append({"from": {"layer": l2, "dim": d2}, "weight": float(gn[l2][-1] @ v2) * float(v2 @ written)})
                tokens_in = [{"from": {"token": j}, "weight": float(w)} for j, w in enumerate((gn["in"] * x_in).sum(-1))] if x_in is not None else []
                for edge in sorted(incoming, key=lambda e: -abs(e["weight"]))[:4] + sorted(tokens_in, key=lambda e: -abs(e["weight"]))[:3]:
                    edges.append({**edge, "to": {"layer": l, "dim": d}, "weight": round(edge["weight"], 4)})
    finally:
        steer.probes, steer.records, steer.span = None, None, None
        steer.clear()

    return {
        "model": chat.id,
        "index": index,
        "reply_tokens": [tokenizer.decode([t]) for t in reply],
        "tail": text,
        "reply_start": max(0, len(prompt) - split),
        "window": window,
        "prediction": prediction,
        "saliency": saliency,
        "leanings": leaning_nodes,
        "steering": steering_by_layer,
        "steering_total": round(sum(s["attr"] for s in steering_by_layer), 4),
        "layers": layer_updates,
        "edges": edges,
        "applied": applied.as_dict() if applied else None,
        "seconds": round(time.time() - started, 2),
    }

