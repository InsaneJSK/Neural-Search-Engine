import tempfile
import unittest
from pathlib import Path

import torch
from safetensors.torch import save_file
from transformers import BertConfig, BertTokenizerFast

from nse.artifacts import find_checkpoint
from nse.models import BiEncoder, CrossEncoder, NeuralRanker, normalize_cross_state, normalize_parameter_names


class ModelTests(unittest.TestCase):
    def test_checkpoint_roundtrip_preserves_projection_and_scoring_heads(self):
        torch.manual_seed(42)
        config = BertConfig(vocab_size=9, hidden_size=8, num_hidden_layers=1, num_attention_heads=2, intermediate_size=16)
        bi, cross = BiEncoder(config).eval(), CrossEncoder(config).eval()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vocab = root / "vocab.txt"
            vocab.write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nquery\nfirst\nsecond\npassage\n", encoding="utf-8")
            tokenizer = BertTokenizerFast(vocab_file=str(vocab))
            bi_dir, cross_dir = root / "bi", root / "cross"
            for path in [bi_dir, cross_dir]:
                config.save_pretrained(path)
                tokenizer.save_pretrained(path)
            save_file(bi.encoder.state_dict(), str(bi_dir / "model.safetensors"))
            save_file(bi.proj.state_dict(), str(bi_dir / "proj.safetensors"))
            save_file(cross.state_dict(), str(cross_dir / "model.safetensors"))
            loaded = NeuralRanker(bi_dir, cross_dir, "cpu")
            passages = ["first passage", "second passage"]
            with torch.inference_mode():
                emb = bi(**tokenizer(["query", *passages], padding=True, return_tensors="pt"))
                expected_bi = emb[1:] @ emb[0]
                expected_cross = cross(**tokenizer(["query"] * 2, passages, padding=True, return_tensors="pt"))
            torch.testing.assert_close(torch.tensor(loaded.bi_scores("query", passages)), expected_bi)
            torch.testing.assert_close(torch.tensor(loaded.cross_scores("query", passages)), expected_cross)
            # Recreate the legacy LayerNorm parameter names found in real Kaggle artifacts.
            def legacy(state):
                return {k.replace(".LayerNorm.weight", ".LayerNorm.gamma").replace(".LayerNorm.bias", ".LayerNorm.beta"): v for k, v in state.items()}
            save_file(legacy(bi.encoder.state_dict()), str(bi_dir / "model.safetensors"))
            save_file(legacy(cross.state_dict()), str(cross_dir / "model.safetensors"))
            loaded = NeuralRanker(bi_dir, cross_dir, "cpu")
            torch.testing.assert_close(torch.tensor(loaded.bi_scores("query", passages)), expected_bi)
            torch.testing.assert_close(torch.tensor(loaded.cross_scores("query", passages)), expected_cross)
            self.assertEqual(find_checkpoint(bi_dir, "retriever"), bi_dir)
            (bi_dir / "proj.safetensors").unlink()
            with self.assertRaisesRegex(ValueError, "proj.safetensors"):
                find_checkpoint(bi_dir, "retriever")

    def test_raw_bert_encoder_layer_prefix_is_not_mistaken_for_full_module_prefix(self):
        config = BertConfig(vocab_size=9, hidden_size=8, num_hidden_layers=1, num_attention_heads=2, intermediate_size=16)
        cross = CrossEncoder(config)
        raw = {k.removeprefix("encoder.") if k.startswith("encoder.") else k: v for k, v in cross.state_dict().items()}
        normalized = normalize_cross_state(raw, cross.state_dict())
        cross.load_state_dict(normalized)
        self.assertIn("encoder.encoder.layer.0.attention.self.query.weight", normalized)
        del normalized["score_head.weight"]
        with self.assertRaises(RuntimeError):
            cross.load_state_dict(normalized)

    def test_unknown_or_colliding_checkpoint_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            normalize_cross_state({"unexpected": torch.zeros(1)}, {"encoder.weight"})
        with self.assertRaises(ValueError):
            normalize_cross_state({"weight": torch.zeros(1), "encoder.weight": torch.zeros(1)}, {"encoder.weight"})
        with self.assertRaises(ValueError):
            normalize_parameter_names({"embeddings.LayerNorm.gamma": torch.zeros(1), "embeddings.LayerNorm.weight": torch.zeros(1)})


if __name__ == "__main__":
    unittest.main()
