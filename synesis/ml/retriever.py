"""Semantic retrieval replacing grep-based rule lookup.

Combines embedding similarity with UCB scores and reward model
predictions for a combined ranking. Falls back gracefully when
ML deps aren't installed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def _rule_id(text: str) -> str:
    return f"rule_{hashlib.sha256(text.encode()).hexdigest()[:12]}"


class SemanticRetriever:
    def __init__(self, ml_dir: Path, kb_dir: Path):
        self._ml_dir = ml_dir
        self._kb_dir = kb_dir
        self._rules: list[tuple[str, str]] = []  # (id, text)

        from synesis.ml.embeddings import EmbeddingEngine
        from synesis.ml.scorer import RuleScorer

        self._embeddings = EmbeddingEngine(ml_dir)
        self._scorer = RuleScorer(ml_dir)
        self._reward_model = None  # lazy loaded

    def index_rules(self) -> int:
        """Parse rules.md and build FAISS index. Returns rule count."""
        self._rules = self._parse_rules()
        if not self._rules:
            return 0

        ids = [r[0] for r in self._rules]
        texts = [r[1] for r in self._rules]

        # Ensure all rules exist in scorer
        for rid in ids:
            self._scorer.ensure_rule(rid)

        return self._embeddings.build_index(ids, texts)

    def retrieve(
        self,
        query: str,
        k: int = 5,
        embedding_weight: float = 0.7,
        score_weight: float = 0.3,
    ) -> list[dict]:
        """Retrieve top-k rules for a given context query.

        Combines:
        1. Embedding similarity (cosine)
        2. UCB1 bandit score
        3. Reward model prediction (if trained)
        """
        # Load config overrides if they exist
        config = self._load_config()
        embedding_weight = config.get("embedding_weight", embedding_weight)
        score_weight = config.get("score_weight", score_weight)
        k = config.get("k", k)

        # Get embedding candidates (fetch more than k for re-ranking)
        candidates = self._embeddings.search(query, k=k * 3)
        if not candidates:
            return []

        # Load rule texts
        texts = self._load_rule_texts()

        # Score and rank
        ranked = []
        for rule_id, similarity in candidates:
            ucb = self._scorer.score_rule(rule_id)
            # Normalize UCB to [0, 1] range (cap at 3.0 for normalization)
            ucb_norm = min(ucb, 3.0) / 3.0 if ucb != float("inf") else 1.0

            # Reward model prediction (if available)
            reward_pred = self._predict_reward(rule_id, query)

            if reward_pred is not None:
                # Three-way blend when reward model is trained
                combined = (
                    embedding_weight * 0.6 * similarity
                    + score_weight * 0.2 * ucb_norm
                    + 0.2 * reward_pred
                )
            else:
                combined = embedding_weight * similarity + score_weight * ucb_norm

            # Record that we pulled this rule (for bandit)
            self._scorer.ensure_rule(rule_id)

            ranked.append({
                "rule_id": rule_id,
                "text": texts.get(rule_id, ""),
                "similarity": round(similarity, 4),
                "ucb_score": round(ucb_norm, 4),
                "reward_prediction": round(reward_pred, 4) if reward_pred else None,
                "combined": round(combined, 4),
            })

        ranked.sort(key=lambda x: x["combined"], reverse=True)
        return ranked[:k]

    def _predict_reward(self, rule_id: str, query: str) -> float | None:
        """Get reward model prediction, lazy-loading the model."""
        try:
            if self._reward_model is None:
                from synesis.ml.reward_model import RewardModel
                self._reward_model = RewardModel(self._ml_dir)
                if not self._reward_model.is_trained():
                    self._reward_model = False  # sentinel: don't try again
                    return None

            if self._reward_model is False:
                return None

            score_data = self._scorer.get_score_data(rule_id)
            text = self._load_rule_texts().get(rule_id, "")
            return self._reward_model.predict(text, query, score_data)
        except Exception:
            return None

    def _parse_rules(self) -> list[tuple[str, str]]:
        """Parse rules.md into (id, text) pairs."""
        rules_path = self._kb_dir / "_agent" / "rules.md"
        if not rules_path.exists():
            return []

        content = rules_path.read_text(encoding="utf-8")
        rules = []

        for line in content.split("\n"):
            # Match lines like: - [2026-04-08T14:30:15.123456] rule text here
            match = re.match(r"^- \[[\dT:.+-]+\]\s*(.+)$", line.strip())
            if match:
                text = match.group(1).strip()
                if text:
                    rules.append((_rule_id(text), text))

        return rules

    def _load_rule_texts(self) -> dict[str, str]:
        path = self._ml_dir / "rule_texts.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _load_config(self) -> dict:
        path = self._ml_dir / "config.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
