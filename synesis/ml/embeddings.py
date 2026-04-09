"""Local embedding engine with FAISS index.

Uses sentence-transformers for embeddings and FAISS for similarity search.
All computation is local - no API calls.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingEngine:
    def __init__(self, ml_dir: Path, model_name: str = "all-MiniLM-L6-v2"):
        self._ml_dir = ml_dir
        self._model_name = model_name
        self._model = None
        self._index = None
        self._rule_ids: list[str] = []
        self._embeddings: np.ndarray | None = None
        ml_dir.mkdir(parents=True, exist_ok=True)

    def _load_model(self):
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self._model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        self._load_model()
        vecs = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.array(vecs, dtype=np.float32)

    def embed_single(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def build_index(self, rule_ids: list[str], texts: list[str]) -> int:
        if not texts:
            return 0

        import faiss

        vecs = self.embed(texts)
        dim = vecs.shape[1]

        index = faiss.IndexFlatIP(dim)
        index.add(vecs)

        faiss.write_index(index, str(self._ml_dir / "faiss.index"))
        np.savez(
            self._ml_dir / "embeddings.npz",
            vectors=vecs,
            rule_ids=np.array(rule_ids, dtype=object),
        )

        # Save id->text mapping for retrieval
        mapping = dict(zip(rule_ids, texts))
        (self._ml_dir / "rule_texts.json").write_text(
            json.dumps(mapping, ensure_ascii=False), encoding="utf-8"
        )

        self._index = index
        self._rule_ids = rule_ids
        self._embeddings = vecs

        logger.info(f"Built index: {len(texts)} rules, {dim}d embeddings")
        return len(texts)

    def search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        self._ensure_index()
        if self._index is None or self._index.ntotal == 0:
            return []

        q = self.embed_single(query).reshape(1, -1)
        k = min(k, self._index.ntotal)
        scores, indices = self._index.search(q, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            results.append((self._rule_ids[idx], float(score)))
        return results

    def get_embedding(self, rule_id: str) -> np.ndarray | None:
        self._ensure_index()
        if self._embeddings is None:
            return None
        try:
            idx = self._rule_ids.index(rule_id)
            return self._embeddings[idx]
        except ValueError:
            return None

    def _ensure_index(self):
        if self._index is not None:
            return
        self._load_cache()

    def _load_cache(self) -> bool:
        import faiss

        index_path = self._ml_dir / "faiss.index"
        emb_path = self._ml_dir / "embeddings.npz"

        if not index_path.exists() or not emb_path.exists():
            return False

        try:
            self._index = faiss.read_index(str(index_path))
            data = np.load(emb_path, allow_pickle=True)
            self._embeddings = data["vectors"]
            self._rule_ids = list(data["rule_ids"])
            return True
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
            return False
