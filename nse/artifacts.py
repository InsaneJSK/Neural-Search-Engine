"""Versioned Kaggle artifacts, stored outside source control."""

from pathlib import Path

DEFAULT_MODELS_DIR = Path(__file__).resolve().parents[1] / ".cache" / "nse" / "models"
MODEL_HANDLES = {
    "retriever": "insanejsk/denseretriever/pytorch/default/1",
    "reranker": "insanejsk/crossencoderreranker/pytorch/default/1",
}


def find_checkpoint(root: Path, kind: str) -> Path:
    required = {"config.json", "model.safetensors", "tokenizer.json"}
    if kind == "retriever":
        required.add("proj.safetensors")
    candidates = [
        config.parent for config in root.rglob("config.json")
        if all((config.parent / name).is_file() for name in required)
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"Expected one complete {kind} checkpoint under {root}; found {len(candidates)}. "
            "Run `python -m nse download-models`, or pass an explicit checkpoint directory. "
            f"Required files: {', '.join(sorted(required))}."
        )
    return candidates[0]


def download_models(root: Path) -> dict[str, Path]:
    import kagglehub

    paths = {}
    for kind, handle in MODEL_HANDLES.items():
        destination = root / kind
        # KaggleHub tracks completed downloads in this directory and reuses them.
        downloaded = kagglehub.model_download(handle, output_dir=str(destination.resolve()))
        paths[kind] = find_checkpoint(Path(downloaded), kind)
    return paths
