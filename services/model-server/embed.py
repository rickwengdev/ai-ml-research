"""A small XLM-RoBERTa encoder in mlx, for bge-m3 and its relatives (sentence embeddings for memory).

This is the whole of what the embedding role needs: the encoder stack, CLS pooling and L2 normalization, loading the
weights from an mlx-community `*-mlx-*` repo (or any HF repo with safetensors in the transformers layout). It keeps
the server free of mlx-vlm, torch and the rest that the general embedding packages pull in.

bge-m3's dense embedding is the normalized CLS vector, which is what sentence-transformers computes for it
(modules.json: Transformer → Pooling(cls) → Normalize), so these vectors match LM Studio's and the reference
implementation to float precision.
"""
from __future__ import annotations

import glob
import json
import os

import mlx.core as mx
import mlx.nn as nn


class Attention(nn.Module):
    def __init__(self, hidden, heads):
        super().__init__()
        self.heads = heads
        self.query = nn.Linear(hidden, hidden)
        self.key = nn.Linear(hidden, hidden)
        self.value = nn.Linear(hidden, hidden)

    def __call__(self, x, mask):
        b, t, h = x.shape
        q = self.query(x).reshape(b, t, self.heads, -1).transpose(0, 2, 1, 3)
        k = self.key(x).reshape(b, t, self.heads, -1).transpose(0, 2, 1, 3)
        v = self.value(x).reshape(b, t, self.heads, -1).transpose(0, 2, 1, 3)
        out = mx.fast.scaled_dot_product_attention(q, k, v, scale=(h // self.heads) ** -0.5, mask=mask)
        return out.transpose(0, 2, 1, 3).reshape(b, t, h)


class Layer(nn.Module):
    def __init__(self, hidden, heads, intermediate, eps):
        super().__init__()
        self.attention = {"self": Attention(hidden, heads), "output": {"dense": nn.Linear(hidden, hidden), "LayerNorm": nn.LayerNorm(hidden, eps=eps)}}
        self.intermediate = {"dense": nn.Linear(hidden, intermediate)}
        self.output = {"dense": nn.Linear(intermediate, hidden), "LayerNorm": nn.LayerNorm(hidden, eps=eps)}

    def __call__(self, x, mask):
        attended = self.attention["self"](x, mask)
        x = self.attention["output"]["LayerNorm"](x + self.attention["output"]["dense"](attended))
        hidden = nn.gelu(self.intermediate["dense"](x))
        return self.output["LayerNorm"](x + self.output["dense"](hidden))


class Encoder(nn.Module):
    """XLM-RoBERTa without heads: token + absolute position embeddings, N post-norm layers."""

    def __init__(self, config):
        super().__init__()
        hidden, eps = config["hidden_size"], config.get("layer_norm_eps", 1e-5)
        self.pad_id = config.get("pad_token_id", 1)
        self.embeddings = {
            "word_embeddings": nn.Embedding(config["vocab_size"], hidden),
            "position_embeddings": nn.Embedding(config["max_position_embeddings"], hidden),
            "token_type_embeddings": nn.Embedding(config.get("type_vocab_size", 1), hidden),
            "LayerNorm": nn.LayerNorm(hidden, eps=eps),
        }
        self.encoder = {"layer": [Layer(hidden, config["num_attention_heads"], config["intermediate_size"], eps) for _ in range(config["num_hidden_layers"])]}

    def __call__(self, input_ids, attention_mask):
        # RoBERTa counts positions from pad_id + 1, skipping padding.
        positions = mx.cumsum(attention_mask, axis=1) * attention_mask + self.pad_id
        x = self.embeddings["word_embeddings"](input_ids) + self.embeddings["position_embeddings"](positions) + self.embeddings["token_type_embeddings"](mx.zeros_like(input_ids))
        x = self.embeddings["LayerNorm"](x)
        # Additive mask over keys: padding gets -inf-ish, broadcast over heads and queries.
        mask = ((1 - attention_mask[:, None, None, :]) * -1e9).astype(x.dtype)
        for layer in self.encoder["layer"]:
            x = layer(x, mask)
        return x


def resolve(path_or_repo):
    if os.path.isdir(path_or_repo):
        return path_or_repo
    from huggingface_hub import snapshot_download

    return snapshot_download(path_or_repo, allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model"])


class Embedder:
    """Tokenizer + encoder + pooling: `embed(texts)` gives unit-length vectors as lists of floats."""

    def __init__(self, path_or_repo, max_length=1024):
        from tokenizers import Tokenizer

        path = resolve(path_or_repo)
        with open(os.path.join(path, "config.json"), encoding="utf-8") as f:
            config = json.load(f)
        if config.get("model_type") not in ("xlm-roberta", "roberta", "bert"):
            raise ValueError(f"{path_or_repo}: model_type {config.get('model_type')!r} is not an encoder this server knows (xlm-roberta/roberta/bert)")
        self.model = Encoder(config)
        weights = {}
        for file in glob.glob(os.path.join(path, "*.safetensors")):
            weights.update(mx.load(file))
        # Some exports keep the transformers prefix; the pooler head is not used.
        weights = {k.removeprefix("roberta.").removeprefix("model."): v for k, v in weights.items() if not k.startswith("pooler.") and "pooler" not in k}
        self.model.load_weights(list(weights.items()))
        mx.eval(self.model.parameters())
        self.tokenizer = Tokenizer.from_file(os.path.join(path, "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length)
        self.tokenizer.enable_padding(pad_id=config.get("pad_token_id", 1), pad_token="<pad>")
        self.dimensions = config["hidden_size"]
        self.pooling = "cls"
        pooling_file = os.path.join(path, "1_Pooling", "config.json")
        if os.path.exists(pooling_file):
            with open(pooling_file, encoding="utf-8") as f:
                pooling = json.load(f)
            if pooling.get("pooling_mode_mean_tokens"):
                self.pooling = "mean"

    def embed(self, texts, batch_size=16):
        out = []
        for start in range(0, len(texts), batch_size):
            batch = [t if t.strip() else " " for t in texts[start : start + batch_size]]
            encoded = self.tokenizer.encode_batch(batch)
            ids = mx.array([e.ids for e in encoded])
            mask = mx.array([e.attention_mask for e in encoded])
            hidden = self.model(ids, mask)
            if self.pooling == "mean":
                m = mask[:, :, None].astype(hidden.dtype)
                pooled = (hidden * m).sum(axis=1) / mx.maximum(m.sum(axis=1), 1)
            else:
                pooled = hidden[:, 0, :]
            pooled = pooled.astype(mx.float32)
            pooled = pooled / mx.maximum(mx.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            mx.eval(pooled)
            out.extend(pooled.tolist())
        return out
