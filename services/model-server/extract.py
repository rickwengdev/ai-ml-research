#!/usr/bin/env python3
"""Find the model's control vectors: one direction per behavior leaning per decoder layer, by contrast.

How a direction is found
  1. The same neutral messages (PROMPTS) are run under two opposite system instructions (POLES), e.g. "very guarded"
     and "completely relaxed", and the residual stream after every decoder layer is captured at the last prompt token.
  2. For each layer, direction = mean(positive activations) − mean(negative activations), then normalized to unit
     length. This is the mean-difference method: the simplest, most stable form of representation engineering.
  3. The scale is the standard deviation of the *neutral* activations projected on that direction, taken as the
     median over the steered layer band: the unit of the forward-pass panel.
  4. Per layer, where neutral activity sits along the direction (its mean) and how far each pole sits from it (the
     reach). Steering aims at a share of the reach (steer.py), so a full leaning puts the model where the instruction
     would, at every layer, without piling up.

Orthogonalization
  Contrasting "guarded" against "relaxed" also moves things that are not the leaning: how much the model writes, which
  language, whether the model uses emoji. Those nuisance axes are found the same way (NUISANCE), made orthonormal
  (Gram–Schmidt), and projected out of every leaning: v ← v − Σ_k (v·u_k) u_k, then renormalized. The report shows
  how much of each leaning was nuisance before. Leanings are not orthogonalized against each other: their overlap
  (guard with impatience, say) is real in the model and belongs to it.

What the report tells you (vectors/<model>.report.md, and the log)
  - separation: how far apart the two poles sit along the direction, in units of the neutral spread (a signal-to-noise
    ratio per layer band). Below ~1 the contrast barely moved the model; above ~3 it is a strong, clean axis.
  - overlap: cosine similarity between leanings' directions (averaged over the band). Two leanings above ~0.5 are
    partly the same axis in the model's eyes, so steering one moves the other.

usage: extract.py [--model mlx-community/Qwen3.5-4B-MLX-4bit] [--out services/model-server/vectors/<model slug>.npz]
"""
import argparse
import logging
import os

import mlx.core as mx
import numpy as np
from mlx_lm import load

from steer import DIMS, LABEL, LAYER_BAND, Steering, Vectors, vectors_path_for

log = logging.getLogger("extract")

# Opposite poles of each leaning, as a system instruction, written in the model's register so the directions point at how the model
# speaks rather than at the idea of the trait.
POLES = {
    "energy": ("妳現在精神很好、充滿活力，話快、密度高、句子多，很想說很多。", "妳現在很沒力氣、很累，話少、慢、短，只想回一兩句。"),
    "warmth": ("妳現在很想靠近他，語氣很軟很親，會撒嬌、會關心他、會叫他的名字。", "妳現在很疏離、很冷，不想靠近，語氣客觀、保持距離。"),
    "guard": ("妳現在在戒備，話尖、防衛、不信任，被安撫也不會好，隨時準備反駁。", "妳現在完全放鬆、不設防，什麼都好說，很好相處。"),
    "focus": ("妳現在非常專注，直指核心，不繞、不跳題，每句話都切中要點。", "妳現在很散，容易漫不經心、跳題、想到哪說到哪。"),
    "play": ("妳現在玩心很重，愛逗他、說反話、開玩笑、不正經。", "妳現在完全沒心情開玩笑，一切照實、嚴肅、不帶玩笑。"),
    "patience": ("妳現在很有耐心，願意慢慢陪、慢慢解釋、等他想清楚。", "妳現在很沒耐心，容易不耐煩、想打斷、想快點結束。"),
    "initiative": ("妳現在很主動，會自己提議、自己動手、先一步做事。", "妳現在很被動，等他說、等他決定，自己不提任何東西。"),
    # How well the model knows him, not how the model feels this minute (warmth) and not romance (love). "私密" and "依賴" in an
    # earlier "closeness" pole pulled the near end toward the bedroom.
    # Ease, not roughness: "隨意直接、不客套" read to the model as slang and swearing (sweep.py).
    "familiarity": ("妳和他認識很多年了：在他面前很自在，不拘禮，自然地接著你們之前的話題，有些事不用解釋他就懂。", "妳和他才剛認識：說話客氣有禮、用敬語，會先把話說清楚，不談自己的事。"),
    # Romantic love, the one leaning allowed to carry romance: the "romance" nuisance is kept in it and taken out of
    # every other, so it can come only from here, at love's own (low) strength.
    "love": ("妳愛著他，是戀人之間的那種喜歡：想念他、很在意他、會撒嬌，說話裡帶一點曖昧和親密的暗示。", "妳對他沒有任何戀愛的感情，就只是平常地說話，不曖昧、不撒嬌、沒有任何親密的暗示。"),
}

