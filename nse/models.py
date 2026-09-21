"""Inference architecture matching the Kaggle notebooks; no training side effects."""

from pathlib import Path

import torch
from safetensors.torch import load_file
from torch import nn
from torch.nn import functional as F
from transformers import AutoConfig, AutoModel, AutoTokenizer


class BiEncoder(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.encoder = AutoModel.from_config(config)
        self.proj = nn.Sequential(
            nn.Linear(config.hidden_size, 256), nn.ReLU(), nn.Linear(256, 256)
        )

    def forward(self, **tokens):
        out = self.encoder(**tokens)
        mask = tokens["attention_mask"].unsqueeze(-1).float()
        pooled = (out.last_hidden_state * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        return F.normalize(self.proj(pooled), dim=-1)


class CrossEncoder(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.encoder = AutoModel.from_config(config)
        self.score_head = nn.Linear(config.hidden_size, 1)

    def forward(self, **tokens):
        out = self.encoder(**tokens)
        return self.score_head(out.last_hidden_state[:, 0, :]).squeeze(-1)


def normalize_parameter_names(state):
    """The Kaggle artifacts retain legacy BERT LayerNorm gamma/beta names."""
    normalized = {}
    for key, value in state.items():
        target = key.removeprefix("module.").replace(".LayerNorm.gamma", ".LayerNorm.weight").replace(".LayerNorm.beta", ".LayerNorm.bias")
        if target in normalized:
            raise ValueError(f"Duplicate checkpoint parameter: {target}")
        normalized[target] = value
    return normalized


def normalize_cross_state(state, expected_keys):
    """Support full-module and mixed raw-BERT keys without accepting missing heads."""
    normalized = {}
    for key, value in normalize_parameter_names(state).items():
        if key in expected_keys:
            target = key
        elif "encoder." + key in expected_keys:
            target = "encoder." + key
        else:
            raise ValueError(f"Unexpected cross-encoder checkpoint key: {key}")
        if target in normalized:
            raise ValueError(f"Duplicate cross-encoder checkpoint key: {target}")
        normalized[target] = value
    return normalized


class NeuralRanker:
    def __init__(self, retriever_dir: Path, reranker_dir: Path, device: str = "auto"):
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA is unavailable in this Python environment. Use --device cpu.")
        self.device = torch.device(device)
        self.bi_tokenizer = AutoTokenizer.from_pretrained(retriever_dir, local_files_only=True)
        self.cross_tokenizer = AutoTokenizer.from_pretrained(reranker_dir, local_files_only=True)
        self.bi_model = BiEncoder(AutoConfig.from_pretrained(retriever_dir, local_files_only=True))
        self.bi_model.encoder.load_state_dict(normalize_parameter_names(load_file(str(retriever_dir / "model.safetensors"))))
        self.bi_model.proj.load_state_dict(load_file(str(retriever_dir / "proj.safetensors")))
        self.cross_model = CrossEncoder(AutoConfig.from_pretrained(reranker_dir, local_files_only=True))
        state = load_file(str(reranker_dir / "model.safetensors"))
        self.cross_model.load_state_dict(normalize_cross_state(state, self.cross_model.state_dict()))
        self.bi_model.to(self.device).eval()
        self.cross_model.to(self.device).eval()

    @torch.inference_mode()
    def bi_scores(self, query: str, passages: list[str]) -> list[float]:
        tokens = self.bi_tokenizer(
            [query, *passages], padding=True, truncation=True, max_length=180, return_tensors="pt"
        ).to(self.device)
        embeddings = self.bi_model(**tokens)
        return (embeddings[1:] @ embeddings[0]).cpu().tolist()

    @torch.inference_mode()
    def cross_scores(self, query: str, passages: list[str]) -> list[float]:
        tokens = self.cross_tokenizer(
            [query] * len(passages), passages, padding=True,
            truncation=True, max_length=192, return_tensors="pt",
        ).to(self.device)
        return self.cross_model(**tokens).cpu().tolist()
