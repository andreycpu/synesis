"""Reward model - predicts rule utility from features.

Trains a logistic regression on feedback data. Features combine
rule embeddings, context embeddings, and behavioral signals.
No LLM calls - pure sklearn.
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class RewardModel:
    def __init__(self, ml_dir: Path):
        self._ml_dir = ml_dir
        self._model = None
        self._model_path = ml_dir / "reward_model.pkl"

        from synesis.ml.embeddings import EmbeddingEngine
        self._embeddings = EmbeddingEngine(ml_dir)

    def is_trained(self) -> bool:
        if self._model is not None:
            return True
        return self._model_path.exists()

    def featurize(self, rule_text: str, context: str, score_data) -> np.ndarray:
        """Build feature vector from rule + context + score data.

        Features (774d):
        - rule_embedding: 384d
        - context_embedding: 384d
        - cosine_similarity: 1d
        - rule_age_days: 1d
        - mean_reward: 1d
        - times_pulled: 1d
        - times_corrected: 1d
        - success_rate: 1d
        """
        rule_emb = self._embeddings.embed_single(rule_text)
        ctx_emb = self._embeddings.embed_single(context)

        cos_sim = float(np.dot(rule_emb, ctx_emb))

        # Score features
        if score_data is not None:
            from datetime import datetime
            age = 0.0
            if score_data.created:
                try:
                    created = datetime.fromisoformat(score_data.created)
                    age = (datetime.now() - created).days
                except Exception:
                    pass
            features = np.array([
                cos_sim,
                age / 365.0,  # normalize
                score_data.mean_reward,
                min(score_data.times_pulled, 100) / 100.0,
                min(score_data.times_corrected, 50) / 50.0,
                score_data.success_rate,
            ], dtype=np.float32)
        else:
            features = np.zeros(6, dtype=np.float32)
            features[0] = cos_sim

        return np.concatenate([rule_emb, ctx_emb, features])

    def train(self, feedback_signals: list, scorer) -> dict:
        """Train on accumulated feedback.

        Labels:
        - accepted/completed -> 1
        - corrected/ignored -> 0
        """
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import cross_val_score

        positive_types = {"accepted", "completed"}
        negative_types = {"corrected", "ignored"}

        X_list = []
        y_list = []

        for signal in feedback_signals:
            if signal.signal_type not in positive_types | negative_types:
                continue

            label = 1.0 if signal.signal_type in positive_types else 0.0
            context = signal.context or ""

            # Use the rule text if available, otherwise use context as proxy
            rule_text = signal.details.get("rule_text", context[:200])
            score_data = scorer.get_score_data(signal.rule_ids[0]) if signal.rule_ids else None

            try:
                features = self.featurize(rule_text, context, score_data)
                X_list.append(features)
                y_list.append(label)
            except Exception as e:
                logger.debug(f"Featurize failed: {e}")
                continue

        if len(X_list) < 10:
            return {"status": "insufficient_data", "n_samples": len(X_list), "min_required": 10}

        X = np.array(X_list)
        y = np.array(y_list)

        model = LogisticRegression(C=1.0, max_iter=1000, class_weight="balanced")
        model.fit(X, y)

        # Cross-validate if enough data
        accuracy = 0.5
        if len(X) >= 20:
            scores = cross_val_score(model, X, y, cv=min(5, len(X) // 4), scoring="accuracy")
            accuracy = float(scores.mean())

        self._model = model
        self._save()

        result = {
            "status": "trained",
            "n_samples": len(X),
            "n_positive": int(y.sum()),
            "n_negative": int(len(y) - y.sum()),
            "accuracy": round(accuracy, 4),
        }
        logger.info(f"Reward model trained: {result}")
        return result

    def predict(self, rule_text: str, context: str, score_data) -> float:
        """Predict P(useful) for a rule in a given context."""
        self._ensure_loaded()
        if self._model is None:
            return 0.5

        features = self.featurize(rule_text, context, score_data)
        proba = self._model.predict_proba(features.reshape(1, -1))
        return float(proba[0][1])  # P(useful)

    def _save(self) -> None:
        if self._model is None:
            return
        with open(self._model_path, "wb") as f:
            pickle.dump(self._model, f)

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        if self._model_path.exists():
            try:
                with open(self._model_path, "rb") as f:
                    self._model = pickle.load(f)
            except Exception as e:
                logger.warning(f"Failed to load reward model: {e}")