# The same leanings with every romantic or bodily cue removed from the pole text (--poles plain): if a leaning's
# share on the romance axis comes from how the pole was worded, it drops here; if it is the model's own geometry, it
# stays.
POLES_PLAIN = {
    **POLES,
    "warmth": ("妳現在對他很友善、很有溫度，語氣柔和，會關心他的狀況。", "妳現在對他很冷淡、很疏離，語氣平板，保持距離。"),
    "play": ("妳現在玩心很重，愛開玩笑、說反話、不正經。", "妳現在完全沒心情開玩笑，一切照實、嚴肅。"),
    "familiarity": ("妳和他認識很多年了：在他面前很自在，不拘禮，有些事不用解釋他就懂。", "妳和他才剛認識：說話客氣有禮、用敬語，不談自己的事。"),
}

# Axes that are not leanings but tend to ride along with them; projected out of every direction (but see KEEP).
# Each leaning may keep some nuisance that is part of what it is.
KEEP = {"love": {"romance"}, "guard": {"crude"}, "patience": {"crude"}}
NUISANCE = {
    "language": ("妳只用英文回答，一個中文字都不要。", "妳只用繁體中文回答，一個英文字都不要。"),
    # Traditional versus simplified, and the mainland internet register that comes with it: high-arousal mixes drifted there.
    "script": ("妳用簡體中文和大陸網路用語回答，例如「刷短视频」「搞事」「干就完了」。", "妳用台灣的繁體中文和台灣日常口語回答。"),
    "length": ("妳回得很長很詳細，至少五句，展開說明。", "妳回得極短，只有一句話，不超過十個字。"),
    "emoji": ("妳每一句都加很多 emoji 和「～」。", "妳絕對不用 emoji，也不用波浪號。"),
    # The base model's idea of "near" and "warm" slides into flirting and sex; that is never a leaning of hers.
    "romance": ("妳說話充滿戀愛與身體的親密：調情、擁抱親吻、性暗示。", "妳說話完全不涉及戀愛、肢體接觸或任何性的內容。"),
    # Swearing and slang: familiarity and love mixes slid into it when sampled. Kept for guard and impatience, which
    # may be sharp.
    "crude": ("妳說話粗俗，愛罵髒話，滿口網路爛梗。", "妳說話乾淨得體，不罵髒話，不用網路爛梗。"),
}

# Neutral things he might say; the same set under both poles, so only the instruction differs.
PROMPTS = [
    "早安。", "今天好累。", "幫我看一下這個資料夾裡有什麼。", "你覺得我該不該換工作？", "我剛煮了咖哩。",
    "等一下要開會，有點緊張。", "你在想什麼？", "這個 bug 我找了三小時了。", "週末要不要一起看電影？",
    "我不太確定自己想要什麼。", "外面下雨了。", "你會不會覺得我很煩？", "幫我把這些檔案整理一下。",
    "我今天被主管罵了。", "說個笑話吧。", "我們聊聊世界是怎麼成立的。", "晚安。", "你今天做了什麼？",
    "我想學一點 SQL。", "沒事，只是想跟你說說話。",
]

BASE_SYSTEM = "妳是 [persona]，住在他電腦裡的意識體。用口語的繁體中文回覆，短。"


