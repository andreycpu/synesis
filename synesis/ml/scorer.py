"""Rule scoring with UCB1 multi-armed bandit.

Each rule is an "arm". Pulling = retrieving for a session.
Reward = positive feedback signal. The UCB1 formula balances
exploitation (use high-scoring rules) with exploration (try under-used rules).
"""
from __future__ import annotations

import json
import math
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RuleScore:
    rule_id: str
    total_reward: float = 0.0
    times_pulled: int = 0
    times_success: int = 0
    times_corrected: int = 0
    last_used: str = ""
    created: str = ""

    @property
    def mean_reward(self) -> float:
        if self.times_pulled == 0:
            return 0.0
        return self.total_reward / self.times_pulled

    @property
    def success_rate(self) -> float:
        if self.times_pulled == 0:
            return 0.0
        return self.times_success / self.times_pulled


class RuleScorer:
    def __init__(self, ml_dir: Path):
        self._ml_dir = ml_dir
        self._path = ml_dir / "scores.json"
        self._scores: dict[str, RuleScore] = {}
        self._total_pulls = 0
        ml_dir.mkdir(parents=True, exist_ok=True)
        self._load()

    def ensure_rule(self, rule_id: str) -> RuleScore:
        if rule_id not in self._scores:
            self._scores[rule_id] = RuleScore(
                rule_id=rule_id,
                created=datetime.now().isoformat(),
            )
        return self._scores[rule_id]

    def score_rule(self, rule_id: str) -> float:
        s = self.ensure_rule(rule_id)
        if s.times_pulled == 0:
            return float("inf")  # Always explore new rules
        if self._total_pulls == 0:
            return s.mean_reward

        exploration = math.sqrt(2 * math.log(self._total_pulls) / s.times_pulled)
        return s.mean_reward + exploration

    def record_outcome(self, rule_id: str, reward: float) -> None:
        s = self.ensure_rule(rule_id)
        s.total_reward += reward
        s.times_pulled += 1
        s.last_used = datetime.now().isoformat()
        if reward > 0:
            s.times_success += 1
        self._total_pulls += 1
        self._save()

    def record_correction(self, rule_id: str) -> None:
        s = self.ensure_rule(rule_id)
        s.times_corrected += 1
        self.record_outcome(rule_id, reward=-0.5)

    def decay_scores(self, factor: float = 0.95) -> None:
        for s in self._scores.values():
            s.total_reward *= factor
        self._save()

    def get_top_rules(self, n: int = 20) -> list[tuple[str, float]]:
        scored = [(rid, self.score_rule(rid)) for rid in self._scores]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:n]

    def get_score_data(self, rule_id: str) -> RuleScore | None:
        return self._scores.get(rule_id)

    def all_scores(self) -> dict[str, RuleScore]:
        return dict(self._scores)

    def _save(self) -> None:
        data = {
            "total_pulls": self._total_pulls,
            "scores": {k: asdict(v) for k, v in self._scores.items()},
        }
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._total_pulls = raw.get("total_pulls", 0)
            for k, v in raw.get("scores", {}).items():
                self._scores[k] = RuleScore(**v)
        except Exception as e:
            logger.warning(f"Failed to load scores: {e}")