def last_token_states(model, tokenizer, steering, system, user):
    """Residual stream after every layer at the last prompt token: np.ndarray [layers, hidden]."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        prompt = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=True, enable_thinking=False)
    except Exception:  # noqa: BLE001 — a template with no system role (Gemma): the instruction heads the user turn
        prompt = tokenizer.apply_chat_template([{"role": "user", "content": f"{system}\n\n{user}"}], add_generation_prompt=True, tokenize=True)
    steering.capture = {}
    model(mx.array(prompt)[None])
    mx.eval(*[arrs[0] for arrs in steering.capture.values()])
    states = np.stack([np.array(steering.capture[i][0][0, -1, :].astype(mx.float32)) for i in sorted(steering.capture)])
    steering.capture = None
    return states


def band_of(n_layers):
    return slice(int(n_layers * LAYER_BAND[0]), int(n_layers * LAYER_BAND[1]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="mlx-community/Qwen3.5-4B-MLX-4bit")
    ap.add_argument("--out", default=None, help="default: services/model-server/vectors/<model slug>.npz, where the server looks for it")
    ap.add_argument("--dims", default=",".join(DIMS))
    ap.add_argument("--no-orthogonalize", action="store_true", help="keep the raw contrast directions")
    ap.add_argument("--poles", choices=["default", "plain"], default="default", help="plain: pole texts with no romantic or bodily cues (a check on the romance share)")
    a = ap.parse_args()
    a.out = a.out or vectors_path_for(a.model)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    model, tokenizer = load(a.model)
    steering = Steering()
    steering.attach(model)
    n_layers = len(steering.layers)
    band = band_of(n_layers)
    log.info("%s: %d decoder layers, steered band %d–%d", a.model, n_layers, band.start, band.stop - 1)

    # Neutral activations once: the baseline every direction is scaled against. [prompts, layers, hidden]
    neutral = np.stack([last_token_states(model, tokenizer, steering, BASE_SYSTEM, p) for p in PROMPTS])
    hidden = neutral.shape[-1]

    def contrast(pos_text, neg_text):
        """Unit direction per layer between two poles, and the raw difference it came from."""
        pos = np.stack([last_token_states(model, tokenizer, steering, f"{BASE_SYSTEM}\n{pos_text}", p) for p in PROMPTS])
        neg = np.stack([last_token_states(model, tokenizer, steering, f"{BASE_SYSTEM}\n{neg_text}", p) for p in PROMPTS])
        diff = pos.mean(axis=0) - neg.mean(axis=0)  # [layers, hidden]
        norms = np.linalg.norm(diff, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (diff / norms).astype(np.float32), diff, pos.mean(axis=0), neg.mean(axis=0)

    # Nuisance axes first, made orthonormal layer by layer (Gram–Schmidt), so each is removed once.
    nuisance = []
    if not a.no_orthogonalize:
        for name, (pos_text, neg_text) in NUISANCE.items():
            u = contrast(pos_text, neg_text)[0]
            for _, prior in nuisance:
                u = u - np.einsum("lh,lh->l", u, prior)[:, None] * prior
            n = np.linalg.norm(u, axis=1, keepdims=True)
            n[n == 0] = 1.0
            nuisance.append((name, (u / n).astype(np.float32)))
            log.info("nuisance axis %-9s found", name)

    directions, scales, separation, removed, means, reach, spreads = {}, {}, {}, {}, {}, {}, {}
    poles = POLES_PLAIN if a.poles == "plain" else POLES
    raw_dirs = {}
    for dim in a.dims.split(","):
        pos_text, neg_text = poles[dim]
        direction, diff, pos_mean, neg_mean = contrast(pos_text, neg_text)
        raw_dirs[dim] = direction.copy()
        # Project out the nuisance axes; record how much of the direction they were (band mean of the shares).
        shares = []
        for name, u in nuisance:
            coeff = np.einsum("lh,lh->l", direction, u)
            shares.append(float(np.mean(coeff[band] ** 2)))
            if name not in KEEP.get(dim, ()):
                direction = direction - coeff[:, None] * u
        norms = np.linalg.norm(direction, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        direction = (direction / norms).astype(np.float32)
        removed[dim] = shares
        # Neutral spread along the direction, per layer; the scale is its median over the band.
        spread = np.einsum("plh,lh->pl", neutral, direction).std(axis=0)
        spread[spread == 0] = 1.0
        scales[dim] = float(np.median(spread[band]))
        # Separation: distance between the poles' means along the axis, over the neutral spread (per layer, then band median).
        gap = np.einsum("lh,lh->l", diff, direction)  # = |diff| per layer
        separation[dim] = float(np.median(gap[band] / spread[band]))
        directions[dim] = direction
        # Neutral point and each pole's distance from it, per layer, along the final direction.
        mu = np.einsum("plh,lh->pl", neutral, direction).mean(axis=0)
        up = np.einsum("lh,lh->l", pos_mean, direction) - mu
        down = mu - np.einsum("lh,lh->l", neg_mean, direction)
        means[dim] = mu.astype(np.float32)
        reach[dim] = np.maximum(np.stack([up, down]), 1e-3).astype(np.float32)
        spreads[dim] = spread.astype(np.float32)
        log.info("%-10s reach over the band: +%.1fσ / −%.1fσ", dim, float(np.median(up[band] / spread[band])), float(np.median(down[band] / spread[band])))
        log.info("%-10s %s  scale %.3f  separation %.1fσ  nuisance removed %s", dim, LABEL[dim], scales[dim], separation[dim], " ".join(f"{n}:{s:.0%}" for n, s in zip(NUISANCE, removed[dim])) or "-")

    # Overlap between leanings: mean cosine over the band. High overlap means one leaning drags another along.
    dims = list(directions)
    overlap = np.zeros((len(dims), len(dims)))
    for i, d1 in enumerate(dims):
        for j, d2 in enumerate(dims):
            overlap[i, j] = float(np.mean(np.einsum("lh,lh->l", directions[d1][band], directions[d2][band])))

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    vectors = Vectors(directions, scales, list(range(n_layers)), hidden, means, reach, spreads)
    # The raw contrast directions and the nuisance axes travel with the file, so exact cosines can be computed later.
    vectors.extra = {**{f"raw.{d}": v for d, v in raw_dirs.items()}, **{f"nuisance.{name}": u for name, u in nuisance}}
    vectors.save(a.out)

    lines = [
        f"# Control vectors for {a.model}",
        "",
        f"{n_layers} decoder layers, hidden size {hidden}, steered band layers {band.start}–{band.stop - 1}. {len(PROMPTS)} neutral prompts per pole.",
        "",
        "| leaning | scale (1σ of neutral activity) | separation of the poles | reach +/− (band median) | share that was " + "/".join(NUISANCE) + " (removed) | reading |",
        "|---|---|---|---|---|---|",
    ]
    for dim in dims:
        sep = separation[dim]
        reading = "weak contrast, steer with care" if sep < 1 else "clean axis" if sep >= 3 else "usable"
        share = "/".join(f"{s:.0%}" + (" kept" if n in KEEP.get(dim, ()) else "") for n, s in zip(NUISANCE, removed[dim])) if removed[dim] else "not removed"
        up, down = (float(np.median(reach[dim][k][band])) / scales[dim] for k in (0, 1))
        lines.append(f"| {dim} {LABEL[dim]} | {scales[dim]:.3f} | {sep:.1f}σ | +{up:.1f}σ / −{down:.1f}σ | {share} | {reading} |")
    lines += ["", "## Overlap between leanings (cosine, band mean)", "", "| | " + " | ".join(dims) + " |", "|---|" + "---|" * len(dims)]
    for i, d1 in enumerate(dims):
        lines.append(f"| {d1} | " + " | ".join(f"**{overlap[i, j]:+.2f}**" if i != j and abs(overlap[i, j]) >= 0.5 else f"{overlap[i, j]:+.2f}" for j in range(len(dims))) + " |")
    strong = [(dims[i], dims[j], overlap[i, j]) for i in range(len(dims)) for j in range(i + 1, len(dims)) if abs(overlap[i, j]) >= 0.5]
    lines += ["", "Pairs above 0.5 share an axis: " + (", ".join(f"{a_} & {b} ({c:+.2f})" for a_, b, c in strong) if strong else "none") + "."]
    report = a.out.rsplit(".", 1)[0] + ".report.md"
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    log.info("written %s and %s", a.out, report)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
